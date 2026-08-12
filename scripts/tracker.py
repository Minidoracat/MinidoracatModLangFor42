# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
tracker.py — MinidoracatModLangFor42 雙上游追蹤器（PZ B42 如一模組翻譯繁中版）

用途：排程（每日）偵測兩層上游變更，確有文本 diff 才開/更新 GitHub issue，跨 cron 保存去重狀態。
  layer-B（主力）：As1 包 3556540080 新 CN 樹（版本樹釘於 sources/snapshot.json）vs 本 repo sources/ → 有 diff 開「待同步」issue。
  layer-A（品保）：原始 mod 全語料 kind|相對路徑|鍵|英文值 hash vs baseline → 分類新增/刪除/修改，開「可能過時」issue。

設計要點：
  * 純標準函式庫（urllib / subprocess / hashlib）→ 供 `uv run scripts/tracker.py` 直接執行，CI 免裝依賴。
  * API client 免 key 為主（研究實證端點無 key 參數）；STEAM_API_KEY 為設定選項、非 429 解藥（附加而已）。
  * 交易順序：取數 → diff → 開/更 issue → 最後 commit 成功子集 state；--dry-run 保證零 issue 零 commit。
  * 核心邏輯（diff / issue 冪等 / git 重試）皆以可注入依賴實作，供內建 self-test 十二情境 mock 驗證。

命令（uv run scripts/tracker.py <命令>）：
  gen-watchlist  由 sources/mods/*/metadata.json 支持清單生成 tracker-state/watchlist.json（固定含 As1；支持清單變動後重跑）
  run            預設：check → diff → issue → commit 全流程（--dry-run 只印計畫）
  check          僅打 API 查時間戳，寫 changed 清單 artifact（workflow check job；無寫權限）
  diff           讀 changed，下載+裁剪+抽取+diff，寫 diffs artifact（workflow download job；無 GitHub 權限）
  issue          讀 diffs，列 open issue 冪等開/更，commit 成功子集 state（workflow issue+state job）
  self-test      內建十二情境 mock 測試
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

# ============================================================
# 路徑與常數配置
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent

TRACKER_STATE = PROJECT_ROOT / "tracker-state"
WATCHLIST_JSON = TRACKER_STATE / "watchlist.json"
TIMESTAMPS_JSON = TRACKER_STATE / "timestamps.json"
EN_CORPUS_HASHES_JSON = TRACKER_STATE / "en_corpus_hashes.json"
EN_TEXT_DIR = PROJECT_ROOT / "sources" / "en"  # EN 全文落地（大同步翻譯對照；rid 與 hash 檔一致）

SOURCES = PROJECT_ROOT / "sources"
ATTRIBUTION_INDEX_JSON = SOURCES / "attribution_index.json"
SNAPSHOT_JSON = SOURCES / "snapshot.json"  # As1 釘定版本樹（issue 內文用；勿在本檔寫死版本號）

# schema 版本（狀態格式演進時 bump；讀取時可據此遷移）
SCHEMA_VERSION = 1
# layer-A 抽取器 schema（media/scripts item/recipe 名為 basic 正則版，改抽取規則時 bump）
# =2：record identity 由 basename 改為相對路徑（同 basename 不同目錄不再互撞）
# =3：script 區塊改行首＋須接 "{" 判定（排除 craftRecipe 內文數量指令）；名稱允許空白全取
# =4：Translate 抽取新增 B41 .txt 格式（Key = "value" 行式）——約 30 個模組僅以 .txt 帶英文文本
# =5：script 抽取改掃「全部」media/scripts 目錄（先前只取第一個，多版本目錄 mod 會漏其一）、
#     relpath 改 mod_dir 相對（跨版本目錄同名檔不互撞）、item 區塊另抽 DisplayName 獨立
#     record（script_item_dn，捕捉上游顯示名漂移——先前 value=區塊 id，DisplayName 改動無感）
# =6：新增 Lua 文本抽取（lua_gettext / lua_literal）——Translate/scripts 之外的第三個文本來源。
#     mod 的玩家可見字串未必都走 Translate 檔：getText("KEY") 的鍵若我方未收＝遊戲顯示英文，
#     而直接寫死在 Lua 的字面英文連鍵都沒有，只能靠 sources/lua/ 覆寫。兩者原先完全不可見。
# =7：Lua 抽取由 regex 改為最小 lexical scan（跳註解／長字串、identifier 邊界、平衡括號）。
#     **擷取行為一變就必須 bump**——否則舊基準 schema 相符但語料 hash 不同，下一次 run
#     會對每個含 Lua 的 mod 開一張假「可能過時」issue（實測 110 張）。schema 不符則走
#     靜默重建，這正是該機制存在的理由。
#     schema 8（2026-08-12）：上游 Translate JSON 改用 `load_upstream_json` 容錯解析
#     結尾多餘逗號——先前整檔跳過，等於該檔的鍵對追蹤器與覆蓋率永久不存在。
EXTRACTOR_SCHEMA = 8

# 只有這些 kind 帶真英文文本，值得落 sources/en/ 鏡像；其餘 script_* 的 value 就是區塊 id
# 本身（實測 118,307 筆鏡像裡有 60,567 筆 value==key），純屬變更偵測用，留在 hash 台帳即可。
TEXT_BEARING_KINDS = frozenset({"translate_en", "script_item_dn", "lua_literal"})

# --- B42 有效分支解析 ------------------------------------------------------- #
# 抽取器忠實記錄 mod 內**所有**分支，但引擎只載入其中兩個。拿非有效分支的鍵去補譯
# ＝死資料：2026-08-06 那批 899 鍵有 385 筆（43%）因此白做，且其中 2 筆的 EN 取自
# 已改名／已作廢的舊分支，直接譯錯。
#
# 規則出處＝反編譯的 42.20.2 遊戲碼（jar sha256 09a80a46…f416，與安裝檔相符）：
#   * ZomboidFileSystem.loadMod():648/:665 全文只有兩次 searchFolders——`common/`
#     與唯一一個「最佳版本夾」，後者疊在前者之上。**mod 根目錄的 media/ 不載入**
#     （B41 遺留）；:486 的可見性門檻也只認 common/mod.info 或 <版本夾>/mod.info。
#   * getModVersionDirName():460 取「換算整數 ≥ 42000 且 ≤ 遊戲版本」的**最大者**。
#   * getGameVersionIntFromName():557 只取前兩段（major*1000+minor），第三段丟棄，
#     所以 42.20.2 與 42.20 同值。
#   * Translator.tryFillMapFromFile():353 路徑寫死 `.json`——legacy `_EN.txt` 在 B42
#     **完全不被讀取**（全庫僅 IsoWorld.java:1333 一句 debug 訊息提及）。故 `.txt`
#     裡的 EN 定義在執行期並不存在，不能拿來當補譯依據。
GAME_VERSION_INT = int(os.environ.get("PZ_GAME_VERSION_INT", "42020"))
MIN_REQUIRED_INT = 42000  # ChooseGameInfo.getMinRequiredVersion() = GameVersion(42, 0)


def _version_int(name: str) -> int:
    """版本夾名 → 引擎整數；規則同 getGameVersionIntFromName（第三段丟棄）。"""
    parts = name.split(".")
    try:
        if len(parts) == 1:
            return int(parts[0]) * 1000
        return int(parts[0]) * 1000 + min(int(parts[1]), 999)
    except ValueError:
        return 0


def resolve_effective_branches(record_ids) -> dict[str, set[str]]:
    """{sub_mod: {遊戲會載入的 tag}}——`common` 恆載入，加上唯一一個最佳版本夾。

    record id 的 relpath 形如 ``mods/<sub_mod>/<tag>/media/...``。tag 為 ``media``
    者代表 mod 根（B41 遺留），永遠不會入選。無合格版本夾時只剩 ``common``。
    """
    tags: dict[str, set[str]] = {}
    for rid in record_ids:
        _, _, rest = rid.partition("|")
        relpath, _, _ = rest.partition("|")
        parts = relpath.split("/")
        if len(parts) >= 3 and parts[0] == "mods":
            tags.setdefault(parts[1], set()).add(parts[2])
    out: dict[str, set[str]] = {}
    for sub, ts in tags.items():
        cands = [t for t in ts
                 if t != "common" and MIN_REQUIRED_INT <= _version_int(t) <= GAME_VERSION_INT]
        out[sub] = {"common"} | ({max(cands, key=_version_int)} if cands else set())
    return out


def is_effective(rid: str, eff: dict[str, set[str]]) -> bool:
    """該 record 在執行期是否真的存在。

    路徑不符 ``mods/<sub>/<tag>/…`` 形狀者一律放行（少數 mod 的語料路徑不帶
    分支層，寧可高估也不要靜默丟棄）。``translate_en`` 另要求副檔名為 ``.json``。
    """
    kind, _, rest = rid.partition("|")
    relpath, _, _ = rest.partition("|")
    parts = relpath.split("/")
    if len(parts) < 3 or parts[0] != "mods":
        return True
    if parts[2] not in eff.get(parts[1], set()):
        return False
    return kind != "translate_en" or relpath.endswith(".json")

# As1「[B42]統一模組漢化」包（layer-B 主力上游）；固定納入 watch-list
AS1_WORKSHOP_ID = "3556540080"
AS1_MOD_ID = "B42ModTrans_CN"

# Steam Workshop / API
STEAM_APPID = "108600"  # Project Zomboid
STEAM_API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
RESULT_OK = 1
RESULT_NOT_FOUND = 9  # 已下架 / 無效 ID：標記 removed、不重試下載

# issue 冪等：單一共通 label + body HTML marker
ISSUE_LABEL = "tracker"
ISSUE_TYPE_SYNC = "sync"  # 待同步（layer-B）
ISSUE_TYPE_STALE = "stale"  # 可能過時（layer-A）
ISSUE_TYPE_REMOVED = "removed"  # 已下架（Workshop 項目不可存取，需人工確認處置）
_MARKER_RE = re.compile(
    r"<!--\s*tracker:type=(?P<type>[^;]+);id=(?P<id>[^;]+);hash=(?P<hash>[^;\s]+)\s*-->"
)


def make_marker(issue_type: str, workshop_id: str, content_hash: str) -> str:
    """生成藏於 issue body 的身分/內容 marker。"""
    return f"<!-- tracker:type={issue_type};id={workshop_id};hash={content_hash} -->"


def parse_markers(body: str) -> list[tuple[str, str, str]]:
    """由 issue body 解析出 marker。只認第一個（工具自置於首行）→ 防上游注入偽 marker 竄改身分。"""
    m = _MARKER_RE.search(body)
    return [(m["type"], m["id"], m["hash"])] if m else []


def _neutralize_markers(text: str) -> str:
    """中和上游字串（record id、mod 名等）中的 HTML comment 邊界，防偽造 tracker marker 注入 body。"""
    return text.replace("<!--", "<!ˍ--").replace("-->", "--ˍ>")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# 通用 JSON I/O（確定性寫出：UTF-8 無 BOM、sort_keys、LF、尾端換行）
# ============================================================
def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


# 容錯上限：每輪刪一個逗號且字串必然變短，故必定收斂；上限只是病態輸入的保險絲
_TRAILING_COMMA_LIMIT = 500


def _next_nonspace(text: str, i: int) -> str:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return text[i : i + 1]


def _drop_trailing_comma(text: str, pos: int) -> str | None:
    """把解析器停在 ``pos`` 的那個多餘逗號刪掉；不是這個情形則回 ``None``。

    **只認真正的尾逗號**——刪掉後緊接的非空白字元必須是 ``}`` 或 ``]``。少了這道
    確認就會把「壞掉但不是尾逗號」的 JSON 靜默改成另一份合法資料
    （2026-08-12 codex review 的反例：``[1,,2]`` → ``[1,2]``、``{,"a":1}`` → ``{"a":1}``），
    那等於偽造上游原文，比整檔跳過更糟。

    兩種停點都要處理，**因為訊息與位置隨行尾格式而異**（實測 CPython 3.13）：
    LF 檔停在逗號本身（``Illegal trailing comma``），CRLF 檔停在後面的 ``}``
    （``Expecting property name enclosed in double quotes``）。只認前者會讓
    CRLF 的上游檔案全部落回「整檔跳過」——而上游 mod 用 CRLF 是常態。

    安全性：``pos`` 是解析器**在結構位置**停下的地方，故其字元與往回略過的空白
    都在字串字面之外，刪掉的逗號必然是結構性的，不會動到值裡的 ``"[x,] "``。
    """
    # 先定位候選逗號：停在逗號上就是它；停在收尾括號上則往回略過空白找。
    if text[pos : pos + 1] == ",":
        i = pos
    elif text[pos : pos + 1] in ("}", "]"):
        i = pos - 1
        while i >= 0 and text[i] in " \t\r\n":
            i -= 1
        if i < 0 or text[i] != ",":
            return None
    else:
        return None
    # 真尾逗號的定義：**後面接收尾括號、前面接一個完整的值**。
    # 少了任一邊就會把壞檔改成另一份合法資料：後面沒檢查 → `[1,,2]`→`[1,2]`；
    # 前面沒檢查 → `{,"a":1}`→`{"a":1}`、`{"a":1,,}`→`{"a":1}`。
    if _next_nonspace(text, i + 1) not in ("}", "]"):
        return None
    j = i - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    if j < 0 or text[j] in (",", "{", "[", ":"):
        return None
    return text[:i] + text[i + 1 :]


def load_upstream_json(path: Path) -> tuple[dict, bool]:
    """讀**上游**模組的 JSON，回傳 (資料, 是否走了容錯路徑)。

    上游翻譯檔常帶結尾多餘逗號——遊戲照樣載入、`json.loads` 直接拋。原本的做法是
    印一行 stderr 就跳過整檔，等於**該檔的每一個鍵對追蹤器、`sources/en/` 鏡像、
    coverage 全部不存在，而所有 gate 都是綠的**。2026-08-12 實測 PompsItems
    （2752664795）四個 EN 檔皆如此，1,766 個鍵長期隱形，其中 104 個是玩家看得到、
    我方沒出貨的文字（issue #111 表面上只有 7 筆 id-only record，就是這樣藏起來的）。

    **只刪解析器自己停下的那一個逗號**（見 `_drop_trailing_comma`），逐次重試。
    不可改用 `re.sub(r",(\\s*[}\\]])", ...)` 之類的全文替換——那會連字串值裡的
    `"list is [x,] here"` 一起改成 `[x]`，靜默竄改上游原文（＝我方 EN 錨點失真）。
    解析器停下的位置在文法上必然落在字串外，這是本作法唯一安全的理由。

    只對「上游來源」容錯：`sources/` 底下是我方人工真相，壞 JSON 應該炸給人看。
    """
    text = path.read_text(encoding="utf-8-sig")
    lenient = False
    for _ in range(_TRAILING_COMMA_LIMIT + 1):   # +1：最後一次修完仍要有機會 parse
        try:
            return json.loads(text), lenient
        except json.JSONDecodeError as exc:
            fixed = _drop_trailing_comma(text, exc.pos)
            if fixed is None:
                raise
            text = fixed
            lenient = True
    raise ValueError(f"{path}：多餘逗號超過 {_TRAILING_COMMA_LIMIT} 個，判定為壞檔而非可容錯的小瑕疵")


def write_json(path: Path, data: dict) -> None:
    """原子寫出：先寫同目錄暫存檔再 os.replace。

    en_corpus_hashes.json 是 30MB+ 的受版控真相，且 backfill 期間每 10 個 mod 就重寫一次；
    直接覆寫時若中途中斷會留下截斷的 JSON＝基準毀損、整輪重跑。同目錄暫存確保 replace
    是同一檔案系統上的原子操作。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        # Windows：目標若正被其他行程開啟讀取（例：backfill 執行中同時跑 coverage），
        # os.replace 會拋 PermissionError——舊的直接覆寫不會。原子性不能換來新的當機，
        # 故短重試；POSIX 無此限制，重試不會執行到。
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.3)
    finally:
        tmp.unlink(missing_ok=True)


# ============================================================
# API client（GetPublishedFileDetails v1；免 key 為主、批次、退避、缺漏重試）
# ============================================================
def _post_form(url: str, params: list[tuple[str, str]], timeout: float = 30.0) -> dict:
    """POST x-www-form-urlencoded，回傳解析後 JSON。HTTPError/URLError 交由呼叫端退避。"""
    data = urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "modlangfor42-tracker/1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_with_retry(
    params: list[tuple[str, str]],
    *,
    max_retries: int = 5,
    base_delay: float = 1.0,
    jitter: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """429/5xx 用 Retry-After + 指數退避 + jitter 重試；其他錯誤直接拋。"""
    for attempt in range(max_retries + 1):
        try:
            return _post_form(STEAM_API_URL, params)
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt >= max_retries:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after and retry_after.strip().isdigit():
                delay = float(retry_after.strip())
            else:
                delay = base_delay * (2 ** attempt)
            sleep(delay + random.uniform(0.0, jitter))
        except urllib.error.URLError:
            if attempt >= max_retries:
                raise
            sleep(base_delay * (2 ** attempt) + random.uniform(0.0, jitter))
    raise RuntimeError("unreachable")  # pragma: no cover


def _details_from_response(resp: dict) -> dict[str, dict]:
    """由 API 回應抽出 {publishedfileid: detail}。"""
    out: dict[str, dict] = {}
    for detail in resp.get("response", {}).get("publishedfiledetails", []):
        pid = str(detail.get("publishedfileid", ""))
        if pid:
            out[pid] = detail
    return out


def _fetch_batch(ids: list[str], api_key: str | None) -> dict[str, dict]:
    """單批查詢（itemcount + publishedfileids[N] 原生批次）。"""
    params: list[tuple[str, str]] = [("itemcount", str(len(ids)))]
    for i, wid in enumerate(ids):
        params.append((f"publishedfileids[{i}]", wid))
    if api_key:  # 設定選項、非解藥：存在才附加
        params.append(("key", api_key))
    return _details_from_response(_post_with_retry(params))


def fetch_details(
    ids: list[str], *, batch: int = 18, api_key: str | None = None
) -> dict[str, dict]:
    """批次查全部 ID → 逐 ID 驗證回傳 → 缺漏 ID 逐項重試一次。回傳 {id: detail}。"""
    result: dict[str, dict] = {}
    for start in range(0, len(ids), batch):
        chunk = ids[start : start + batch]
        result.update(_fetch_batch(chunk, api_key))
    # 缺漏 ID（批次未回）逐項重試一次，壓低批次偶發丟項
    missing = [wid for wid in ids if wid not in result]
    for wid in missing:
        try:
            result.update(_fetch_batch([wid], api_key))
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"  ⚠️ 缺漏重試失敗 {wid}: {exc}", file=sys.stderr)
    return result


def coverage_guard(ids: list[str], details: dict[str, dict]) -> None:
    """API 回應覆蓋率檢查並印「查得 X/Y」；全空或缺項 >50% 視為 API 異常 → 非零退出。
    （避免把 API 故障誤判為『全數無變更/全下架』而污染 state。）"""
    total = len(ids)
    if total == 0:
        return
    got = len(details)
    print(f"  查得 {got}/{total} 筆 API 回應")
    if got == 0:
        print("❌ ids 非空但 API 回應全空，中止（疑似 API 故障/封鎖）。", file=sys.stderr)
        sys.exit(1)
    miss_ratio = (total - got) / total
    if miss_ratio > 0.5:
        print(f"❌ API 缺項比例 {miss_ratio:.0%} > 50%，中止（疑似 API 異常）。", file=sys.stderr)
        sys.exit(1)


def ci_baseline_guard(bootstrap: bool) -> None:
    """CI 缺 baseline fail-fast：TRACKER_CI=1 且非 --bootstrap 時，baseline 檔缺失即非零退出。
    （本機首建 baseline 走顯式 --bootstrap 允許空 state 起跑。）"""
    if bootstrap:
        return
    if os.environ.get("TRACKER_CI") != "1":
        return
    missing = [p for p in (TIMESTAMPS_JSON, EN_CORPUS_HASHES_JSON) if not p.exists()]
    if missing:
        names = "、".join(p.relative_to(PROJECT_ROOT).as_posix() for p in missing)
        print(
            f"❌ CI baseline 缺失（{names}）。"
            "須先於本機執行 `uv run scripts/tracker.py run --bootstrap ...` 建立 baseline 並 commit 後，再跑 CI。",
            file=sys.stderr,
        )
        sys.exit(1)


# ============================================================
# 狀態讀寫（timestamps.json / en_corpus_hashes.json）
# ============================================================
def load_timestamps() -> dict:
    if TIMESTAMPS_JSON.exists():
        data = load_json(TIMESTAMPS_JSON)
        data.setdefault("schema_version", SCHEMA_VERSION)
        data.setdefault("items", {})
        return data
    return {"schema_version": SCHEMA_VERSION, "items": {}}


def load_corpus_hashes() -> dict:
    if EN_CORPUS_HASHES_JSON.exists():
        data = load_json(EN_CORPUS_HASHES_JSON)
        data.setdefault("schema_version", SCHEMA_VERSION)
        data.setdefault("extractor_schema", EXTRACTOR_SCHEMA)
        data.setdefault("mods", {})
        return data
    return {"schema_version": SCHEMA_VERSION, "extractor_schema": EXTRACTOR_SCHEMA, "mods": {}}


def load_watchlist() -> dict:
    if not WATCHLIST_JSON.exists():
        print(
            f"❌ 找不到 {WATCHLIST_JSON.relative_to(PROJECT_ROOT)}。"
            f"請先執行：uv run scripts/tracker.py gen-watchlist",
            file=sys.stderr,
        )
        sys.exit(1)
    return load_json(WATCHLIST_JSON)


def load_attribution_keys() -> set[str]:
    """載入 sources/attribution_index.json 的鍵集（若存在）；用於標註『As1 是否已翻譯』。"""
    if not ATTRIBUTION_INDEX_JSON.exists():
        return set()
    try:
        idx = load_json(ATTRIBUTION_INDEX_JSON)
    except (json.JSONDecodeError, OSError):
        return set()
    # attribution_index key 形狀為『檔名|鍵』→ owner；鍵集即『As1 已涵蓋』的翻譯項
    return set(idx.keys()) if isinstance(idx, dict) else set()


# ============================================================
# 語料抽取與標準化（layer-A / layer-B 共用；record = (kind, relpath, key, value)）
# ============================================================
# PZ script 定義區塊（extractor_schema=3）：行首 <keyword> <name>，名稱可含空白（craftRecipe 常見），
# 且名稱後必須接 "{"（同行或下一非空行）才算定義——排除 craftRecipe 內文數量指令（"item 1 Base.Bandage,"）。
_SCRIPT_LINE_RE = re.compile(r"^\s*(item|craftRecipe|recipe|vehicle|fixing)\s+([^{}\r\n]+?)\s*(\{)?\s*$")


# B41 translate .txt 的鍵值行（basic）：Key = "value"（值取至行內最後一個引號；多行接續只取首段，
# 足供變更偵測）。檔頭宣告行（IG_UI_EN = {）無引號不會誤中。
_TXT_KV_RE = re.compile(r'^\s*([A-Za-z0-9_.]+)\s*=\s*"(.*)"', re.MULTILINE)


def _in_translate_lang(path: Path, lang: str) -> bool:
    parts = path.parts
    if "Translate" not in parts:
        return False
    ti = parts.index("Translate")
    return ti + 1 < len(parts) and parts[ti + 1] == lang


def _iter_translate_records(mod_dir: Path, lang: str) -> list[tuple[str, str, str, str]]:
    """抽取 media/**/Translate/<lang>/ 下 *.json（PZ 扁平 {鍵:值}）與 *.txt（B41 行式）的
    (kind, relpath, key, value)。"""
    records: list[tuple[str, str, str, str]] = []
    for jf in sorted(mod_dir.rglob("*.json")):
        if jf.is_symlink():  # 跳過 symlink，避免逸出下載目錄
            continue
        if not _in_translate_lang(jf, lang):
            continue
        try:
            data, lenient = load_upstream_json(jf)
        # ValueError 涵蓋 JSONDecodeError 與容錯上限——單一壞檔不該炸掉整輪排程
        except (ValueError, OSError) as exc:
            # 容錯後仍失敗＝這一整檔的鍵對追蹤器與覆蓋率報表永久不存在，講清楚後果
            print(f"  ❌ JSON 無法解析，整檔的翻譯鍵將不被追蹤：{jf}（{exc}）", file=sys.stderr)
            continue
        if lenient:
            print(f"  ⚠️ JSON 帶結尾多餘逗號，已容錯解析：{jf}", file=sys.stderr)
        if not isinstance(data, dict):
            continue
        # record identity 帶相對路徑（同 basename 不同目錄不互撞；EXTRACTOR_SCHEMA=2）
        relpath = jf.relative_to(mod_dir).as_posix()
        for key in sorted(data):
            records.append((f"translate_{lang.lower()}", relpath, key, str(data[key])))
    for tf in sorted(mod_dir.rglob("*.txt")):  # B41 格式（EXTRACTOR_SCHEMA=4）
        if tf.is_symlink():
            continue
        if not _in_translate_lang(tf, lang):
            continue
        try:
            text = tf.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        relpath = tf.relative_to(mod_dir).as_posix()
        kv: dict[str, str] = {}
        for m in _TXT_KV_RE.finditer(text.replace("\r\n", "\n")):
            kv[m.group(1)] = m.group(2)  # 同檔重複鍵取後者（PZ 後定義生效；上游 .txt 偶見重複定義）
        for key in sorted(kv):
            records.append((f"translate_{lang.lower()}", relpath, key, kv[key]))
    return records


_DISPLAYNAME_RE = re.compile(r"^\s*DisplayName\s*=\s*(.+?)\s*,?\s*$")


def _scan_item_displayname(lines: list[str], start: int) -> str | None:
    """自 item 區塊標頭往下以大括號配對界定範圍，取區塊頂層「最後一筆」DisplayName（無則 None）。

    只認 depth==1（item 本層），巢狀子區塊（component 等）內的 DisplayName 不誤歸屬；
    同區塊重複 property 取後者——PZ Item.DoParam 逐條覆寫欄位，後定義生效。
    """
    # ponytail: 逐行大括號計數，跳過 '/' 開頭註解行；跨行 /* */ 內的不成對大括號仍會干擾
    # 配對（實測 1575 個 workshop script 檔 0 命中）——若未來誤判，升級為去註解預處理。
    depth = 0
    entered = False
    found: str | None = None
    for line in lines[start:]:
        if line.lstrip().startswith("/"):
            continue
        if entered and depth == 1:
            m = _DISPLAYNAME_RE.match(line)
            if m:
                found = m.group(1).strip()
        depth += line.count("{") - line.count("}")
        if depth > 0:
            entered = True
        elif entered:
            break
    return found


def _iter_script_records(mod_dir: Path) -> list[tuple[str, str, str, str]]:
    """抽取所有 media/scripts/**/*.txt 的 item/recipe 區塊名（basic 正則、value=名本身）；
    item 區塊另抽 DisplayName 為獨立 record（script_item_dn）。

    EXTRACTOR_SCHEMA=5：掃全部 media/scripts 目錄、relpath 為 mod_dir 相對。
    同檔同名 item 重複定義時 DisplayName 取後者（PZ 後定義生效，同 translate .txt 慣例）。
    """
    records: list[tuple[str, str, str, str]] = []
    script_dirs = [
        cand for cand in sorted(mod_dir.rglob("scripts"))
        if cand.is_dir() and cand.parent.name == "media"
    ]
    for scripts_dir in script_dirs:
        for tf in sorted(scripts_dir.rglob("*.txt")):
            if tf.is_symlink():  # 跳過 symlink，避免逸出下載目錄
                continue
            try:
                text = tf.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            rel = tf.relative_to(mod_dir).as_posix()
            lines = text.splitlines()
            dn_map: dict[str, str] = {}
            for i, line in enumerate(lines):
                m = _SCRIPT_LINE_RE.match(line)
                if not m:
                    continue
                kw, name, brace = m.group(1), m.group(2).strip(), m.group(3)
                if not brace:
                    nxt = next((ln.strip() for ln in lines[i + 1:] if ln.strip()), "")
                    if not nxt.startswith("{"):
                        continue
                records.append((f"script_{kw}", rel, name, name))
                if kw == "item":
                    dn = _scan_item_displayname(lines, i)
                    if dn is not None:
                        dn_map[name] = dn
            for name, dn in dn_map.items():
                records.append(("script_item_dn", rel, name, dn))
    return records


# --- Lua 文本抽取（EXTRACTOR_SCHEMA=6）------------------------------------- #
# 這一層刻意不用純 regex。實測 regex 版四種錯法（皆已納入 self-test 情境 11）：
#   1. `-- getText("IGUI_Dead")` 註解裡的呼叫被當成真引用
#   2. `targetText(` 因未檢查 identifier 邊界而從字中命中 `getText`
#   3. `setText("Don't open this")` 因 quote class 排除 `'` 而整串漏抓
#   4. 「sink 之後 N 字元內找第一個字串」會抓到不相干的下一句
# 故先做最小 lexical scan（跳註解與長字串、取出短字串常值的精確 span），
# 再用平衡括號界定呼叫範圍。
_LUA_IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")

# 直接吃字面字串的 UI 文字 API——命中即「寫死英文」，連翻譯鍵都沒有，
# 只能靠 sources/lua/ 覆寫。清單保守，寧可漏抓也不要灌一堆 false positive。
_LUA_UI_SINKS = (
    "setTitle", "setName", "setText", "setTooltip", "setToolTip", "setSecondLine",
    "addOption", "addLabel", "ISModalDialog.new", "ISTextBox.new",
)
_LUA_GETTEXT_NAMES = ("getText", "getTextOrNull")
# 平衡括號掃描上限：避免對病態輸入退化，也擋掉「呼叫沒收尾」時吃到整個檔案。
_LUA_CALL_MAX_SPAN = 2000
# 字面看起來像「英文句子」才收：至少兩個詞、開頭字母、不含路徑/識別字特徵。
_LUA_PROSE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ,.'!?:;()\-/%]*\s[A-Za-z0-9].*$")
_LUA_NOT_PROSE_RE = re.compile(r"\.(lua|png|txt|ogg|wav|json)\b|[\\/]{1,2}|^\s*$", re.I)
_LUA_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\"}


def _lua_long_bracket(text: str, i: int) -> int | None:
    """`text[i]` 起若為長括號 `[=*[`，回傳 `=` 的層數，否則 None。"""
    if i >= len(text) or text[i] != "[":
        return None
    j = i + 1
    while j < len(text) and text[j] == "=":
        j += 1
    return j - i - 1 if j < len(text) and text[j] == "[" else None


def _lua_scan(text: str) -> tuple[str, list[tuple[int, int, str]]]:
    """最小 Lua lexer：回傳 (masked, strings)。

    * ``masked``：與原文等長，註解與所有字串「內容」置換為空白——供 identifier
      邊界判斷與平衡括號掃描，確保註解／字串裡的括號與關鍵字不干擾。
    * ``strings``：短字串常值 ``(起, 迄, 解碼後內容)``；起迄為含引號的 span。
      長字串 `[[...]]` 不收（PZ mod 的 UI 文字實務上都用短字串，長字串多為資料塊）。
    """
    n = len(text)
    out = list(text)
    strings: list[tuple[int, int, str]] = []
    i = 0
    while i < n:
        c = text[i]
        if c == "-" and text.startswith("--", i):
            lvl = _lua_long_bracket(text, i + 2)
            if lvl is None:  # 行註解
                j = text.find("\n", i)
                j = n if j < 0 else j
            else:  # 長註解 --[=*[ ... ]=*]
                close = "]" + "=" * lvl + "]"
                k = text.find(close, i + 2)
                j = n if k < 0 else k + len(close)
            for p in range(i, j):
                if out[p] != "\n":
                    out[p] = " "
            i = j
            continue
        if c in "\"'":
            quote = c
            j = i + 1
            buf: list[str] = []
            while j < n:
                ch = text[j]
                if ch == "\\" and j + 1 < n:
                    buf.append(_LUA_ESCAPES.get(text[j + 1], text[j + 1]))
                    j += 2
                    continue
                if ch == quote or ch == "\n":  # 收尾或未閉合（Lua 短字串不跨行）
                    break
                buf.append(ch)
                j += 1
            if j < n and text[j] == quote:
                strings.append((i, j + 1, "".join(buf)))
                for p in range(i + 1, j):
                    out[p] = " "
                i = j + 1
                continue
            i += 1  # 未閉合：不當字串，避免吃掉整個檔案
            continue
        lvl = _lua_long_bracket(text, i)
        if lvl is not None:
            close = "]" + "=" * lvl + "]"
            k = text.find(close, i)
            j = n if k < 0 else k + len(close)
            for p in range(i, j):
                if out[p] != "\n":
                    out[p] = " "
            i = j
            continue
        i += 1
    return "".join(out), strings


def _lua_calls(masked: str, names: tuple[str, ...]) -> list[tuple[int, int]]:
    """在 masked 文字中找 `name(` 呼叫，回傳 (左括號位置, 右括號位置) 的平衡括號 span。

    identifier 邊界必檢——否則 `targetText(` 會從字中命中 `getText`。
    """
    spans: list[tuple[int, int]] = []
    for name in names:
        start = 0
        while True:
            idx = masked.find(name, start)
            if idx < 0:
                break
            start = idx + 1
            prev = idx - 1
            # 名稱前一字元不得是 identifier 字元（`.` 允許：ISModalDialog.new / self.getText）
            if prev >= 0 and masked[prev] in _LUA_IDENT_CHARS:
                continue
            end_id = idx + len(name)
            if end_id < len(masked) and masked[end_id] in _LUA_IDENT_CHARS:
                continue  # `getTextWidth(` 之類不算
            j = end_id
            while j < len(masked) and masked[j] in " \t":
                j += 1
            if j >= len(masked) or masked[j] != "(":
                continue
            depth, k, limit = 0, j, min(len(masked), j + _LUA_CALL_MAX_SPAN)
            close = -1
            while k < limit:
                if masked[k] == "(":
                    depth += 1
                elif masked[k] == ")":
                    depth -= 1
                    if depth == 0:
                        close = k
                        break
                k += 1
            if close > 0:
                spans.append((j, close))
    return spans


def _iter_lua_records(mod_dir: Path) -> list[tuple[str, str, str, str]]:
    """抽取 Lua 兩類文本（schema 6）：

    * ``lua_gettext``：getText/getTextOrNull 的**第一個引數字面**＝翻譯鍵。
      value=鍵本身（無英文可取；鍵有沒有譯文要跟 Translate 語料交叉比對）。
      **用途是覆蓋率查核**——被 Lua 引用＝確證玩家可見，優先序高於「在上游 EN 檔
      裡但可能根本沒用到」的鍵。
    * ``lua_literal``：UI 文字 API 直接吃的英文字面。value=字面本身，key=其
      sha1[:12]（用 hash 而非行號，讓上游改行不製造假變更）。**這是唯一沒有翻譯鍵
      可用的文本**，要蓋只能走 sources/lua/ 覆寫。

    判準：
    * 字面落在任一 getText 呼叫的括號內 → 屬 `getText("KEY", "English")` 慣用法，
      該鍵已由 lua_gettext 收錄，不重複算成「寫死」。
    * 只收「至少兩個詞、不含路徑/副檔名特徵、長度 ≥8」的字面；單字標籤
      （Cancel/Building）與資源名一律放掉——寧可漏抓也不要污染語料。

    已知盲區：動態組鍵 ``getText("Pre" .. v)`` 只會收到前綴（使用端以
    `_is_real_key` 濾掉）；`[[長字串]]` 不收。
    """
    records: list[tuple[str, str, str, str]] = []
    for lf in sorted(mod_dir.rglob("*.lua")):
        if lf.is_symlink():  # 跳過 symlink，避免逸出下載目錄
            continue
        try:
            text = lf.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        rel = lf.relative_to(mod_dir).as_posix()
        masked, strings = _lua_scan(text)
        gt_spans = _lua_calls(masked, _LUA_GETTEXT_NAMES)

        def first_arg(open_i: int, close_i: int) -> tuple[int, int, str] | None:
            """呼叫的第一個引數若是字串常值（其前只有空白）則回傳之。"""
            for s, e, v in strings:
                if s <= open_i or s >= close_i:
                    continue
                return (s, e, v) if not masked[open_i + 1:s].strip() else None
            return None

        keys: set[str] = set()
        for o, c in gt_spans:
            arg = first_arg(o, c)
            if arg:
                keys.add(arg[2])
        for key in sorted(keys):
            records.append(("lua_gettext", rel, key, key))

        lits: dict[str, str] = {}
        for o, c in _lua_calls(masked, _LUA_UI_SINKS):
            for s, _e, v in strings:
                if not (o < s < c):
                    continue
                if any(go < s < gc for go, gc in gt_spans):
                    continue  # getText 的引數，有鍵可譯，不算寫死
                if len(v) < 8 or _LUA_NOT_PROSE_RE.search(v) or not _LUA_PROSE_RE.match(v):
                    continue
                lits[hashlib.sha1(v.encode("utf-8")).hexdigest()[:12]] = v
                break  # 每個呼叫只取第一個合格字面，避免一次呼叫灌一堆
        for kh in sorted(lits):
            records.append(("lua_literal", rel, kh, lits[kh]))
    return records


def extract_corpus(mod_dir: Path, lang: str = "EN") -> list[tuple[str, str, str, str]]:
    """layer-A 全語料：Translate/<lang> + media/scripts item/recipe 名 + Lua 文本（schema 6）。"""
    return (
        _iter_translate_records(mod_dir, lang)
        + _iter_script_records(mod_dir)
        + _iter_lua_records(mod_dir)
    )


def records_to_map(records: list[tuple[str, str, str, str]]) -> dict[str, str]:
    """record 清單 → {record_id: value_hash}；record_id = kind|relpath|key。重複 ID 報錯不覆寫。"""
    out: dict[str, str] = {}
    for kind, relpath, key, value in records:
        rid = f"{kind}|{relpath}|{key}"
        vh = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
        if rid in out:
            if out[rid] == vh:  # 同值重複（如同名 script 區塊）無資訊損失，靜默折疊
                continue
            raise ValueError(f"重複 record ID 且值不同（拒絕覆寫，恐掩蓋上游變更）：{rid}")
        out[rid] = vh
    return out


def corpus_hash(records: list[tuple[str, str, str, str]]) -> str:
    """全語料標準化 hash：sort 後逐行 kind|relpath|key|value 串接 sha256。"""
    lines = sorted(f"{k}|{r}|{key}|{v}" for k, r, key, v in records)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def diff_corpus(
    old_map: dict[str, str], new_records: list[tuple[str, str, str, str]]
) -> dict[str, list[str]]:
    """比對 baseline record_map vs 新 records，分類新增/刪除/修改（回 record_id 清單）。"""
    new_map = records_to_map(new_records)
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    modified = sorted(rid for rid in set(old_map) & set(new_map) if old_map[rid] != new_map[rid])
    return {"added": added, "removed": removed, "modified": modified}


def rid_file_key(record_id: str) -> str:
    """由 record_id（kind|relpath|key）取出 attribution 比對鍵『檔名|鍵』（basename|key）。"""
    parts = record_id.split("|", 2)
    if len(parts) < 3:
        return record_id
    _kind, relpath, key = parts
    return f"{Path(relpath).name}|{key}"


# ============================================================
# layer-B：As1 CN 樹 vs 本 repo sources/ 現況
# ============================================================
def _merge_cn_maps(records: list[tuple[str, str, str, str]]) -> dict[str, dict[str, str]]:
    """把 CN records 併成 {檔名: {鍵: 值}}（多來源同鍵同值靜默；此處僅供比對）。"""
    merged: dict[str, dict[str, str]] = {}
    for _kind, relpath, key, value in records:
        merged.setdefault(Path(relpath).name, {})[key] = value
    return merged


def _is_own_mod(mod_dir: Path) -> bool:
    """metadata.json 標 origin=='own' 的原創翻譯 mod（非 As1 衍生）。

    無法判別（metadata 缺失/壞損）時 fail-closed：own CN 一旦誤入 layer-B
    基準會被假報為 As1 removed，寧可中止也不可降級成 As1 來源。
    """
    meta = mod_dir / "metadata.json"
    if not meta.is_file():
        raise SystemExit(f"{mod_dir} 缺 metadata.json，無法判別 As1/own 來源（layer-B 基準需明確歸類）")
    try:
        return json.loads(meta.read_text(encoding="utf-8-sig")).get("origin") == "own"
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"無法解析 {meta}：{exc}") from exc


def read_repo_sources_cn() -> list[tuple[str, str, str, str]]:
    """讀本 repo sources/mods/*/CN + sources/_unsorted/CN 的 CN 語料（layer-B 基準）。

    origin=='own' 的原創 mod 不屬 As1 語料，納入會使 layer-B 恆報 removed，跳過。
    """
    records: list[tuple[str, str, str, str]] = []
    cn_dirs: list[Path] = []
    mods_dir = SOURCES / "mods"
    if mods_dir.is_dir():
        for mod_dir in sorted(mods_dir.iterdir()):
            if _is_own_mod(mod_dir):
                continue
            cn = mod_dir / "CN"
            if cn.is_dir():
                cn_dirs.append(cn)
    unsorted = SOURCES / "_unsorted" / "CN"
    if unsorted.is_dir():
        cn_dirs.append(unsorted)
    for cn in cn_dirs:
        for jf in sorted(cn.glob("*.json")):
            try:
                data = load_json(jf)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  ⚠️ 壞 JSON 跳過：{jf}（{exc}）", file=sys.stderr)
                continue
            for key in sorted(data):
                records.append(("translate_cn", jf.name, key, str(data[key])))
    return records


def diff_layer_b(
    new_as1_records: list[tuple[str, str, str, str]],
    repo_records: list[tuple[str, str, str, str]],
) -> dict:
    """As1 新 CN 樹 vs repo sources 現況；回 {has_diff, added, removed, modified 計數 + 樣本}。"""
    new_merged = _merge_cn_maps(new_as1_records)
    repo_merged = _merge_cn_maps(repo_records)
    added: list[str] = []
    removed: list[str] = []
    modified: list[str] = []
    all_files = sorted(set(new_merged) | set(repo_merged))
    for fname in all_files:
        nf = new_merged.get(fname, {})
        rf = repo_merged.get(fname, {})
        for key in set(nf) - set(rf):
            added.append(f"{fname}|{key}")
        for key in set(rf) - set(nf):
            removed.append(f"{fname}|{key}")
        for key in set(nf) & set(rf):
            if nf[key] != rf[key]:
                modified.append(f"{fname}|{key}")
    has_diff = bool(added or removed or modified)
    return {
        "has_diff": has_diff,
        "added": sorted(added),
        "removed": sorted(removed),
        "modified": sorted(modified),
    }


# ============================================================
# downloader module（steamcmd wrapper + 裁剪）；僅真實模式執行，self-test 以 mock 取代
# ============================================================
# steamcmd 成功時輸出此訊號；缺此訊號一律視為失敗（防偽成功）
STEAMCMD_SUCCESS_SIGNAL = "Success. Downloaded item"


def _tracker_scratch_roots() -> list[Path]:
    """允許 steamcmd 下載/裁剪/刪除的根目錄白名單（防 trim_download 誤刪 Steam library）。"""
    return [
        (TRACKER_STATE / "_dl").resolve(),
        (Path(tempfile.gettempdir()) / "modlangfor42-tracker").resolve(),
    ]


def _within_scratch(path: Path) -> bool:
    """path 是否位於（或等於）任一 tracker 專屬 scratch root 之下。"""
    resolved = path.resolve()
    for root in _tracker_scratch_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def resolve_install_dir(raw: str | None) -> Path:
    """解析並限制 --install-dir：必須位於 tracker 專屬 scratch root 內，外部路徑直接拒絕退出。"""
    install_dir = (Path(raw).resolve() if raw else (TRACKER_STATE / "_dl").resolve())
    if not _within_scratch(install_dir):
        print(
            "❌ --install-dir 必須位於 tracker 專屬目錄內"
            "（repo tracker-state/_dl 或系統 temp/modlangfor42-tracker）；"
            f"外部路徑遭拒：{install_dir}",
            file=sys.stderr,
        )
        sys.exit(1)
    return install_dir


def steamcmd_download(
    workshop_id: str, steamcmd: Path, install_dir: Path
) -> Path | None:
    """steamcmd 匿名下載單一 Workshop 物品。防偽成功：rc==0＋成功訊號＋目錄非空缺一不可 → 否則 None。"""
    # workshop_id 進 argv 前檢核純數字，杜絕注入 steamcmd 命令
    if not workshop_id.isdigit():
        print(f"  ⚠️ 非法 workshop_id（非純數字），跳過：{workshop_id!r}", file=sys.stderr)
        return None
    content = install_dir / "steamapps" / "workshop" / "content" / STEAM_APPID / workshop_id
    # 下載前安全清除舊內容（僅限 tracker scratch root 內），避免上一輪殘檔偽裝成功
    if content.exists():
        if not _within_scratch(content):
            print(f"  ⚠️ content 目錄不在 tracker scratch root 內，拒絕清除：{content}", file=sys.stderr)
            return None
        shutil.rmtree(content, ignore_errors=True)
    cmd = [
        str(steamcmd),
        "+force_install_dir",
        str(install_dir),
        "+login",
        "anonymous",
        "+workshop_download_item",
        STEAM_APPID,
        workshop_id,
        "+quit",
    ]
    # 匿名下載兩大失敗模式，皆以原地重試（最多 3 次）處理：
    #   1. workshop manifest（ACF）連續下載後毒化 → 之後所有物品固定 Failure（實測換新目錄立即成功）
    #      → 重試前刪 ACF 讓 steamcmd 重建，內容檔不受影響。
    #   2. 大型物品逾時斷線 → steamcmd 於 downloads/ staging 續傳。
    acf = install_dir / "steamapps" / "workshop" / f"appworkshop_{STEAM_APPID}.acf"
    for attempt in range(1, 4):
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        out = proc.stdout + proc.stderr
        # 三項全過才算成功；任一不滿足視為本次失敗（steamcmd rc 不可靠，故三重把關）
        if (
            proc.returncode == 0
            and STEAMCMD_SUCCESS_SIGNAL in out
            and content.is_dir()
            and any(content.iterdir())
        ):
            return content
        if attempt < 3:
            if acf.exists() and _within_scratch(acf):
                acf.unlink(missing_ok=True)
            print(f"  …{workshop_id} 第 {attempt} 次未完成，清 ACF 後重試", file=sys.stderr)
            time.sleep(5)
    return None


def trim_download(item_dir: Path) -> None:
    """裁剪：只留 media/**/Translate/、media/scripts/ 與 *.lua，其餘刪除（縮小 artifact）。

    schema 6 起 Lua 也是文本來源（getText 鍵引用＋寫死英文字面），**不能再刪**——
    先前刪掉 Lua 等於讓該層文本對追蹤器永久不可見。
    """

    def keep(path: Path) -> bool:
        parts = path.parts
        return (
            "Translate" in parts
            or ("media" in parts and "scripts" in parts)
            or path.suffix.lower() == ".lua"
        )

    for f in list(item_dir.rglob("*")):
        if f.is_file() and not keep(f):
            f.unlink(missing_ok=True)
    # 清空目錄由下而上移除
    for d in sorted(item_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()


# ============================================================
# issue 冪等（gh 客戶端可注入；real 走 gh CLI，self-test 走記憶體 fake）
# ============================================================
class GhClient:
    """真實 GitHub CLI 客戶端（GITHUB_TOKEN 由環境提供）。"""

    def list_tracker_issues(self) -> list[dict]:
        """列出全部 open『tracker』label issue（gh api --paginate 突破 1000 上限）。
        失敗即 raise 中止本輪 → state 不推進、下輪自癒（fail-closed，避免漏索引誤開重複 issue）。"""
        proc = subprocess.run(
            [
                "gh", "api", "--paginate",
                f"repos/:owner/:repo/issues?labels={ISSUE_LABEL}&state=open",
                "--jq", ".[] | {number, body, title}",
            ],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"gh api 列 tracker issue 失敗（中止本輪，state 未推進下輪自癒）：{proc.stderr.strip()}"
            )
        # --jq `.[] | {...}` 逐行輸出 JSON 物件（非陣列），逐行 parse
        issues: list[dict] = []
        for line in proc.stdout.splitlines():
            s = line.strip()
            if s:
                issues.append(json.loads(s))
        return issues

    def ensure_label(self) -> None:
        """確保『tracker』label 存在（冪等）。缺 label 時 create_issue 會直接失敗
        （實案：首次真實 issue 於 CI 撞 could not add label: 'tracker' not found）。"""
        proc = subprocess.run(
            [
                "gh", "label", "create", ISSUE_LABEL,
                "--description", "上游追蹤器自動 issue（待同步/可能過時/已下架）",
                "--color", "1D76DB",
            ],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        if proc.returncode != 0 and "already exists" not in (proc.stderr + proc.stdout):
            raise RuntimeError(f"gh label create 失敗：{proc.stderr}")

    def create_issue(self, title: str, body: str) -> int:
        proc = subprocess.run(
            ["gh", "issue", "create", "--label", ISSUE_LABEL, "--title", title, "--body", body],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        if proc.returncode != 0:
            raise RuntimeError(f"gh issue create 失敗：{proc.stderr}")
        m = re.search(r"/issues/(\d+)", proc.stdout)
        return int(m.group(1)) if m else -1

    def add_comment(self, number: int, body: str) -> None:
        subprocess.run(
            ["gh", "issue", "comment", str(number), "--body", body],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), check=True,
        )

    def update_body(self, number: int, body: str) -> None:
        subprocess.run(
            ["gh", "issue", "edit", str(number), "--body", body],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), check=True,
        )


def index_issues(issues: list[dict]) -> dict[tuple[str, str], dict]:
    """由 open issue 清單建索引：key=(類型, workshop_id) → {number, hash, body}。"""
    index: dict[tuple[str, str], dict] = {}
    for issue in issues:
        for issue_type, wid, content_hash in parse_markers(issue.get("body", "")):
            index[(issue_type, wid)] = {
                "number": issue["number"],
                "hash": content_hash,
                "body": issue.get("body", ""),
            }
    return index


def apply_issue_plan(
    plan: dict, index: dict[tuple[str, str], dict], gh: GhClient, *, dry_run: bool
) -> str:
    """依 (類型,id) 索引決定 skip / comment / new。回傳實際動作。"""
    ident = (plan["type"], plan["workshop_id"])
    existing = index.get(ident)
    if existing is None:
        action = "new"
    elif existing["hash"] == plan["content_hash"]:
        action = "skip"  # 同 (類型,id) 同 hash → 無事
    else:
        action = "comment"  # 同 (類型,id) 新 hash → 追加 comment + 更新 body 摘要

    if dry_run:
        return action  # dry-run：只回傳計畫動作，不呼叫 gh

    if action == "new":
        number = gh.create_issue(plan["title"], plan["body"])
        index[ident] = {"number": number, "hash": plan["content_hash"], "body": plan["body"]}
    elif action == "comment":
        gh.add_comment(existing["number"], plan["comment"])
        gh.update_body(existing["number"], plan["body"])
        index[ident] = {"number": existing["number"], "hash": plan["content_hash"], "body": plan["body"]}
    return action


# ============================================================
# git commit 重試（可注入 runner；供 self-test 情境 6 mock 併發 fetch-rebase）
# ============================================================
GitRunner = Callable[[list[str]], tuple[int, str, str]]


def _real_git(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    return proc.returncode, proc.stdout, proc.stderr


# commit_state_with_retry 回傳狀態（呼叫端據此區分「無變更」與「失敗」）
COMMIT_OK = "committed"
COMMIT_NOCHANGE = "nochange"
COMMIT_FAILED = "failed"


def _is_non_fast_forward(stderr: str) -> bool:
    """push 失敗是否為 non-fast-forward（他跑先推）；僅此情形值得 rebase 重推。"""
    s = stderr.lower()
    return "non-fast-forward" in s or "rejected" in s or "fetch first" in s


def commit_state_with_retry(
    add_paths: list[str],
    message: str,
    *,
    branch: str | None = None,
    max_retries: int = 3,
    git: GitRunner = _real_git,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """add → commit → (fetch → rebase → push) 全鏈 rc 檢查。
    rebase 失敗立即 abort；只對 non-fast-forward push 重試。回傳 COMMIT_OK / NOCHANGE / FAILED。"""
    if branch is None:
        branch = os.environ.get("TRACKER_BRANCH") or "main"
    rc, _out, err = git(["add", *add_paths])
    if rc != 0:
        print(f"  ⚠️ git add 失敗：{err.strip()}", file=sys.stderr)
        return COMMIT_FAILED
    rc, _out, _err = git(["diff", "--cached", "--quiet"])
    if rc == 0:
        return COMMIT_NOCHANGE  # 無 staged 變更（故不能靠 commit 當活動來源）
    rc, _out, err = git(["commit", "-m", message])
    if rc != 0:
        print(f"  ⚠️ git commit 失敗：{err.strip()}", file=sys.stderr)
        return COMMIT_FAILED
    for attempt in range(max_retries + 1):
        rc, _out, err = git(["fetch", "origin", branch])
        if rc != 0:
            print(f"  ⚠️ git fetch 失敗：{err.strip()}", file=sys.stderr)
            return COMMIT_FAILED
        rc, _out, err = git(["rebase", f"origin/{branch}"])
        if rc != 0:
            print(f"  ⚠️ git rebase 失敗，abort 復原：{err.strip()}", file=sys.stderr)
            git(["rebase", "--abort"])
            return COMMIT_FAILED
        prc, _po, perr = git(["push", "origin", f"HEAD:{branch}"])
        if prc == 0:
            return COMMIT_OK
        if not _is_non_fast_forward(perr):
            print(f"  ⚠️ git push 失敗（非 non-fast-forward，不重試）：{perr.strip()}", file=sys.stderr)
            return COMMIT_FAILED
        if attempt < max_retries:
            sleep(1.0 + random.uniform(0.0, 0.5))
    print("  ⚠️ git push 重試耗盡仍為 non-fast-forward。", file=sys.stderr)
    return COMMIT_FAILED


# ============================================================
# 業務流程：分類變更 / 診斷 diff / 產出 issue plan
# ============================================================
def classify_changes(
    ids: list[str], details: dict[str, dict], ts: dict
) -> tuple[list[str], list[str], list[str], dict[str, dict]]:
    """回傳 (時間戳變動需下載的 ids, 已下架 ids, 本輪新下架 ids, 每 id 的 meta 更新)。"""
    items = ts.get("items", {})
    changed: list[str] = []
    removed: list[str] = []
    newly_removed: list[str] = []
    meta: dict[str, dict] = {}
    for wid in ids:
        prev = items.get(wid, {})
        entry = {
            "last_attempt": now_iso(),
            "last_success": prev.get("last_success"),
            "time_updated": prev.get("time_updated"),
            "removed": prev.get("removed", False),
            "removed_at": prev.get("removed_at"),
        }
        detail = details.get(wid)
        if detail is None:
            meta[wid] = entry  # 查無回應：僅記 last_attempt
            continue
        result = int(detail.get("result", 0))
        entry["last_result"] = result  # 記錄本輪 API result 供診斷
        if result == RESULT_NOT_FOUND:
            if not prev.get("removed"):
                newly_removed.append(wid)  # 首次偵測到下架 → 開 issue 確認
            entry["removed"] = True
            if not entry["removed_at"]:  # 首次偵測（或舊 state 無此欄）補記時間
                entry["removed_at"] = now_iso()
            meta[wid] = entry
            removed.append(wid)
            continue
        if result != RESULT_OK:
            print(f"  ⚠️ 非預期 API result={result}（id={wid}），本輪略過", file=sys.stderr)
            meta[wid] = entry
            continue
        new_tu = int(detail.get("time_updated", 0))
        entry["removed"] = False
        entry["removed_at"] = None  # 重新上架 → 清除下架標記，自動恢復追蹤
        if prev.get("time_updated") != new_tu:
            changed.append(wid)
        entry["_new_time_updated"] = new_tu  # 成功處理後才寫入 time_updated
        meta[wid] = entry
    return changed, removed, newly_removed, meta


def build_removed_plans(newly_removed: list[str], watchlist: dict) -> list[dict]:
    """為本輪新偵測到的下架項目組『已下架』issue plan（content_hash 固定 → 冪等不重複開）。"""
    items = watchlist.get("items", {})
    plans: list[dict] = []
    for wid in newly_removed:
        mod_ids = items.get(wid, {}).get("mod_ids", [])
        label = _neutralize_markers(mod_ids[0] if mod_ids else wid)
        content_hash = hashlib.sha256(f"removed|{wid}".encode("utf-8")).hexdigest()
        marker = make_marker(ISSUE_TYPE_REMOVED, wid, content_hash)
        body = "\n".join([
            marker,
            f"## 已下架：{label}（Workshop {wid}）",
            "",
            "追蹤器於每日檢查發現此 Workshop 項目已無法存取（Steam API result=9），",
            "可能為作者隱藏／移除，或遭 Steam 下架。",
            "",
            "**處置確認**：",
            "- 本包對應翻譯**預設保留**（既有訂閱者與側載玩家仍受益，多餘翻譯鍵無副作用）。",
            "- 若日後重新上架，追蹤器會自動清除下架標記並恢復更新追蹤，屆時關閉本 issue 即可。",
            "- 若確認永久移除且要清理翻譯：自 `sources/mods/` 移除該目錄並重跑 split→build→manifest 管線。",
            "",
            "（`SUPPORTED_MODS.md` 的「已下架」清單由 manifest 依 tracker state 自動維護。）",
        ])
        plans.append({
            "type": ISSUE_TYPE_REMOVED,
            "workshop_id": wid,
            "content_hash": content_hash,
            "title": f"[已下架] {label} Workshop 項目已無法存取 ({wid})",
            "body": body,
            "comment": "追蹤器再次確認此項目仍不可存取。",
        })
    return plans


def build_layer_a_plan(
    workshop_id: str,
    mod_ids: list[str],
    new_records: list[tuple[str, str, str, str]],
    corpus_state: dict,
    attribution_keys: set[str],
) -> tuple[dict | None, dict]:
    """layer-A：全語料 diff → 「可能過時」issue plan（首跑無基準則靜默建 baseline）。回傳 (plan|None, 新 mod 狀態)。"""
    mods = corpus_state.get("mods", {})
    is_first_run = workshop_id not in mods  # 以 key 是否存在判首跑，勿用空 old_map（空 baseline 亦有效）
    old_mod = mods.get(workshop_id, {})
    old_map = old_mod.get("records", {})
    new_map = records_to_map(new_records)
    new_hash = corpus_hash(new_records)
    new_state = {
        "corpus_hash": new_hash,
        "extractor_schema": EXTRACTOR_SCHEMA,
        "records": new_map,
        "updated_at": now_iso(),
    }
    # 首跑（此 workshop_id 從未建 baseline）→ 靜默建 baseline、零 issue（避免 500+ 洪水）
    if is_first_run:
        return None, new_state
    # 抽取器 schema 演進 → 新舊語料不可比，靜默重建 baseline（避免規則變更引發假 issue 洪水）
    if old_mod.get("extractor_schema") != EXTRACTOR_SCHEMA:
        return None, new_state
    # 純時間戳變動但語料一致 → 不開
    if old_mod.get("corpus_hash") == new_hash:
        return None, new_state
    diff = diff_corpus(old_map, new_records)
    if not (diff["added"] or diff["removed"] or diff["modified"]):
        return None, new_state
    plan = _format_stale_plan(workshop_id, mod_ids, diff, new_hash, attribution_keys)
    return plan, new_state


def _format_stale_plan(
    workshop_id: str,
    mod_ids: list[str],
    diff: dict[str, list[str]],
    content_hash: str,
    attribution_keys: set[str],
) -> dict:
    """組『可能過時』issue plan（含新增鍵『As1 是否已翻譯』標註）。"""
    label = _neutralize_markers(mod_ids[0] if mod_ids else workshop_id)
    title = f"[可能過時] {label} 上游文本變更 ({workshop_id})"
    marker = make_marker(ISSUE_TYPE_STALE, workshop_id, content_hash)

    def annotate(rid: str) -> str:
        if attribution_keys:
            translated = "已翻譯" if rid_file_key(rid) in attribution_keys else "未翻譯"
        else:
            translated = "未知"
        return f"  - `{_neutralize_markers(rid)}`（As1：{translated}）"

    lines = [
        marker,
        f"## 可能過時：{label}（Workshop {workshop_id}）",
        "",
        f"上游原始 MOD 全語料相對基準有變更（extractor_schema={EXTRACTOR_SCHEMA}）。",
        "",
        f"- 新增鍵：{len(diff['added'])}",
        f"- 刪除鍵：{len(diff['removed'])}",
        f"- 修改鍵：{len(diff['modified'])}",
    ]
    for cat, header in (("added", "新增"), ("modified", "修改"), ("removed", "刪除")):
        rows = diff[cat]
        if rows:
            lines.append("")
            lines.append(f"### {header}（{len(rows)}；最多列 30）")
            lines.extend(annotate(rid) for rid in rows[:30])
    body = "\n".join(lines)
    comment = (
        f"追蹤器偵測到新一輪語料變更（新 hash `{content_hash[:12]}`）：\n"
        f"新增 {len(diff['added'])}／修改 {len(diff['modified'])}／刪除 {len(diff['removed'])}。\n"
        f"詳見更新後的 issue 內文摘要。"
    )
    return {
        "type": ISSUE_TYPE_STALE,
        "workshop_id": workshop_id,
        "content_hash": content_hash,
        "title": title,
        "body": body,
        "comment": comment,
    }


def build_layer_b_plan(
    new_as1_records: list[tuple[str, str, str, str]],
    repo_records: list[tuple[str, str, str, str]],
) -> dict | None:
    """layer-B：As1 新 CN 樹 vs repo sources → 有 diff 開『待同步』plan。"""
    diff = diff_layer_b(new_as1_records, repo_records)
    if not diff["has_diff"]:
        return None
    payload = json.dumps(
        {"added": diff["added"], "removed": diff["removed"], "modified": diff["modified"]},
        ensure_ascii=False, sort_keys=True,
    )
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    marker = make_marker(ISSUE_TYPE_SYNC, AS1_WORKSHOP_ID, content_hash)
    # 版本樹取自 snapshot.json，勿寫死：Steam 直接覆蓋版本資料夾（2026-08-05 的
    # 42.19→42.20 前例），寫死的版本號在每次重釘快照後就變成錯的。
    as1_tree = load_json(SNAPSHOT_JSON)["as1"]["source_tree"]
    lines = [
        marker,
        f"## 待同步：As1 包更新（Workshop {AS1_WORKSHOP_ID}）",
        "",
        f"As1「[B42]統一模組漢化」新 {as1_tree} CN 樹與本 repo `sources/` 現況存在差異，需重跑拆分/build 管線同步。",
        "",
        f"- 新增：{len(diff['added'])}",
        f"- 刪除：{len(diff['removed'])}",
        f"- 修改：{len(diff['modified'])}",
    ]
    for cat, header in (("added", "新增"), ("modified", "修改"), ("removed", "刪除")):
        rows = diff[cat]
        if rows:
            lines.append("")
            lines.append(f"### {header}（{len(rows)}；最多列 30）")
            lines.extend(f"  - `{_neutralize_markers(r)}`" for r in rows[:30])
    body = "\n".join(lines)
    comment = (
        f"追蹤器偵測到 As1 包新一輪差異（新 hash `{content_hash[:12]}`）：\n"
        f"新增 {len(diff['added'])}／修改 {len(diff['modified'])}／刪除 {len(diff['removed'])}。"
    )
    return {
        "type": ISSUE_TYPE_SYNC,
        "workshop_id": AS1_WORKSHOP_ID,
        "content_hash": content_hash,
        "title": f"[待同步] As1 包更新 ({AS1_WORKSHOP_ID})",
        "body": body,
        "comment": comment,
    }


# ============================================================
# 命令：gen-watchlist（支持清單變動後重跑）
# ============================================================
def cmd_gen_watchlist() -> int:
    print("=" * 60)
    print("gen-watchlist：由 sources/mods/ 支持清單生成 tracker-state/watchlist.json")
    print("=" * 60)
    metas = sorted((SOURCES / "mods").glob("*/metadata.json"))
    if not metas:
        print(f"❌ {SOURCES / 'mods'} 下找不到任何 metadata.json（請先跑 split_sources.py）", file=sys.stderr)
        return 1
    items: dict[str, dict] = {}
    for meta_path in metas:
        meta = load_json(meta_path)
        wid = str(meta.get("workshop_id") or meta_path.parent.name)
        items[wid] = {"mod_ids": list(meta.get("mod_ids", [])), "role": "mod"}
    # 固定納入 As1 包（非 sources/mods 成員）
    items[AS1_WORKSHOP_ID] = {"mod_ids": [AS1_MOD_ID], "role": "as1"}
    watchlist = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source": "sources/mods/*/metadata.json + As1 fixed",
        "count": len(items),
        "items": items,
    }
    write_json(WATCHLIST_JSON, watchlist)
    print(f"  sources/mods {len(metas)} 個 + As1 = {len(items)} 個 workshop_id")
    print(f"✅ 已寫出 {WATCHLIST_JSON.relative_to(PROJECT_ROOT)}")
    return 0


# ============================================================
# 命令：run（預設全流程；--dry-run 保證零 issue 零 commit）
# ============================================================
def cmd_run(args) -> int:
    print("=" * 60)
    print(f"run：check → diff → issue → commit（dry_run={args.dry_run}）")
    print("=" * 60)
    watchlist = load_watchlist()
    ids = list(watchlist.get("items", {}).keys())
    if args.limit:
        ids = ids[: args.limit]
    ts = load_timestamps()

    api_key = os.environ.get("STEAM_API_KEY") or None
    print(f"  查詢 {len(ids)} 個 workshop_id（batch={args.batch}，key={'有' if api_key else '無'}）...")
    details = fetch_details(ids, batch=args.batch, api_key=api_key)
    coverage_guard(ids, details)  # 全空/缺項 >50% → 非零退出
    changed, removed, newly_removed, meta = classify_changes(ids, details, ts)
    print(f"  時間戳變動：{len(changed)}；已下架：{len(removed)}（本輪新下架 {len(newly_removed)}）")

    if args.dry_run:
        print("\n[dry-run] 不下載、不開 issue、不 commit。計畫動作：")
        for wid in changed[:20]:
            print(f"  - 會下載並 diff：{wid}")
        if len(changed) > 20:
            print(f"  ... 另有 {len(changed) - 20} 個")
        for wid in removed[:20]:
            print(f"  - 標記 removed（不下載）：{wid}")
        for wid in newly_removed:
            print(f"  - 新下架，將開 [已下架] issue：{wid}")
        print("\n完成：dry-run 零 issue 零 commit。")
        return 0

    ci_baseline_guard(args.bootstrap)  # CI 缺 baseline fail-fast（非 --bootstrap）
    if args.steamcmd is None:
        print("❌ 非 dry-run 需 --steamcmd 指定 steamcmd 路徑。", file=sys.stderr)
        return 1
    steamcmd = Path(args.steamcmd)
    install_dir = resolve_install_dir(args.install_dir)  # 限 tracker scratch root，外部路徑拒絕
    corpus_state = load_corpus_hashes()
    attribution = load_attribution_keys()

    plans, ok_ids, corpus_updates, failed_ids, en_texts = _diff_changed(
        changed, watchlist, steamcmd, install_dir, corpus_state, attribution
    )
    plans.extend(build_removed_plans(newly_removed, watchlist))
    if changed and not ok_ids:
        print(f"❌ {len(changed)} 個變動全部處理失敗，中止（state 不推進、下輪自癒）。", file=sys.stderr)
        return 1
    if failed_ids:
        print(f"  ⚠️ 部分失敗 {len(failed_ids)}/{len(changed)}：{', '.join(failed_ids[:20])}", file=sys.stderr)
    gh = GhClient()
    if plans:
        gh.ensure_label()
    index = index_issues(gh.list_tracker_issues())
    for plan in plans:
        action = apply_issue_plan(plan, index, gh, dry_run=False)
        print(f"  issue {plan['type']}/{plan['workshop_id']} → {action}")

    # 提交成功子集 state（僅成功處理者推進 last_success/time_updated）
    _persist_state(ts, meta, ok_ids, removed, corpus_state, corpus_updates, en_texts)
    status = commit_state_with_retry(
        [str(TIMESTAMPS_JSON.relative_to(PROJECT_ROOT)),
         str(EN_CORPUS_HASHES_JSON.relative_to(PROJECT_ROOT)),
         str(EN_TEXT_DIR.relative_to(PROJECT_ROOT))],
        f"chore(tracker): 更新追蹤器狀態 {now_iso()}",
    )
    if status == COMMIT_FAILED:
        print("❌ state commit/push 失敗（下輪自癒）。", file=sys.stderr)
        return 1
    print(f"\n完成：issue {len(plans)} 筆、state {'已提交' if status == COMMIT_OK else '無變更'}。")
    return 0


def _diff_changed(changed, watchlist, steamcmd, install_dir, corpus_state, attribution):
    """對變動 ids 下載+裁剪+抽取+diff，回 (plans, 成功 ids, corpus 更新, 失敗 ids, EN 全文)。
    下載失敗/偽成功、或抽取語料為空的 ID 皆不進 ok_ids（不推進 time_updated、不建空 baseline）。
    EN 全文（{wid: {rid: value}}）供 _persist_state 落 sources/en/——tracker 為算 hash 本已
    下載全文，順手入庫當大同步翻譯對照，免得在最糟時機重新取得 EN（steamcmd 有全滅日前科）。"""
    plans: list[dict] = []
    ok_ids: list[str] = []
    corpus_updates: dict[str, dict] = {}
    en_texts: dict[str, dict[str, str]] = {}
    failed_ids: list[str] = []
    items = watchlist.get("items", {})
    for wid in changed:
        item_dir = steamcmd_download(wid, steamcmd, install_dir)
        if item_dir is None:
            print(f"  ⚠️ 下載失敗/已下架/偽成功，跳過（不推進狀態）：{wid}", file=sys.stderr)
            failed_ids.append(wid)
            continue
        trim_download(item_dir)
        try:
            if wid == AS1_WORKSHOP_ID:
                new_records = _iter_translate_records(item_dir, "CN")
                if not new_records:
                    print(f"  ⚠️ As1 CN 語料解析為空，跳過（不推進狀態）：{wid}", file=sys.stderr)
                    failed_ids.append(wid)
                    continue
                plan = build_layer_b_plan(new_records, read_repo_sources_cn())
                if plan:
                    plans.append(plan)
            else:
                new_records = extract_corpus(item_dir, "EN")
                mod_ids = items.get(wid, {}).get("mod_ids", [])
                plan, new_state = build_layer_a_plan(wid, mod_ids, new_records, corpus_state, attribution)
                if not new_records:
                    # 下載成功但無可抽取文本（如僅 B41 .txt 格式的模組）＝合法空語料：
                    # 建帶標記的空 baseline 推進時間戳，止住每日重抓；未來若新增 JSON 文本，
                    # 空→非空 diff 照樣觸發「可能過時」issue（見自測情境 7）。
                    new_state["empty_corpus"] = True
                    print(f"  ℹ️ 語料為空，建空 baseline（疑似僅 B41 格式文本）：{wid}")
                corpus_updates[wid] = new_state
                # 空語料也要傳遞 {}：_persist_state 據此清掉殘留的 sources/en/<wid>.json，
                # 避免 hash state 已空而全文檔殘留（兩個真相來源脫鉤）
                # 只鏡像帶真英文的 kind（見 TEXT_BEARING_KINDS）：其餘 script_* 的 value
                # 就是區塊 id 本身，鏡像它等於把檔案灌大一倍卻零翻譯價值。
                en_texts[wid] = {
                    f"{kind}|{relpath}|{key}": value
                    for kind, relpath, key, value in sorted(new_records)
                    if kind in TEXT_BEARING_KINDS
                }
                if plan:
                    plans.append(plan)
        except ValueError as exc:  # 單一模組語料異常不炸全場（成功子集照常推進，失敗者下輪重試）
            print(f"  ⚠️ 語料處理失敗，跳過（不推進狀態）：{wid}：{exc}", file=sys.stderr)
            failed_ids.append(wid)
            continue
        ok_ids.append(wid)
    return plans, ok_ids, corpus_updates, failed_ids, en_texts


def _persist_state(ts, meta, ok_ids, removed, corpus_state, corpus_updates, en_texts=None):
    """把成功子集寫回狀態物件並落盤（含 sources/en/ EN 全文）。"""
    items = ts.setdefault("items", {})
    ok_set = set(ok_ids) | set(removed)
    for wid, entry in meta.items():
        new_tu = entry.pop("_new_time_updated", None)
        if wid in ok_set:
            entry["last_success"] = now_iso()
            if new_tu is not None:
                entry["time_updated"] = new_tu
        items[wid] = entry
    ts["schema_version"] = SCHEMA_VERSION
    write_json(TIMESTAMPS_JSON, ts)
    for wid, state in corpus_updates.items():
        corpus_state.setdefault("mods", {})[wid] = state
    corpus_state["schema_version"] = SCHEMA_VERSION
    corpus_state["extractor_schema"] = EXTRACTOR_SCHEMA
    write_json(EN_CORPUS_HASHES_JSON, corpus_state)
    # EN 全文落受版控正式目錄（非 _dl 暫存）；只寫成功處理的 wid，逐 mod 一檔。
    # 語料變空 → 刪殘檔，與 hash state 保持同步（缺其一即兩個真相來源脫鉤）。
    for wid, texts in (en_texts or {}).items():
        if texts:
            write_json(EN_TEXT_DIR / f"{wid}.json", texts)
        else:
            (EN_TEXT_DIR / f"{wid}.json").unlink(missing_ok=True)


# ============================================================
# 命令：check / diff / issue（workflow 三 job 分工，經 artifact 傳遞）
# ============================================================
def cmd_check(args) -> int:
    """check job：只查 API 時間戳，寫 changed artifact（無 GitHub / 下載）。"""
    ci_baseline_guard(args.bootstrap)  # CI 缺 baseline fail-fast（非 --bootstrap）
    watchlist = load_watchlist()
    ids = list(watchlist.get("items", {}).keys())
    if args.limit:
        ids = ids[: args.limit]
    ts = load_timestamps()
    api_key = os.environ.get("STEAM_API_KEY") or None
    details = fetch_details(ids, batch=args.batch, api_key=api_key)
    coverage_guard(ids, details)  # 印「查得 X/Y」；全空/缺項 >50% → 非零退出
    changed, removed, newly_removed, meta = classify_changes(ids, details, ts)
    out = {
        "generated_at": now_iso(),
        "changed": changed,
        "removed": removed,
        "newly_removed": newly_removed,
        "meta": meta,
    }
    out_path = Path(args.out) if args.out else TRACKER_STATE / "_changed.json"
    write_json(out_path, out)
    print(f"✅ check：變動 {len(changed)}、下架 {len(removed)}（新 {len(newly_removed)}）→ {out_path}")
    return 0


def cmd_diff(args) -> int:
    """diff job：讀 changed，下載+裁剪+抽取+diff，寫 diffs artifact（無 GitHub 寫權限）。"""
    if not args.inp:
        print("❌ diff 需 --in 指定 changed artifact。", file=sys.stderr)
        return 1
    if args.steamcmd is None:
        print("❌ diff 需 --steamcmd。", file=sys.stderr)
        return 1
    ci_baseline_guard(args.bootstrap)  # CI 缺 baseline fail-fast（非 --bootstrap）
    changed_data = load_json(Path(args.inp))
    watchlist = load_watchlist()
    corpus_state = load_corpus_hashes()
    attribution = load_attribution_keys()
    install_dir = resolve_install_dir(args.install_dir)  # 限 tracker scratch root，外部路徑拒絕
    changed_ids = changed_data.get("changed", [])
    plans, ok_ids, corpus_updates, failed_ids, en_texts = _diff_changed(
        changed_ids, watchlist, Path(args.steamcmd),
        install_dir, corpus_state, attribution,
    )
    plans.extend(build_removed_plans(changed_data.get("newly_removed", []), watchlist))
    if changed_ids and not ok_ids:
        print(f"❌ {len(changed_ids)} 個變動全部處理失敗，中止（state 不推進、下輪自癒）。", file=sys.stderr)
        return 1
    if failed_ids:
        print(f"  ⚠️ 部分失敗 {len(failed_ids)}/{len(changed_ids)}：{', '.join(failed_ids[:20])}", file=sys.stderr)
    out = {
        "generated_at": now_iso(),
        "plans": plans,
        "ok_ids": ok_ids,
        "removed": changed_data.get("removed", []),
        "meta": changed_data.get("meta", {}),
        "corpus_updates": corpus_updates,
        "en_texts": en_texts,
        "failed_ids": failed_ids,
    }
    out_path = Path(args.out) if args.out else TRACKER_STATE / "_diffs.json"
    write_json(out_path, out)
    print(f"✅ diff：issue plan {len(plans)}、成功 {len(ok_ids)}、失敗 {len(failed_ids)} → {out_path}")
    return 0


def cmd_issue(args) -> int:
    """issue job：讀 diffs，冪等開/更 issue，commit 成功子集 state（issues:write + contents:write）。"""
    if not args.inp:
        print("❌ issue 需 --in 指定 diffs artifact。", file=sys.stderr)
        return 1
    if not args.dry_run:
        ci_baseline_guard(args.bootstrap)  # CI 缺 baseline fail-fast（非 --bootstrap）
    diffs = load_json(Path(args.inp))
    plans = diffs.get("plans", [])
    gh = GhClient()
    if plans and not args.dry_run:
        gh.ensure_label()
    index = index_issues(gh.list_tracker_issues())
    for plan in plans:
        action = apply_issue_plan(plan, index, gh, dry_run=args.dry_run)
        print(f"  issue {plan['type']}/{plan['workshop_id']} → {action}")
    if args.dry_run:
        print("完成：dry-run 零 issue 零 commit。")
        return 0
    ts = load_timestamps()
    corpus_state = load_corpus_hashes()
    _persist_state(
        ts, diffs.get("meta", {}), diffs.get("ok_ids", []), diffs.get("removed", []),
        corpus_state, diffs.get("corpus_updates", {}), diffs.get("en_texts", {}),
    )
    status = commit_state_with_retry(
        [str(TIMESTAMPS_JSON.relative_to(PROJECT_ROOT)),
         str(EN_CORPUS_HASHES_JSON.relative_to(PROJECT_ROOT)),
         str(EN_TEXT_DIR.relative_to(PROJECT_ROOT))],
        f"chore(tracker): 更新追蹤器狀態 {now_iso()}",
    )
    if status == COMMIT_FAILED:
        print("❌ state commit/push 失敗（下輪自癒）。", file=sys.stderr)
        return 1
    print(f"完成：issue {len(plans)} 筆、state {'已提交' if status == COMMIT_OK else '無變更'}。")
    return 0


# ============================================================
# 命令：coverage（上游 EN vs 我方已收 的缺口報表）
# ============================================================
# PZ 允許同一檔內 legacy `<Stem>_KEY` 與 B42 bare `KEY` 兩種寫法並存（實測上游 EN 側
# prefixed 56,205 / bare 38,042）。兩側比對前必須正規化到同一形式，否則虛增缺口約 6,300 鍵。
def _key_stem(basename: str) -> str:
    """檔名 → 語意 namespace（`IG_UI_EN.txt` / `IG_UI.json` 皆為 `IG_UI`）。"""
    stem = basename.rsplit(".", 1)[0]
    for suf in ("_EN", "_CN", "_CH"):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
    return stem


def _canon_key(basename: str, key: str) -> str:
    stem = _key_stem(basename)
    return key[len(stem) + 1:] if stem and key.startswith(stem + "_") else key


# PZ 翻譯鍵形：`[A-Za-z0-9_.-]`。`lua_gettext` 記錄的是 getText 第一引數的**原始字面**，
# 兩類不是真鍵，須於使用端濾掉（擷取器刻意只記錄所見、不做解讀）：
#   1. 非鍵形——mod 拿 getText 當 no-op 包英文/符號用（'I drop items!'、' / 100 %'、'<'）
#   2. 以 `_` 結尾——動態組鍵前綴 getText("IGUI_AnimalType_" .. t)，前綴本身不是鍵
# 實測 8,950 個去重鍵中此類共 306 個（3.4%）。
_TRANSLATION_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _is_real_key(key: str) -> bool:
    return bool(_TRANSLATION_KEY_RE.match(key)) and not key.endswith("_")


def _load_shipped_keys() -> tuple[set[tuple[str, str]], set[str]]:
    """我方實際出貨的鍵，回傳 (身分集, runtime 完整鍵集)。

    * **身分集** `(stem, canon)` — 給 `translate_en` 缺口用。**namespace 必須保留**：
      只留 canon 會讓 `Tooltip_OpenJacket` 與 `ContextMenu_OpenJacket` 塌成同一身分，
      使某 mod 的 Tooltip 真缺口被另一 mod 的 ContextMenu 鍵遮蔽（實測遮掉 405 個）。
      同時容納 legacy `<Stem>_KEY` 與 B42 bare `KEY` 兩種寫法。
    * **runtime 完整鍵集** — 給 `lua_gettext` 缺口用。Lua 寫的是程式碼裡的完整鍵
      （`getText("ItemName_Base.X")`），故同時放入 `canon` 與 `<stem>_<canon>` 兩種別名。
    """
    ident: set[tuple[str, str]] = set()
    full: set[str] = set()

    def take(basename: str, ks) -> None:
        stem = _key_stem(basename)
        for k in ks:
            c = _canon_key(basename, k)
            ident.add((stem, c))
            full.add(k)
            full.add(c)
            if stem:
                full.add(f"{stem}_{c}")

    mods_dir = SOURCES / "mods"
    if mods_dir.is_dir():
        for wid_dir in mods_dir.iterdir():
            cn = wid_dir / "CN"
            if cn.is_dir():
                for jf in cn.glob("*.json"):
                    take(jf.name, load_json(jf))
    uns = SOURCES / "_unsorted" / "CN"
    if uns.is_dir():
        for jf in uns.glob("*.json"):
            take(jf.name, load_json(jf))
    own = SOURCES / "own_translations.json"
    if own.is_file():
        for fname, entries in load_json(own).get("entries", {}).items():
            take(fname, entries)
    return ident, full


def cmd_coverage(args) -> int:
    """報表：上游 EN 鍵有多少我方沒收，並以「Lua 確證可見」優先排序。

    三個口徑，可信度由高到低：
      * ``lua_gettext`` 缺口 — mod 的 Lua **真的去取了這個鍵**＝確證玩家看得到，最該補。
      * ``translate_en`` 缺口 — 上游 EN 檔裡有，但未必被用到（含廢棄鍵）。
      * ``lua_literal`` — 寫死在 Lua、根本沒有翻譯鍵，JSON 補再多也蓋不掉，
        只能走 sources/lua/ 覆寫。
    vanilla 鍵一律扣除（收錄鐵律：不得覆寫本體）。
    """
    corpus_state = load_corpus_hashes()
    mods = corpus_state.get("mods", {})
    shipped_ident, shipped_full = _load_shipped_keys()
    vraw = set(load_json(SOURCES / "vanilla_keys.json").get("keys", []))
    vanilla = vraw | {k.split("_", 1)[1] for k in vraw if "_" in k}

    rows = []
    tot = {"en": 0, "en_gap": 0, "lua": 0, "lua_gap": 0, "lit": 0, "lua_undef": 0}
    for wid in sorted(mods):
        en_ids: set[tuple[str, str]] = set()
        en_full: set[str] = set()
        lua_ids: set[str] = set()
        lits: set[str] = set()
        # 只認引擎真的會載入的分支——舊版本夾／mod 根 media/ 的鍵補了也是死資料
        eff = resolve_effective_branches(mods[wid].get("records", {}))
        for rid in mods[wid].get("records", {}):
            if not is_effective(rid, eff):
                continue
            kind, _, rest = rid.partition("|")
            relpath, _, key = rest.partition("|")
            if kind == "translate_en":
                base = relpath.rsplit("/", 1)[-1]
                stem, canon = _key_stem(base), _canon_key(base, key)
                en_ids.add((stem, canon))  # 保留 namespace，否則跨檔同名鍵互相遮蔽
                en_full.add(key)           # runtime 完整鍵，供 lua_gettext 判上游有無定義
                en_full.add(canon)
                if stem:
                    en_full.add(f"{stem}_{canon}")
            elif kind == "lua_gettext":
                if _is_real_key(key):  # 濾掉非鍵形字面與動態組鍵前綴（見 _is_real_key）
                    lua_ids.add(key)
            elif kind == "lua_literal":
                lits.add(key)
        en_gap = {x for x in en_ids - shipped_ident if x[1] not in vanilla}
        lua_all_gap = (lua_ids - shipped_full) - vanilla
        # Lua 引用但上游自己也沒定義＝上游 bug（遊戲顯示鍵名），非我方可補的缺口
        lua_undef = lua_all_gap - en_full
        lua_gap = lua_all_gap - lua_undef
        # **totals 先累加再決定是否列表**：放在 continue 之後會把「完全無缺口」的 mod
        # 排除在分母外，覆蓋率分母因而嚴重低報（實測 EN 76,063 vs 實際 89,764）。
        tot["en"] += len(en_ids); tot["en_gap"] += len(en_gap)
        tot["lua"] += len(lua_ids); tot["lua_gap"] += len(lua_gap)
        tot["lit"] += len(lits); tot["lua_undef"] += len(lua_undef)
        if not (en_gap or lua_gap or lits):
            continue
        rows.append((wid, len(en_ids), len(en_gap), len(lua_ids), len(lua_gap), len(lits),
                     sorted(lua_gap)[:5], len(lua_undef)))

    print(f"基準涵蓋 {len(mods)} 個 mod（extractor_schema={corpus_state.get('extractor_schema')}）")
    print(f"我方已出貨鍵 {len(shipped_ident)}；vanilla 排除鍵 {len(vanilla)}")
    print()
    print(f"上游 EN 鍵 {tot['en']}  → 缺口 {tot['en_gap']}")
    print(f"Lua 引用鍵 {tot['lua']}  → **可補的確證可見缺口 {tot['lua_gap']}**（最高優先）")
    print(f"  （另有 {tot['lua_undef']} 個鍵上游自己也沒定義＝上游 bug，遊戲顯示鍵名，非我方缺口）")
    print(f"Lua 寫死英文 {tot['lit']}（無翻譯鍵，只能走 sources/lua/ 覆寫）")
    print()
    top = args.limit or 30
    print(f"=== 依「確證可見缺口」排序 Top {top} ===")
    print(f"{'workshop_id':>12} {'EN缺':>6} {'可補':>5} {'上游bug':>7} {'寫死':>5}  範例")
    for r in sorted(rows, key=lambda r: (-r[4], -r[5], -r[2]))[:top]:
        wid, _en, en_gap, _lua, lua_gap, lit, samp, undef = r
        print(f"{wid:>12} {en_gap:>6} {lua_gap:>5} {undef:>7} {lit:>5}  {[x[:26] for x in samp[:3]]}")
    if args.out:
        write_json(Path(args.out), {
            "totals": tot,
            "mods": {r[0]: {"en": r[1], "en_gap": r[2], "lua": r[3], "lua_gap": r[4],
                            "lua_literal": r[5], "lua_undefined_upstream": r[7]} for r in rows},
        })
        print(f"\n明細 → {args.out}")
    return 0


# ============================================================
# 命令：backfill-en（一次性全量 EN 落地）
# ============================================================
def cmd_backfill_en(args) -> int:
    """把 watchlist 全部 mod 的上游 EN 全文補齊到 sources/en/，並重建 hash 基準。

    存在理由：`sources/en/` 原本只在「tracker 偵測到該 mod 有更新」時順手落地，
    是漸進累積（481 個 mod 只有 75 個有檔）。要達到「所有支援 MOD 的 EN 都可在 git
    追蹤比對」得主動補齊一次，之後才由排程自然維護。

    可續跑：已有現行 extractor schema 基準 **且** sources/en 檔存在者跳過。
    schema 演進（如 5→6 新增 Lua 抽取）會使既有檔全部過時，屆時本指令即重抽工具。
    逐 mod 落盤、失敗不中斷全場，末尾列出失敗清單供重跑。
    """
    if args.steamcmd is None:
        print("❌ backfill-en 需 --steamcmd 指定 steamcmd 路徑。", file=sys.stderr)
        return 1
    steamcmd = Path(args.steamcmd)
    install_dir = resolve_install_dir(args.install_dir)  # 限 tracker scratch root
    watchlist = load_watchlist()
    corpus_state = load_corpus_hashes()
    attribution = load_attribution_keys()
    items = watchlist.get("items", {})

    # As1 包本身走 layer-B（它帶的是 CN 不是 EN），不在 EN backfill 範圍。
    wids = [w for w in items if w != AS1_WORKSHOP_ID]
    # 已自 Workshop 下架者（timestamps 的 removed 旗標，API result=9）永遠抓不到：
    # 不跳過的話每輪都要對它們各重試 3 次＋逾時，且退出碼永遠非零。
    ts_items = load_timestamps().get("items", {})
    gone = [w for w in wids if ts_items.get(w, {}).get("removed")]
    if gone and not args.only:
        print(f"跳過已下架 {len(gone)} 個（Workshop 已移除，抓不到）：{','.join(gone)}")
        wids = [w for w in wids if w not in gone]
    if args.only:
        want = {w.strip() for w in args.only.split(",") if w.strip()}
        wids = [w for w in wids if w in want]
    if args.limit:
        wids = wids[: args.limit]

    def is_done(wid: str) -> bool:
        st = corpus_state.get("mods", {}).get(wid)
        if not st or st.get("extractor_schema") != EXTRACTOR_SCHEMA:
            return False
        if (EN_TEXT_DIR / f"{wid}.json").is_file():
            return True
        # 合法無檔的兩種情形，缺一即會每輪重抓（實測曾有 7 個 mod 卡在第二種）：
        #   1. 語料整個為空（empty_corpus）
        #   2. 語料非空但**全是不進鏡像的 kind**（純 script_item/craftRecipe 的 mod）
        recs = st.get("records") or {}
        return bool(st.get("empty_corpus")) or (
            bool(recs) and not any(r.split("|", 1)[0] in TEXT_BEARING_KINDS for r in recs)
        )

    todo = [w for w in wids if args.force or not is_done(w)]
    print(f"backfill-en：watchlist {len(wids)} 個 mod，待處理 {len(todo)}（已完成 {len(wids) - len(todo)}）")
    if not todo:
        return 0
    EN_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    done = 0
    for i, wid in enumerate(todo, 1):
        mod_ids = items.get(wid, {}).get("mod_ids", [])
        print(f"[{i}/{len(todo)}] {wid} …", flush=True)
        item_dir = None
        try:
            # 下載也放進 try：steamcmd_download 的 subprocess.run(timeout=1800) 會拋
            # TimeoutExpired，留在 try 外時單一 mod 逾時就中止整批，違反「失敗不中斷」。
            item_dir = steamcmd_download(wid, steamcmd, install_dir)
            if item_dir is None:
                print(f"  ⚠️ 下載失敗，跳過（可重跑）：{wid}", file=sys.stderr)
                failed.append(wid)
                continue
            records = extract_corpus(item_dir)
            # schema 不符 → build_layer_a_plan 靜默重建基準（回傳 plan=None），正是 backfill 要的。
            # 但 --force 對 schema 已相符的 mod 會拿到**真 plan**＝上游有變更、本該開
            # 「可能過時」issue；backfill 不開 issue，靜默丟棄等於吃掉訊號，故明示警告。
            plan, new_state = build_layer_a_plan(wid, mod_ids, records, corpus_state, attribution)
            if plan is not None:
                print(
                    f"  ⚠️ {wid} 偵測到上游語料變更（本該開「可能過時」issue）；"
                    "backfill 只重建基準，該訊號已被吸收——需要追蹤請改跑 `tracker.py run`。",
                    file=sys.stderr,
                )
            if not records:
                new_state["empty_corpus"] = True
            corpus_state.setdefault("mods", {})[wid] = new_state
            texts = {
                f"{kind}|{relpath}|{key}": value
                for kind, relpath, key, value in sorted(records)
                if kind in TEXT_BEARING_KINDS
            }
            if texts:
                write_json(EN_TEXT_DIR / f"{wid}.json", texts)
            else:
                (EN_TEXT_DIR / f"{wid}.json").unlink(missing_ok=True)
            kinds: dict[str, int] = {}
            for r in records:
                kinds[r[0]] = kinds.get(r[0], 0) + 1
            print(f"  ✓ {len(records)} 筆（鏡像 {len(texts)}）{kinds}")
            done += 1
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            # 單一 mod 的語料異常／IO 失敗／steamcmd 逾時一律不炸全場，記入失敗清單可重跑。
            # 只捕 ValueError 太窄：write_json 的 OSError 會漏出去中止整輪。
            print(f"  ⚠️ 處理失敗，跳過：{wid}：{type(exc).__name__}: {exc}", file=sys.stderr)
            failed.append(wid)
        finally:
            # _dl 是暫存：抽完即刪，避免 481 個 mod 的內容堆在磁碟上
            if item_dir is not None and _within_scratch(item_dir):
                shutil.rmtree(item_dir, ignore_errors=True)
        if done % 10 == 0:  # 每 10 個落一次 hash 基準（中斷不丟已完成的工作）
            corpus_state["schema_version"] = SCHEMA_VERSION
            corpus_state["extractor_schema"] = EXTRACTOR_SCHEMA
            write_json(EN_CORPUS_HASHES_JSON, corpus_state)

    corpus_state["schema_version"] = SCHEMA_VERSION
    corpus_state["extractor_schema"] = EXTRACTOR_SCHEMA
    write_json(EN_CORPUS_HASHES_JSON, corpus_state)
    print(f"\n完成 {done}/{len(todo)}；失敗 {len(failed)}")
    if failed:
        print("失敗清單（重跑本指令即續傳）：" + ",".join(failed))
    return 1 if failed else 0


# ============================================================
# 命令：self-test（十二情境 mock 測試，assert-based）
# ============================================================
def cmd_self_test() -> int:
    print("=" * 60)
    print("self-test：十二情境 mock 測試")
    print("=" * 60)

    def rec(kind, rel, key, val):
        return (kind, rel, key, val)

    # 情境 1：首跑無基準 → 靜默 baseline、零 issue
    new_records = [rec("translate_en", "Items_EN.json", "Base.Axe", "Axe")]
    plan, state = build_layer_a_plan("111", ["ModA"], new_records, {"mods": {}}, set())
    assert plan is None, "情境1：首跑應靜默無 issue"
    assert state["records"], "情境1：baseline 應記錄語料"
    print("  ✅ 情境1 首跑靜默 baseline：無 issue、已建 baseline")

    # 情境 2：As1 有 diff → 待同步
    as1_new = [rec("translate_cn", "IG_UI_CN.json", "IGUI_x", "新值")]
    repo_now = [rec("translate_cn", "IG_UI_CN.json", "IGUI_x", "舊值")]
    b_plan = build_layer_b_plan(as1_new, repo_now)
    assert b_plan is not None and b_plan["type"] == ISSUE_TYPE_SYNC, "情境2：應開待同步 issue"
    assert AS1_WORKSHOP_ID in b_plan["body"], "情境2：body 應含 As1 id"
    print("  ✅ 情境2 As1 diff → 待同步 issue")

    # 情境 3：原 mod 全語料 diff（含新增鍵）→ 可能過時
    corpus_state = {"mods": {"222": {
        "corpus_hash": "old", "extractor_schema": EXTRACTOR_SCHEMA,
        "records": records_to_map([rec("translate_en", "Items_EN.json", "Base.Axe", "Axe")]),
    }}}
    new3 = [
        rec("translate_en", "Items_EN.json", "Base.Axe", "Axe"),
        rec("translate_en", "Items_EN.json", "Base.Saw", "Saw"),   # 新增鍵
        rec("script_item", "items.txt", "Base.Hammer", "Base.Hammer"),  # 新增
    ]
    attribution = {"Items_EN.json|Base.Saw"}  # attribution key 形狀為『檔名|鍵』（As1 已翻譯 Base.Saw）
    plan3, _st3 = build_layer_a_plan("222", ["ModB"], new3, corpus_state, attribution)
    assert plan3 is not None and plan3["type"] == ISSUE_TYPE_STALE, "情境3：應開可能過時 issue"
    assert "新增" in plan3["body"], "情境3：body 應含新增分類"
    assert "已翻譯" in plan3["body"], "情境3：新增鍵應標註 As1 已翻譯"
    print("  ✅ 情境3 原 mod 全語料 diff（含新增鍵）→ 可能過時，含 As1 翻譯標註")

    # 情境 4：純時間戳變動、語料一致 → 不開
    same_records = [rec("translate_en", "Items_EN.json", "Base.Axe", "Axe")]
    corpus_state4 = {"mods": {"333": {
        "corpus_hash": corpus_hash(same_records),
        "extractor_schema": EXTRACTOR_SCHEMA,
        "records": records_to_map(same_records),
    }}}
    plan4, _st4 = build_layer_a_plan("333", ["ModC"], same_records, corpus_state4, set())
    assert plan4 is None, "情境4：語料一致不應開 issue"
    print("  ✅ 情境4 純時間戳無語料 diff → 不開 issue")

    # 情境 5：同 (mod,類型) 新 hash → 追加 comment（非新開）；同 hash → skip
    class FakeGh:
        def __init__(self):
            self.issues: dict[int, dict] = {}
            self.comments: list[tuple[int, str]] = []
            self._next = 1

        def create_issue(self, title, body):
            n = self._next
            self._next += 1
            self.issues[n] = {"number": n, "title": title, "body": body}
            return n

        def add_comment(self, number, body):
            self.comments.append((number, body))

        def update_body(self, number, body):
            self.issues[number]["body"] = body

    fake = FakeGh()
    existing_body = make_marker(ISSUE_TYPE_STALE, "222", "OLDHASH") + "\n舊摘要"
    fake.issues[7] = {"number": 7, "title": "[可能過時] ModB", "body": existing_body}
    index = index_issues([fake.issues[7]])
    # 同 hash → skip
    same_plan = {"type": ISSUE_TYPE_STALE, "workshop_id": "222", "content_hash": "OLDHASH",
                 "title": "t", "body": "b", "comment": "c"}
    assert apply_issue_plan(same_plan, index, fake, dry_run=False) == "skip", "情境5a：同 hash 應 skip"
    # 新 hash → comment（非 new）
    new_plan = {"type": ISSUE_TYPE_STALE, "workshop_id": "222", "content_hash": "NEWHASH",
                "title": "t2", "body": make_marker(ISSUE_TYPE_STALE, "222", "NEWHASH") + "\n新摘要",
                "comment": "有新變更"}
    assert apply_issue_plan(new_plan, index, fake, dry_run=False) == "comment", "情境5b：新 hash 應 comment"
    assert fake.comments and fake.comments[0][0] == 7, "情境5：comment 應加到既有 issue #7"
    assert "NEWHASH" in fake.issues[7]["body"], "情境5：body 摘要應更新為新 hash"
    print("  ✅ 情境5 同(mod,類型) 同 hash skip、新 hash 追加 comment 不新開")

    # 情境 6：併發雙跑 → fetch-rebase 重試（第一次 push non-fast-forward，rebase 後成功）
    calls: list[list[str]] = []
    push_attempts = {"n": 0}

    def fake_git(cmd_args):
        calls.append(cmd_args)
        verb = cmd_args[0]
        if verb == "add":  # 比照真 git：pathspec 不存在即 rc=128（防 sources/en 類缺目錄 bug 再漏）
            missing = [
                p for p in cmd_args[1:]
                if not p.startswith("-") and not (PROJECT_ROOT / p).exists()
            ]
            if missing:
                return 128, "", f"fatal: pathspec '{missing[0]}' did not match any files"
            return 0, "", ""
        if verb == "diff":  # diff --cached --quiet：rc=1 表有變更
            return 1, "", ""
        if verb == "push":
            push_attempts["n"] += 1
            if push_attempts["n"] == 1:
                return 1, "", "! [rejected] (non-fast-forward)"  # 他跑先推
            return 0, "", ""
        return 0, "", ""

    status = commit_state_with_retry(
        ["tracker-state/timestamps.json"], "test", branch="main",
        git=fake_git, sleep=lambda _s: None,
    )
    assert status == COMMIT_OK, "情境6：rebase 後應 push 成功"
    assert push_attempts["n"] == 2, "情境6：應在 non-ff 後重試一次 push"
    verbs = [c[0] for c in calls]
    assert verbs.count("fetch") >= 2 and verbs.count("rebase") >= 2, "情境6：每次重試前應 fetch+rebase"
    print("  ✅ 情境6 併發 non-fast-forward → fetch-rebase 重試後成功、無重複 commit")

    # 情境 6b：生產 commit pathspec 必須存在於工作樹（sources/en 需有 .gitkeep 佔位，
    # 否則零 EN 落地日的 git add 會 pathspec 失敗、state 永遠 commit 不出去）
    prod_paths = [
        str(TIMESTAMPS_JSON.relative_to(PROJECT_ROOT)),
        str(EN_CORPUS_HASHES_JSON.relative_to(PROJECT_ROOT)),
        str(EN_TEXT_DIR.relative_to(PROJECT_ROOT)),
    ]
    for p in prod_paths:
        assert (PROJECT_ROOT / p).exists(), f"情境6b：生產 commit pathspec 不存在：{p}"
    status = commit_state_with_retry(prod_paths, "test", branch="main",
                                     git=fake_git, sleep=lambda _s: None)
    assert status == COMMIT_OK, "情境6b：生產 pathspec 組合應可 add"
    print("  ✅ 情境6b 生產 commit pathspec（含 sources/en）存在且可 add")

    # 情境 7：空 baseline 已存在（此 workshop_id 曾記錄空語料）＋上游新增 → 應開 issue（非誤判首跑）
    empty_state = {"mods": {"444": {
        "corpus_hash": corpus_hash([]),
        "extractor_schema": EXTRACTOR_SCHEMA,
        "records": records_to_map([]),  # {} 空 baseline，但 key 已存在
    }}}
    new7 = [rec("translate_en", "Items_EN.json", "Base.New", "New")]
    plan7, _st7 = build_layer_a_plan("444", ["ModD"], new7, empty_state, set())
    assert plan7 is not None and plan7["type"] == ISSUE_TYPE_STALE, "情境7：空 baseline 已存在＋新增應開 issue"
    assert "新增" in plan7["body"], "情境7：body 應含新增分類"
    print("  ✅ 情境7 空 baseline 已存在＋上游新增 → 開 issue（未誤判首跑）")

    # 情境 8：同 basename 不同版本目錄 → record id 帶相對路徑不互撞（records_to_map 不覆寫、不 raise）
    multi = [
        rec("translate_en", "v1/Items_EN.json", "Base.Axe", "Axe"),
        rec("translate_en", "v2/Items_EN.json", "Base.Axe", "AxeV2"),  # 同 basename 同 key、不同目錄
    ]
    m8 = records_to_map(multi)
    assert len(m8) == 2, "情境8：同 basename 不同目錄應產生 2 個不同 record id"
    assert (
        m8["translate_en|v1/Items_EN.json|Base.Axe"]
        != m8["translate_en|v2/Items_EN.json|Base.Axe"]
    ), "情境8：兩者 value hash 應不同"
    print("  ✅ 情境8 同 basename 不同版本目錄 → record id 帶相對路徑不互撞")

    # 情境 9：下架偵測——新下架列入 newly_removed＋開 [已下架] plan；已知下架不重複；重新上架清除標記
    wl9 = {"items": {"901": {"mod_ids": ["ModR"]}, "902": {"mod_ids": ["ModS"]}}}
    ts9 = {"items": {"902": {"removed": True, "removed_at": "2026-07-16T00:00:00Z"}}}
    details9 = {"901": {"result": 9}, "902": {"result": 9}}
    changed9, removed9, newly9, meta9 = classify_changes(["901", "902"], details9, ts9)
    assert removed9 == ["901", "902"], "情境9：兩者皆應列 removed"
    assert newly9 == ["901"], "情境9：僅新下架者列 newly_removed"
    assert meta9["901"]["removed_at"], "情境9：新下架應記 removed_at"
    assert meta9["902"]["removed_at"] == "2026-07-16T00:00:00Z", "情境9：既有 removed_at 應保留"
    plans9 = build_removed_plans(newly9, wl9)
    assert len(plans9) == 1 and plans9[0]["type"] == ISSUE_TYPE_REMOVED, "情境9：應僅為新下架開 plan"
    assert "ModR" in plans9[0]["title"], "情境9：標題應含 mod 名"
    plans9b = build_removed_plans(newly9, wl9)
    assert plans9[0]["content_hash"] == plans9b[0]["content_hash"], "情境9：hash 應穩定（冪等）"
    revive9 = {"901": {"result": 1, "time_updated": 123}}
    _c, _r, _n, meta9r = classify_changes(["901"], revive9, {"items": dict(meta9)})
    assert meta9r["901"]["removed"] is False and meta9r["901"]["removed_at"] is None, "情境9：重新上架應清除下架標記"
    print("  ✅ 情境9 下架偵測：新下架開 plan、已知不重複、上架自動復活")

    # 情境 10：extractor schema 演進 → 舊 schema 基準靜默重建（不開 issue）；B41 .txt 翻譯檔可抽取
    old10 = {"mods": {"555": {
        "corpus_hash": "deadbeef", "extractor_schema": EXTRACTOR_SCHEMA - 1,
        "records": {"translate_en|Items_EN.json|Base.Old": "aaa"},
    }}}
    recs10 = [rec("translate_en", "Items_EN.json", "Base.New", "New")]
    plan10, st10 = build_layer_a_plan("555", ["ModT"], recs10, old10, set())
    assert plan10 is None, "情境10：schema 不符應靜默重建、不開 issue"
    assert st10["extractor_schema"] == EXTRACTOR_SCHEMA, "情境10：新基準應帶現行 schema"
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td) / "42" / "media" / "lua" / "shared" / "Translate" / "EN"
        tdir.mkdir(parents=True)
        (tdir / "IG_UI_EN.txt").write_text(
            'IG_UI_EN = {\n    IGUI_Test_A = "Hello",\n    IGUI_Test_B = "World, \\"quoted\\"",\n'
            '    IGUI_Test_A = "Hello v2",\n}\n',  # 上游偶見同檔重複定義 → 取後者
            encoding="utf-8",
        )
        recs_txt = _iter_translate_records(Path(td), "EN")
    assert {r[2] for r in recs_txt} == {"IGUI_Test_A", "IGUI_Test_B"}, "情境10：.txt 鍵應被抽取"
    assert dict((r[2], r[3]) for r in recs_txt)["IGUI_Test_A"] == "Hello v2", "情境10：重複鍵應取後者"
    print("  ✅ 情境10 schema 演進靜默重建＋B41 .txt 翻譯抽取")

    # 情境 11（schema 6）：Lua 文本抽取——getText 鍵引用與「寫死英文」要分得開。
    # 上游常見 getText("KEY", "English") 慣用法：那串英文有鍵、由 lua_gettext 收，
    # 誤收成 lua_literal 會虛報「無鍵可譯」（實測某 mod 因此假報 16 筆）。
    with tempfile.TemporaryDirectory() as td:
        ld = Path(td) / "42" / "media" / "lua" / "client"
        ld.mkdir(parents=True)
        (ld / "Sample.lua").write_text(
            'context:addOption(getText("IGUI_Foo_Bar"), a, b)\n'                 # 有鍵 → 只算 gettext
            'context:addOption(getText("IGUI_Foo_Baz",\n'
            '        "Custom claim is disabled here."), a)\n'                    # 第二引數有鍵 → 不算寫死
            'btn:setTitle("Open Debug Panel")\n'                                 # 真寫死 → lua_literal
            'x:setText("Cancel")\n'                                              # 單字＜8 → 保守放掉
            'y:setName("icons/thing.png")\n'                                     # 資源路徑 → 排除
            'z:setTooltip(myVariable)\n'                                         # 非字面 → 無記錄
            'w = getTextOrNull("IGUI_Foo_Qux")\n'                                # OrNull 也要收
            # --- 以下四項是 regex 版實際踩過的錯，改 lexical scan 後才擋得住 ---
            '-- getText("IGUI_InLineComment")\n'                                 # 行註解內不得收
            '--[[ getText("IGUI_InBlockComment") ]]\n'                           # 長註解內不得收
            'targetText("IGUI_MidIdentifier")\n'                                 # identifier 中段不得命中
            'local sn = getTextWidth("Some Wide Label")\n'                       # getTextWidth 不是 getText
            'local s2 = "a -- b"\n'                                              # 字串裡的 -- 不是註解
            'lbl:setText("Don\'t open this window")\n',                          # 雙引號內的 ' 要抓得到
            encoding="utf-8",
        )
        rl = _iter_lua_records(Path(td))
    gk = {r[2] for r in rl if r[0] == "lua_gettext"}
    lits = {r[3] for r in rl if r[0] == "lua_literal"}
    assert gk == {"IGUI_Foo_Bar", "IGUI_Foo_Baz", "IGUI_Foo_Qux"}, f"情境11：getText 鍵抽取錯誤 {gk}"
    assert lits == {"Open Debug Panel", "Don't open this window"}, \
        f"情境11：寫死字面判定錯誤 {lits}"
    assert all(r[1].startswith("42/media/lua/") for r in rl), "情境11：relpath 應為 mod_dir 相對"
    # 同一字面於同檔重複出現只留一筆（key=sha1），且 relpath 不同才各自成 record
    assert len([r for r in rl if r[0] == "lua_literal"]) == 2, "情境11：同檔同字面應折疊"
    # trim_download 不得再刪 Lua（schema 6 起 Lua 是文本來源）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "media" / "lua" / "client").mkdir(parents=True)
        (root / "media" / "lua" / "client" / "A.lua").write_text("-- x", encoding="utf-8")
        (root / "media" / "textures").mkdir(parents=True)
        (root / "media" / "textures" / "b.png").write_bytes(b"x")
        trim_download(root)
        assert (root / "media" / "lua" / "client" / "A.lua").exists(), "情境11：trim 不得刪 Lua"
        assert not (root / "media" / "textures" / "b.png").exists(), "情境11：trim 應刪非文本檔"
    # 鏡像只收帶真英文的 kind
    assert "lua_gettext" not in TEXT_BEARING_KINDS and "script_item" not in TEXT_BEARING_KINDS, \
        "情境11：id-only kind 不得進鏡像"
    assert {"translate_en", "script_item_dn", "lua_literal"} <= TEXT_BEARING_KINDS, \
        "情境11：帶文本的 kind 必須進鏡像"
    print("  ✅ 情境11 Lua 文本抽取（gettext/寫死分流）＋trim 留 Lua＋鏡像 kind 白名單")

    # 情境 12：coverage 的鍵形正規化——本次唯一寫錯兩次的地方，錯了不會有任何測試變紅。
    #   錯法一：只留 canon 形 → Tooltip_X 與 ContextMenu_X 塌成同身分，跨 mod 互相遮蔽缺口
    #   錯法二：兩側都加雙形式 → translate_en 缺口被重複計算
    assert _key_stem("IG_UI_EN.txt") == "IG_UI" == _key_stem("IG_UI.json"), "情境12：stem 正規化"
    assert _canon_key("ItemName.json", "ItemName_Base.Axe") == "Base.Axe", "情境12：去 legacy 前綴"
    assert _canon_key("ItemName.json", "Base.Axe") == "Base.Axe", "情境12：bare 形不動"
    assert _canon_key("Sandbox_EN.txt", "Sandbox_Foo") == "Foo", "情境12：_EN 檔名 stem"
    # namespace 必須保留：兩者 canon 相同但身分不得相同
    id_a = (_key_stem("Tooltip.json"), _canon_key("Tooltip.json", "Tooltip_OpenJacket"))
    id_b = (_key_stem("ContextMenu.json"), _canon_key("ContextMenu.json", "ContextMenu_OpenJacket"))
    assert id_a[1] == id_b[1] and id_a != id_b, "情境12：namespace 塌陷會讓缺口互相遮蔽"
    # lua_gettext 使用端過濾：非鍵形與動態組鍵前綴都不是真鍵
    assert _is_real_key("IGUI_Foo_Bar"), "情境12：正常鍵應通過"
    assert not _is_real_key("I drop items!"), "情境12：非鍵形字面應濾掉"
    assert not _is_real_key(" / 100 %"), "情境12：符號字面應濾掉"
    assert not _is_real_key("IGUI_AnimalType_"), "情境12：動態組鍵前綴應濾掉"
    print("  ✅ 情境12 coverage 鍵形正規化（stem/canon/namespace 保留/真鍵過濾）")

    # 情境 13：B42 有效分支解析——2026-08-06 那批 899 鍵有 385 筆補在遊戲不載入的
    # 分支上（43% 白做），其中 2 筆的 EN 還取自已改名的舊分支而直接譯錯。
    assert _version_int("42") == 42000, "情境13：單段版本"
    assert _version_int("42.15") == 42015, "情境13：兩段版本"
    assert _version_int("42.20.2") == _version_int("42.20"), "情境13：第三段須丟棄"
    assert _version_int("common") == 0, "情境13：非版本名"
    ids = [
        "translate_en|mods/M/common/media/lua/shared/Translate/EN/UI.json|K_common",
        "translate_en|mods/M/42.12/media/lua/shared/Translate/EN/UI.json|K_old",
        "translate_en|mods/M/42.15/media/lua/shared/Translate/EN/UI.json|K_best",
        "translate_en|mods/M/42.99/media/lua/shared/Translate/EN/UI.json|K_future",
        "translate_en|mods/M/media/lua/shared/Translate/EN/UI.json|K_root",
        "translate_en|mods/M/42.15/media/lua/shared/Translate/EN/UI_EN.txt|K_legacy",
        "lua_gettext|mods/M/42.15/media/lua/client/X.lua|K_lua",
    ]
    eff = resolve_effective_branches(ids)
    assert eff["M"] == {"common", "42.15"}, f"情境13：應為 common+最佳版本夾，實得 {eff['M']}"
    got = {rid.rsplit("|", 1)[-1] for rid in ids if is_effective(rid, eff)}
    # K_old 舊版本夾、K_future 高於遊戲版本、K_root mod 根 media/ 都不載入；
    # K_legacy 在有效版本夾內但 Translator 只讀 .json，執行期不存在
    assert got == {"K_common", "K_best", "K_lua"}, f"情境13：有效集錯誤，實得 {got}"
    # 無合格版本夾時只剩 common（引擎的 versionDir 指向不存在的 42.0）
    only = resolve_effective_branches(["translate_en|mods/N/common/media/x/UI.json|K"])
    assert only["N"] == {"common"}, "情境13：無版本夾時只認 common"
    # 路徑不符 mods/<sub>/<tag>/ 形狀者放行——寧可高估也不要靜默丟棄
    assert is_effective("translate_en|generated/UI.json|K", eff), "情境13：非分支路徑應放行"
    print("  ✅ 情境13 B42 有效分支（common+最佳版本夾／排除 root 與 legacy .txt）")

    # --- 情境14：上游 JSON 帶結尾多餘逗號時仍抽得到鍵（PZ 容忍、Python 不容忍）---
    # 舊行為是整檔跳過＝該檔的鍵對追蹤器與覆蓋率永久不存在，而所有 gate 都是綠的
    # （實測 PompsItems 2752664795 因此隱形 1,766 鍵、104 個玩家可見缺口）。
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td) / "mods/M/42/media/lua/shared/Translate/EN"
        tdir.mkdir(parents=True)
        # 值裡刻意放 `[x,]` 與 `, }`——全文 regex 版的容錯會把它們一起改掉（實測踩過）。
        # **行尾兩種都要測**：CPython 對 LF 檔報「Illegal trailing comma」並停在逗號，
        # 對 CRLF 檔報「Expecting property name」並停在 `}`；只處理前者會讓 CRLF 上游檔全滅。
        body = '{{{nl} "Base.A": "list is [x,] here",{nl} "Base.B": "brace , }} inside",{nl}}}{nl}'
        (tdir / "ItemName.json").write_bytes(body.format(nl="\n").encode("utf-8"))
        (tdir / "ItemNameCRLF.json").write_bytes(body.format(nl="\r\n").encode("utf-8"))
        (tdir / "UI.json").write_bytes(b'{ "UI_X": "X" }')
        (tdir / "Broken.json").write_bytes(b'{ "UI_Y": ')  # 容錯也救不回
        recs = {(r[2], r[3]) for r in _iter_translate_records(Path(td), "EN")}
        assert ("Base.A", "list is [x,] here") in recs, "情境14：尾逗號檔的鍵被丟棄或值被竄改"
        assert ("Base.B", "brace , } inside") in recs, "情境14：末鍵漏抽或值被竄改"
        assert ("UI_X", "X") in recs, "情境14：正常檔受影響"
        assert not any(k == "UI_Y" for k, _ in recs), "情境14：真正壞掉的 JSON 不該生出記錄"
        want = {"Base.A": "list is [x,] here", "Base.B": "brace , } inside"}
        for fname in ("ItemName.json", "ItemNameCRLF.json"):
            data, lenient = load_upstream_json(tdir / fname)
            assert lenient, f"情境14：{fname} 應標記為走了容錯路徑"
            assert data == want, f"情境14：{fname} 容錯把字串值裡的逗號一起刪了（只能刪結構性的那一個）"
        # 巢狀陣列＋物件各一個尾逗號，逐次修好；正常檔不得標記為容錯
        multi = Path(td) / "multi.json"
        multi.write_bytes(b'{"a": ["x", "y",], "b": "z",}')
        assert load_upstream_json(multi) == ({"a": ["x", "y"], "b": "z"}, True), "情境14：多處尾逗號未修好"
        # 負例：**不是**尾逗號的壞 JSON 一律拒絕，不可靜默「修」成另一份合法資料
        # （codex review 反例：舊版把 [1,,2] 修成 [1,2]、{,"a":1} 修成 {"a":1}＝偽造上游原文）
        for i, bad in enumerate((b'[1,,2]', b'{"a":1,,"b":2}', b'{,"a":1}', b'{"a":1,,}')):
            bp = Path(td) / f"bad{i}.json"
            bp.write_bytes(bad)
            try:
                load_upstream_json(bp)
                raise AssertionError(f"情境14：壞 JSON {bad!r} 被容錯靜默改成合法資料")
            except json.JSONDecodeError:
                pass
        clean = Path(td) / "clean.json"
        clean.write_bytes('{"K": "a, b} c", "L": "[x,]"}'.encode("utf-8"))
        assert load_upstream_json(clean) == ({"K": "a, b} c", "L": "[x,]"}, False), "情境14：正常檔誤走容錯"
    print("  ✅ 情境14 上游 JSON 尾逗號容錯（LF/CRLF 皆修、壞 JSON 不生記錄、字串值不被竄改）")

    print("\n✅ self-test 十四情境全通過。")
    return 0


# ============================================================
# 入口
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="MinidoracatModLangFor42 雙上游追蹤器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例：
  uv run scripts/tracker.py gen-watchlist          # 由 sources/mods/ 生成 watchlist.json（含 As1）
  uv run scripts/tracker.py --dry-run --limit 5    # 真打 API 查 5 個時間戳，不下載/不開 issue
  uv run scripts/tracker.py self-test              # 十四情境 mock 測試
  uv run scripts/tracker.py check  --out c.json    # workflow check job
  uv run scripts/tracker.py diff   --in c.json --out d.json --steamcmd <path>
  uv run scripts/tracker.py issue  --in d.json     # workflow issue+state job
        """,
    )
    parser.add_argument(
        "command", nargs="?", default="run",
        choices=["gen-watchlist", "run", "check", "diff", "issue", "self-test", "backfill-en", "coverage"],
        help="執行的命令（預設：run）",
    )
    parser.add_argument(
        "--only", default=None,
        help="backfill-en：只處理這些 workshop_id（逗號分隔），供抽查／重跑失敗清單",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="backfill-en：已完成者也重抽（schema 未變但想強制重建時用）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只印計畫，零 issue 零 commit")
    parser.add_argument(
        "--bootstrap", action="store_true",
        help="本機首建 baseline：允許空 state 起跑，並豁免 CI 缺 baseline fail-fast",
    )
    parser.add_argument("--limit", type=int, default=0, help="只處理前 N 個 workshop_id（0=全部）")
    parser.add_argument("--batch", type=int, default=18, help="API 批次大小（預設 18）")
    parser.add_argument("--steamcmd", default=None, help="steamcmd 執行檔路徑（diff/run 非 dry-run 需要）")
    parser.add_argument("--install-dir", default=None, help="steamcmd 下載目錄（預設 tracker-state/_dl）")
    parser.add_argument("--in", dest="inp", default=None, help="輸入 artifact 路徑（diff/issue）")
    parser.add_argument("--out", default=None, help="輸出 artifact 路徑（check/diff）")
    args = parser.parse_args()

    if args.command == "gen-watchlist":
        sys.exit(cmd_gen_watchlist())
    elif args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "diff":
        sys.exit(cmd_diff(args))
    elif args.command == "issue":
        sys.exit(cmd_issue(args))
    elif args.command == "self-test":
        sys.exit(cmd_self_test())
    elif args.command == "backfill-en":
        sys.exit(cmd_backfill_en(args))
    elif args.command == "coverage":
        sys.exit(cmd_coverage(args))


if __name__ == "__main__":
    main()
