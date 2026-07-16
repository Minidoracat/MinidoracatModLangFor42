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
    as1_cn: str, dist_cn: str, exceptions: dict[str, dict]
) -> tuple[bool, list[str], list[str], int]:
    """[1] dist CN 對 As1 快照：檔案集合 + 逐檔鍵集 + 逐鍵值逐字一致。

    登記例外鍵（sources/placeholder_exceptions.json）改判「dist CN 值 == cn_safe_value」，
    不再要求等於 As1 原值。回傳 (ok, details, warn, applied_count)。
    """
    as1_files, as1_err = _load_json_dir(as1_cn)
    dist_files, dist_err = _load_json_dir(dist_cn)
    details: list[str] = []
    warn: list[str] = []
    details += [f"As1 {e}" for e in as1_err]
    details += [f"dist {e}" for e in dist_err]

    as1_set, dist_set = set(as1_files), set(dist_files)
    for missing in sorted(as1_set - dist_set):
        details.append(f"檔案缺少：dist 少了 {missing}")
    for extra in sorted(dist_set - as1_set):
        details.append(f"檔案多出：dist 多了 {extra}")

    applied: set[str] = set()  # 實際命中 dist(檔,鍵) 的例外
    for fname in sorted(as1_set & dist_set):
        a, d = as1_files[fname], dist_files[fname]
        ak, dk = set(a), set(d)
        for mk in sorted(ak - dk):
            details.append(f"{fname}: 缺鍵 {mk!r}")
        for ek in sorted(dk - ak):
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
            elif a[key] != d[key]:
                details.append(
                    f"{fname}: 鍵 {key!r} 值不符 | As1={a[key]!r} dist={d[key]!r}"
                )

    # 登記但未命中任何 dist(檔,鍵) 的例外 → WARN（多半是打錯 key 名）
    for ekey in sorted(set(exceptions) - applied):
        warn.append(f"例外鍵 {ekey!r} 未對應任何 dist CN(檔,鍵)，登記可能過期或打錯")

    return (not details), details, warn, len(applied)


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
      * format-token 值殘留字面 `%.`（JDK format crash 簽名）——CN/CH 任一側出現即 FAIL，
        即使兩邊對稱也不放行。
      * grammar token multiset 不一致（%1/%s/%.1f/%% 等被增刪改）。
    WARN：可疑（非 grammar）% 的**數量**在 CN/CH 不一致（純字面 % 的 OpenCC 轉換誤差）。
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
            cg, cs = extract_tokens(cn[key]) if isinstance(cn[key], str) else ([], [])
            hg, hs = extract_tokens(ch[key]) if isinstance(ch[key], str) else ([], [])

            if not exempt:
                # crash 簽名：CN/CH 各自獨立判定（對稱也 FAIL）
                if has_crash_signature(cn[key]):
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
            # WARN 對例外鍵仍照列（只是不影響退出碼）
            if len(cs) != len(hs):
                warn.append(
                    f"{fname}: 鍵 {key!r} 可疑 % 數量 CN={len(cs)}({cs}) CH={len(hs)}({hs})"
                )
    return (not fail), fail, warn


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

    ok1, d1, w1, n_exc = check_cn_parity(as1_cn, dist_cn, exceptions)
    ok2, d2 = check_ch_mirror(dist_cn, dist_ch)
    ok3, d3 = check_encoding(dist_translate)
    ok4, d4_fail, d4_warn = check_placeholder(dist_cn, dist_ch, exceptions)
    ok6, d6 = check_language_txt(dist_cn, dist_ch)
    ok7, d7 = check_lua(repo, lua_client)
    ok8, d8, w8 = check_as1_drift(repo, as1_cn)

    rows = [
        ("1", "CN 逐檔 parity", ok1, d1, w1),
        ("2", "CH 鏡像", ok2, d2, []),
        ("3", "編碼（UTF-8 無 BOM）", ok3, d3, []),
        ("4", "placeholder", ok4, d4_fail, d4_warn),
        ("6", "language.txt", ok6, d6, []),
        ("7", "lua 防護", ok7, d7, []),
        ("8", "As1 來源漂移", ok8, d8, w8),
    ]

    n_pass = sum(1 for _, _, ok, _, _ in rows if ok)
    n_fail = sum(1 for _, _, ok, _, _ in rows if not ok)
    n_warn = sum(len(warn) for _, _, _, _, warn in rows)

    for num, name, ok, _det, warn in rows:
        status = "PASS" if ok else "FAIL"
        tail = f"  (WARN {len(warn)})" if warn else ""
        print(f" [{num}] {name:.<28} {status}{tail}")
    print("-" * 64)
    print(f" 例外鍵 {n_exc} 個已依登記值核對")
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
    return run_all(paths)


if __name__ == "__main__":
    sys.exit(main())
