# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
verify_dist.py — MinidoracatModLangFor42 的獨立 dist 驗證器（oracle）。

設計原則：
  * 這是**獨立 oracle**：絕不 import 或共用 build_mod.py 的任何函式。
    producer（build_mod.py）與 oracle（本檔）不得共享同一 bug，
    故所有驗證邏輯（讀檔、鍵集比對、placeholder token 化、hash）皆自行實作。
  * 純標準函式庫，無第三方相依 → 供 `uv run scripts/verify_dist.py` 直接執行。

驗證項（預設全跑；任一 FAIL → 退出碼 1，全 PASS → 0）：
  [1] CN 逐檔 parity：dist CN/*.json 對 As1 快照逐檔逐鍵值逐字一致
      （登記例外鍵改為對 cn_safe_value 核對，見 sources/placeholder_exceptions.json）
  [2] CH 鏡像       ：dist CH/*.json 與 dist CN 檔案集合、逐檔鍵集一致（值不比）
  [3] 編碼          ：dist 全部 .json 為 UTF-8 無 BOM 且可解析
  [4] placeholder   ：format-token 值殘留 `%.` → FAIL（JDK format crash 簽名）；
                      token multiset 不符 → FAIL；純字面可疑 % 數量不符 → WARN
  [6] language.txt  ：CH/CN 目錄各有 language.txt 且 text 欄位正確
  [7] lua 防護       ：dist media/lua/client/*.lua 與 sources/lua/*/*.lua basename 集合、
                      逐檔 bytes 一致，且每檔含 getActivatedMods/isModActive 防護
  [8] As1 來源漂移   ：sources/as1_manifest.json 存在時重算 As1 CN 逐檔 sha256 比對
  [9] CH corpus parity：dist CH 逐檔逐鍵值對 sources/ch/ 人工真相 corpus 逐字一致
                      （原創鍵對 own_translations 的 ch；CH 已斷絕 OpenCC 機轉，值有真相源）
  [10] sync worklist ：sources/ch_sync_worklist.json 未處理條目必須清空（上游變更未反映不得出貨）
  [11] 已審鍵漂移     ：ch_review_state.json 已審鍵重算現行 CN hash，不符 → WARN（須重審）

冪等子命令（獨立於預設全跑，供「連跑兩次 build 第二次零 diff」驗證）：
  --snapshot-dist <dir>：把 dist 現況（.json + language.txt + client/*.lua 的 sha256）存到 <dir>/dist_hashes.json
  --compare-dist  <dir>：比對現況與 <dir>/dist_hashes.json，有 diff 退出 1
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter

# dist 內層 Translate 目錄（相對 repo 根）的 glob；避免硬編長資料夾名，
# 執行期以實際存在的路徑為準（模板慣例：資料夾=長名、mod.info id=短名）。
DIST_TRANSLATE_GLOB = "MOD/*/Contents/mods/*/42/media/lua/shared/Translate"

# As1 CN 語料相對 <local_path>/<source_tree> 的子路徑。
AS1_CN_SUBPATH = "media/lua/shared/Translate/CN"

# placeholder grammar：與 build_mod.py 的文法定義對齊（153 個合法 %.1f 不可誤殺）。
# 順序即優先序：%% > %.Nf > %N（正整數位置參數）> %s/%d/%i。
# 未被此文法吸收的 % 一律歸「可疑」桶（裸 % 只列 warning）——
# 例如裸 % (如 "50%") 與 crash 簽名 %. (percent 緊接句點) 都刻意不算 grammar。
_GRAMMAR = re.compile(r"%%|%\.\d+f|%\d+|%[sdi]")

# lua 防護規則：每個 client lua 必須含這兩個 API 之一（未啟用目標 MOD 即 no-op）。
_LUA_GUARD = re.compile(rb"getActivatedMods|isModActive")

# ASCII 標籤（<LINE>、<br>、<RGB:...>）multiset 比對：builder 契約含標籤層，
# oracle 獨立實作對齊。角括號內容含 CJK 者是翻譯文字（如 <吱吱声>），不算標籤。
_TAG_RE = re.compile(r"<[^<>]+>")
_TAG_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


def extract_tags(value: str) -> list[str]:
    """抽出值裡的 ASCII 標籤（排除含 CJK 的假標籤）。"""
    return [t for t in _TAG_RE.findall(value) if not _TAG_CJK_RE.search(t)]

DETAIL_CAP = 20  # 每項失敗明細上限


# --------------------------------------------------------------------------- #
# 低階工具（全部自行實作，不共用 builder）
# --------------------------------------------------------------------------- #
def _read_json(path: str) -> dict:
    """以 utf-8-sig 讀取（容忍 BOM，BOM 本身由 [3] 編碼檢查獨立把關）。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"頂層非物件：{type(data).__name__}")
    return data


def _load_json_dir(directory: str) -> tuple[dict[str, dict], list[str]]:
    """回傳 ({檔名: {鍵:值}}, [解析錯誤訊息])；只收 *.json。"""
    out: dict[str, dict] = {}
    errors: list[str] = []
    if not os.path.isdir(directory):
        return out, errors
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            out[name] = _read_json(os.path.join(directory, name))
        except Exception as exc:  # noqa: BLE001 — 任何解析失敗都要記錄
            errors.append(f"{name}: 解析失敗（{exc}）")
    return out, errors


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_tokens(value: str) -> tuple[list[str], list[str]]:
    """把字串裡的 % 序列拆成 (grammar tokens, 可疑序列)。

    grammar tokens 進 FAIL 比對；可疑序列（未被文法吸收的 %）進 WARN / crash 判定。
    可疑序列取「% + 後一字元」做人類可讀 context（末尾裸 % 只回一字元）。
    """
    grammar: list[str] = []
    suspicious: list[str] = []
    i, n = 0, len(value)
    while i < n:
        if value[i] == "%":
            m = _GRAMMAR.match(value, i)
            if m:
                grammar.append(m.group())
                i = m.end()
            else:
                suspicious.append(value[i : i + 2])  # % 加後一字元當 context
                i += 1
        else:
            i += 1
    return grammar, suspicious


def has_crash_signature(value: object) -> bool:
    """JDK String.format crash 簽名：值同時含 format token 且殘留字面 `%.`。

    格式化字串（含 %N/%s/%d/%i/%.Nf 任一）若又出現未構成 %.Nf 的 `%.`，
    Java `String.formatted()` 會擲 UnknownFormatConversionException 而崩潰。
    無 format token 的純文字 `%.`（如 "5%.等"）不會被格式化，不算 crash（見 [4] WARN）。
    """
    if not isinstance(value, str):
        return False
    grammar, suspicious = extract_tokens(value)
    has_format_token = any(g != "%%" for g in grammar)  # %% 是逸出字面，非轉換
    residual_dot = any(s.startswith("%.") for s in suspicious)
    return has_format_token and residual_dot


def _load_exceptions(repo: str) -> dict[str, dict]:
    """讀 sources/placeholder_exceptions.json。

    schema：{"<檔名>|<鍵>": {"reason": "...", "cn_safe_value": "..."}}
    不存在 → 空 dict。頂層非物件 → 擲例外（呼叫端轉 FAIL）。
    """
    path = os.path.join(repo, "sources", "placeholder_exceptions.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("placeholder_exceptions.json 頂層非物件")
    return data


def _load_cn_overrides(repo: str) -> dict[str, dict]:
    """讀 sources/cn_overrides.json（CN 人工修正層，修 As1 上游錯誤）。

    schema：{"<檔名>|<鍵>": {"value": "...", "reason": "..."}}
    登記於此的鍵，CN parity 改對 value 核對而非 As1 原值——CN 不再要求與快照
    逐字一致，但偏離必須逐案登記，oracle 效力保留。
    不存在 → 空 dict（此時 CN 全數對 As1 逐字核對）。頂層非物件 → 擲例外。
    """
    path = os.path.join(repo, "sources", "cn_overrides.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("cn_overrides.json 頂層非物件")
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _load_own(repo: str) -> dict[str, dict]:
    """讀 sources/own_translations.json 的 entries（原創翻譯層）。

    schema：{"entries": {"<檔名>": {"<鍵>": {"en":..., "ch":..., "cn":...}}}}
    不存在 → 空 dict。頂層非物件 → 擲例外（呼叫端轉 FAIL）。
    """
    path = os.path.join(repo, "sources", "own_translations.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("entries", {}), dict):
        raise ValueError("own_translations.json 頂層非物件或 entries 形狀錯誤")
    return data.get("entries", {})


def _load_own_mods(repo: str) -> dict[str, dict]:
    """讀 origin=='own' 的原創翻譯 mod 目錄 CN，轉成 own oracle 條目。

    回傳 {"<檔名>": {"<鍵>": {"cn": 值}}}——這些 CN 為人工直寫真相
    （非 As1 快照亦非 build 產物），比照 own_translations 作 parity 核對值。
    """
    entries: dict[str, dict] = {}
    mods_dir = os.path.join(repo, "sources", "mods")
    if not os.path.isdir(mods_dir):
        return entries
    for wid in sorted(os.listdir(mods_dir)):
        meta_path = os.path.join(mods_dir, wid, "metadata.json")
        if not os.path.isfile(meta_path):
            continue
        with open(meta_path, "r", encoding="utf-8-sig") as f:
            if json.load(f).get("origin") != "own":
                continue
        cn_dir = os.path.join(mods_dir, wid, "CN")
        if not os.path.isdir(cn_dir):
            raise ValueError(f"原創 mod {wid} 缺 CN 目錄")
        for fname in sorted(os.listdir(cn_dir)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(cn_dir, fname), "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            bucket = entries.setdefault(fname, {})
            for key, value in data.items():
                if key in bucket:
                    # build 端值感知去重允許同值共存，oracle 比照：僅異值視為衝突
                    if bucket[key].get("cn") == value:
                        continue
                    raise ValueError(f"原創 mod 重複鍵且值不一致：{fname}|{key}")
                bucket[key] = {"cn": value}
    return entries


def _load_ch_corpus(repo: str) -> dict[str, dict]:
    """讀 sources/ch/*.json（CH 人工真相 corpus）。缺目錄/解析失敗 → 擲例外（呼叫端轉 FAIL）。"""
    d = os.path.join(repo, "sources", "ch")
    if not os.path.isdir(d):
        raise ValueError("sources/ch 目錄不存在（CH corpus 為人工真相層，必要）")
    out, errors = _load_json_dir(d)
    if errors:
        raise ValueError("; ".join(errors))
    return out


def _load_worklist(repo: str) -> dict[str, object]:
    """讀 sources/ch_sync_worklist.json 的待辦條目（不含 | 的鍵為說明欄）。

    受版控狀態檔、值變更防線的單點：**缺檔即擲例外**（呼叫端轉 FAIL）——
    「待辦清空」以「僅剩說明欄的物件」表示，絕不以「檔案不存在」表示。
    """
    path = os.path.join(repo, "sources", "ch_sync_worklist.json")
    if not os.path.isfile(path):
        raise ValueError(
            "ch_sync_worklist.json 不存在（受版控狀態檔，缺失＝值變更防線被移除，"
            "請自版控還原）"
        )
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("ch_sync_worklist.json 頂層非物件")
    return {k: v for k, v in data.items() if "|" in k}


_HASH16_RE = re.compile(r"^[0-9a-f]{16}$")


def _load_review_state(repo: str) -> dict[str, str]:
    """讀 sources/ch_review_state.json（已審鍵 → 審定當下有效 CN 值 sha256[:16]）。

    受版控真相檔：缺檔／schema 不符（非字串、非 16 位 hex）→ 擲例外轉 FAIL，
    不得靜默丟棄條目（丟棄＝該鍵漂移偵測無聲消失）。
    """
    path = os.path.join(repo, "sources", "ch_review_state.json")
    if not os.path.isfile(path):
        raise ValueError("ch_review_state.json 不存在（受版控真相檔，請自版控還原）")
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("ch_review_state.json 頂層非物件")
    out: dict[str, str] = {}
    for k, v in data.items():
        if "|" not in k:
            continue  # _comment 等說明欄
        if not isinstance(v, str) or not _HASH16_RE.match(v):
            raise ValueError(f"ch_review_state.json 條目 {k!r} 非 16 位 hex hash：{v!r}")
        out[k] = v
    return out


def _parse_language_txt(path: str) -> dict[str, str]:
    """解析 PZ language.txt（形如 `text = Traditional Chinese,`）成 {key: value}。"""
    result: dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip().rstrip(",").strip()
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    return result


def _cap(items: list[str]) -> list[str]:
    """明細上限 DETAIL_CAP，超出附一行提示。"""
    if len(items) <= DETAIL_CAP:
        return items
    return items[:DETAIL_CAP] + [f"...（還有 {len(items) - DETAIL_CAP} 條，已截斷）"]


# --------------------------------------------------------------------------- #
# 路徑解析
# --------------------------------------------------------------------------- #
def _resolve_paths(repo: str, snapshot_path: str) -> dict:
    """從 repo 根與 snapshot.json 推導 As1 CN、dist CH/CN、dist lua client 路徑。"""
    with open(snapshot_path, "r", encoding="utf-8-sig") as f:
        snap = json.load(f)
    as1 = snap["as1"]
    as1_base = os.path.join(as1["local_path"], str(as1["source_tree"]))
    as1_cn = os.path.join(as1_base, *AS1_CN_SUBPATH.split("/"))

    matches = sorted(glob.glob(os.path.join(repo, *DIST_TRANSLATE_GLOB.split("/"))))
    dist_translate = matches[0] if matches else None
    # dist lua client 是 Translate 的手足：<...>/42/media/lua/shared/Translate
    # → dirname×2 得 <...>/42/media/lua → 再接 client。
    lua_client = (
        os.path.join(os.path.dirname(os.path.dirname(dist_translate)), "client")
        if dist_translate
        else None
    )
    return {
        "repo": repo,
        "as1_base": as1_base,
        "as1_cn": as1_cn,
        "dist_translate": dist_translate,
        "dist_cn": os.path.join(dist_translate, "CN") if dist_translate else None,
        "dist_ch": os.path.join(dist_translate, "CH") if dist_translate else None,
        "lua_client": lua_client,
    }


def _dist_is_built(dist_cn: str | None) -> bool:
    """dist 視為已 build 的條件：CN 目錄存在且至少含一個 .json。"""
    if not dist_cn or not os.path.isdir(dist_cn):
        return False
    return any(n.endswith(".json") for n in os.listdir(dist_cn))


# --------------------------------------------------------------------------- #
# 各驗證項（回傳 (ok: bool, details: list[str], ...)）
# --------------------------------------------------------------------------- #
def check_cn_parity(
    as1_cn: str,
    dist_cn: str,
    exceptions: dict[str, dict],
    own: dict[str, dict],
    cn_overrides: dict[str, dict] | None = None,
) -> tuple[bool, list[str], list[str], int, int]:
    """[1] dist CN 對 As1 快照：檔案集合 + 逐檔鍵集 + 逐鍵值逐字一致。

    三類登記偏離改判（優先序同 build：placeholder 例外最後套故最優先）：
      1. sources/placeholder_exceptions.json → 「dist CN 值 == cn_safe_value」
      2. sources/cn_overrides.json           → 「dist CN 值 == value」（修上游錯誤）
      3. sources/own_translations.json       → 合法「多鍵/多檔」，「dist CN 值 == own cn」
    回傳 (ok, details, warn, applied_count, own_count)。
    """
    cn_overrides = cn_overrides or {}
    as1_files, as1_err = _load_json_dir(as1_cn)
    dist_files, dist_err = _load_json_dir(dist_cn)
    details: list[str] = []
    warn: list[str] = []
    details += [f"As1 {e}" for e in as1_err]
    details += [f"dist {e}" for e in dist_err]

    def own_cn(fname: str, key: str) -> str | None:
        spec = own.get(fname, {}).get(key)
        return spec.get("cn") if isinstance(spec, dict) else None

    applied_own: set[str] = set()

    def check_own_key(fname: str, key: str, dist_val: object) -> bool:
        """dist 多出的 (檔,鍵) 若屬原創層 → 核對 own cn 值。回傳是否已處理。"""
        expect = own_cn(fname, key)
        if expect is None:
            return False
        applied_own.add(f"{fname}|{key}")
        if dist_val != expect:
            details.append(
                f"{fname}: 原創鍵 {key!r} 值不符 | dist={dist_val!r} 應為 own cn={expect!r}"
            )
        return True

    as1_set, dist_set = set(as1_files), set(dist_files)
    for missing in sorted(as1_set - dist_set):
        details.append(f"檔案缺少：dist 少了 {missing}")
    for extra in sorted(dist_set - as1_set):
        # 純原創檔（As1 無此檔）：逐鍵核對 own；任何非原創鍵仍屬違規
        for key in sorted(dist_files[extra]):
            if not check_own_key(extra, key, dist_files[extra][key]):
                details.append(f"檔案多出：dist 多了 {extra}（含非原創鍵 {key!r}）")

    applied_cn_ov: set[str] = set()  # 實際命中的 CN 修正鍵
    applied: set[str] = set()  # 實際命中 dist(檔,鍵) 的例外
    for fname in sorted(as1_set & dist_set):
        a, d = as1_files[fname], dist_files[fname]
        ak, dk = set(a), set(d)
        for mk in sorted(ak - dk):
            details.append(f"{fname}: 缺鍵 {mk!r}")
        for ek in sorted(dk - ak):
            if not check_own_key(fname, ek, d[ek]):
                details.append(f"{fname}: 多鍵 {ek!r}")
        for key in sorted(ak & dk):
            exc = exceptions.get(f"{fname}|{key}")
            if isinstance(exc, dict) and isinstance(exc.get("cn_safe_value"), str):
                # 例外鍵：與登記安全值核對（不再對 As1 原值）
                applied.add(f"{fname}|{key}")
                if d[key] != exc["cn_safe_value"]:
                    details.append(
                        f"{fname}: 例外鍵 {key!r} 未套用安全值 | "
                        f"dist={d[key]!r} 應為 cn_safe_value={exc['cn_safe_value']!r}"
                    )
            elif isinstance(
                (cov := cn_overrides.get(f"{fname}|{key}")), dict
            ) and isinstance(cov.get("value"), str):
                # CN 人工修正鍵：與登記值核對（不再對 As1 原值）
                applied_cn_ov.add(f"{fname}|{key}")
                if d[key] != cov["value"]:
                    details.append(
                        f"{fname}: CN 修正鍵 {key!r} 未套用登記值 | "
                        f"dist={d[key]!r} 應為 value={cov['value']!r}"
                    )
            elif a[key] != d[key]:
                details.append(
                    f"{fname}: 鍵 {key!r} 值不符 | As1={a[key]!r} dist={d[key]!r}"
                )

    # 登記但未命中任何 dist(檔,鍵) 的例外 → WARN（多半是打錯 key 名）
    for ekey in sorted(set(exceptions) - applied):
        warn.append(f"例外鍵 {ekey!r} 未對應任何 dist CN(檔,鍵)，登記可能過期或打錯")
    for ckey in sorted(set(cn_overrides) - applied_cn_ov):
        warn.append(f"CN 修正鍵 {ckey!r} 未對應任何 dist CN(檔,鍵)，登記可能過期或打錯")

    # registry as1_value 錨點漂移 → WARN（上游已自行修正，override/例外可能該退役；
    # 鏡射 build 的同名警告到 oracle 報表，讓它出現在發布前必看的地方）
    for reg_label, reg in (("cn_overrides", cn_overrides), ("placeholder_exceptions", exceptions)):
        for rkey, spec in sorted(reg.items()):
            anchor = spec.get("as1_value") if isinstance(spec, dict) else None
            if not isinstance(anchor, str):
                continue
            rf, _, rk = rkey.partition("|")
            cur = as1_files.get(rf, {}).get(rk)
            if isinstance(cur, str) and cur != anchor:
                warn.append(f"{reg_label} 錨點漂移：{rkey!r} 上游原值已變，請複核是否退役")

    # 原創層完整性：登記的鍵必須落地；被 As1 收錄者提示退役（build 端 As1 優先）
    for fname in sorted(own):
        for key in sorted(own[fname]):
            oid = f"{fname}|{key}"
            if fname in as1_files and key in as1_files[fname]:
                warn.append(f"原創鍵 {oid!r} 已被 As1 收錄（As1 優先），建議自對應原創來源（own_translations.json 或原創 mod 目錄）退役")
            elif oid not in applied_own:
                details.append(f"原創鍵 {oid!r} 未落地於 dist CN")

    return (not details), details, warn, len(applied), len(applied_own)


def check_ch_mirror(dist_cn: str, dist_ch: str) -> tuple[bool, list[str]]:
    """[2] dist CH 與 dist CN：檔案集合 + 逐檔鍵集一致（值不比）。"""
    cn_files, cn_err = _load_json_dir(dist_cn)
    ch_files, ch_err = _load_json_dir(dist_ch)
    details: list[str] = []
    details += [f"CN {e}" for e in cn_err]
    details += [f"CH {e}" for e in ch_err]

    cn_set, ch_set = set(cn_files), set(ch_files)
    for missing in sorted(cn_set - ch_set):
        details.append(f"檔案缺少：CH 少了 {missing}")
    for extra in sorted(ch_set - cn_set):
        details.append(f"檔案多出：CH 多了 {extra}")

    for fname in sorted(cn_set & ch_set):
        ck, hk = set(cn_files[fname]), set(ch_files[fname])
        for mk in sorted(ck - hk):
            details.append(f"{fname}: CH 缺鍵 {mk!r}")
        for ek in sorted(hk - ck):
            details.append(f"{fname}: CH 多鍵 {ek!r}")
    return (not details), details


def check_encoding(dist_translate: str) -> tuple[bool, list[str]]:
    """[3] dist 全部 .json：UTF-8 無 BOM 且可解析。"""
    details: list[str] = []
    for path in sorted(glob.glob(os.path.join(dist_translate, "**", "*.json"), recursive=True)):
        rel = os.path.relpath(path, dist_translate).replace(os.sep, "/")
        with open(path, "rb") as f:
            raw = f.read()
        if raw.startswith(b"\xef\xbb\xbf"):
            details.append(f"{rel}: 含 UTF-8 BOM")
            continue
        try:
            json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            details.append(f"{rel}: 非合法 UTF-8（{exc}）")
        except json.JSONDecodeError as exc:
            details.append(f"{rel}: JSON 無法解析（{exc}）")
    return (not details), details


def check_placeholder(
    dist_cn: str, dist_ch: str, exceptions: dict[str, dict]
) -> tuple[bool, list[str], list[str]]:
    """[4] placeholder 三層把關（登記例外鍵豁免 FAIL，但登記安全值本身仍受檢）。

    FAIL：
      * format-token 值殘留字面 `%.`（JDK format crash 簽名）——CN 側僅未登記例外鍵檢；
        CH 側**一律檢**（CH 為獨立人工資料，登記例外不豁免 CH 安全）。
      * grammar token multiset 不一致（%1/%s/%.1f/%% 等被增刪改）——例外鍵不豁免。
      * ASCII 標籤 multiset 不一致（<LINE>/<br>/<RGB:...> 被增刪改）——例外鍵不豁免。
    WARN：可疑（非 grammar）% 的**數量**在 CN/CH 不一致（純字面 % 的值層差異）。
    """
    cn_files, _ = _load_json_dir(dist_cn)
    ch_files, _ = _load_json_dir(dist_ch)
    fail: list[str] = []
    warn: list[str] = []

    # 先驗每個登記安全值本身真的安全（schema 完整 + cn_safe_value 不含 crash 簽名）。
    for ekey, entry in sorted(exceptions.items()):
        if not isinstance(entry, dict) or not isinstance(entry.get("cn_safe_value"), str):
            fail.append(f"例外 {ekey!r} 缺合法字串 cn_safe_value（schema 不符）")
            continue
        if has_crash_signature(entry["cn_safe_value"]):
            fail.append(
                f"例外 {ekey!r} 的 cn_safe_value 仍含 format token + 殘留 '%.'（安全值不安全）"
                f" | {entry['cn_safe_value']!r}"
            )

    for fname in sorted(set(cn_files) & set(ch_files)):
        cn, ch = cn_files[fname], ch_files[fname]
        for key in sorted(set(cn) & set(ch)):
            exempt = f"{fname}|{key}" in exceptions
            cn_v = cn[key] if isinstance(cn[key], str) else ""
            ch_v = ch[key] if isinstance(ch[key], str) else ""
            cg, cs = extract_tokens(cn_v)
            hg, hs = extract_tokens(ch_v)

            # 登記例外僅豁免 CN 側崩潰簽名（安全值本身已於上方獨立驗過）；
            # CH 為獨立人工資料，崩潰簽名／token／標籤 multiset 一律照檢。
            if not exempt and has_crash_signature(cn[key]):
                fail.append(
                    f"{fname}: 鍵 {key!r} CN 值含 format token 且殘留 '%.'（crash 簽名）"
                    f" | {cn[key]!r}"
                )
            if has_crash_signature(ch[key]):
                fail.append(
                    f"{fname}: 鍵 {key!r} CH 值含 format token 且殘留 '%.'（crash 簽名）"
                    f" | {ch[key]!r}"
                )
            if Counter(cg) != Counter(hg):
                fail.append(
                    f"{fname}: 鍵 {key!r} token 不符 | CN={sorted(cg)} CH={sorted(hg)}"
                )
            ct, ht = extract_tags(cn_v), extract_tags(ch_v)
            if Counter(ct) != Counter(ht):
                fail.append(
                    f"{fname}: 鍵 {key!r} 標籤不符 | CN={sorted(ct)} CH={sorted(ht)}"
                )
            # WARN 對例外鍵仍照列（只是不影響退出碼）
            if len(cs) != len(hs):
                warn.append(
                    f"{fname}: 鍵 {key!r} 可疑 % 數量 CN={len(cs)}({cs}) CH={len(hs)}({hs})"
                )
    return (not fail), fail, warn


def check_ch_corpus_parity(
    repo: str, dist_ch: str, own: dict[str, dict]
) -> tuple[bool, list[str]]:
    """[9] dist CH 逐檔逐鍵值對 sources/ch corpus 逐字一致（雙向）。

    取值優先序同 build：corpus（As1/own-mod 鍵）優先，own_translations 的 ch 其次；
    兩者皆無＝無真相源 FAIL。corpus 鍵未落地 dist 亦 FAIL。
    """
    corpus = _load_ch_corpus(repo)
    dist, derr = _load_json_dir(dist_ch)
    details: list[str] = [f"dist CH {e}" for e in derr]

    for fname in sorted(dist):
        cmap = corpus.get(fname, {})
        for key in sorted(dist[fname]):
            val = dist[fname][key]
            if key in cmap:
                if val != cmap[key]:
                    details.append(
                        f"{fname}: 鍵 {key!r} 值不符 corpus | dist={val!r} corpus={cmap[key]!r}"
                    )
            else:
                spec = own.get(fname, {}).get(key)
                own_ch = spec.get("ch") if isinstance(spec, dict) else None
                if own_ch is None:
                    details.append(f"{fname}: 鍵 {key!r} 無真相源（corpus 與原創層皆無）")
                elif val != own_ch:
                    details.append(
                        f"{fname}: 原創鍵 {key!r} 值不符 own ch | dist={val!r} own={own_ch!r}"
                    )
    for fname in sorted(corpus):
        dmap = dist.get(fname)
        if dmap is None:
            details.append(f"corpus 檔 {fname} 未出現在 dist CH")
            continue
        for key in sorted(set(corpus[fname]) - set(dmap)):
            details.append(f"{fname}: corpus 鍵 {key!r} 未落地 dist CH")
    return (not details), details


def check_sync_worklist(repo: str) -> tuple[bool, list[str]]:
    """[10] sync worklist 待辦必須清空（上游變更未反映到 corpus 不得出貨）。

    自動對帳（與 build 端獨立實作同語意）：added 條目其鍵已落 corpus、
    removed 條目其鍵已自 corpus 移除 → 已滿足不列；changed 一律列 FAIL
    直到人工確認移除。corpus 無法載入時保守視為全部未滿足（fail-closed）。
    """
    wl = _load_worklist(repo)
    try:
        corpus = _load_ch_corpus(repo)
    except Exception:  # noqa: BLE001 — corpus 壞掉由 [9] 報，此處保守全列
        corpus = {}
    details: list[str] = []
    for k, v in sorted(wl.items()):
        kind = v.get("kind") if isinstance(v, dict) else None
        fname, _, key = k.partition("|")
        present = key in corpus.get(fname, {})
        if (kind == "added" and present) or (kind == "removed" and not present):
            continue
        details.append(f"未處理條目：{k}（{kind or '?'}）")
    return (not details), details


def check_review_drift(repo: str, dist_cn: str) -> tuple[bool, list[str], list[str]]:
    """[11] 已審鍵 CN 漂移（WARN-only）：review_state 記錄 hash 對現行 dist CN 重算比對。"""
    state = _load_review_state(repo)
    cn_files, _ = _load_json_dir(dist_cn)
    warn: list[str] = []
    for skey in sorted(state):
        fname, _, key = skey.partition("|")
        val = cn_files.get(fname, {}).get(key)
        if not isinstance(val, str):
            warn.append(f"已審鍵 {skey!r} 已不在 dist CN（登記過時，請自 ch_review_state.json 移除）")
        elif hashlib.sha256(val.encode("utf-8")).hexdigest()[:16] != state[skey]:
            warn.append(f"已審鍵 {skey!r} 的 CN 已漂移（上游改文，請重審 CH 並更新 hash）")
    return True, [], warn


def check_language_txt(dist_cn: str, dist_ch: str) -> tuple[bool, list[str]]:
    """[6] CH/CN 目錄各有 language.txt 且 text 欄位正確。"""
    details: list[str] = []
    expected = {dist_cn: "Simplified Chinese", dist_ch: "Traditional Chinese"}
    for directory, want in expected.items():
        label = os.path.basename(directory.rstrip(os.sep))
        path = os.path.join(directory, "language.txt")
        if not os.path.isfile(path):
            details.append(f"{label}/language.txt 不存在")
            continue
        got = _parse_language_txt(path).get("text")
        if got != want:
            details.append(f"{label}/language.txt: text={got!r}，應為 {want!r}")
    return (not details), details


def check_lua(repo: str, lua_client: str | None) -> tuple[bool, list[str]]:
    """[7] dist lua client 與 sources/lua/*/*.lua：basename 集合、bytes、防護。

    * 來源同 basename 衝突（兩個 sources/lua/*/ 出現同名）→ FAIL（無法確定要哪份）。
    * dist 缺檔 / 多檔 → FAIL。
    * 逐檔 source 與 dist bytes 一致 → 否則 FAIL。
    * 每個非衝突 source lua 含 getActivatedMods/isModActive → 否則 FAIL（防護規則）。
    """
    details: list[str] = []
    src_paths = sorted(glob.glob(os.path.join(repo, "sources", "lua", "*", "*.lua")))
    src_by_base: dict[str, list[str]] = {}
    for p in src_paths:
        src_by_base.setdefault(os.path.basename(p), []).append(p)

    for base, ps in sorted(src_by_base.items()):
        if len(ps) > 1:
            rels = [os.path.relpath(x, repo).replace(os.sep, "/") for x in ps]
            details.append(f"來源 lua basename 衝突：{base} 同時來自 {rels}")

    dist_paths = (
        sorted(glob.glob(os.path.join(lua_client, "*.lua")))
        if lua_client and os.path.isdir(lua_client)
        else []
    )
    dist_bases = {os.path.basename(p) for p in dist_paths}
    src_bases = set(src_by_base)

    for missing in sorted(src_bases - dist_bases):
        details.append(f"dist 缺少 lua：{missing}")
    for extra in sorted(dist_bases - src_bases):
        details.append(f"dist 多出 lua：{extra}")

    for base in sorted(src_bases):
        if len(src_by_base[base]) != 1:
            continue  # 衝突已 FAIL，byte/guard 比對無意義
        with open(src_by_base[base][0], "rb") as f:
            sb = f.read()
        if not _LUA_GUARD.search(sb):
            details.append(f"{base}: 缺防護（未含 getActivatedMods/isModActive）")
        if base in dist_bases:
            with open(os.path.join(lua_client, base), "rb") as f:
                db = f.read()
            if sb != db:
                details.append(f"{base}: 來源與 dist bytes 不一致")
    return (not details), details


def check_as1_drift(repo: str, as1_cn: str) -> tuple[bool, list[str], list[str]]:
    """[8] As1 來源漂移：sources/as1_manifest.json 存在時，重算 As1 CN 逐檔 sha256 比對。

    manifest schema：{"<relpath 或 basename>": "<sha256>"}（split 產出的 As1 CN 逐檔 hash）；
    以 basename 正規化比對，只涵蓋 parity 依賴的 *.json 語料。
    不存在 → WARN 一行（不 fail）。
    """
    path = os.path.join(repo, "sources", "as1_manifest.json")
    if not os.path.isfile(path):
        return True, [], ["sources/as1_manifest.json 不存在，跳過 As1 漂移偵測（parity 仍對 live As1）"]

    with open(path, "r", encoding="utf-8-sig") as f:
        raw = json.load(f)
    manifest = raw.get("files", raw) if isinstance(raw, dict) else raw
    if not isinstance(manifest, dict):
        return False, ["as1_manifest.json 格式錯誤：期望 {relpath: sha256} 物件"], []

    # manifest → {basename: sha256}，只認 .json；重複 basename 即 manifest 本身有問題。
    want: dict[str, str] = {}
    details: list[str] = []
    for k, v in manifest.items():
        base = os.path.basename(str(k).replace("\\", "/"))
        if not base.endswith(".json"):
            continue
        if base in want:
            details.append(f"manifest 重複 basename：{base}")
        want[base] = str(v)

    # 重算 As1 CN 現況（parity 讀的同一批 .json）。
    got: dict[str, str] = {}
    if os.path.isdir(as1_cn):
        for name in sorted(os.listdir(as1_cn)):
            if name.endswith(".json"):
                got[name] = _sha256(os.path.join(as1_cn, name))

    drift = "（As1 來源已漂移，parity 結論不可信，請重跑 split 或更新 snapshot）"
    for gone in sorted(set(want) - set(got)):
        details.append(f"As1 少了 {gone}{drift}")
    for added in sorted(set(got) - set(want)):
        details.append(f"As1 多了 {added}{drift}")
    for name in sorted(set(want) & set(got)):
        if want[name] != got[name]:
            details.append(f"As1 內容變動 {name}{drift}")
    return (not details), details, []


# --------------------------------------------------------------------------- #
# --cn-diff：git 層 CN 值變動複核（封住四條 registry/手改盲徑的出口檢查）
# --------------------------------------------------------------------------- #
def _git_show_json(repo: str, ref: str, relpath: str) -> dict | None:
    """讀 <ref>:<relpath> 的 JSON；該 ref 無此檔 → None。"""
    proc = subprocess.run(
        ["git", "-C", repo, "show", f"{ref}:{relpath}"], capture_output=True
    )
    if proc.returncode != 0:
        return None
    data = json.loads(proc.stdout.decode("utf-8-sig"))
    return data if isinstance(data, dict) else None


def cmd_cn_diff(paths: dict, base_ref: str) -> int:
    """列出 base_ref → 現況間 dist CN 值有變、而 CH 真相層未同步變動的鍵。

    觀察「輸出」而非輸入：不論變動來自 As1 同步、cn_overrides、placeholder 例外
    還是 own 層，一律在此匯流受檢。CH 真相層＝`sources/ch/`（corpus 鍵）＋
    `own_translations.json` 的 ch（原創鍵）。已審台帳中 hash 與現行 CN 相符的鍵
    視為已背書，不列待複核。範圍註記：只看現況存在的鍵——被移除的鍵由 build
    corpus gate（孤兒鍵）把關，不在本檢查視野。
    有待複核鍵 → 退出 1（供 release 前把關）；base_ref 無法解析 → 退出 2。
    """
    repo = paths["repo"]
    dist_cn = paths["dist_cn"]
    proc = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        print(f"ERROR：base_ref 無法解析為 commit：{base_ref!r}", file=sys.stderr)
        return 2
    dist_cn_rel = os.path.relpath(dist_cn, repo).replace(os.sep, "/")
    try:
        review_state = _load_review_state(repo)
    except ValueError as exc:
        print(f"⚠️ 已審台帳不可用，本次不套用背書豁免（{exc}）")
        review_state = {}

    def own_ch_map(data: dict | None) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for fname, keys in (data or {}).get("entries", {}).items():
            for key, spec in keys.items():
                if isinstance(spec, dict) and isinstance(spec.get("ch"), str):
                    out.setdefault(fname, {})[key] = spec["ch"]
        return out

    own_path = os.path.join(repo, "sources", "own_translations.json")
    own_new = own_ch_map(_read_json(own_path) if os.path.isfile(own_path) else None)
    own_old = own_ch_map(_git_show_json(repo, base_ref, "sources/own_translations.json"))

    pending: list[str] = []
    n_changed = 0
    for path in sorted(glob.glob(os.path.join(dist_cn, "*.json"))):
        name = os.path.basename(path)
        new_cn = _read_json(path)
        old_cn = _git_show_json(repo, base_ref, f"{dist_cn_rel}/{name}") or {}
        new_ch: dict | None = None
        old_ch: dict = {}
        for key in sorted(new_cn):
            if old_cn.get(key) == new_cn[key]:
                continue
            n_changed += 1
            skey = f"{name}|{key}"
            state_hash = review_state.get(skey)
            if state_hash and isinstance(new_cn[key], str):
                if hashlib.sha256(new_cn[key].encode("utf-8")).hexdigest()[:16] == state_hash:
                    continue  # 已審背書涵蓋現值
            if new_ch is None:  # 惰性載入該檔的 CH 新舊值
                ch_path = os.path.join(repo, "sources", "ch", name)
                new_ch = _read_json(ch_path) if os.path.isfile(ch_path) else {}
                old_ch = _git_show_json(repo, base_ref, f"sources/ch/{name}") or {}
            if key in new_ch or key in old_ch:
                covered = old_ch.get(key) != new_ch.get(key)
            else:
                # 原創鍵：CH 真相在 own_translations 的 ch
                covered = own_old.get(name, {}).get(key) != own_new.get(name, {}).get(key)
            if not covered:
                pending.append(
                    f"  {skey}：CN 值已變但 CH 真相層未動｜新 CN={new_cn[key]!r}"
                )
    print(f"cn-diff（{base_ref} → 現況）：CN 值變動 {n_changed} 鍵、待複核 {len(pending)} 鍵")
    for line in _cap(pending):
        print(line)
    if pending:
        print("→ 逐鍵確認 CH 是否須跟進；確認無須變動者於 ch_review_state.json 登記現值 hash。")
        return 1
    return 0


# --------------------------------------------------------------------------- #
# 冪等子命令
# --------------------------------------------------------------------------- #
def _dist_hash_map(dist_translate: str, lua_client: str | None) -> dict[str, str]:
    """dist 內 .json / language.txt / client lua 的 {相對路徑: sha256}。"""
    result: dict[str, str] = {}
    for pattern in ("**/*.json", "**/language.txt"):
        for path in glob.glob(os.path.join(dist_translate, pattern), recursive=True):
            rel = os.path.relpath(path, dist_translate).replace(os.sep, "/")
            result[rel] = _sha256(path)
    if lua_client and os.path.isdir(lua_client):
        for path in glob.glob(os.path.join(lua_client, "*.lua")):
            result[f"lua/client/{os.path.basename(path)}"] = _sha256(path)
    return result


def cmd_snapshot_dist(dist_translate: str, lua_client: str | None, out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    hashes = _dist_hash_map(dist_translate, lua_client)
    out = os.path.join(out_dir, "dist_hashes.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(hashes, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"已存 {len(hashes)} 個檔案的 hash → {out}")
    return 0


def cmd_compare_dist(dist_translate: str, lua_client: str | None, snap_dir: str) -> int:
    snap_file = os.path.join(snap_dir, "dist_hashes.json")
    if not os.path.isfile(snap_file):
        print(f"FAIL：找不到快照 {snap_file}（請先 --snapshot-dist）")
        return 1
    with open(snap_file, "r", encoding="utf-8") as f:
        old = json.load(f)
    new = _dist_hash_map(dist_translate, lua_client)
    details: list[str] = []
    for rel in sorted(set(old) - set(new)):
        details.append(f"消失：{rel}")
    for rel in sorted(set(new) - set(old)):
        details.append(f"新增：{rel}")
    for rel in sorted(set(old) & set(new)):
        if old[rel] != new[rel]:
            details.append(f"變更：{rel}")
    if details:
        print(f"FAIL：冪等比對發現 {len(details)} 處差異")
        for line in _cap(details):
            print(f"  {line}")
        return 1
    print(f"PASS：冪等比對零 diff（{len(new)} 個檔案）")
    return 0


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def check_vanilla_collision(repo: str, dist_cn: str) -> tuple[bool, list[str], list[str]]:
    """[12] own_translations 原創鍵不得撞 vanilla 鍵名。

    JSON 全量共存＝同鍵全域覆寫本體翻譯，會影響未安裝該 mod 的使用者；
    比對基準與 no-op 豁免登記於 sources/vanilla_keys.json（獨立重讀，不共用 builder 載入）。
    origin=own 的 mod 目錄暫不納入：比對是「裸鍵名」層級，own-mod 的逐地圖檔泛用鍵
    （title/description 等）會與 vanilla 逐地圖檔內同名鍵跨檔假陽性；待清單改檔域
    （fname|key）重生後方可納入——own-mod lane 的 vanilla-override 排除目前仍靠人工
    （見各 metadata note）。
    allowlist 值可為 {"reason", "own_anchor"}；own_anchor＝登記當時 own 條目
    sha256(en|ch|cn)[:16]，值變動即豁免失效（同 cn_overrides/lint_exemptions 錨點慣例）。
    """
    with open(os.path.join(repo, "sources", "vanilla_keys.json"), encoding="utf-8-sig") as f:
        data = json.load(f)
    # 清單完整性 fail-closed：合法 JSON 但形狀壞損（空清單/非字串/非 dict allowlist）
    # 一律擲例外由呼叫端轉 FAIL，不得靜默視為零碰撞。
    keys_raw = data.get("keys")
    if (
        not isinstance(keys_raw, list)
        or len(keys_raw) < 10000  # vanilla EN 鍵量級 4.7 萬；遠低於此＝清單殘缺
        or not all(isinstance(k, str) and k for k in keys_raw)
    ):
        raise ValueError("vanilla_keys.json keys 形狀壞損（須為非空字串清單、量級數萬）")
    allow = data.get("allowlist", {})
    if not isinstance(allow, dict) or not all(
        isinstance(s, dict) and isinstance(s.get("own_anchor"), str) and s["own_anchor"]
        for s in allow.values()
    ):
        raise ValueError("vanilla_keys.json allowlist 形狀壞損（每筆須為含非空 own_anchor 的物件）")
    vanilla = set(keys_raw)
    own = _load_own(repo)
    details: list[str] = []
    for fname, keys in sorted(own.items()):
        for key in sorted(keys):
            if key not in vanilla:
                continue
            spec = allow.get(key)
            if spec is None:
                details.append(
                    f"  {fname}|{key} 撞 vanilla 鍵（覆寫本體翻譯；確認 no-op 後於 vanilla_keys.json allowlist 登記）"
                )
                continue
            entry = keys[key]
            joined = f"{entry.get('en', '')}|{entry.get('ch', '')}|{entry.get('cn', '')}"
            got = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
            if got != spec["own_anchor"]:
                details.append(
                    f"  {fname}|{key} allowlist own_anchor 失效（own 值已變動 {got}≠{spec['own_anchor']}，"
                    "須重新確認 no-op 後更新錨點）"
                )
    # report-only：As1 lane 的「新增」vanilla 碰撞顯性化——已知碰撞登記於
    # as1_overlap_known；不在清單者出 WARN（非阻斷，值層裁決屬人工，台帳見
    # sources/vanilla_overlap_triage.json）。
    #
    # provenance 直接掃 As1 來源（sources/mods/<wid>/CN 排除 origin=own ＋ _unsorted/CN），
    # 不從 dist 反推——dist 混入 own_translations 與 own-mod 鍵，反推會同時假報與漏報。
    # 檔域模型：一般鍵屬全域字串表（任何檔內同名鍵都覆寫本體）；地圖檔泛用鍵
    # （title/description）以檔名查找——vanilla 自身多個地圖檔各帶同名鍵而不互撞——
    # 故以 vendor 的精確 (檔|鍵) 對判定，避免鍵集×檔名集的笛卡兒積誤報。
    known_raw = data.get("as1_overlap_known", [])
    pairs_raw = data.get("vanilla_scoped_pairs", [])
    if not isinstance(known_raw, list) or not all(isinstance(x, str) for x in known_raw):
        raise ValueError("vanilla_keys.json as1_overlap_known 形狀壞損（須為字串清單）")
    if not isinstance(pairs_raw, list) or not all(isinstance(x, str) and "|" in x for x in pairs_raw):
        raise ValueError("vanilla_keys.json vanilla_scoped_pairs 形狀壞損（須為 '檔|鍵' 字串清單）")
    warns: list[str] = []
    known = set(known_raw)
    scoped_pairs = set(pairs_raw)
    generic = {"title", "description"}
    current: set[str] = set()
    for fname, keys in sorted(_load_as1_lane_cn(repo, warns).items()):
        for key in sorted(keys):
            pair = f"{fname}|{key}"
            hit = pair in scoped_pairs if key in generic else key in vanilla
            if not hit:
                continue
            current.add(pair)
            if pair not in known:
                warns.append(f"  新增 vanilla 碰撞（As1 lane）：{pair}（裁決後補登 as1_overlap_known）")
    for stale in sorted(known - current):
        warns.append(f"  as1_overlap_known 陳舊條目：{stale}（As1 來源已無此碰撞，建議清理以防同鍵回歸被靜默放行）")
    return not details, details, warns


def _load_as1_lane_cn(repo: str, warns: list[str]) -> dict[str, set[str]]:
    """As1 lane 的 (檔 → 鍵集)：sources/mods/<wid>/CN 排除 origin=='own' ＋ sources/_unsorted/CN。

    獨立重讀（不共用 builder 收集函式），與 verify 的 oracle 原則一致。
    """
    out: dict[str, set[str]] = {}
    cn_dirs: list[str] = []
    mods_dir = os.path.join(repo, "sources", "mods")
    for wid in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        mod_dir = os.path.join(mods_dir, wid)
        meta_path = os.path.join(mod_dir, "metadata.json")
        try:
            with open(meta_path, encoding="utf-8-sig") as f:
                if json.load(f).get("origin") == "own":
                    continue
        except (OSError, json.JSONDecodeError):
            warns.append(f"  {wid}/metadata.json 無法解析，該 mod 併入 As1 lane 掃描（保守）")
        cn = os.path.join(mod_dir, "CN")
        if os.path.isdir(cn):
            cn_dirs.append(cn)
    unsorted_cn = os.path.join(repo, "sources", "_unsorted", "CN")
    if os.path.isdir(unsorted_cn):
        cn_dirs.append(unsorted_cn)
    for cn in cn_dirs:
        for path in sorted(glob.glob(os.path.join(cn, "*.json"))):
            fname = os.path.basename(path)
            try:
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                warns.append(f"  {path} 無法解析，跳過碰撞掃描")
                continue
            if isinstance(data, dict):
                out.setdefault(fname, set()).update(data)
    return out


def run_all(paths: dict) -> int:
    repo = paths["repo"]
    as1_cn = paths["as1_cn"]
    dist_translate = paths["dist_translate"]
    dist_cn, dist_ch = paths["dist_cn"], paths["dist_ch"]
    lua_client = paths["lua_client"]

    print("=" * 64)
    print(" verify_dist.py — 獨立驗證器（oracle）")
    print("=" * 64)
    print(f" As1 CN : {as1_cn}")
    print(f" dist   : {dist_translate}")
    print()

    if not os.path.isdir(as1_cn):
        print(f"ERROR：As1 快照 CN 目錄不存在：{as1_cn}")
        return 1

    try:
        exceptions = _load_exceptions(repo)
    except Exception as exc:  # noqa: BLE001 — 例外檔壞掉直接判 FAIL
        print(f"ERROR：placeholder_exceptions.json 無法解析（{exc}）")
        return 1
    try:
        cn_overrides = _load_cn_overrides(repo)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR：cn_overrides.json 無法解析（{exc}）")
        return 1
    try:
        own = _load_own(repo)
        for fname, keys in _load_own_mods(repo).items():
            bucket = own.setdefault(fname, {})
            for key, entry in keys.items():
                if key in bucket:
                    raise ValueError(
                        f"原創鍵重複登錄：{fname}|{key} 同時存在於 own_translations 與原創 mod 目錄"
                    )
                bucket[key] = entry
    except Exception as exc:  # noqa: BLE001 — 原創層檔壞掉直接判 FAIL
        print(f"ERROR：原創翻譯層無法解析（{exc}）")
        return 1

    ok1, d1, w1, n_exc, n_own = check_cn_parity(
        as1_cn, dist_cn, exceptions, own, cn_overrides
    )
    ok2, d2 = check_ch_mirror(dist_cn, dist_ch)
    ok3, d3 = check_encoding(dist_translate)
    ok4, d4_fail, d4_warn = check_placeholder(dist_cn, dist_ch, exceptions)
    ok6, d6 = check_language_txt(dist_cn, dist_ch)
    ok7, d7 = check_lua(repo, lua_client)
    ok8, d8, w8 = check_as1_drift(repo, as1_cn)
    try:
        ok9, d9 = check_ch_corpus_parity(repo, dist_ch, own)
    except Exception as exc:  # noqa: BLE001 — corpus 壞掉直接判 FAIL
        ok9, d9 = False, [f"corpus 無法載入（{exc}）"]
    try:
        ok10, d10 = check_sync_worklist(repo)
    except Exception as exc:  # noqa: BLE001
        ok10, d10 = False, [f"worklist 無法載入（{exc}）"]
    try:
        ok11, d11, w11 = check_review_drift(repo, dist_cn)
    except Exception as exc:  # noqa: BLE001
        ok11, d11, w11 = False, [f"review_state 無法載入（{exc}）"], []
    try:
        ok12, d12, w12 = check_vanilla_collision(repo, dist_cn)
    except Exception as exc:  # noqa: BLE001 — 清單檔缺失/壞損直接判 FAIL（gate 資料是受版控真相）
        ok12, d12, w12 = False, [f"vanilla_keys.json 無法載入（{exc}）"], []

    rows = [
        ("1", "CN 逐檔 parity", ok1, d1, w1),
        ("2", "CH 鏡像", ok2, d2, []),
        ("3", "編碼（UTF-8 無 BOM）", ok3, d3, []),
        ("4", "placeholder", ok4, d4_fail, d4_warn),
        ("6", "language.txt", ok6, d6, []),
        ("7", "lua 防護", ok7, d7, []),
        ("8", "As1 來源漂移", ok8, d8, w8),
        ("9", "CH corpus parity", ok9, d9, []),
        ("10", "sync worklist", ok10, d10, []),
        ("11", "已審鍵 CN 漂移（WARN-only）", ok11, d11, w11),
        ("12", "vanilla 鍵碰撞", ok12, d12, w12),
    ]

    n_pass = sum(1 for _, _, ok, _, _ in rows if ok)
    n_fail = sum(1 for _, _, ok, _, _ in rows if not ok)
    n_warn = sum(len(warn) for _, _, _, _, warn in rows)

    for num, name, ok, _det, warn in rows:
        status = "PASS" if ok else "FAIL"
        tail = f"  (WARN {len(warn)})" if warn else ""
        print(f" [{num}] {name:.<28} {status}{tail}")
    print("-" * 64)
    print(f" 例外鍵 {n_exc} 個已依登記值核對；原創鍵 {n_own} 個已依 own cn 核對")
    overall = "PASS" if n_fail == 0 else "FAIL"
    print(f" 結果：{overall}  (PASS {n_pass} / FAIL {n_fail} / WARN {n_warn})")
    print("=" * 64)

    for num, name, ok, det, warn in rows:
        if not ok and det:
            print(f"\n--- [{num}] {name} 失敗明細（上限 {DETAIL_CAP}）---")
            for line in _cap(det):
                print(f"  {line}")
        if warn:
            print(f"\n--- [{num}] {name} WARNING（上限 {DETAIL_CAP}，不影響退出碼）---")
            for line in _cap(warn):
                print(f"  {line}")

    return 0 if n_fail == 0 else 1


def main(argv: list[str] | None = None) -> int:
    default_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description="MinidoracatModLangFor42 dist 獨立驗證器")
    parser.add_argument("--repo", default=default_repo, help="repo 根目錄（預設：本檔上兩層）")
    parser.add_argument("--snapshot", default=None, help="snapshot.json 路徑（預設：<repo>/sources/snapshot.json）")
    parser.add_argument("--snapshot-dist", metavar="DIR", help="把 dist 現況 hash 存到 <DIR>/dist_hashes.json")
    parser.add_argument("--compare-dist", metavar="DIR", help="比對 dist 現況與 <DIR>/dist_hashes.json（有 diff 退出 1）")
    parser.add_argument(
        "--cn-diff", metavar="BASE_REF",
        help="列出 BASE_REF→現況 dist CN 值變動而 sources/ch 未同步、亦無已審背書的鍵（有即退出 1）",
    )
    args = parser.parse_args(argv)

    repo = os.path.abspath(args.repo)
    snapshot_path = args.snapshot or os.path.join(repo, "sources", "snapshot.json")
    if not os.path.isfile(snapshot_path):
        print(f"ERROR：snapshot.json 不存在：{snapshot_path}")
        return 1

    paths = _resolve_paths(repo, snapshot_path)
    dist_translate, dist_cn = paths["dist_translate"], paths["dist_cn"]
    lua_client = paths["lua_client"]

    # dist 尚未 build → 明確報錯退出 1（CN/CH 目錄可能存在但無 .json）。
    if not _dist_is_built(dist_cn):
        print(f"ERROR：dist 不存在或尚未 build（找不到 .json）：{dist_cn or paths['dist_translate']}")
        return 1

    if args.snapshot_dist:
        return cmd_snapshot_dist(dist_translate, lua_client, args.snapshot_dist)
    if args.compare_dist:
        return cmd_compare_dist(dist_translate, lua_client, args.compare_dist)
    if args.cn_diff is not None:
        return cmd_cn_diff(paths, args.cn_diff)
    return run_all(paths)


if __name__ == "__main__":
    sys.exit(main())
