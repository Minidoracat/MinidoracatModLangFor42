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
  ※ As1 快照樹缺席（Steam 覆蓋了 Workshop 版本目錄）時 [1]/[8] 判 **SKIP**，其餘照跑；
    SKIP≠PASS，退出碼仍為 1，除非明示 --allow-missing-as1。
  [1] CN 逐檔 parity：dist CN/*.json 對 sanitize(As1 快照值) 逐檔逐鍵一致
      （42.20.1 formatted() 安全逸出後的應出貨值；登記例外鍵改為對
      sanitize(cn_safe_value) 核對，見 sources/placeholder_exceptions.json）
  [2] CH 鏡像       ：dist CH/*.json 與 dist CN 檔案集合、逐檔鍵集一致（值不比）
  [3] 編碼          ：dist 全部 .json 為 UTF-8 無 BOM 且可解析
  [4] placeholder   ：dist 兩側殘留 grammar 外的必炸 % 序列 → FAIL（42.20.1 硬性）；
                      format-token 值殘留 `%.` → FAIL（JDK format crash 簽名）；
                      token multiset 不符（%% 不入 multiset）→ FAIL
  [6] language.txt  ：CH/CN 目錄各有 language.txt 且 text 欄位正確
  [7] lua 防護       ：dist media/lua/client/*.lua 與 sources/lua/*/*.lua basename 集合、
                      逐檔 bytes 一致，且每檔含 getActivatedMods/isModActive 防護
  [8] As1 來源漂移   ：sources/as1_manifest.json 存在時重算 As1 CN 逐檔 sha256 比對
  [9] CH corpus parity：dist CH 逐檔逐鍵值對 sources/ch/ 人工真相 corpus 逐字一致
                      （原創鍵對 own_translations 的 ch；CH 已斷絕 OpenCC 機轉，值有真相源）
  [10] sync worklist ：sources/ch_sync_worklist.json 未處理條目必須清空（上游變更未反映不得出貨）
  [11] 已審鍵漂移     ：ch_review_state.json 已審鍵重算現行 CN hash，不符 → WARN（須重審）
  [12] vanilla 鍵碰撞 ：own 原創鍵不得撞 vanilla 鍵名（JSON 全量共存＝全域覆寫，
                      會影響未安裝該 mod 的使用者）
  [13] 檔名可載入性   ：有前綴路由的鍵不得只存在於 PZ 不會載入的檔名裡（放錯＝永遠取不到）；
                      上游查無同名鍵者＝作廢鍵名 → WARN
  [14] own 層 CN 用字 ：own 層 CN 不得殘留 t2s 抓不到的台灣字形（助詞「著」須寫「着」、
                      「牠」「妳」、直角引號）——只掃 own，As1 快照忠實鏡像不歸本項管
  [15] ItemName 死鍵  ：`ItemName_<M>.<I>` 是 B41 鍵形，B42 只查裸 `<M>.<I>`（反編譯實證）；
                      前綴鍵無裸鍵對應＝玩家看到英文。豁免須登記 itemname_dead_allowlist.json。
                      **`Base.` 不等於本體**——MOD 也能往 module Base 加物品，只認 vanilla scoped 基準
  [16] Recipes 死鍵   ：`Recipe_<X>`／`craftRecipe_<X>` 是 B41 配方鍵形，B42 只查裸
                      craftRecipe 區塊名（Translator.getRecipeName→recipe.get(name)）；
                      去前綴後對得上上游現行區塊名、卻沒出貨該裸鍵＝玩家看到英文配方名。
                      豁免須登記 recipe_dead_allowlist.json

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# [16] 的有效版本分支判定沿用 tracker 的實作，不另寫第二套（AGENTS.md 明載勿分岔）。
import tracker  # noqa: E402

# dist 內層 Translate 目錄（相對 repo 根）的 glob；避免硬編長資料夾名，
# 執行期以實際存在的路徑為準（模板慣例：資料夾=長名、mod.info id=短名）。
DIST_TRANSLATE_GLOB = "MOD/*/Contents/mods/*/42/media/lua/shared/Translate"

# As1 CN 語料相對 <local_path>/<source_tree> 的子路徑。
AS1_CN_SUBPATH = "media/lua/shared/Translate/CN"

# placeholder grammar：與 build_mod.py 的文法定義對齊（153 個合法 %.1f 不可誤殺）。
# 順序即優先序：%% > %.Nf（可帶 + 旗標）> %N（%1-%9 位置參數）> %s/%d。
# %i 已自 grammar 移除：42.20.1 Translator 對 getText 結果強制 String.formatted()，
# Java 無 %i 轉換符（UnknownFormatConversionException 未被捕捉＝主選單黑畫面）。
# 編號佔位收緊為 %[1-9]（原 %\d+）：遊戲 FORMAT_TOKEN 為 %%|%([1-9])，%0 不在其內、
# formatted() 對其必炸——若當合法 token 吸收，[4] 的必炸殘留檢查會靜默漏掉 %0 類序列。
# 未被此文法吸收的 % 一律歸「可疑」桶——sanitize 後 dist 不得殘留任何可疑 %（[4] FAIL）。
# precision 一律 ASCII [0-9] 且限 2 位：\d 是 Unicode-aware（%.١f 會被誤判為合法，
# 而 JDK 拋 UnknownFormatConversionException）；無上限則 %.2147483648f 會拋
# IllegalFormatPrecisionException。兩者皆非 MissingFormatArgumentException＝未被捕＝崩潰。
_PREC = r"%\+?\.[0-9]{1,2}f"
# 「佔位符緊接 %%」整體吸收為單一 token（格式單位，CN/CH 須配對）——順序在前。
# 與獨立字面 %%（自 multiset 排除，允許「百分之…」譯法）區隔；獨立實作對齊 builder。
_GRAMMAR = re.compile(rf"(?:%[1-9]|%[sd]|{_PREC})%%|%%|{_PREC}|%[1-9]|%[sd]")
# dist 不得殘留任何 `%<數字>$` 形式：sanitize 會把合法的 %N$<conv> 正規化為 %N，
# 殘留者即歧義值（%1$s$A）或超出 PZ %1-%9 的 index（%10$s）——兩者 formatFixer
# 都處理不了，顯示必然損壞，一律 fail-loud 交人工裁決。
_POSITIONAL_AT = re.compile(r"%[0-9]+\$")
# 「`%%` 後面接的是一個已經安全的 token」＝上游逸出過頭的簽名（見 as1_expectation）
_OVER_ESCAPE_TAIL = re.compile(r"(?:[1-9]|s|d|\.\d+f|\+\.\d+f)")


def has_positional_residue(value: str) -> bool:
    """找 `%<數字>$` 殘留——**left-to-right 掃描且先消費字面 `%%`**。

    不可用全域 search：那會穿透逸出。`%%1$s` 是「字面百分號＋文字 `1$s`」，
    formatFixer 保持原樣、`.formatted()` 顯示 `%1$s`，本來就是安全值；
    但 search 會從第二個 `%` 命中 `%1$` 而誤報（`%%0$s`、`%%10$s`、`%%%%1$s` 同）。
    negative lookbehind 也不夠——`%%%1$s` 的第三個 `%` 才是真殘留。
    與 sanitize 同一套優先序，兩處必須一起改。
    """
    i, n = 0, len(value)
    while i < n:
        if value[i] != "%":
            i += 1
        elif value.startswith("%%", i):
            i += 2
        elif _POSITIONAL_AT.match(value, i):
            return True
        else:
            i += 1
    return False

# sanitize 期望值語意（獨立實作，與 builder 同語意不共用碼）：
# build 對合併後 CN 全量逸出裸 %——oracle 對 As1 原值/registry 登記值套同一轉換
# 得到「應出貨值」再核對 parity。安全 token 對齊遊戲 FORMAT_TOKEN（%%|%[1-9]）
# 與 .formatted() 可捕捉集（%s/%d/%.Nf/%+.Nf）；其餘 % 逸出為 %%。
_SANITIZE_TOKEN = re.compile(rf"{_PREC}|%[1-9]|%[sd]")
# Java 完整位置參數 `%N$<conversion>` → PZ 簡寫 %N（formatFixer 自行補 $s，
# 寫全形式會疊成 %N$s$s 導致顯示損壞）。conversion 須完整消費：date/time 為
# [tT] 後再接一字母，只吃 t 會留下孤兒字母。與 builder 的 _POSITIONAL_RE 同語意。
# flags 有界重複（見 builder 同名常數註解）：與 width `[0-9]*` 在 `0` 上重疊，
# 無界時對長 0 串的失敗匹配呈 O(N²) 回溯。
_POSITIONAL = re.compile(
    r"%([1-9])\$[-#+ 0,(]{0,8}[0-9]*(?:\.[0-9]+)?(?:[tT][a-zA-Z]|[a-zA-Z])"
)


def restore_over_escape(value: str) -> str:
    """只做「還原上游過度逸出」：`%%`+安全 token → `%`、`%%%%` → `%%`，迭代至定點。

    獨立實作（不 import builder）：上游把已安全的 `%1`/`%s`/`%.2f` 又逸出一次，
    照收會讓佔位符變字面文字；全域 `%`→`%%` 另使合法字面 `%%` 變成 `%%%%`。

    與 `as1_expectation` 分開是因為 **`as1_value` 錨點記的是 As1 原值、不是應出貨值**，
    比對錨點時只能還原、不可再套 sanitize。
    """
    if "%%" not in value:
        return value
    prev = None
    cur = value
    guard = 0
    while cur != prev and guard < 8:
        prev, guard = cur, guard + 1
        buf: list[str] = []
        i = 0
        while i < len(cur):
            if cur.startswith("%%%%", i):
                buf.append("%%")
                i += 4
                continue
            if cur.startswith("%%", i) and _OVER_ESCAPE_TAIL.match(cur, i + 2):
                buf.append("%")
                i += 2
                continue
            buf.append(cur[i])
            i += 1
        cur = "".join(buf)
    return cur


def as1_expectation(value: object) -> object:
    """As1 原值 → build 應出貨形式：**先還原上游過度逸出，再套 sanitize**。

    只用於 As1 原值比對。registry 值（cn_safe_value / cn_overrides value）是人工
    直寫真相，不套還原——那層必須直寫正確形式，錯了就要 fail-loud。
    """
    if not isinstance(value, str):
        return sanitize_expectation(value)
    return sanitize_expectation(restore_over_escape(value))


def sanitize_expectation(value: object) -> object:
    """把期望值（As1 原值 / cn_safe_value / cn_overrides value）轉為 build 應出貨形式。

    left-to-right 單次掃描，`%%` 最優先消費——不可用全域 sub 前置改寫位置參數，
    那會穿透字面 `%%`（`%%1$s` → `%%1`）。緊接另一 `$` 的歧義值保守不轉以保冪等，
    由 [4] 的 `%N$` 殘留檢查 fail-loud。非字串原樣返還（parity 對非字串仍逐字比對）。
    own 層（own_translations cn / 原創 mod 目錄 CN）為人工直寫真相，**不套本轉換**
    ——真相檔必須直寫安全值，dist 與其不一致即 FAIL（fail-loud 逼修真相檔）。
    """
    if not isinstance(value, str) or "%" not in value:
        return value
    out: list[str] = []
    i, n = 0, len(value)
    while i < n:
        if value[i] != "%":
            out.append(value[i])
            i += 1
            continue
        if value.startswith("%%", i):
            out.append("%%")
            i += 2
            continue
        pos = _POSITIONAL.match(value, i)
        if pos and not value.startswith("$", pos.end()):
            out.append(f"%{pos.group(1)}")
            i = pos.end()
            continue
        m = _SANITIZE_TOKEN.match(value, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        out.append("%%")
        i += 1
    return "".join(out)

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

    格式化字串（含 %N/%s/%d/%.Nf 任一）若又出現未構成 %.Nf 的 `%.`，
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
# vanilla 必有的核心字串檔（獨立列舉，不共用 builder 常數——oracle 原則）
VANILLA_CORE_FILES = frozenset({
    "ItemName.json", "UI.json", "IG_UI.json", "ContextMenu.json", "Tooltip.json",
    "Recipes.json", "Sandbox.json", "Fluids.json", "Moveables.json", "Moodles.json",
})


def _load_vanilla_basis(repo: str) -> tuple[dict[str, set[str]], dict[str, dict]]:
    """vanilla 檔域鍵基準與 keep 豁免（獨立重讀，不共用 builder 載入）。

    形狀壞損一律擲例外由呼叫端轉 FAIL——合法 JSON 但基準殘缺若靜默視為「零 vanilla 鍵」，
    出貨抑制與 [12] 會同時失效，等於本體覆寫防線整個消失。
    """
    with open(os.path.join(repo, "sources", "vanilla_keys.json"), encoding="utf-8-sig") as f:
        data = json.load(f)
    scoped = data.get("scoped_keys")
    if not isinstance(scoped, dict) or not scoped:
        raise ValueError("vanilla_keys.json scoped_keys 缺失或非物件")
    union: set[str] = set()
    for fname, ks in scoped.items():
        if not isinstance(fname, str) or not fname:
            raise ValueError(f"vanilla_keys.json scoped_keys 檔名非法：{fname!r}")
        if not isinstance(ks, list) or not all(isinstance(k, str) and k for k in ks):
            raise ValueError(f"vanilla_keys.json scoped_keys[{fname}] 非非空字串清單")
        if len(set(ks)) != len(ks):
            raise ValueError(f"vanilla_keys.json scoped_keys[{fname}] 有重複鍵")
        union.update(ks)
    # **量級門檻不足以 fail-closed**：整個 ItemName.json bucket 消失後仍有 42,364 鍵、
    # 同鍵重複萬次也能湊數，兩者都會讓該檔的抑制整批靜默失效。故另驗結構不變式。
    if missing := VANILLA_CORE_FILES - set(scoped):
        raise ValueError(f"vanilla_keys.json 缺少核心字串檔 {sorted(missing)}")
    if len(scoped) < 30 or len(union) < 10000:
        raise ValueError(
            f"vanilla_keys.json 基準殘缺（{len(scoped)} 檔／{len(union)} 鍵；vanilla 量級 43 檔／4.7 萬鍵）"
        )
    if set(data.get("keys") or []) != union:
        raise ValueError("vanilla_keys.json keys 與 scoped_keys 聯集不一致（基準只重生了一半？）")
    keep = data.get("keep", {})
    # 2026-08-12 使用者裁決：不得覆蓋本體任何一個現有 EN/CH/CN 鍵，一個都不行。
    # oracle 獨立再擋一次——build 端若被繞過，這裡仍會炸。
    if keep:
        raise ValueError(
            f"vanilla_keys.json 的 keep 有 {len(keep)} 條登記（{sorted(keep)[:5]}）；"
            "本包不得覆蓋本體任何現有翻譯鍵，keep 必須維持全空"
        )
    if not isinstance(keep, dict) or not all(
        isinstance(s, dict)
        and isinstance(s.get("anchor"), str)
        and s["anchor"]
        and isinstance(s.get("reason"), str)
        and s["reason"].strip()
        for s in keep.values()
    ):
        raise ValueError("vanilla_keys.json keep 形狀壞損（每筆須為含非空 anchor 與非空 reason 的物件）")
    return {f: set(ks) for f, ks in scoped.items()}, keep


def suppressed_pairs(repo: str) -> set[str]:
    """出貨抑制的 (檔|鍵)：vanilla 檔域鍵扣掉 keep 登記，再加上 unshipped_keys 登記。

    dist 面向的期望（[1] 缺鍵、[9] corpus 落地、[11] 已審鍵在位）一律扣除本集合——
    真相層仍保有這些鍵（As1 CN 是 canonical import、corpus 是人工真相），
    抑制只發生在出貨那一步。

    `unshipped_keys.json` 是第二個來源：鍵落在 PZ 不載入的檔名、且找不到正確落點者
    （見該檔 `_rule`）。兩者語意相同，故共用同一個扣除集合。
    """
    scoped, keep = _load_vanilla_basis(repo)
    pairs = {f"{f}|{k}" for f, ks in scoped.items() for k in ks} - set(keep)
    path = os.path.join(repo, "sources", "unshipped_keys.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            pairs |= set(json.load(f).get("entries", {}))
    return pairs


def check_cn_parity(
    as1_cn: str,
    dist_cn: str,
    exceptions: dict[str, dict],
    own: dict[str, dict],
    cn_overrides: dict[str, dict] | None = None,
    as1_available: bool = True,
    suppressed: set[str] | None = None,
    unshipped: set[str] | None = None,
) -> tuple[bool, list[str], list[str], int, int]:
    """[1] dist CN 對 As1 快照：檔案集合 + 逐檔鍵集 + 逐鍵值逐字一致。

    三類登記偏離改判（優先序同 build：placeholder 例外最後套故最優先）：
      1. sources/placeholder_exceptions.json → 「dist CN 值 == cn_safe_value」
      2. sources/cn_overrides.json           → 「dist CN 值 == value」（修上游錯誤）
      3. sources/own_translations.json       → 合法「多鍵/多檔」，「dist CN 值 == own cn」
    回傳 (ok, details, warn, applied_count, own_count)。

    ``as1_available=False``（快照樹被 Steam 覆蓋而消失）時**只降級 As1 相關比對**：
    檔案集合、缺鍵/多鍵、以及對 As1 原值的 parity 一律跳過。**其餘照驗**——
    own CN 值、placeholder 例外安全值、cn_overrides 登記值、原創鍵落地完整性都
    不依賴 As1，整個函式一起 SKIP 會讓 `--allow-missing-as1` 在這些真相層損壞時
    仍然 exit 0，等於把獨立 oracle 讓掉一大半。
    """
    cn_overrides = cn_overrides or {}
    suppressed = suppressed if suppressed is not None else set()
    unshipped = unshipped if unshipped is not None else set()
    as1_files, as1_err = ({}, []) if not as1_available else _load_json_dir(as1_cn)
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
    if as1_available:
        for missing in sorted(as1_set - dist_set):
            details.append(f"檔案缺少：dist 少了 {missing}")
    for extra in sorted(dist_set - as1_set):
        # 純原創檔（As1 無此檔）：逐鍵核對 own；任何非原創鍵仍屬違規。
        # As1 缺席時整個 dist 都落在這裡，無從判斷「該不該有」——只驗 own 值，不報多出。
        for key in sorted(dist_files[extra]):
            if not check_own_key(extra, key, dist_files[extra][key]) and as1_available:
                details.append(f"檔案多出：dist 多了 {extra}（含非原創鍵 {key!r}）")

    applied_cn_ov: set[str] = set()  # 實際命中的 CN 修正鍵
    applied: set[str] = set()  # 實際命中 dist(檔,鍵) 的例外
    # As1 缺席時仍逐檔走一遍 dist——例外／override 的值層核對不依賴 As1，不可一起跳過。
    for fname in sorted(as1_set & dist_set) if as1_available else sorted(dist_set):
        a, d = as1_files.get(fname, {}), dist_files[fname]
        ak, dk = set(a), set(d)
        if as1_available:
            for mk in sorted(ak - dk):
                if f"{fname}|{mk}" in suppressed:
                    continue  # vanilla 同名鍵：build 刻意不出貨（本體譯文優先）
                details.append(f"{fname}: 缺鍵 {mk!r}")
            for ek in sorted(dk - ak):
                if not check_own_key(fname, ek, d[ek]):
                    details.append(f"{fname}: 多鍵 {ek!r}")
        else:
            for ek in sorted(dk):
                check_own_key(fname, ek, d[ek])  # own 值照驗，非 own 無從判斷
        for key in sorted(dk if not as1_available else (ak & dk)):
            # 期望值一律過 sanitize_expectation（As1 原值與 registry 登記值皆為
            # sanitize 前語意，build 出貨前會逸出裸 %；own 鍵不在本迴圈——
            # ak & dk 僅含 As1 鍵，own 層於 check_own_key 以原值核對）。
            exc = exceptions.get(f"{fname}|{key}")
            if isinstance(exc, dict) and isinstance(exc.get("cn_safe_value"), str):
                # 例外鍵：與登記安全值核對（不再對 As1 原值）
                applied.add(f"{fname}|{key}")
                if d[key] != sanitize_expectation(exc["cn_safe_value"]):
                    details.append(
                        f"{fname}: 例外鍵 {key!r} 未套用安全值 | "
                        f"dist={d[key]!r} 應為 sanitize(cn_safe_value)="
                        f"{sanitize_expectation(exc['cn_safe_value'])!r}"
                    )
            elif isinstance(
                (cov := cn_overrides.get(f"{fname}|{key}")), dict
            ) and isinstance(cov.get("value"), str):
                # CN 人工修正鍵：與登記值核對（不再對 As1 原值）
                applied_cn_ov.add(f"{fname}|{key}")
                if d[key] != sanitize_expectation(cov["value"]):
                    details.append(
                        f"{fname}: CN 修正鍵 {key!r} 未套用登記值 | "
                        f"dist={d[key]!r} 應為 sanitize(value)="
                        f"{sanitize_expectation(cov['value'])!r}"
                    )
            elif key in a and as1_expectation(a[key]) != d[key]:
                # `key in a` 守門：As1 缺席時 a 為空，此比對無從進行（其餘核對照跑）
                details.append(
                    f"{fname}: 鍵 {key!r} 值不符 | 期望(As1 還原+sanitize)="
                    f"{as1_expectation(a[key])!r} dist={d[key]!r}"
                )

    # 登記但未命中任何 dist(檔,鍵) 的例外 → WARN（多半是打錯 key 名）。
    # 抑制鍵不算「登記過期」：registry 仍作用於合併結果（真相層照樣被修正），
    # 只是最後不出貨；把它們列進來會讓真正打錯的登記淹沒在噪音裡。
    for label, reg, hit in (
        ("例外鍵", exceptions, applied),
        ("CN 修正鍵", cn_overrides, applied_cn_ov),
    ):
        for rkey in sorted(set(reg) - hit):
            if rkey in suppressed:
                # 登記仍有作用：placeholder / CH 值層等 gate 跑在出貨抑制之前，對完整合併
                # 結果把關，退役這類登記會讓真相層失去校驗（實測會直接炸 placeholder gate）。
                # 故只提示「不出貨」，**不要建議退役**。
                warn.append(f"{label} {rkey!r} 命中出貨抑制鍵（本體同名，僅作用於 gate 前的合併結果，不出貨）")
            else:
                warn.append(f"{label} {rkey!r} 未對應任何 dist CN(檔,鍵)，登記可能過期或打錯")

    # registry as1_value 錨點漂移 → WARN（上游已自行修正，override/例外可能該退役；
    # 鏡射 build 的同名警告到 oracle 報表，讓它出現在發布前必看的地方）
    for reg_label, reg in (("cn_overrides", cn_overrides), ("placeholder_exceptions", exceptions)):
        for rkey, spec in sorted(reg.items()):
            anchor = spec.get("as1_value") if isinstance(spec, dict) else None
            if not isinstance(anchor, str):
                continue
            rf, _, rk = rkey.partition("|")
            cur = as1_files.get(rf, {}).get(rk)
            # 比對前先還原上游過度逸出：42.20 的 As1 把 `%s`/`%1` 全逸出成 `%%s`/`%%1`，
            # 拿原始值比對會讓每一條帶佔位符的登記都假報漂移（實測 6 條全是這樣）。
            # build 端不受影響是因為它的錨點快照取在 normalize_over_escape **之後**；
            # 這裡直接讀 As1 檔，必須自己還原才能與 build 同語意。
            if isinstance(cur, str) and restore_over_escape(cur) != anchor:
                warn.append(f"{reg_label} 錨點漂移：{rkey!r} 上游原值已變，請複核是否退役")

    # 原創層完整性：登記的鍵必須落地；被 As1 收錄者提示退役（build 端 As1 優先）
    for fname in sorted(own):
        for key in sorted(own[fname]):
            oid = f"{fname}|{key}"
            if fname in as1_files and key in as1_files[fname]:
                warn.append(f"原創鍵 {oid!r} 已被 As1 收錄（As1 優先），建議自對應原創來源（own_translations.json 或原創 mod 目錄）退役")
            elif oid in suppressed:
                if oid in unshipped:
                    warn.append(
                        f"原創鍵 {oid!r} 已由 unshipped_keys／owner conflict 人工裁決不出貨；"
                        "真相層刻意保留供 gate／上游追蹤，依 owner_signature／as1_value 漂移重審"
                    )
                else:
                    warn.append(
                        f"原創鍵 {oid!r} 命中 vanilla 出貨抑制；"
                        "本包不得覆寫本體鍵，真相層僅保留供 gate／上游追蹤"
                    )
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
      * **任何可疑（非 grammar）% 殘留**——42.20.1 Translator 對 getText 結果強制
        String.formatted()，grammar 外的 % 拋 UnknownFormatConversionException
        （主選單黑畫面）。build 端 sanitize 後 dist 兩側都必須歸零，例外鍵不豁免。
      * format-token 值殘留字面 `%.`（JDK format crash 簽名）——CN 側僅未登記例外鍵檢；
        CH 側**一律檢**（CH 為獨立人工資料，登記例外不豁免 CH 安全）。
      * grammar token multiset 不一致（%1/%s/%.1f 等被增刪改）——例外鍵不豁免。
        %% 為字面逸出非佔位，不入 multiset（sanitize 後字面 % 繁簡寫法允許不同）。
      * ASCII 標籤 multiset 不一致（<LINE>/<br>/<RGB:...> 被增刪改）——例外鍵不豁免。
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
            # 42.20.1 硬性：dist 任一側殘留 grammar 外的 % ＝必炸序列，一律 FAIL
            # （build sanitize 後應歸零；此為 oracle 端獨立重驗，例外鍵不豁免）。
            for side, seqs in (("CN", cs), ("CH", hs)):
                if seqs:
                    fail.append(
                        f"{fname}: 鍵 {key!r} {side} 值殘留必炸 % 序列 {seqs}"
                        f"（42.20.1 formatted() 拋 UnknownFormatConversionException）"
                        f" | {(cn_v if side == 'CN' else ch_v)[:60]!r}"
                    )
            # %N$ 殘留＝顯示損壞：$s 不含 %，上面的 % 掃描看不到它——獨立檢查。
            # sanitize 會把合法的 %N$<conv> 正規化為 %N，故 dist 殘留者必為歧義值
            # （%1$s$A）或超出 PZ %1-%9 的 index（%10$s）——formatFixer 都處理不了。
            for side, val in (("CN", cn_v), ("CH", ch_v)):
                if has_positional_residue(val):
                    fail.append(
                        f"{fname}: 鍵 {key!r} {side} 值殘留 %N$ 位置參數（formatFixer 會疊成 "
                        f"%N$s$s ＝顯示損壞；歧義或 index 超出 %1-%9，須人工改寫）"
                        f" | {val[:60]!r}"
                    )
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
            # %% 為字面逸出（非佔位），不入 multiset 比對
            if Counter(t for t in cg if t != "%%") != Counter(t for t in hg if t != "%%"):
                fail.append(
                    f"{fname}: 鍵 {key!r} token 不符 | CN={sorted(cg)} CH={sorted(hg)}"
                )
            ct, ht = extract_tags(cn_v), extract_tags(ch_v)
            if Counter(ct) != Counter(ht):
                fail.append(
                    f"{fname}: 鍵 {key!r} 標籤不符 | CN={sorted(ct)} CH={sorted(ht)}"
                )
    return (not fail), fail, warn


def check_ch_corpus_parity(
    repo: str, dist_ch: str, own: dict[str, dict], suppressed: set[str] | None = None
) -> tuple[bool, list[str]]:
    """[9] dist CH 逐檔逐鍵值對 sources/ch corpus 逐字一致（雙向）。

    取值優先序同 build：corpus（As1/own-mod 鍵）優先，own_translations 的 ch 其次；
    兩者皆無＝無真相源 FAIL。corpus 鍵未落地 dist 亦 FAIL。
    """
    corpus = _load_ch_corpus(repo)
    suppressed = suppressed if suppressed is not None else set()
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
            if f"{fname}|{key}" in suppressed:
                continue  # vanilla 同名鍵：corpus 保有真相，出貨刻意抑制
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


def check_review_drift(
    repo: str, dist_cn: str, suppressed: set[str] | None = None
) -> tuple[bool, list[str], list[str]]:
    """[11] 已審鍵 CN 漂移（WARN-only）：review_state 記錄 hash 對現行 dist CN 重算比對。"""
    state = _load_review_state(repo)
    suppressed = suppressed if suppressed is not None else set()
    cn_files, _ = _load_json_dir(dist_cn)
    # 抑制鍵不在 dist，無從對出貨值重算 hash；但「登記過時」這件事仍要守——
    # 改以真相層（sources/ch corpus）是否還有該鍵判定，否則這批登記會變成永遠沒人看的死條目。
    corpus = _load_ch_corpus(repo) if suppressed else {}
    warn: list[str] = []
    for skey in sorted(state):
        fname, _, key = skey.partition("|")
        if skey in suppressed:
            if key not in corpus.get(fname, {}):
                warn.append(
                    f"已審鍵 {skey!r} 為出貨抑制鍵且已自 corpus 消失"
                    "（登記過時，請自 ch_review_state.json 移除）"
                )
            continue  # 值層漂移無從對出貨值驗——該鍵永不出貨，無玩家影響
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
def check_vanilla_collision(
    repo: str, dist_cn: str, dist_ch: str | None = None
) -> tuple[bool, list[str], list[str]]:
    """[12] 出貨物不得覆寫本體字串；own_translations 原創鍵不得撞 vanilla 鍵名。

    **主閘門（dist 面）**：PZ 的 `Translator.tryFillMapFromFile()` 把每個 mod 的
    Translate 檔 `map.put()` 進同一張全域字串表、後載入者覆寫，故 dist 內任何
    vanilla 同 (檔,鍵) 都會改寫本體譯文——連沒裝任何模組的玩家都受影響
    （2026-08-10 玩家回報：原版霰彈槍被改名為 Remington M870）。build 的
    `suppress_vanilla()` 應已剔除；本項獨立重掃 dist 確認抑制真的生效，
    只有登記於 `keep` 者放行。

    **副閘門（own 來源面）**：原創鍵一開始就不該撞 vanilla 鍵名；
    比對基準與 no-op 豁免登記於 sources/vanilla_keys.json（獨立重讀，不共用 builder 載入）。
    own_translations 走裸鍵名比對（跨檔即算撞，對「原創鍵不得撞本體」是刻意保守的網）；
    origin=own 的 mod 目錄走**檔域**比對——它們帶逐地圖檔泛用鍵（title/description），
    裸鍵比對會與 vanilla 各地圖檔跨檔假陽性，這也是 2026-08-02 當時暫不納入的原因；
    `scoped_keys` 落地後該理由消失，改以精確 (檔|鍵) 納入 blocking。
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

    # --- 主閘門：dist 不得殘留 vanilla 同 (檔,鍵) ---
    scoped, keep = _load_vanilla_basis(repo)
    for label, dist_dir in (("CN", dist_cn), ("CH", dist_ch)):
        if dist_dir is None:
            continue
        dist_files, dist_err = _load_json_dir(dist_dir)
        details += [f"dist {label} {e}" for e in dist_err]
        for fname, van_keys in sorted(scoped.items()):
            for key in sorted(van_keys & set(dist_files.get(fname, {}))):
                pair = f"{fname}|{key}"
                spec = keep.get(pair)
                if spec is None:
                    details.append(
                        f"  dist {label}/{fname}|{key} 覆寫本體字串"
                        "（模組翻譯包不得改動 vanilla 譯文；確認無害後於 vanilla_keys.json keep 登記）"
                    )
                elif label == "CH":
                    # keep 錨點對出貨 CH 值——豁免是對「當時那個值」的背書，值一變背書即失效。
                    # build 也驗一次；oracle 獨立重驗，避免 dist 被手改後無人察覺。
                    got = hashlib.sha256(str(dist_files[fname][key]).encode("utf-8")).hexdigest()[:16]
                    if got != spec["anchor"]:
                        details.append(
                            f"  {pair} keep 錨點失效（出貨 CH 值已變動 {got}≠{spec['anchor']}，"
                            "須重新確認無害後更新錨點）"
                        )
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

    # origin=own 的 mod 目錄：檔域比對（無 allowlist——原創 mod 譯文本就不該碰本體鍵）
    for fname, keys in sorted(_load_own_mods(repo).items()):
        for key in sorted(set(keys) & scoped.get(fname, set())):
            details.append(
                f"  {fname}|{key} 撞 vanilla 鍵（origin=own mod 目錄；原創譯文不得覆寫本體，請改鍵名或移除）"
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


# --- [13] 檔名可載入性 ------------------------------------------------------ #
# PZ 的 Translator 只載入白名單檔名（Translator.BY_NAME，31 個）＋ 每張地圖以自身
# 目錄名載入的 title/description（readMapTranslation():392）。**其餘檔名一律不讀。**
# 而 getTextInternal():419 是按**鍵前綴**嚴格路由到特定 map，沒有 fallback 全域搜尋——
# 所以「鍵放對檔名」是生效的必要條件，放錯就永遠取不到（玩家看到鍵名）。
# 上游 As1 自己就出貨 UI_EN.json / Compendium.json 等不可載入檔名，我方忠實鏡像，
# 於是 2026-08-07 查出 205 個鍵**只**存在於不可載入檔而從未生效。
# 本檢查不管「有沒有多餘檔案」（那是 As1 的事，我方不動），只管**鍵有沒有被困住**。
TRANSLATOR_WHITELIST = frozenset({
    "Tooltip", "IG_UI", "Recipes", "RecipeGroups", "Farming", "ContextMenu", "SurvivalGuide",
    "UI", "Items", "ItemName", "Moodles", "Sandbox", "Challenge", "Stash", "Moveables",
    "MakeUp", "GameSound", "DynamicRadio", "EvolvedRecipeName", "Recorded_Media",
    "SurvivorNames", "Attributes", "Fluids", "Print_Media", "Print_Text", "Entity",
    "RadioData", "BodyParts", "MapLabel", "Credits", "Mod",
})
# getTextInternal 的前綴路由表（長前綴優先，避免 Print_Media_ 被 Print_ 之類截走）
PREFIX_ROUTE = (
    ("SurvivorSurname_", "SurvivorNames"), ("SurvivorName_", "SurvivorNames"),
    ("SurvivalGuide_", "SurvivalGuide"), ("Print_Media_", "Print_Media"),
    ("Print_Text_", "Print_Text"), ("ContextMenu_", "ContextMenu"),
    ("Attributes_", "Attributes"), ("BODYPART_", "BodyParts"), ("GameSound_", "GameSound"),
    ("Challenge_", "Challenge"), ("MapLabel_", "MapLabel"), ("Moodles_", "Moodles"),
    ("Farming_", "Farming"), ("Sandbox_", "Sandbox"), ("Tooltip_", "Tooltip"),
    ("credits_", "Credits"), ("AEBS_", "DynamicRadio"), ("Stash_", "Stash"),
    ("Fluid_", "Fluids"), ("IGUI_", "IG_UI"), ("MakeUp", "MakeUp"), ("EC_", "Entity"),
    ("RD_", "RadioData"), ("RM_", "Recorded_Media"), ("UI_", "UI"),
)


def _routed_file(key: str) -> str | None:
    for prefix, target in PREFIX_ROUTE:
        if key.startswith(prefix):
            return target
    return None


def _renamed_successors(key: str) -> tuple[str, ...]:
    """同一鍵在上游改名後可能的新鍵名（僅 UI_ ↔ IGUI_ 前綴互換）。

    只收這一組是因為它有實據（DeadMansDossier：`UI_DMD_*` → `IGUI_DMD_*`），且兩者
    路由到不同檔（UI.json / IG_UI.json）故舊鍵必然受困。刻意不做模糊比對——猜錯會把
    真缺口靜默吞掉，比多報一條嚴重得多。
    """
    if key.startswith("UI_"):
        return ("IGUI_" + key[3:],)
    if key.startswith("IGUI_"):
        return ("UI_" + key[5:],)
    return ()


def _upstream_keys(repo: str) -> set[str]:
    """sources/en/ 鏡像裡所有上游 translate_en 鍵名（判斷「這個鍵名還算數嗎」）。"""
    out: set[str] = set()
    en_dir = os.path.join(repo, "sources", "en")
    if not os.path.isdir(en_dir):
        return out
    for name in os.listdir(en_dir):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(en_dir, name), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001 — 單一鏡像壞掉不該讓整項 gate 誤判
            continue
        for rid in data:
            kind, _, rest = rid.partition("|")
            if kind == "translate_en":
                out.add(rest.partition("|")[2])
    return out


def check_loadable_files(
    repo: str, dist_ch: str, suppressed: set[str] | None = None
) -> tuple[bool, list[str], list[str]]:
    """[13] 有前綴路由的鍵不得只存在於 PZ 不會載入的檔案裡。

    只看 CH——CH/CN 檔案結構由 [2] CH 鏡像保證一致，重複掃兩次沒有額外資訊。

    **FAIL 只給「上游現在還在用這個鍵名」者**——那才是真正的浪費：上游會呼叫它、
    我方也譯好了，只因放錯檔案而永遠取不到。上游查無同名鍵者判 WARN。

    **已由改名後繼者涵蓋者完全不報**：上游把 `UI_X` 改名為 `IGUI_X`（實例
    DeadMansDossier）時，我方常同時留著 As1 鏡像的舊鍵與已補好的新鍵。舊鍵確實死著，
    但玩家看得到新鍵、沒有任何缺口——把它報成缺陷只是噪音，2026-08-10 實測 60 條裡
    有 22 條屬此類，害人重複追查。判準要**兩個條件同時成立**：後繼鍵在上游語料裡
    存在（證明那是真的改名，不是我方自己亂猜前綴），且已在可載入檔出貨。
    """
    stems = {p[:-5] for p in os.listdir(dist_ch) if p.endswith(".json")}
    live: dict[str, dict] = {}
    for stem in stems & TRANSLATOR_WHITELIST:
        with open(os.path.join(dist_ch, f"{stem}.json"), encoding="utf-8") as f:
            live[stem] = json.load(f)
    live_all = {k for d in live.values() for k in d}
    upstream = _upstream_keys(repo)
    stranded: list[str] = []
    obsolete: list[str] = []
    for stem in sorted(stems - TRANSLATOR_WHITELIST):
        with open(os.path.join(dist_ch, f"{stem}.json"), encoding="utf-8") as f:
            data = json.load(f)
        # 地圖名檔由 readMapTranslation 以目錄名載入，只取這兩鍵——合法，非死檔
        if set(data) <= {"title", "description"}:
            continue
        for key in data:
            target = _routed_file(key)
            if not target or key in live.get(target, {}):
                continue
            if f"{target}.json|{key}" in (suppressed or set()):
                continue  # 本體同名鍵：目標檔裡的缺席是刻意的，搬過去只會被 [12] 擋下
            if any(s in upstream and s in live_all for s in _renamed_successors(key)):
                continue  # 上游改名後的新鍵已在出貨，舊鍵死著但零缺口
            line = f"{stem}.json|{key} → 應落在 {target}.json（PZ 不載入 {stem}.json）"
            (stranded if key in upstream else obsolete).append(line)
    if obsolete:
        obsolete.insert(0, (
            f"（以下 {len(obsolete)} 鍵在上游語料查無同名鍵。**這不等於鍵已作廢**——"
            "也可能該 mod 根本不在監看清單（As1 收錄但 attribution 歸不了屬者落在 "
            "sources/_unsorted，我方對其上游狀態零資料），本檢查無法區分。"
            "判定前先確認該 mod 有無上游語料）"))
    return not stranded, stranded, obsolete


# --- [14] own 層 CN 用字 ---------------------------------------------------- #
# own 層 CN 是我方人工真相（own_translations.json 的 cn 欄 ＋ origin=own 的 mod CN），
# 且多數由 CH 跑 opencc t2s 生成——t2s **只換字形不換詞彙**，還有幾個字它根本不動：
#   * `著`：簡化字表保留「著」(zhù，著名/著作/顯著/土著)，故助詞 zhe 的「抱著」
#     轉完仍是「抱著」，大陸須寫「抱着」。任何字集檢查與 hash 錨點都攔不到。
#   * `牠`／`妳`：大陸不使用動物與女性專用第三／第二人稱。
#   * 直角引號 `「」`：own 層 CN 慣例用 `“”`。
# 2026-08-08 全庫稽核後這四類在 own 層皆為 0，此檢查是防回歸的棘輪。
# **掃描域只有 own 層**：As1 快照的 CN 我方忠實鏡像（實測 52 鍵用「」皆與快照逐字相同），
# 要偏離須走 cn_overrides 登記，不歸本檢查管。
CN_ZHU_WORDS = (  # 「著」在大陸的合法用法（zhù），掃描前先剝掉避免誤報
    "著名", "著作", "著述", "著者", "著錄", "著录", "著書", "著书", "著稱", "著称",
    "顯著", "显著", "土著", "原著", "名著", "巨著", "專著", "专著", "編著", "编著",
    "論著", "论著", "合著", "譯著", "译著",
)
CN_BAD_GLYPHS = (("牠", "它"), ("妳", "你"), ("「", "“"), ("」", "”"))
# 句尾／標點前的「著」＝署名（「由 Kkat 著.」「…尤塞恩・博爾特著」），大陸正字。
# 助詞 zhe 幾乎恆在句中（抱著一線希望／潦草寫著「…」／地下室藏著補給——實測四例皆然），
# 故放行句尾形是可接受的取捨：**寧可漏報，不可逼人把正確的簡中改壞**。
CN_ZHU_TAIL = re.compile(r"著(?=$|[\s.,;!?)\]」』”、。，；！？]|<)")


def check_own_cn_glyphs(repo: str) -> tuple[bool, list[str], list[str]]:
    """[14] own 層 CN 不得殘留 t2s 抓不到的台灣字形。"""
    src: list[tuple[str, str, str]] = []
    for fname, bucket in _load_own(repo).items():
        for key, spec in bucket.items():
            if isinstance(spec, dict) and isinstance(spec.get("cn"), str):
                src.append((f"own_translations:{fname}", key, spec["cn"]))
    for fname, bucket in _load_own_mods(repo).items():
        for key, spec in bucket.items():
            if isinstance(spec, dict) and isinstance(spec.get("cn"), str):
                src.append((f"own-mod:{fname}", key, spec["cn"]))

    fail: list[str] = []
    for label, key, val in src:
        stripped = val
        for word in CN_ZHU_WORDS:
            stripped = stripped.replace(word, "")
        stripped = CN_ZHU_TAIL.sub("", stripped)
        if "著" in stripped:
            fail.append(f"{label}|{key}：CN 有「著」（助詞 zhe 須寫「着」）：{val[:44]!r}")
        for bad, good in CN_BAD_GLYPHS:
            if bad in val:
                fail.append(f"{label}|{key}：CN 有「{bad}」（應為「{good}」）：{val[:44]!r}")
    return not fail, fail, []


# --- [15] ItemName 死鍵 ------------------------------------------------------ #
# `ItemName_<Module>.<Item>` 是 B41 `ItemName_EN.txt` 時代的鍵形，**B42 不會讀它**：
#   * Translator.tryFillMapFromFile():362-366 把 JSON 鍵原封不動 map.put(k,…)，零前綴處理。
#   * Translator.getItemNameFromFullType():601 只做 itemName.get(fullType)，fullType 是
#     裸的 `Module.Item`（Item.java:3053 以 getFullName() 呼叫）。
#   * 全庫 `ItemName_` 只出現在 debugItemNames() 的除錯輸出。
# （出處：反編譯 42.20.2，jar sha256 09a80a46…f416，與安裝檔相符。）
# 所以前綴鍵若沒有對應的裸 fullType，該物品名等於沒翻譯——玩家看到英文，而 build／
# CH parity／lint 三道都是綠的，2026-08-10 就是這樣漏了 1,034 鍵才被雙邊 review 抓到。
# **`Base.` 開頭不等於本體**：MOD 同樣能往 `module Base` 加物品（實例 `Base.44Clip20`
# 是 mod 的高容量彈匣，vanilla 只有 `Base.44Clip`），故豁免只認 vanilla scoped 基準。
ITEMNAME_DEAD_ALLOWLIST = "itemname_dead_allowlist.json"
ITEM_FULLTYPES_MIN = 1000

def _is_item_fulltype(value: str) -> bool:
    """Check only invariants guaranteed by tracker's unescaped producer."""
    return (
        value == value.strip()
        and "." in value[1:-1]
        and not any(char in value for char in "{}\r\n")
    )




def _upstream_item_fulltypes(repo: str) -> set[str]:
    """Return effective-branch `script_item_dn` fullTypes, fail-closed.

    Module names are never inferred from suffixes. The only evidence accepted
    by [15] is the exact `Module.Item` extracted by tracker schema 9+ from the
    currently loadable branch. This keeps `Foo.Bar` distinct from `Other.Bar`
    and prevents a missing module from being "repaired" to whichever suffix
    happens to be unique in today's incomplete tracker universe.
    """
    path = os.path.join(repo, "tracker-state", "en_corpus_hashes.json")
    with open(path, encoding="utf-8-sig") as fh:
        state = json.load(fh)
    if not isinstance(state, dict):
        raise ValueError("en_corpus_hashes.json 頂層形狀壞損（須為 dict）")
    mods = state.get("mods")
    if not isinstance(mods, dict) or not mods:
        raise ValueError("en_corpus_hashes.json 的 mods 形狀壞損（須為非空 dict）")
    out: set[str] = set()
    corrupt: list[str] = []
    for wid, info in mods.items():
        if not isinstance(info, dict):
            corrupt.append(f"{wid}: mod entry 非 dict")
            continue
        records = info.get("records")
        if not isinstance(records, dict):
            corrupt.append(f"{wid}: records 非 dict")
            continue
        schema = info.get("extractor_schema")
        if type(schema) is not int:
            corrupt.append(f"{wid}: extractor_schema 非整數")
            continue
        parsed: list[tuple[str, str, str]] = []
        for rid in records:
            kind, first_sep, rest = rid.partition("|")
            relpath, second_sep, key = rest.partition("|")
            if (
                kind not in tracker.EXTRACTOR_KINDS
                or not first_sep or not second_sep or not relpath
                or (not key and kind != "lua_gettext")
            ):
                corrupt.append(f"{wid}: 壞損 record `{rid}`")
                continue
            parsed.append((rid, kind, key))
        if len(parsed) != len(records):
            continue
        if schema < tracker.ITEM_MODULE_SCHEMA:
            continue
        eff = tracker.resolve_effective_branches(records)
        for rid, kind, full in parsed:
            if kind != "script_item_dn":
                continue
            # Legacy/stale state can contain module-less item names even after a
            # wid-level schema bump. They are undecidable, never exact evidence.
            if "." not in full[1:-1] or full.startswith(f"{tracker.UNKNOWN_MODULE}."):
                continue
            if not _is_item_fulltype(full):
                corrupt.append(f"{wid}: 壞損 script_item_dn fullType `{full}`")
                continue
            if tracker.is_effective(rid, eff):
                out.add(full)
    if corrupt:
        raise ValueError(
            f"en_corpus_hashes.json 有 {len(corrupt)} 處 ItemName 上游實據壞損"
            f"（{'; '.join(corrupt[:5])}）")
    if len(out) < ITEM_FULLTYPES_MIN:
        raise ValueError(
            f"en_corpus_hashes.json 只取得 {len(out)} 個有效分支 script_item_dn fullType"
            f"（現況量級 15300+，下限 {ITEM_FULLTYPES_MIN}）——不得以零缺口放行")
    return out




def check_itemname_dead_keys(repo: str, dist_ch: str) -> tuple[bool, list[str], list[str]]:
    """[15] Require exact effective fullType coverage or an explicit deferral.

    `ItemName_` suffix matching is intentionally forbidden. Even one apparent
    `*.Bar` candidate does not prove the module. A non-exact prefix is therefore
    not ignored: it blocks until a human identifies the real module and repairs
    it, or records why it cannot yet be repaired in the allowlist.
    """
    files, err = _load_json_dir(dist_ch)
    if err:
        return False, err, []
    data = files.get("ItemName.json", {})
    pref = {k[len("ItemName_"):]: k for k in data if k.startswith("ItemName_")}
    bare = {k for k in data if not k.startswith("ItemName_")}
    effective = _upstream_item_fulltypes(repo)

    vpath = os.path.join(repo, "sources", "vanilla_keys.json")
    with open(vpath, encoding="utf-8-sig") as fh:
        vanilla = set(json.load(fh).get("scoped_keys", {}).get("ItemName.json", []))

    apath = os.path.join(repo, "sources", ITEMNAME_DEAD_ALLOWLIST)
    with open(apath, encoding="utf-8-sig") as fh:
        allow_data = json.load(fh)
    if not isinstance(allow_data, dict) or "entries" not in allow_data:
        raise ValueError(f"{ITEMNAME_DEAD_ALLOWLIST} 須為含 entries 的物件")
    allow = allow_data["entries"]
    if not isinstance(allow, dict) or any(
        not isinstance(full, str) or not full
        or not isinstance(reason, str) or not reason.strip()
        for full, reason in allow.items()
    ):
        raise ValueError(
            f"{ITEMNAME_DEAD_ALLOWLIST} entries 須為 {{鍵: 非空理由}} 物件")

    resolved = vanilla | (effective & bare)
    fail: list[str] = []
    for body in sorted(pref):
        if body in resolved or body in allow:
            continue
        if body in effective:
            fail.append(
                f"{pref[body]} 對應 effective fullType `{body}`，但無精確裸鍵——"
                f"玩家看到英文。補裸鍵，或查證後登記 sources/{ITEMNAME_DEAD_ALLOWLIST}")
        else:
            fail.append(
                f"{pref[body]} 的 prefix body `{body}` 無法精確對上 effective "
                f"script_item_dn fullType；禁止依 suffix 猜 module。請查 owner/mod script "
                f"後補正確裸鍵，或登記 sources/{ITEMNAME_DEAD_ALLOWLIST}")
    # A non-exact allowlist entry is an intentional unresolved-module deferral.
    # It becomes stale only when its prefix disappears or independent evidence
    # (vanilla, or effective tracker fullType plus shipped bare key) resolves it.
    warn = [
        f"{ITEMNAME_DEAD_ALLOWLIST} 條目過時，請移除：{full}"
        for full in sorted(allow)
        if full not in pref or full in resolved
    ]
    return not fail, fail, warn


# --- [16] Recipes 死鍵 ------------------------------------------------------- #
# `Recipe_<X>` 是 B41 `Recipes_EN.txt` 時代的鍵形；`craftRecipe_<X>` 不是 B41 遺留，而是
# B42 端多加了 script 類型名當前綴（上游自己寫錯，實例 SVRP ClassicBows 的
# `craftRecipe_SVRP_CB_*`）。兩者結果一樣：B42 的配方顯示名查表是
# `Translator.getRecipeName(name)` → `recipe.get(name)`，`name` 是**裸的 craftRecipe
# 區塊名**（CraftRecipe.java:362 以區塊名呼叫，ScriptBucket 只 trim、不去空格），零前綴
# 處理。所以帶前綴的鍵永遠不會被查到——譯得再好也顯示英文。
# 判定要有上游實據才算數：只有「去前綴後對得上上游現行 script_craftRecipe 區塊名」的
# 前綴鍵才判死鍵，否則無從區分「B41 遺留鍵形」與「上游 Translate 檔自帶、無從還原的
# 閒置前綴鍵」（實例：測試情境 3 的 `Recipe_SomethingUpstreamNeverHad`）。無前綴的鍵
# 一律在本 gate 視野外——`MakeCarMuffler*` 這類不帶前綴的閒置鍵不是本項要抓的東西。
# 由來：2026-08-16 的 #170 SVRP ClassicBows 收了 4 個 `Recipe_*_from_Plank`，build／
# verify 14 項／lint 全綠通過，靠人工 review 才攔下；同批盤點另發現 69 個既有同類缺口。
# **區塊名刻意取全庫 union、不按 owner 切**：PZ 的字串表沒有 per-mod 命名空間
# （`Translator.tryFillMapFromFile()` 把每個 mod 的鍵 put 進同一張全域 map），
# `recipe.get(name)` 只認裸名。上游任一 mod 有區塊 `X`，我方出貨鍵 `X` 就會被查到；
# 前綴鍵原本屬於哪個 mod 對「玩家看不看得到中文」零影響。改按 owner 比對反而要靠
# attribution 索引，而該索引本身有 `_unsorted` 盲區，只會製造漏報。
# 同名區塊分屬多 mod 而語意不同者（實例 `Make DIY Battery` 屬 2969478819＋3652024179）
# 屬**資料層裁決**——補值時須確認譯文對每個 owner 都成立，與本 gate 的判定維度無關。
RECIPE_DEAD_ALLOWLIST = "recipe_dead_allowlist.json"
RECIPE_DEAD_PREFIXES = ("craftRecipe_", "Recipe_")


# 現況量級：481 個 mod、8,816 個 craftRecipe 區塊名（**濾前**），濾掉只存在死分支者後
# 約 6,900 個——門檻比的是**濾後** `len(out)`。設 1000 是為了抓「實據整批消失」：那才是
# 這道 gate 最危險的失效模式，`blocks` 空集合會讓 `_recipe_bare_names()` 全回空清單、
# 一鍵不報、gate 綠燈，整道防線靜默關閉（#170 類死鍵可再次全綠出貨）。合法 JSON
# 但形狀壞損（`mods` 被清空／寫成 `[]`／`null`、extractor schema 改版使 `script_craftRecipe`
# 記錄改名、單一 mod 的 `records` 寫成 list）都走這條路，故一律 fail-closed 擲例外由
# 呼叫端轉 FAIL，比照 [12] `check_vanilla_collision` 對 `keys` 的量級門檻。
RECIPE_BLOCKS_MIN = 1000

# `script_craftRecipe` 抽取完整性的最低 per-mod schema。`tracker.EXTRACTOR_SCHEMA=5` 起
# 「掃**全部** media/scripts 目錄」——先前只取第一個，多版本目錄的 mod 會漏掉其餘目錄的
# 區塊名。schema 6/7/8 的變更只動 Lua 與 Translate JSON 解析，不影響 script 抽取；schema 9
# 動了 script 抽取（item key 改帶 module、區塊名剝除行內註解），但 craftRecipe 的區塊名
# **零影響**——實測 13,776 個 craftRecipe 記錄無一含行內註解，且加 module 前綴刻意只套在
# item 系列（配方名走 `getRecipeName(裸區塊名)`）。故門檻仍為 >=5。低於此者的區塊名清單
# 可能殘缺，gate 會對它們的 legacy 鍵誤判「無實據」＝**局部漏報**，而 RECIPE_BLOCKS_MIN
# 是總量門檻、抓不到這種。
# 刻意判 WARN 而非 FAIL：schema 落後是**正常狀態**（tracker 只在該 mod 有更新時重抽，
# 沒更新就一直停在舊 schema），硬 FAIL 會讓 gate 永遠紅、逼人做與本次變更無關的
# backfill。要消除盲區跑 `tracker.py backfill-en` 或等該 mod 更新。
CRAFT_SCHEMA_MIN = 5


def _upstream_craft_blocks(repo: str) -> tuple[set[str], list[str]]:
    """上游**有效分支**的 craftRecipe 區塊名（＝B42 真正會查的鍵），與 schema 落後的 mod。

    有效分支過濾是必要的、不是保險：tracker 忠實記錄 mod 內所有版本分支，但引擎只載入
    `common/` ＋唯一一個最佳版本夾。2026-08-16 實測 8,816 個區塊名裡有 1,889 個只存在於
    死分支——不濾就會把「上游早就改名的舊區塊」當成現行實據，逼人去補永不被查的裸鍵
    （實例：Firearms 2256623447 的 `ConvertAmmo`／`DetractStock`／`ExtendStock` 只在
    42.12–42.13，現行有效分支 42.16 已改名 `ToggleStock`）。判定沿用 `tracker.py` 的
    `resolve_effective_branches()`／`is_effective()`，**不得另寫第二套**。
    """
    path = os.path.join(repo, "tracker-state", "en_corpus_hashes.json")
    with open(path, encoding="utf-8-sig") as fh:
        state = json.load(fh)
    mods = state.get("mods")
    if not isinstance(mods, dict) or not mods:
        raise ValueError("en_corpus_hashes.json 的 mods 形狀壞損（須為非空 dict）")
    out: set[str] = set()
    corrupt: list[str] = []
    stale: list[str] = []
    for wid, info in mods.items():
        records = info.get("records") if isinstance(info, dict) else None
        if not isinstance(records, dict):
            corrupt.append(str(wid))
            continue
        schema = info.get("extractor_schema")
        if not isinstance(schema, int) or schema < CRAFT_SCHEMA_MIN:
            stale.append(f"{wid}(schema={schema})")
        eff = tracker.resolve_effective_branches(records)
        for rid in records:
            kind, _, rest = rid.partition("|")
            if kind == "script_craftRecipe" and tracker.is_effective(rid, eff):
                out.add(rest.rpartition("|")[2])
    if corrupt:
        raise ValueError(
            f"en_corpus_hashes.json 有 {len(corrupt)} 個 mod 的 records 形狀壞損"
            f"（{', '.join(corrupt[:5])}…）——上游實據殘缺，不得以「零死鍵」放行")
    if len(out) < RECIPE_BLOCKS_MIN:
        raise ValueError(
            f"en_corpus_hashes.json 只取得 {len(out)} 個有效分支 script_craftRecipe 區塊名"
            f"（現況量級 6900+，下限 {RECIPE_BLOCKS_MIN}）——上游實據殘缺或 extractor schema"
            " 已改版，不得以「零死鍵」放行")
    return out, sorted(stale)


def _block_index(blocks: set[str]) -> dict[str, list[str]]:
    """區塊名查找索引 `{查找鍵: [原區塊名…]}`，同時收原形與空格底線化形。

    上游區塊名可能含空格（`Craft Metal Arrows from Plank`）、含底線（`MakeBeeSmoker`）
    或**兩者混用**（`SVRP_CB_Pack Metal Arrows`），而 B41 legacy 鍵一般把空格寫成底線。
    所以還原不能用 `body.replace("_", " ")`——那會把區塊本來就有的底線也換掉，混用形一律
    漏報。方向要反過來：把**區塊名**底線化後當索引鍵，用 legacy 鍵的 body 去查。
    原形也一併收，因為 JSON 鍵允許空格，legacy 鍵不保證一定把空格換成底線。
    """
    index: dict[str, list[str]] = {}
    for block in blocks:
        index.setdefault(block, []).append(block)
        underscored = block.replace(" ", "_")
        if underscored != block:
            index.setdefault(underscored, []).append(block)
    return index


def _recipe_bare_names(key: str, index: dict[str, list[str]]) -> list[str]:
    """前綴鍵還原成上游區塊名候選：0 個＝無實據不判死鍵，>1 個＝歧義（由呼叫端報 WARN）。

    精確命中優先：`body` 本身就是現行區塊名時直接採用，不讓底線化索引把它擴成多義。
    """
    for prefix in RECIPE_DEAD_PREFIXES:
        if not key.startswith(prefix):
            continue
        body = key[len(prefix):]
        if not body:
            return []
        cands = index.get(body, [])
        if body in cands:
            return [body]
        return sorted(cands)
    return []


def _load_recipe_allowlist(repo: str) -> dict[str, str]:
    """`recipe_dead_allowlist.json` 的 entries，形狀壞損一律擲例外（gate 資料是受版控真相）。"""
    path = os.path.join(repo, "sources", RECIPE_DEAD_ALLOWLIST)
    with open(path, encoding="utf-8-sig") as fh:
        entries = json.load(fh).get("entries")
    if not isinstance(entries, dict) or not all(
        isinstance(k, str) and k and isinstance(v, str) and v for k, v in entries.items()
    ):
        raise ValueError(
            f"{RECIPE_DEAD_ALLOWLIST} 的 entries 形狀壞損"
            "（須為 {裸區塊名: 非空理由字串} 的 dict）")
    return entries


def check_recipe_dead_keys(repo: str, dist_ch: str) -> tuple[bool, list[str], list[str]]:
    """[16] 對得上上游區塊名的 `Recipe_`／`craftRecipe_` 前綴鍵必須另有裸鍵。"""
    files, err = _load_json_dir(dist_ch)
    if err:
        return False, err, []
    # 只掃 CH：CH/CN 的檔案集合與逐檔鍵集由 [2] CH 鏡像保證一致（run_all 無條件跑），
    # 本項只需要鍵集、不看值，重複掃 CN 沒有額外資訊。
    data = files.get("Recipes.json", {})
    blocks, stale_schema = _upstream_craft_blocks(repo)
    index = _block_index(blocks)

    vpath = os.path.join(repo, "sources", "vanilla_keys.json")
    with open(vpath, encoding="utf-8-sig") as fh:
        vanilla = set(json.load(fh).get("scoped_keys", {}).get("Recipes.json", []))
    allow = _load_recipe_allowlist(repo)

    def satisfied(bare: str) -> bool:
        """該裸名已出貨／屬本體／已裁決豁免＝玩家看得到中文，不算缺口。"""
        return bare in data or bare in vanilla or bare in allow

    pref: dict[str, list[str]] = {}
    fail: list[str] = []
    for key in data:
        cands = _recipe_bare_names(key, index)
        missing = [b for b in cands if not satisfied(b)]
        if not missing:
            continue
        if len(cands) > 1:
            # **歧義一律 fail-closed**：底線化後撞名是會自然發生的（`Foo Bar_Baz` 與
            # `Foo_Bar Baz` 都正規化成 `Foo_Bar_Baz`），只記 WARN 就會讓「兩個裸鍵都沒
            # 出貨」的真缺口綠燈放行。歧義本身不可機械消解——prefix 鍵沒帶 owner 資訊，
            # 只能人工裁決：補齊全部候選，或查證後把不該補的登記 allowlist。
            fail.append(
                f"{key} 可還原成多個上游區塊名（{', '.join(cands)}），其中"
                f" {', '.join(missing)} 未出貨——請人工裁決：補齊裸鍵，"
                f"或查證後登記 sources/{RECIPE_DEAD_ALLOWLIST}")
        else:
            pref.setdefault(cands[0], []).append(key)

    fail += [
        f"{'／'.join(sorted(pref[b]))} 是死鍵且無裸鍵 `{b}`——玩家看到英文配方名。"
        f"補裸鍵，或查證後登記 sources/{RECIPE_DEAD_ALLOWLIST}"
        for b in sorted(pref)
    ]
    # 反向棘輪：已補好、前綴鍵已消失、或已由 vanilla 基準自動放行的條目都該移除，
    # 否則清單會爛掉沒人發現（漏掉 vanilla 這條，基準日後移除該鍵時過時豁免會靜默接手）。
    # `pref` 只收「未滿足」的裸名，故過時判定要另掃全部 prefix 鍵的候選集合。
    referenced = {b for key in data for b in _recipe_bare_names(key, index)}
    warn = [
        f"{RECIPE_DEAD_ALLOWLIST} 條目過時，請移除：{b}"
        for b in sorted(allow)
        if b in data or b not in referenced or b in vanilla
    ]
    if stale_schema:
        # 局部漏報盲區可見化：這些 mod 的 script 抽取用的是「只掃第一個 media/scripts
        # 目錄」的舊規則，區塊名清單可能殘缺，本項對它們的 legacy 鍵會誤判「無實據」。
        warn.append(
            f"{len(stale_schema)} 個 mod 的 extractor_schema < {CRAFT_SCHEMA_MIN}"
            "（script 抽取當時只掃第一個 media/scripts 目錄），其 craftRecipe 區塊名清單"
            f"可能殘缺＝本項對它們的 legacy 鍵會漏報：{', '.join(stale_schema)}。"
            "要消除跑 `tracker.py backfill-en`，或等該 mod 更新時自動重抽")
    return not fail, fail, warn


def run_all(paths: dict, allow_missing_as1: bool = False) -> int:
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

    # As1 快照樹是 Steam 管理的 Workshop 目錄，Valve 會在上游改版時直接覆蓋版本資料夾
    # （實例：2026-08-05 As1 的 42.19/ 被 42.20/ 取代，舊版 Workshop 不提供重新下載＝
    # 該快照永久消失）。舊行為是在此硬性 return 1，導致其餘 10 項完全跑不到；
    # 改為把 [1]/[8] 判 SKIP、其餘照跑，讓「哪些還好、哪些壞了」看得見。
    # 退出碼預設仍為 1（SKIP 不等於 PASS，不得讓 release gate 靜默放行）。
    as1_missing = not os.path.isdir(as1_cn)
    if as1_missing:
        print(f"⚠ As1 快照 CN 目錄不存在：{as1_cn}")
        print("  → [8] As1 漂移判 SKIP；[1] 仍照跑，只降級「對 As1 原值」的比對——")
        print("     own CN 值、placeholder 例外安全值、cn_overrides 登記值、原創鍵落地照驗。")
        print("  → 成因多為 Steam 覆蓋了 Workshop 版本目錄；舊版無法重新下載，")
        print("     須改釘新快照（sources/snapshot.json 的 source_tree）並處理其值差異。")
        print("  → 退出碼仍為 1。確知要以降級結果當 gate 時加 --allow-missing-as1。")
        print()

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

    # 出貨抑制集合：dist 面向的期望一律扣除（真相層仍持有這些鍵，只是不出貨）。
    # 基準壞損直接判 FAIL——靜默當成空集合會讓 [1]/[9]/[11] 誤報一整批「缺鍵」。
    try:
        suppressed = suppressed_pairs(repo)
        upath = os.path.join(repo, "sources", "unshipped_keys.json")
        unshipped = set()
        if os.path.isfile(upath):
            with open(upath, encoding="utf-8-sig") as fh:
                udata = json.load(fh)
            entries = udata.get("entries") if isinstance(udata, dict) else None
            if not isinstance(entries, dict):
                raise ValueError("unshipped_keys.json 的 entries 形狀壞損")
            unshipped = set(entries)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR：vanilla 鍵名基準無法載入（{exc}）")
        return 1

    # ok 為 None＝SKIP（無法判定），有別於 False＝FAIL（判定為壞）。
    # [1] 即使 As1 缺席也照跑：只降級 As1 相關比對，own 值／例外／override／原創落地
    # 這些不依賴 As1 的核對必須留著，否則 --allow-missing-as1 會連它們一起放行。
    ok1, d1, w1, n_exc, n_own = check_cn_parity(
        as1_cn,
        dist_cn,
        exceptions,
        own,
        cn_overrides,
        as1_available=not as1_missing,
        suppressed=suppressed,
        unshipped=unshipped,
    )
    ok2, d2 = check_ch_mirror(dist_cn, dist_ch)
    ok3, d3 = check_encoding(dist_translate)
    ok4, d4_fail, d4_warn = check_placeholder(dist_cn, dist_ch, exceptions)
    ok6, d6 = check_language_txt(dist_cn, dist_ch)
    ok7, d7 = check_lua(repo, lua_client)
    ok8, d8, w8 = (None, [], []) if as1_missing else check_as1_drift(repo, as1_cn)
    try:
        ok9, d9 = check_ch_corpus_parity(repo, dist_ch, own, suppressed)
    except Exception as exc:  # noqa: BLE001 — corpus 壞掉直接判 FAIL
        ok9, d9 = False, [f"corpus 無法載入（{exc}）"]
    try:
        ok10, d10 = check_sync_worklist(repo)
    except Exception as exc:  # noqa: BLE001
        ok10, d10 = False, [f"worklist 無法載入（{exc}）"]
    try:
        ok11, d11, w11 = check_review_drift(repo, dist_cn, suppressed)
    except Exception as exc:  # noqa: BLE001
        ok11, d11, w11 = False, [f"review_state 無法載入（{exc}）"], []
    try:
        ok12, d12, w12 = check_vanilla_collision(repo, dist_cn, dist_ch)
    except Exception as exc:  # noqa: BLE001 — 清單檔缺失/壞損直接判 FAIL（gate 資料是受版控真相）
        ok12, d12, w12 = False, [f"vanilla_keys.json 無法載入（{exc}）"], []
    try:
        ok13, d13, w13 = check_loadable_files(repo, dist_ch, suppressed)
    except Exception as exc:  # noqa: BLE001
        ok13, d13, w13 = False, [f"檔名可載入性檢查失敗（{exc}）"], []
    try:
        ok14, d14, w14 = check_own_cn_glyphs(repo)
    except Exception as exc:  # noqa: BLE001
        ok14, d14, w14 = False, [f"own CN 用字檢查失敗（{exc}）"], []
    try:
        ok15, d15, w15 = check_itemname_dead_keys(repo, dist_ch)
    except Exception as exc:  # noqa: BLE001 — 清單檔缺失/壞損直接判 FAIL（gate 資料是受版控真相）
        ok15, d15, w15 = False, [f"ItemName 死鍵檢查失敗（{exc}）"], []
    try:
        ok16, d16, w16 = check_recipe_dead_keys(repo, dist_ch)
    except Exception as exc:  # noqa: BLE001 — 清單檔缺失/壞損直接判 FAIL（gate 資料是受版控真相）
        ok16, d16, w16 = False, [f"Recipes 死鍵檢查失敗（{exc}）"], []

    rows = [
        ("1", "CN 逐檔 parity（As1 缺席時僅降級 As1 比對）" if as1_missing else "CN 逐檔 parity",
         ok1, d1, w1),
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
        ("13", "檔名可載入性", ok13, d13, w13),
        ("14", "own 層 CN 用字", ok14, d14, w14),
        ("15", "ItemName 死鍵", ok15, d15, w15),
        ("16", "Recipes 死鍵", ok16, d16, w16),
    ]

    n_pass = sum(1 for _, _, ok, _, _ in rows if ok is True)
    n_fail = sum(1 for _, _, ok, _, _ in rows if ok is False)
    n_skip = sum(1 for _, _, ok, _, _ in rows if ok is None)
    n_warn = sum(len(warn) for _, _, _, _, warn in rows)

    for num, name, ok, _det, warn in rows:
        status = "PASS" if ok is True else ("SKIP" if ok is None else "FAIL")
        tail = f"  (WARN {len(warn)})" if warn else ""
        print(f" [{num}] {name:.<28} {status}{tail}")
    print("-" * 64)
    print(f" 例外鍵 {n_exc} 個已依登記值核對；原創鍵 {n_own} 個已依 own cn 核對"
          + ("（As1 原值 parity 因快照缺席未驗）" if as1_missing else ""))
    # SKIP 不是 PASS：預設仍判 FAIL，除非呼叫端明示接受降級。
    degraded = n_skip > 0 and not allow_missing_as1
    overall = "PASS" if (n_fail == 0 and not degraded) else "FAIL"
    tail = f" / SKIP {n_skip}" if n_skip else ""
    print(f" 結果：{overall}  (PASS {n_pass} / FAIL {n_fail}{tail} / WARN {n_warn})")
    if n_skip and allow_missing_as1:
        print(" ⚠ --allow-missing-as1：以其餘項目當 gate，As1 端未驗證")
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

    return 0 if (n_fail == 0 and not degraded) else 1


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
    parser.add_argument(
        "--allow-missing-as1", action="store_true",
        help="As1 快照樹缺席時，以其餘 10 項當 gate（[1]/[8] 判 SKIP 但不影響退出碼）。"
             "僅供快照重釘期間的過渡使用，release 前務必移除。",
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
    return run_all(paths, allow_missing_as1=args.allow_missing_as1)


if __name__ == "__main__":
    sys.exit(main())
