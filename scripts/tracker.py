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
  * 核心邏輯（diff / issue 冪等 / git 重試）皆以可注入依賴實作，供內建 self-test 十五情境 mock 驗證。

命令（uv run scripts/tracker.py <命令>）：
  gen-watchlist  由 sources/mods/*/metadata.json 支持清單生成 tracker-state/watchlist.json（固定含 As1；支持清單變動後重跑）
  run            預設：check → diff → issue → commit 全流程（--dry-run 只印計畫）
  check          僅打 API 查時間戳，寫 changed 清單 artifact（workflow check job；無寫權限）
  diff           讀 changed，下載+裁剪+抽取+diff，寫 diffs artifact（workflow download job；無 GitHub 權限）
  issue          讀 diffs，列 open issue 冪等開/更，commit 成功子集 state（workflow issue+state job）
  self-test      內建十五情境 mock 測試
"""
from __future__ import annotations

import argparse
import bisect
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
BACKFILL_PLANS_JSON = PROJECT_ROOT / ".omc" / "tmp" / "backfill_plans.json"

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
#     schema 9（2026-08-19）：`script_item`／`script_item_dn` 的 key 由裸區塊名改為完整
#     fullType `Module.Item`（見 `_module_by_line`）。B42 查物品名走
#     Item.OnScriptsLoaded() → Translator.getItemNameFromFullType() → itemName.get(fullType)，
#     對應出貨鍵是 ItemName.json 的裸鍵 `Module.Item`；record 少了 module 就無法把「上游有
#     這個物品」對上「我方出貨了這個鍵」，coverage 因此完全看不到 script 物品顯示名缺口
#     （#221，粗篩下限 6,758 鍵／108 個 mod 隱形；#184 是玩家附截圖才發現的個案）。
#     拿 suffix 猜會把「別的 module 同名鍵已出貨」誤判為已覆蓋，違反「module 名不可猜」
#     硬規則，故只有把 module 記進 record 這一條精確路徑。
#     schema 10：停止把 MOD Lua 納入 layer-A。專案只維護 JSON 翻譯；Lua 寫死文字或
#     consumer 行為交由 issue 提交者向 MOD 作者回報。schema bump 讓既有 Lua records
#     靜默重建 baseline，不因大量 removed records 開「可能過時」issue。
EXTRACTOR_SCHEMA = 10

# `script_item`／`script_item_dn` 的 key 自此 schema 起帶 module（＝可與 ItemName 出貨鍵
# 精確比對）。低於此值的 per-mod 基準一律判「不可判定」，不得當成零缺口。
ITEM_MODULE_SCHEMA = 9

# schema 10 現行抽取面；Lua kinds 只保留在歷史 schema 9 讀取白名單。
TEXT_BEARING_KINDS = frozenset({"translate_en", "script_item_dn"})
CURRENT_EXTRACTOR_KINDS = frozenset({
    "translate_en", "script_item_dn", "script_item", "script_recipe",
    "script_vehicle", "script_fixing", "script_craftRecipe",
})
LEGACY_LUA_KINDS = frozenset({"lua_gettext", "lua_literal"})
EXTRACTOR_KINDS = CURRENT_EXTRACTOR_KINDS | LEGACY_LUA_KINDS

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


def _branch_tag(rid: str) -> str:
    """record id 的分支 tag（``mods/<sub_mod>/<tag>/…`` 的 tag；不符該形狀回空字串）。

    用於「同一鍵在 common 與版本夾都定義」時決定誰勝出——引擎是 common 恆載入、
    最佳版本夾疊在其上，故版本夾的值才是實際顯示值。
    """
    parts = rid.partition("|")[2].partition("|")[0].split("/")
    return parts[2] if len(parts) >= 3 and parts[0] == "mods" else ""

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

    en_corpus_hashes.json 是 30MB+ 的受版控真相，且 backfill 期間**每個 mod** 都重寫一次
    （state-first 落盤是關住「非鏡像 kind record 永久遺失」的唯一防線，見 `cmd_backfill_en`）；
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


def _mask_comments(text: str) -> str:
    """把 `/* … */` 區塊註解的內容換成空白（**等長、行數不變**），供區塊掃描與大括號配對用。

    出處＝反編譯的 `ScriptParser.stripComments()`（42.17/42.18/42.19 三版一致）：它只刪
    **成對**的 `/* */`——`lastIndexOf("*/")` 為 -1 時整個 while 不進、原文保留——且
    **完全不認 `//`**。故這裡刻意只遮成對 `/* */`，未閉合的 `/*` 原樣留下，`//` 一概不遮：
    `DisplayName = Foo // bar,` 的值在引擎眼中就是 `Foo // bar`（`readBlock` 的 value
    收到逗號為止），整檔遮 `//` 會憑空改掉上游原文。行尾 `//` 裡的大括號因此仍可能墊高
    depth，那條路由 `_module_by_line` 的毒化防線接手（退化成可見盲區，不產出錯 fullType）。

    先前只跳「整行以 `/` 開頭」的行，於是跨行 `/* … */` 內的 item 宣告照樣被抽成
    record：落在 module 之外時只是 `?.` 雜訊（可見），落在 module 之內時會變成**假
    缺口**送進補譯管線、最終出貨一個引擎永遠查不到的死鍵（實測 583 個 workshop
    script 檔有 1 筆：`AhuToolWeapon.Sledgehammer_Broken`）。

    **巢狀註解必須整段一起遮**，與 `stripComments` 的後向掃描等效：它由最後一個 `*/`
    往前找 `/*`，若兩者之間還夾著 `*/` 就把起點再往前推，等於巢狀整組刪除。改用天真的
    前向 `find("*/")` 會在**第一個內層** `*/` 就收尾，把外層註解的後半段暴露出來——
    實測 `Ahu'sToolWeapon/Ahu_Blunt.txt:125-175` 正是這個形狀（外層註解包著一個已停用
    的 item，內含三段 `/* ==== */` 分隔線）：暴露的 `}` 會提前關掉 `module AhuToolWeapon`，
    使其後所有真 item 全部落 `?.`（4 筆），把可見缺口變成不可判定。

    **已知語意偏離（實測 489 個 workshop script 檔 0 命中，故現況輸出與引擎一致；要修
    必須連同 `EXTRACTOR_SCHEMA` bump 並全庫重抽——同一 schema 必須同一 parser，本機樣本
    不是全宇宙）**：對「落單 `*/`」（前面沒有配對 `/*`，編輯時刪掉 `/*` 的常見殘留）
    本實作照前向計數忽略它、只遮成對區間。引擎是後向掃描（`stripComments():51-85`：由
    最後一個 `*/` 往前，內層 while 處理巢狀，`lastIndexOf("/*", …)` 回 -1 就 `break`
    **整個函式**），**行為依落單 `*/` 的位置分三種，方向並不一致**：
      * 落單在**所有成對之後**（檔尾殘留）→ 第一輪就走到它，內層巢狀回走耗盡使
        `start == -1` → break → **整檔一個註解都不刪**。我方遮掉全部成對＝假零缺口，
        這是影響面最大的形狀。
      * 落單在**中間** → 它之後的成對照常被刪；回走到它時 break → 落單**之前**的成對
        連同其中的 item 完整保留。我方遮掉那些＝假零缺口。
      * 落單在**所有成對之前** → 每個成對都被刪、落單本身保留 → 與我方等效。
    另有一種形似但不同的形狀：`/*U … /*P*/ … */`（外層 `/*U` 未閉合）。回走終止在未閉合
    的 `/*U`，引擎刪 `[U, 最後的 */]` **整段**（連中間真實內容），這是巢狀整組刪除的正常
    語意，我方 `_mask_comments` 同樣如此處理，不算偏離。

    同批未命中的另一項偏離：本實作把註解**換成等長空白**（行號與 offset 必須守恆，
    `_module_by_line` 依賴逐行對位），引擎則是真的**刪除**。差別只在註解夾在識別字中間
    時——`it/*x*/em Foo {` 引擎接成 `item Foo {`、我方留下 `it     em Foo {` 而不認得。
    要同時保住行號對位與貼合刪除語意，得改成「刪除＋維護 offset 映射表」，成本遠高於
    收益（0 命中）。
    """
    out = list(text)
    n = len(text)
    i = 0
    depth = 0
    start = 0
    while i < n:
        if text.startswith("/*", i):
            if depth == 0:
                start = i
            depth += 1
            i += 2
        elif depth and text.startswith("*/", i):
            depth -= 1
            i += 2
            if depth == 0:
                for p in range(start, i):
                    if out[p] != "\n":
                        out[p] = " "
        else:
            i += 1
    # depth>0 收尾＝未閉合註解：引擎不刪（lastIndexOf("*/") 找不到配對即 break），
    # 這裡同樣原樣留下——遮到檔尾會憑空吃掉整批真 item。
    return "".join(out)


# item 區塊宣告。引擎的權威路徑是 `ScriptBucket.CreateFromTokenPP()`（42.20.3 反編譯
# `ScriptBucket.java:94-97`）：`token.split("[{}]")[0].replace(scriptTag, "").trim()`
# ——取 `{` 之前的整段 header、去掉 tag 字樣、只 trim 兩端。**不是** `readBlock()` 的
# `header.split("\\s+")[1]`（那是 Block 樹的 id，不是 script 物件的載入名），所以區塊名
# 允許含空白，且 `//` 之後的字元**屬於名字的一部分**（引擎完全不認 `//` 為註解）。
_ITEM_DECL_RE = re.compile(r"(?<![A-Za-z0-9_])item[ \t]+([^{}\r\n]+?)\s*\{")


def _top_level_item_decls(masked: str) -> list[tuple[int, int, str]]:
    """module body 頂層的 item 宣告：`[(名字起點, body 起點, 名字)]`。

    **不看「行」**：引擎的 `parseTokens()` 按大括號切 token，沒有行的概念，故
    `item JacketBulky01 { DisplayName = X, Hidden = true }`（同列）與 `}item Frostmourne {`
    （同一行第二個 item）都合法。行首錨定的版本會整批漏掉，該 item 連 record 都沒有，
    coverage 於是報假零缺口——實測 585 個 workshop script 檔：同列寫法 192 筆／3 個 mod、
    同行第二個 item 1 筆。

    **depth gate 是必要的**：`ScriptModule.ParseScriptPP()` 只把 module 頂層 token 交給
    item bucket，故巢狀層（`craftRecipe` 的 `inputs { item 1 Base.X, }`、`component { … }`）
    裡的 `item` 不是物品定義；沒有 gate 的寬鬆匹配會多收 6,190 筆 phantom fullType。
    `depth==1`＝module body 內（正常情形）；`depth==0`＝module 之外，引擎的
    `CreateFromToken()` 只處理 `token.indexOf("module") == 0` 的 token，故那種 item 不會
    被載入——仍收下但由呼叫端標成 `UNKNOWN_MODULE`（可見盲區），不當成真物品。

    **已知語意偏離（實測 489 個 workshop script 檔全部 0 命中，故現況輸出與引擎一致；
    要修必須連同 `EXTRACTOR_SCHEMA` bump 並全庫重抽——同一 schema 必須同一 parser，
    本機樣本不是全宇宙，未訂閱 mod 若命中就會留下舊 parser 的 phantom/漏值）**：
      1. `_ITEM_DECL_RE` 只檢查前一字元非識別字，沒有錨到 token 邊界。引擎的
         `ScriptModule.GetTokenType()` 取 `token.substring(0, indexOf('{')).trim()` 再截到
         第一個空白，故 `// item Foo {` 的 type 是 `//`、**不會**交給 item bucket；本實作
         會收下它。正解＝match 後回掃到最近的 `{`／`}`（或檔首），中間須全為空白才收。
      2. `depth >= 2` 的 item 宣告一律靜默丟棄。正常情形那是巢狀層（該丟），但若大括號
         配對被墊高（行尾 `//` 裡的大括號、屬性值裸大括號），module 層的**真** item 也會
         被丟成「連 record 都沒有」——比 `_module_by_line` 的毒化（退化成可見 `?.`）更隱蔽。
         **沒有安全的 heuristic**：真巢狀 item 通常同樣位於實體行首（self-test 的
         `PhantomInput` 就是），拿行首當判準會把大量巢狀 item 誤記成 `UNKNOWN_MODULE`。
         要修就得重建可信的 token/depth 邊界（與 `parseTokens()` 同構），或把
         `_module_by_line` 的毒化狀態一併傳進來共用同一份判斷。
    """
    out: list[tuple[int, int, str]] = []
    depth = 0
    pos = 0
    n = len(masked)
    while pos < n:
        m = _ITEM_DECL_RE.search(masked, pos)
        if m is None:
            break
        # 把 depth 推進到這個 match 的 `{`（不含），沿途累計大括號
        for c in masked[pos:m.end() - 1]:
            if c == "{":
                depth += 1
            elif c == "}":
                depth = max(0, depth - 1)
        name = m.group(1).strip()
        if depth <= 1 and name:
            out.append((m.start(), m.end(), name))
        depth += 1              # 消費該 item 自己的 `{`
        pos = m.end()
    return out


def _item_display_name(text: str, body_start: int) -> str | None:
    """自 item body（`{` 之後）取頂層最後一筆 `DisplayName` 值；無則 None。

    逐字複製引擎的兩層語意（42.20.3 反編譯）：
      1. `ScriptParser.readBlock()`：只在遇到 `,` 時 `new Value(substring(start, i))`，
         遇到 `}` **直接 return**。故沒有尾逗號的 property 引擎根本不套用（Value 從未
         建立），掃到 `}` 就停、殘料丟棄；`Type = Normal, DisplayName = Foo,` 這種同列
         多 property 也自然抽得到（逐行版錨在行首會漏，實測受影響 192 筆）。
      2. `Item.Load()`：`p = s.split("=")`，`param = p[0].trim()`、`val = p[1].trim()`。
         **必須取 p[1] 而不是整段 RHS**：`DisplayName == Vepr…` 的 p[1] 是空字串（雙等號
         中間），引擎顯示空白，整段 RHS 會誤抽成 `= Vepr…`（實測 Base.MagVepr）。
         `DisplayName = A = B` 同理只取 `A`。`param` 比對不分大小寫（`DoParam` 用
         `equalsIgnoreCase`）。
      3. 空值一律回 None 並**覆寫**先前結果（後定義生效）：遊戲顯示空白，填中文＝憑空
         造內容，同 AGENTS.md 對上游空值鍵的既有原則。
    巢狀子區塊（component 等）內的 DisplayName 不誤歸屬——只認 depth==0 的 token。

    **已知語意偏離（實測 489 個 workshop script 檔 0 命中；要修必須連同 `EXTRACTOR_SCHEMA`
    bump 並全庫重抽）**：引擎的 `readBlock()` 在子區塊 parse 完後是 recursive-return，
    緊貼在子區塊 `}` 後面的那個逗號屬於**外層迴圈尚未開始的一輪**，於是 `}` 與 `,` 之間
    的殘料不成為 token；本實作把 `}` 之後直接當新 segment 起點，形同多切一刀。差別只在
    `{…},DisplayName = X,` 這種「子區塊收尾後緊接同一段內還塞了 property」的寫法上。
    """
    found: str | None = None
    depth = 0
    seg_start = body_start
    for i in range(body_start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            if depth == 0:
                break          # item 區塊結束；未收尾的殘料同引擎一樣丟棄
            depth -= 1
            seg_start = i + 1
        elif c == "," and depth == 0:
            parts = text[seg_start:i].split("=")
            if len(parts) >= 2 and parts[0].strip().lower() == "displayname":
                found = parts[1].strip() or None
            seg_start = i + 1
    return found


# `module X { … }` 的區塊邊界（EXTRACTOR_SCHEMA=9）。只有 item 需要它——物品名查表用
# 完整 fullType，而配方名走 `Translator.getRecipeName(裸區塊名)`、車輛名走
# `IGUI_VehicleName<裸名>`，那些 kind 加前綴反而會讓 verify_dist [16] 的上游實據對不上。
#
# 名字的取法與 item 同源（`ScriptManager.CreateFromToken()`，`ScriptManager.java:1308-1311`）：
# `token.split("[{}]")[0].replace("module", "").trim()`。故**不剝 `//`**——`module Base // x`
# 的 module 名在引擎眼中真的是 `Base // x`，剝掉會產出偏離引擎的鍵，違反「module 名不可猜」
# （實測 585 個 workshop script 檔 0 命中此形，故現況零影響）。`/* */` 已由 `_mask_comments`
# 遮成空白，regex 尾端的 `\s*` 自然吃掉，不需另一層剝除。
# 另注意引擎的 `replace` 是**大小寫敏感且全域**：名字裡若含小寫 tag 子字串會被挖掉
# （`item my item x` → `my  x`）。實測 0 命中，故本實作不模擬該邊角。
_MODULE_LINE_RE = re.compile(r"^\s*module\s+([^{}\r\n]+?)\s*(\{)?\s*$")

# 無法歸屬 module 的 item，其 key 用此前綴標記。**刻意不回退成裸名**：裸名混在
# fullType 裡會被 coverage 當成另一種鍵形處理，於是「module 解析漏判」與「該 item
# 真的不存在」兩件事無從區分，缺口再次隱形（正是 #221 的病）。前綴含 `?`，永不可能
# 與出貨鍵相符，故 coverage 只能把它計為「不可判定」並把 wid 列出來。
UNKNOWN_MODULE = "?"


def _module_by_line(lines: list[str]) -> list[str | None]:
    """每行 → 所屬 module 名（不在任何 module 區塊內則 None）。

    以大括號配對界定範圍，故同檔多 module 各自歸屬（#184 那個 mod 同檔就有
    `module Base` 與 `module FrockinSplendor`），**不是取檔內第一個**。PZ 的 module
    只能是頂層區塊，故只在 depth==0 認標頭；`{` 允許同行或下一非空行（同
    `_SCRIPT_LINE_RE` 慣例）。

    呼叫端（`_iter_script_records`）傳入的是 `_mask_comments` 遮蔽過的行，故 `/* */` 內的
    大括號不再干擾；本函式仍自行跳 '/' 開頭的整行註解，對未遮蔽輸入也不致誤判。剩下的
    失準來源是**行尾 `//`**（引擎不認 `//`，故不遮）與屬性值裡的裸大括號（實測 583 個
    workshop script 檔各 0 命中）：失準後 `depth != 0` 會使後續 `module Y` 標頭永遠不被辨識，
    Y 的 item
    會沿用前一個 module 名而拼出**看似有效卻錯誤**的 fullType——那比落入 `UNKNOWN_MODULE`
    更糟（錯 module 可能剛好命中另一個已出貨鍵，於是真缺口再次靜默）。故一旦在 depth>0
    看見頂層 `module` 標頭（PZ 的 module 只能是頂層，這就是配對已失準的確證），即**毒化
    該檔剩餘部分**：其後所有行一律不歸屬 module，item 落 `UNKNOWN_MODULE` 而顯性化。

    已知殘留（fail-visible，不修）：`module X { // 註解` 這種「同行 `{` 之後還有註解」
    整行不匹配 `_MODULE_LINE_RE`（`\\s*$` 吃不下），該 module 認不出 → 其 item 落
    `UNKNOWN_MODULE`。實測同樣 0 命中，且後果可見而非錯值。

    **已知語意偏離（實測 489 個 workshop script 檔 0 命中；要修必須連同
    `EXTRACTOR_SCHEMA` bump 並全庫重抽）**：本函式對「整行以 `/` 開頭」`continue`，因而
    **不計該行的大括號**。`/* */` 已由 `_mask_comments` 遮成空白（那種行的 `stripped`
    是空的），所以這個分支現在只攔到 `//` 開頭的行——而依 `ScriptBucket.CreateFromTokenPP()`
    的實據，引擎**不認 `//` 為註解**、那些大括號是真的。於是同一份 masked 文字有兩套
    depth 模型：`_top_level_item_decls` 逐字元計入 `//` 行的大括號（與引擎一致），本函式
    不計。方向是**本函式讓 module 持續過久**：`// }` 那個 `}` 引擎會算、depth 提早降回 0，
    本函式不算、`cur` 繼續掛著，於是其後的 item 被歸到**早已關閉的 module** 而拼出看似
    有效的錯 fullType（不是 fail-visible 的 `?.`）。錯 module 可能剛好命中另一個已出貨鍵，
    真缺口再次靜默——與本函式毒化防線要防的失效模式同類。
    """
    out: list[str | None] = [None] * len(lines)
    cur: str | None = None      # 目前生效的 module
    pending: str | None = None  # 已見 `module X`，等它的 "{"
    depth = 0
    poisoned = False            # 大括號配對已失準 → 其後一律不歸屬
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("/"):
            out[i] = cur
            continue
        m = _MODULE_LINE_RE.match(line)
        if m and depth > 0:     # 頂層標頭卻在區塊內 ⇒ 配對失準（見 docstring）
            poisoned = True
        if poisoned:
            out[i] = None
            continue
        if depth == 0:
            if m:
                # `module Rotators /* Legacy */` 真實存在；名字解不出時 cur 留 None，
                # 該區塊內的 item 就落 UNKNOWN_MODULE（可見），而非拼出錯誤 fullType。
                # 名字只 trim（引擎 `replace(tag,"").trim()`）；`/* */` 已由 `_mask_comments`
                # 遮成空白，`//` 依實據**屬於名字**，都不另外剝除。
                name = m.group(1).strip() or None
                if m.group(2):          # `module X {` 同行：該行的 "{" 即區塊起點
                    cur, pending, depth = name, None, 1
                    out[i] = cur
                else:                   # `{` 在下一非空行（regex 保證本行無大括號）
                    pending = name
                continue
            if pending is not None:
                # 空行不作廢（`module X` 與 `{` 之間空行是常見寫法）；任何其他非註解
                # 內容出現＝該標頭沒接區塊，`pending` 必須立刻作廢——留著會讓後面第
                # 一個無關的頂層 `{` 被誤認成它的起點，產出**看似有效卻錯誤**的
                # fullType，比落入 UNKNOWN_MODULE 更糟（錯 module 會誤判已覆蓋）。
                if stripped.startswith("{"):
                    cur, pending = pending, None
                elif stripped:
                    pending = None
        out[i] = cur
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            depth, cur = 0, None
    return out


def _iter_script_records(mod_dir: Path) -> list[tuple[str, str, str, str]]:
    """抽取所有 media/scripts/**/*.txt 的 item/recipe 區塊名（basic 正則、value=名本身）；
    item 區塊另抽 DisplayName 為獨立 record（script_item_dn）。

    EXTRACTOR_SCHEMA=5：掃全部 media/scripts 目錄、relpath 為 mod_dir 相對。
    同檔同名 item 重複定義時 DisplayName 取後者（PZ 後定義生效，同 translate .txt 慣例）。
    EXTRACTOR_SCHEMA=9：item 系列的 key 為完整 fullType `Module.Item`；其餘 kind 維持
    裸區塊名（見 `_MODULE_LINE_RE` 註解）。
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
            # 遮蔽 `/* */` 後再掃：註解掉的 item 區塊在引擎眼中不存在，抽出來會變成
            # 假缺口（見 `_mask_comments`）。行數不變，故行號與原檔一一對應。
            masked = _mask_comments(text)
            lines = masked.splitlines()
            module_of = _module_by_line(lines)
            # 非 item 的區塊名維持逐行匹配——verify_dist [16] 以現行 `script_craftRecipe`
            # 集合為死鍵判定實據，放寬它的匹配會改變 gate 行為，屬另一件事。
            for i, line in enumerate(lines):
                m = _SCRIPT_LINE_RE.match(line)
                if not m or m.group(1) == "item":
                    continue
                kw, name, brace = m.group(1), m.group(2).strip(), m.group(3)
                if not name:  # `craftRecipe /* x */`：解不出區塊名，不能記成空鍵
                    continue
                if not brace:
                    nxt = next((ln.strip() for ln in lines[i + 1:] if ln.strip()), "")
                    if not nxt.startswith("{"):
                        continue
                records.append((f"script_{kw}", rel, name, name))
            # item 走**字元級**宣告掃描（`{` 同行或換行皆可）＋ comma-token DisplayName，
            # 與 ScriptParser.readBlock 的語意一致（見 `_ITEM_DECL_RE`／`_item_display_name`）。
            dn_map: dict[str, str] = {}
            # 行號一次算好（`count("\n", 0, pos)` 逐筆重掃前綴＝O(items × 檔長)）
            nl_pos = [i for i, c in enumerate(masked) if c == "\n"]
            for start, body, name in _top_level_item_decls(masked):
                ln_no = bisect.bisect_left(nl_pos, start)
                full = f"{module_of[ln_no] or UNKNOWN_MODULE}.{name}"
                records.append(("script_item", rel, full, full))
                dn = _item_display_name(masked, body)
                if dn is not None:
                    dn_map[full] = dn   # 同檔同名重複定義取後者（PZ 後定義生效）
            for full, dn in dn_map.items():
                records.append(("script_item_dn", rel, full, dn))
    return records



def extract_corpus(mod_dir: Path, lang: str = "EN") -> list[tuple[str, str, str, str]]:
    """layer-A 語料：Translate/<lang> JSON/TXT + media/scripts 顯示名；不追蹤 MOD Lua。"""
    return _iter_translate_records(mod_dir, lang) + _iter_script_records(mod_dir)


def records_to_map(records: list[tuple[str, str, str, str]]) -> dict[str, str]:
    """record 清單 → {record_id: value_hash}；record_id = kind|relpath|key。重複 ID 報錯不覆寫。"""
    out: dict[str, str] = {}
    for kind, relpath, key, value in records:
        rid = f"{kind}|{relpath}|{key}"
        vh = value_hash(value)
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
    """裁剪：保留 Translate、media/scripts 與既有 Lua 路徑，其餘刪除。

    schema 10 不抽取 Lua；保留 `*.lua` 只是沿用下載裁剪行為，不形成持久取證、
    corpus record 或變更訊號。
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


# SUPPORTED_MODS.md／README 支援清單摘要是 manifest 的生成物，而其輸入之一正是本追蹤器
# 每日刷新的 `sources/en/**`：「覆寫本體」欄由 `build_mod.vanilla_override_counts()` 拿
# `sources/en/<wid>.json`（濾有效分支、只算 translate_en）對 `vanilla_keys.json` 的
# `scoped_keys` 取交集算出。排程刷了 EN 鏡像卻不重跑 manifest，生成物就靜默過期，
# 而 build／verify／lint **沒有任何一道驗生成物新鮮度**。
# 實例：c8f5064 讓 Hephas 那列停在 `—`（正確值 `⚠️ ≥3`，該 mod 的 B42 分支由 legacy
# `_EN.txt` 換成 `.json`，三個撞本體的 `UI_prof_*` 首次進入有效集）錯了一整天而三道 gate
# 全綠；AGENTS.md 另記載 cfcf3d8 同款前例（鍵數錯一整天）。
# 故 state commit 前一併重生，並與 state 進**同一個 commit** 保持原子性。
MANIFEST_OUTPUTS = ("SUPPORTED_MODS.md", "README.md")


def refresh_manifest() -> bool:
    """重生 SUPPORTED_MODS.md／README 支援清單摘要。回傳是否成功。

    失敗**不阻斷** state commit——追蹤器停止推進的代價（issue 不再開、上游變更漏偵測）
    遠大於生成物晚一輪同步，且 state 推進本身是自癒的。呼叫端改以非零退出碼讓 CI 轉紅。
    """
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_mod.py"), "manifest"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        print(f"  ⚠️ manifest 重生失敗（rc={proc.returncode}）：{detail}", file=sys.stderr)
        return False
    return True


def state_add_paths() -> list[str]:
    """state commit 的 pathspec（追蹤器狀態＋EN 鏡像＋manifest 生成物）。

    生產與 self-test 情境 6b 共用同一份，避免兩邊各自維護而漂移。
    """
    return [
        str(TIMESTAMPS_JSON.relative_to(PROJECT_ROOT)),
        str(EN_CORPUS_HASHES_JSON.relative_to(PROJECT_ROOT)),
        str(EN_TEXT_DIR.relative_to(PROJECT_ROOT)),
        *MANIFEST_OUTPUTS,
    ]


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
    # **舊基準形狀壞損＝視同首跑，靜默重建 baseline**（同「schema 不符」的既有處理）：
    # 否則 `old_mod.get()` 會拋 AttributeError、`diff_corpus` 的 `set(old_map)` 會拋
    # TypeError，而那發生在 `cmd_backfill_en` 的 per-mod 失敗處理**之前**——每次重跑都在
    # 寫回新 state 前中止，於是 `backfill_done` 判未完成、重抽、再炸，永久修不好那個 wid
    # （prep 的 `_unchecked` 叫人「重抽該 mod」就成了空指示）。
    if not isinstance(old_mod, dict) or not isinstance(old_mod.get("records"), dict):
        is_first_run = True
        old_mod = {}
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
    old_schema = old_mod.get("extractor_schema")
    if old_schema == EXTRACTOR_SCHEMA:
        # 純時間戳變動但語料一致 → 不開
        if old_mod.get("corpus_hash") == new_hash:
            return None, new_state
    elif old_schema == 9:
        # 9→10 只是停止追蹤 Lua，JSON 語料仍可比：先從舊 baseline 扣掉兩個 Lua kind 再
        # diff，才不會把同輪真正的 JSON 變更一起吞掉（舊 corpus_hash 含 Lua，不可比）。
        old_map = {
            rid: value for rid, value in old_map.items()
            if rid.partition("|")[0] not in {"lua_gettext", "lua_literal"}
        }
    else:
        # 其他抽取器 schema 演進 → 新舊語料不可比，靜默重建 baseline（避免規則變更引發假 issue 洪水）
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
    manifest_ok = refresh_manifest()  # EN 鏡像變動會改到 SUPPORTED_MODS.md 的「覆寫本體」欄
    status = commit_state_with_retry(
        state_add_paths(),
        f"chore(tracker): 更新追蹤器狀態 {now_iso()}",
    )
    if status == COMMIT_FAILED:
        print("❌ state commit/push 失敗（下輪自癒）。", file=sys.stderr)
        return 1
    print(f"\n完成：issue {len(plans)} 筆、state {'已提交' if status == COMMIT_OK else '無變更'}。")
    return 0 if manifest_ok else 1


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
    manifest_ok = refresh_manifest()  # EN 鏡像變動會改到 SUPPORTED_MODS.md 的「覆寫本體」欄
    status = commit_state_with_retry(
        state_add_paths(),
        f"chore(tracker): 更新追蹤器狀態 {now_iso()}",
    )
    if status == COMMIT_FAILED:
        print("❌ state commit/push 失敗（下輪自癒）。", file=sys.stderr)
        return 1
    if status == COMMIT_OK and Path(args.inp).resolve() == BACKFILL_PLANS_JSON.resolve():
        BACKFILL_PLANS_JSON.unlink(missing_ok=True)
    print(f"完成：issue {len(plans)} 筆、state {'已提交' if status == COMMIT_OK else '無變更'}。")
    return 0 if manifest_ok else 1


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


def _load_shipped_keys() -> tuple[set[tuple[str, str]], set[str]]:
    """我方實際出貨的鍵，回傳 (身分集, ItemName fullType 集)。

    * **身分集** `(stem, canon)` — 給 `translate_en` 缺口用。**namespace 必須保留**：
      只留 canon 會讓 `Tooltip_OpenJacket` 與 `ContextMenu_OpenJacket` 塌成同一身分，
      使某 mod 的 Tooltip 真缺口被另一 mod 的 ContextMenu 鍵遮蔽（實測遮掉 405 個）。
      同時容納 legacy `<Stem>_KEY` 與 B42 bare `KEY` 兩種寫法。
    * **ItemName fullType 集** — 給 `script_item_dn` 缺口用，**唯一完全不做正規化的
      口徑**：`getItemNameFromFullType()` 以裸 `Module.Item` 查 ItemName map，故只有
      `ItemName.json` 裡真的長成 `Module.Item` 的鍵會被引擎查到。前綴形
      `ItemName_Base.X` 是 B41 遺留死鍵（B42 完全不讀，見 verify_dist [15]），
      **刻意不去前綴計入**——那會把「只出貨死鍵」誤報成已覆蓋。同理不扣除
      `itemname_dead_allowlist` 的已裁決豁免：gate 放行與「玩家是否看到英文」是
      兩件事，報表要看得到。
    """
    ident: set[tuple[str, str]] = set()
    itemnames: set[str] = set()

    def take(basename: str, ks) -> None:
        stem = _key_stem(basename)
        for k in ks:
            ident.add((stem, _canon_key(basename, k)))
        if basename == "ItemName.json":
            itemnames.update(k for k in ks if _is_runtime_item_key(k))

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
    return ident, itemnames


def load_untranslatable(path: Path | None = None) -> tuple[set[tuple[str, str]], set[str]]:
    """讀 registry，回 `(canonical 檔域身分集, ItemName raw fullType 集)`。

    缺檔＝空集合（漸進登記）；存在但形狀壞損一律炸。registry key 嚴格是
    `<非空檔名.json>|<非空鍵>`——漏 `.json` 時 prep 可能仍扣、coverage 的 ItemName
    口徑卻不扣；`UI.json|UI_Foo` 若不 canonicalize，coverage 以 `(UI, Foo)`、prep 以
    `(UI, UI_Foo)`，同樣分岔。兩個 consumer 必須吃同一個 identity。
    """
    p = path or SOURCES / "untranslatable_keys.json"
    if not p.is_file():
        return set(), set()
    data = load_json(p)
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        raise ValueError(f"{p.name}：形狀壞損（需 {{'entries': {{'<檔.json>|<鍵>': '<理由>'}}}}）")
    pairs: set[tuple[str, str]] = set()
    items: set[str] = set()
    for pair, reason in entries.items():
        if not isinstance(pair, str) or "|" not in pair or not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{p.name}：形狀壞損（需 {{'entries': {{'<檔.json>|<鍵>': '<理由>'}}}}）")
        fname, key = pair.split("|", 1)
        if not fname.endswith(".json") or not fname[:-5] or not key:
            raise ValueError(f"{p.name}：非法 pair {pair!r}（檔名須以 .json 結尾、兩側非空）")
        pairs.add((_key_stem(fname), _canon_key(fname, key)))
        if fname == "ItemName.json":
            items.add(key)
    return pairs, items


def _is_runtime_item_key(key: str) -> bool:
    """`ItemName.json` 的鍵是否真的會被 `getItemNameFromFullType()` 查到。

    引擎以裸 `Module.Item` 查表：B41 前綴形 `ItemName_Base.X` 是死鍵（B42 完全不讀，
    見 verify_dist [15]），無 module 段的鍵也不可能是 fullType。兩者都不算覆蓋——
    把它們算進去就會把「只出貨死鍵」誤報成已覆蓋。
    """
    return "." in key and not key.startswith("ItemName_")

def value_hash(value: str) -> str:
    """state 的 record 值就是這個（`records_to_map` 的口徑），consumer 端比對共用。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def mirror_incoherent_rids(records: dict, mirror: dict) -> set[str]:
    """鏡像與 state 不一致的 rid：**鏡像有而 state 沒有**，或**同 rid 值 hash 不符**。

    `backfill-en` 每個 mod 先原子落 state、再寫鏡像，故正常狀態下兩者恆一致。不一致只
    會發生在**中斷／寫入失敗留下的殘跡**或人工動過鏡像檔，而兩種形狀都會害到 consumer：
      * 鏡像多 rid（state 舊）→ 宇宙取自 state，那些鍵的缺口靜默低報成零。
      * 同 rid 值不同（state 已是新 hash、鏡像仍是舊文本，或反之）→ 值取自鏡像，於是
        拿**過期英文**當翻譯來源，還會讓 id-only／malformed 判定用錯的值。
    兩者都是 #221 那種「看起來綠燈、其實沒看」的失效模式，故 `coverage`／
    `prep_mod_strings` 都必須顯性列出而非靜默採用。

    刻意**不**驗「state 有而鏡像沒有」：那是 `backfill_done()` 的職責，且合法狀態
    （該 mod 無 text-bearing record ⇒ 鏡像被刪除）也長這樣。
    """
    bad = {rid for rid in mirror if rid not in records}
    for rid, val in mirror.items():
        if rid in records and (not isinstance(val, str)
                               or value_hash(val) != records[rid]):
            bad.add(rid)
    return bad


def owner_of(rid: str) -> str:
    """rid → 引擎實際的載入單位（mod root），**不是 workshop id**。

    `ZomboidFileSystem.loadMod()` 是按**啟用的 mod ID** 載入，一個 workshop 項目常含多個
    可獨立啟用的 mod（addon）。把整個 wid 壓成單一 owner 會把真衝突當成「同一個 mod 自己
    的疊加」吃掉——實例 wid `2791656602` 的 `fhqwhgads' Motorious Zone` 與
    `... - Real Names Adddon`，同鍵 `IGUI_VehicleNamefhq250GTO` 一邊 Ferrari、一邊
    Impennarsi，只啟用 base mod 的玩家會拿到 addon 的譯名。common→版本夾的優先序也只
    存在於同一個 mod root 內。
    """
    relpath = rid.partition("|")[2].partition("|")[0]
    parts = relpath.split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "mods" else relpath


def winning_dn_text(recs: dict, mirror: dict, eff: dict, is_eff=None) -> dict:
    """每個 `(owner, fullType)` 的 **runtime 勝出值**。

    勝出 rid 由 **state** 決定：同一 owner 內 common 先、有效版本夾後覆寫（引擎讓版本夾
    疊在 common 之上）。值查鏡像；**勝出 rid 缺值或非字串時整鍵不入結果**（交給
    `missing` 盲區），**絕不可回退用 common 的舊值**——common 與版本夾同 fullType、鏡像
    只剩 common 那筆時（backfill 中斷殘跡；`mirror_incoherent_rids` 依設計不驗 state 有
    →鏡像沒有），回退等於拿**低優先序的舊英文**當翻譯來源，census 也會用它比 owner
    衝突＝與引擎執行期相反的結論。先前兩個 consumer 都直接迭代 mirror rows 建值，正是
    這個遮蔽。

    **一律按 `(owner, fullType)` 分組，無「不分 owner」模式**：同 wid 可有多個獨立
    mod root，跨 root 選單一 winner 會讓 A 的值遮掉 B 的缺值／id-only 判定——正是
    owner 粒度要修的盲區。
    """
    chk = is_eff or is_effective
    winner: dict = {}
    rows = [r for r in recs if r.startswith("script_item_dn|") and chk(r, eff)]
    for rid in sorted(rows, key=lambda r: _branch_tag(r) != "common"):
        winner[(owner_of(rid), rid.rpartition("|")[2])] = rid
    out: dict = {}
    for key, rid in winner.items():
        v = mirror.get(rid)
        if isinstance(v, str):
            out[key] = v
    return out


def _item_dn_stats(
    schema, dn_keys: set[str], dn_text: dict[str, str],
    shipped_items: set[str], vanilla_items: set[str], item_keys: int = 0,
) -> dict:
    """script 物品顯示名的覆蓋統計：`{total, gap, idonly, blind, kinds, why}`。

    **四種盲區一律計數、絕不靜默跳過**（#221 的病因就是靜默），且分成兩種行動：
      重抽可消除 —
      1. `schema < ITEM_MODULE_SCHEMA`（`kinds` 記 `schema`）— 舊基準的 key 沒有 module，
         無從精確比對。backfill 會略過已下架項目、失敗項也保留舊 state，故混合 schema
         必然存在。
      2. `mirror` — `dn_text` 缺該筆的值（鏡像整個不存在時 `dn_text` 為空，該 mod 全數
         落入這一類），取不到 DisplayName 就無法判斷上游是否只給了 item id。
      重抽無效 —
      3. `unknown_module` — `_module_by_line` 沒解出 module（畸形檔、大括號配對失準）。
         要修的是 parser，不是重抽。
      4. `malformed` — 上游 property 沒收尾逗號，引擎的 `split("=")[1]` 把下一欄名稱一起
         吃進 DisplayName（值含換行）。是上游 script 格式錯誤，只能回報上游或個案處理。
    `idonly`（DisplayName 等於 item id 或為空白）**不是盲區**，是獨立的扣除項，另行回報。
    """
    if not isinstance(schema, int) or schema < ITEM_MODULE_SCHEMA:
        # `dn_keys` 空**不等於**沒有 script 物品：`script_item_dn` 是 schema 5 才加的
        # kind，schema 3/4 的舊基準只有 `script_item`（實測 2 個 mod 共 79 筆）。只看
        # `dn_keys` 會把它們判成零缺口而完全不列出——那正是 #221 的靜默。故以
        # 「有任何 item record」為準。
        n = len(dn_keys) or item_keys
        why = f"schema={schema}（key 無 module）" if n else None
        # `blind_keys` 給空集：schema<9 的鍵是裸名，不可能與 `Module.Item` 形的本批鍵相交
        return {"total": len(dn_keys), "gap": set(), "idonly": 0, "blind_keys": set(),
                "blind": n, "kinds": {"schema"} if n else set(), "why": why}
    # schema 9 起 `script_item_dn` 的 key 必須是完整 `Module.Item`；裸 key 代表 extractor
    # 升級後 state 沒真正重抽（實測 schema=10 仍殘留 369 筆／4 mod：ClassicTire1、
    # 12GClip5、KatanaSheath、Makarov 等）。把它們當 gap 會要求人翻一個**引擎永遠不查的
    # 裸鍵**；prep 反而從同 mod legacy ItemName_EN.txt 錨到 `Base.X`，兩 consumer 分歧。
    # 這不是「module 未解出」的 parser 盲區（producer 正常會寫 `?.X`），而是 state/schema
    # 自相矛盾，重抽可消除，故獨立列 `stale_schema`。
    stale_bare = {k for k in dn_keys if "." not in k}
    unknown = {k for k in dn_keys if k.startswith(UNKNOWN_MODULE + ".")}
    known = dn_keys - unknown - stale_bare
    # **先扣已出貨與 vanilla**：那些鍵不論鏡像缺值或上游格式壞損都不是我方的待辦，
    # 算進 blind 只會讓「不可判定 N 筆」與行動分類虛胖。
    todo = (known - shipped_items) - vanilla_items
    missing = todo - dn_text.keys()
    # 上游的 property 沒收尾逗號、下一個 property 才有時，引擎的 `split("=")[1]` 會把
    # 下一欄名稱一起吃進值（`Item.Load`），玩家真的看到那串含換行的垃圾。抽取器忠實
    # 記錄它（變更偵測需要），但它**不能當翻譯來源**——譯什麼都不對。故計為不可判定，
    # 兩支工具同口徑（實測 24 筆／1 個檔）。
    malformed = {k for k in todo - missing if "\n" in dn_text[k] or "\r" in dn_text[k]}
    # 「上游沒給真英文名」的兩種形狀，一律扣除、不進 gap：
    #   * 值等於 item id 本身（`DisplayName = Sledgehammer_Broken`）
    #   * 值為空白（`DisplayName = ,` 或整串空白）。**這一支在 producer 路徑上不可達**：
    #     `_item_display_name()` 對空值回 `None`，該 item 根本不產生 `script_item_dn`
    #     record。留著是 consumer 端的 fail-closed（鏡像被人工改動、或值非字串時仍成立），
    #     成本近乎零；勿因「用不到」而刪。
    # **判定必須留在這個共用函式裡**：先前 prep 自己在 `local` 那層多加一道 `.strip()`
    # 濾網，於是 coverage 的 `dn_gap` 恆比 prep 的 `_gap` 多，差額既不進 `_undecidable`
    # 也不進 `_unchecked`＝兩支腳本分岔（正是本函式註解一開始要避免的事）。
    candidate = todo - missing - malformed
    idonly = {k for k in candidate
              if not dn_text[k].strip() or dn_text[k] == k.rpartition(".")[2]}
    gap = candidate - idonly
    kinds = set()
    reasons = []
    if unknown:
        kinds.add("unknown_module")
        reasons.append(f"{len(unknown)} 筆 module 未解出")
    if stale_bare:
        kinds.add("stale_schema")
        reasons.append(f"{len(stale_bare)} 筆 schema={schema} 卻仍是裸 key（重抽該 mod）")
    if missing:
        kinds.add("mirror")
        reasons.append(f"{len(missing)} 筆 sources/en 鏡像缺值")
    if malformed:
        kinds.add("malformed")
        reasons.append(f"{len(malformed)} 筆上游 DisplayName 夾帶下一欄（無尾逗號）")
    # `blind_keys` 是 **mirror／malformed 兩桶的明細**，給 prep 的 census 盲區交集用。
    # 刻意不含 `unknown`（`?.` 前綴不可能與任何真 fullType 相交）也不含 schema 桶（裸名
    # 鍵形同樣對不上 `Module.Item`）；**絕不可用「不在 census 的都算盲區」反推**——id-only
    # 與上游留白也不在 census，那是合法扣除，誤列會把正常批次 fail-closed 卡死
    # （實測 `Base.M249`：一邊 translate_en "FN M249"、另一邊 script id-only "M249"）。
    return {"total": len(dn_keys), "gap": gap, "idonly": len(idonly),
            "blind": len(unknown) + len(stale_bare) + len(missing) + len(malformed),
            "kinds": kinds, "blind_keys": missing | malformed,
            "why": "；".join(reasons) or None}


def cmd_coverage(args) -> int:
    """報表：上游 JSON／script 文本有多少我方沒收。

    兩個口徑：
      * ``item_dn`` 缺口 — script 定義的物品顯示名。物品欄一定顯示它＝確證可見，
        且 schema 9 起 key 帶 module，可與 `ItemName.json` 出貨鍵**精確**比對
        （不做任何 suffix 猜測，見 `_load_shipped_keys`）。
      * ``translate_en`` 缺口 — 上游 EN JSON/TXT 裡有，但未必被用到（含廢棄鍵）。
    schema 10 起不再統計 MOD Lua；非 JSON 根因交由 issue 提交者向 MOD 作者回報。
    vanilla 鍵一律扣除。不可判定者逐 mod 列出，既不併入缺口也不當成零缺口。
    """
    corpus_state = load_corpus_hashes()
    mods = corpus_state.get("mods", {})
    shipped_ident, shipped_items = _load_shipped_keys()
    vjson = load_json(SOURCES / "vanilla_keys.json")
    vraw = set(vjson.get("keys", []))
    vanilla = vraw | {k.split("_", 1)[1] for k in vraw if "_" in k}
    # item_dn 用**檔域**基準：物品名只查 ItemName map，扁平聯集會把其他檔的同名鍵
    # 也當成本體鍵而過度扣除（於是真缺口被藏起來）。
    # 欄位缺失一律炸（同 verify_dist/_load_vanilla_basis、lint_ch、build_mod 的
    # fail-closed 慣例）：靜默退化成空集合＝這道本體排除整批失效，於是本體鍵被
    # 當成缺口送進補譯管線，違反「不得覆寫本體」鐵律的第一道防線。
    vanilla_items = set(vjson["scoped_keys"]["ItemName.json"])
    # 已裁決不補譯的鍵。兩個口徑各自形狀：EN 走 `(檔 stem, 鍵)`、物品名走裸 fullType。
    untr_pairs, untr_items = load_untranslatable()

    rows: list[dict] = []
    tot = {"en": 0, "en_gap": 0, "dn": 0, "dn_gap": 0, "dn_idonly": 0, "dn_blind": 0}
    blind: list[tuple[str, str, set[str]]] = []   # (wid, 人讀原因, kinds)
    en_stale: list[tuple[str, int]] = []          # (wid, translate_en 的不一致 rid 數)
    for wid in sorted(mods):
        en_ids: set[tuple[str, str]] = set()
        # per-owner 分開統計（owner=mod root，引擎的載入單位）；wid 級累加器已無人讀
        o_dn: dict[str, set] = {}     # owner（mod root）→ script_item_dn fullType 集
        o_item: dict[str, set] = {}   # owner → script_item 裸名集
        # 只認引擎真的會載入的分支——舊版本夾／mod 根 media/ 的鍵補了也是死資料
        recs = mods[wid].get("records")
        # **形狀壞損一律炸，不得靜默退化成空集合**：`records` 若是 list／字串／None，
        # 下面每個迴圈都跑零圈，於是這個 mod 的缺口與盲區雙雙為 0＝#221 的靜默零缺口
        # （同 `verify_dist` [16] 對實據殘缺 fail-closed 的既定慣例）。
        if not isinstance(recs, dict):
            raise ValueError(
                f"{wid}：tracker state 的 records 形狀壞損（{type(recs).__name__}），"
                "缺口統計無法信任——修 `tracker-state/en_corpus_hashes.json` 或重跑 backfill-en")
        eff = resolve_effective_branches(recs)
        for rid in recs:
            if not is_effective(rid, eff):
                continue
            kind, _, rest = rid.partition("|")
            relpath, _, key = rest.partition("|")
            if kind == "translate_en":
                base = relpath.rsplit("/", 1)[-1]
                stem, canon = _key_stem(base), _canon_key(base, key)
                en_ids.add((stem, canon))  # 保留 namespace，否則跨檔同名鍵互相遮蔽
            elif kind == "script_item_dn":
                o_dn.setdefault(owner_of(rid), set()).add(key)
            elif kind == "script_item":
                o_item.setdefault(owner_of(rid), set()).add(key)
        en_gap = {x for x in en_ids - shipped_ident
                  if x[1] not in vanilla and x not in untr_pairs}
        # DisplayName 值只在 sources/en 鏡像裡（狀態檔只有 hash）。缺鏡像／缺該筆值的
        # 後果交給 _item_dn_stats 計成盲區，不在這裡靜默跳過。
        # **值一律走 `winning_dn_text`**：勝出 rid 由 state 決定（同 owner 內 common 先、
        # 版本夾後覆寫），勝出 rid 缺值即整鍵落 missing——直接迭代 mirror rows 會在
        # 「版本夾那筆缺值」時回退用 common 的舊英文（backfill 中斷殘跡可達），與引擎
        # 執行期相反。
        win: dict = {}
        stale_dn: set[str] = set()
        mirror = EN_TEXT_DIR / f"{wid}.json"
        if mirror.is_file():
            mdata = load_json(mirror)
            # **先驗 state↔鏡像 coherence**：兩個口徑的宇宙都取自 state，state 落後或值
            # 不符時缺口會靜默低報成零。不能只在 `dn_keys` 非空時讀鏡像——state 落後的
            # 極端情形正是 `dn_keys` 為空而鏡像滿的那一種。
            # **不可只濾 `script_item_dn`**：鏡像以 `translate_en` 為大宗，只看 dn 會讓
            # EN 口徑的同一種低報完全不出聲（而 `prep_mod_strings` 對它 fail-closed，
            # 於是兩支工具對同一份 state 給出互相矛盾的結論）。
            bad = mirror_incoherent_rids(recs, mdata)
            # **只認有效分支**：死分支的鏡像殘跡不影響任何判定（那些鍵補了也是死資料），
            # 拿它去剔除會把有效分支的好值一起砍掉、把死資料鍵計進不可判定。
            stale_dn = {r for r in bad
                        if r.startswith("script_item_dn|") and is_effective(r, eff)}
            other_bad = bad - stale_dn
            if other_bad:
                en_stale.append((wid, len(other_bad)))
            # **排除層級是 `(owner, fullType)`，不是裸 fullType**：A root 的壞 rid 若以
            # 裸 fullType 過濾，會把 B root 同鍵的健康勝出值一起刪掉（多扣）；反向另計
            # 時 B state 有同鍵又會誤判「已在宇宙」而漏計。
            stale_ok = {(owner_of(r), r.rpartition("|")[2]) for r in stale_dn}
            win = {ok: v for ok, v in winning_dn_text(recs, mdata, eff).items()
                   if ok not in stale_ok}
        # **逐 owner 各算一次**（owner=mod root，引擎的載入單位）：同 wid 可有多個獨立
        # mod root，跨 root 合併會讓 A 的值遮掉 B 的缺值／id-only 判定。彙總時 total／
        # idonly／blind 相加、gap 取聯集（同鍵多 owner 都缺就是一個缺口）。
        schema_w = mods[wid].get("extractor_schema")
        dn = {"total": 0, "gap": set(), "idonly": 0, "blind": 0,
              "kinds": set(), "why": None}
        whys = []
        for o in sorted(set(o_dn) | set(o_item)):
            st_o = _item_dn_stats(schema_w, o_dn.get(o, set()),
                                  {k: v for (ow, k), v in win.items() if ow == o},
                                  shipped_items, vanilla_items,
                                  len(o_item.get(o, set())))
            dn["total"] += st_o["total"]; dn["idonly"] += st_o["idonly"]
            dn["blind"] += st_o["blind"]; dn["gap"] |= st_o["gap"]
            dn["kinds"] |= st_o["kinds"]
            if st_o["why"]:
                # 判準要用**實際迭代的集合**：只看 `o_dn` 時，schema<9（只有 `script_item`）
                # 的多 root mod 會輸出多筆未標 owner 的完全相同字串。
                whys.append(st_o["why"] if len(set(o_dn) | set(o_item)) < 2
                            else f"[{o}] {st_o['why']}")
        # 已裁決不補譯者在**逐 owner 累加之後**統一扣：`_item_dn_stats` 的 total／idonly／
        # blind 是同一份輸入的分類統計，只從 gap 扣才不會讓那些分母跟著失真。
        dn["gap"] -= untr_items
        dn["why"] = "；".join(whys) or None
        if stale_dn:
            # **不重複計 blind**：`stale_ok ∩ 宇宙` 已因上面的剔除自然落入 `missing`
            # （`mirror` 盲區）。留著更糟——`_item_dn_stats` 會拿**過期值**去判 gap／
            # id-only／malformed。只有「鏡像新增而 state 尚無**該 owner**」的 (owner,鍵)
            # 不在宇宙內、missing 算不到，必須另計，否則又是低報。
            # **另計時同樣先扣已出貨與 vanilla**（同 `_item_dn_stats` 的既定原則）。
            extra = {(o, k) for o, k in stale_ok
                     if k not in o_dn.get(o, set())
                     and k not in shipped_items and k not in vanilla_items}
            dn["blind"] += len(extra)
            dn["kinds"] = dn["kinds"] | {"stale_state"}
            # 只報**另計**的那批：全數列出會含已被 `missing` 計過的鍵，讀者把兩個
            # 子句相加就會高估不可判定量。
            dn["why"] = "；".join(filter(None, [
                dn["why"], f"{len(stale_ok)} 個物品名的鏡像與 state 不一致"
                           f"（其中 {len(extra)} 個另計、其餘已列於上或屬已出貨／vanilla）"]))
        if dn["why"]:
            blind.append((wid, dn["why"], dn["kinds"]))
        # **totals 先累加再決定是否列表**：放在 continue 之後會把「完全無缺口」的 mod
        # 排除在分母外，覆蓋率分母因而嚴重低報（實測 EN 76,063 vs 實際 89,764）。
        tot["en"] += len(en_ids); tot["en_gap"] += len(en_gap)
        tot["dn"] += dn["total"]; tot["dn_gap"] += len(dn["gap"])
        tot["dn_idonly"] += dn["idonly"]; tot["dn_blind"] += dn["blind"]
        if not (en_gap or dn["gap"]):
            continue
        rows.append({
            "wid": wid, "en": len(en_ids), "en_gap": len(en_gap),
            "dn": dn["total"], "dn_gap": len(dn["gap"]),
            "samples": sorted(dn["gap"])[:5],
        })

    print(f"基準涵蓋 {len(mods)} 個 mod（extractor_schema={corpus_state.get('extractor_schema')}）")
    print(f"我方已出貨鍵 {len(shipped_ident)}（其中 ItemName fullType {len(shipped_items)}）"
          f"；vanilla 排除鍵 {len(vanilla)}（ItemName 檔域 {len(vanilla_items)}）")
    print()
    print(f"上游 EN 鍵 {tot['en']}  → 缺口 {tot['en_gap']}")
    print(f"script 物品名 {tot['dn']}  → **可補的確證可見缺口 {tot['dn_gap']}**（精確比對 fullType）")
    print(f"  （另扣除 {tot['dn_idonly']} 筆 DisplayName 等於 item id 或為空白＝上游沒給真英文名）")
    print("MOD Lua 口徑：schema 10 起停用，不納入缺口、排序或 artifact")
    if en_stale:
        # 物品名不一致另計 blind；其餘（translate_en、退役／未知 kind）獨立通報。
        print()
        print(f"⚠️ {len(en_stale)} 個 mod 的非物品名／非現行 record 鏡像與 state 不一致"
              f"（共 {sum(n for _, n in en_stale)} 筆）→ 跑 `tracker.py backfill-en` 重抽消除：")
        for wid, n in sorted(en_stale, key=lambda x: -x[1])[:10]:
            print(f"    {wid}：{n} 筆")
    if blind:
        # 每種成因對應不同行動，混在一起就會給出假保證（對 parser 漏判與上游格式錯誤
        # 說「重抽即消除」，人會白燒一輪 backfill 而不去修真正的東西）。
        REFETCHABLE = {"schema", "mirror", "stale_state"}
        refetch_blind = [b for b in blind if b[2] <= REFETCHABLE]
        parser_blind = [b for b in blind if "unknown_module" in b[2]]
        upstream_blind = [b for b in blind if "malformed" in b[2]]
        stale_blind = [b for b in blind if "stale_state" in b[2]]
        print()
        print(f"⚠️ {len(blind)} 個 mod 的物品名缺口**不可判定**（共 {tot['dn_blind']} 筆，"
              "未計入上方缺口，也不算零缺口）：")
        # **部分數字與上方「script 物品名」不是同一個宇宙，別直接加減**：`schema` 桶用
        # `len(dn_keys) or item_keys`——schema 5–8 有 `script_item_dn`，那些鍵**同時**進
        # total 與 blind；只有 schema 3/4（只有 `script_item`）的 blind 不在 total 裡。
        # 實測 910 筆 blind 中 479 筆在 total 內、431 筆跨宇宙。
        print("  （schema 3/4 的 blind 計的是 `script_item` 裸名鍵、不在上方 total 宇宙內；"
              "schema 5–8 的則同時計入兩邊，勿直接加減）")
        if refetch_blind:
            # 標籤要涵蓋 `stale_state`——它也在 `REFETCHABLE` 裡，只寫「schema 落後／鏡像
            # 缺值」會讓 `kinds == {"stale_state"}` 的 mod 被算進一個名不符實的分類。
            print(f"  · {len(refetch_blind)} 個純屬 schema 落後／鏡像缺值／state 不一致"
                  " → 跑 `tracker.py backfill-en` 重抽即消除")
        if stale_blind:
            # **不寫「其中」**：`stale_blind` 自 blind 全集算，kinds 同時含 unknown_module
            # 的 mod 不在 `refetch_blind` 裡卻仍被算進來，「其中」會讓兩個數字對不上。
            print(f"  · {len(stale_blind)} 個有**鏡像與 state 不一致**（backfill 中斷殘跡）"
                  " → 重抽該 mod 即消除，但在那之前它的缺口數是低報的")
        if parser_blind:
            print(f"  · {len(parser_blind)} 個有 module 未解出（`?.` 鍵）"
                  " → **重抽無效**，要修的是 `_module_by_line` 的 module 邊界解析")
        if upstream_blind:
            print(f"  · {len(upstream_blind)} 個有上游 DisplayName 夾帶下一欄（無尾逗號）"
                  " → **重抽無效**，是上游 script 格式錯誤，只能回報上游或個案處理")
        # 需要動手的兩類排前面，不該被 schema 雜訊擠出預覽
        def _pri(b):
            return (not (b[2] - REFETCHABLE), b[0])
        for wid, why, _k in sorted(blind, key=_pri)[:15]:
            print(f"    {wid}：{why}")
        if len(blind) > 15:
            print(f"    ...（還有 {len(blind) - 15} 個）")
    print()
    top = args.limit or 30
    print(f"=== 依「JSON／script 可補缺口」排序 Top {top} ===")
    print(f"{'workshop_id':>12} {'EN缺':>6} {'物品名':>6}  範例")
    order = sorted(rows, key=lambda r: (-r["dn_gap"], -r["en_gap"]))
    for r in order[:top]:
        print(f"{r['wid']:>12} {r['en_gap']:>6} {r['dn_gap']:>6}  "
              f"{[x[:24] for x in r['samples'][:3]]}")
    if args.out:
        write_json(Path(args.out), {
            "schema": {"extractor": EXTRACTOR_SCHEMA, "lua_tracking": "disabled"},
            "totals": tot,
            "state_mirror_incoherent": {wid: n for wid, n in sorted(en_stale)},
            "undecidable": {wid: {"why": why, "kinds": sorted(kinds)}
                            for wid, why, kinds in blind},
            "mods": {r["wid"]: {"en": r["en"], "en_gap": r["en_gap"],
                                "item_dn": r["dn"], "item_dn_gap": r["dn_gap"]}
                     for r in rows},
        })
        print(f"\n明細 → {args.out}")
    return 0


def backfill_done(st: dict | None, mirror: Path) -> bool:
    """該 mod 的 `sources/en` 鏡像是否與 state 完全對齊（backfill 續跑的跳過判準）。

    **必須比對鏡像內容，不能只看「檔案存在」**：`--force` 重抽已是現行 schema 的 mod 時，
    schema 標記兩邊相同，只看存在性會把「鏡像已是新版、state 仍是舊版」判成已完成 → 該
    mod 永久不重抽，而 coverage 以舊 state 的 records 當宇宙，新增的 item 既不進 gap 也不
    進 blind＝#221 的靜默零缺口重演。

    逐 rid 比對**值 hash**（state 的 record 值就是 `sha256(value)[:12]`，見
    `records_to_map`）。只比鍵集不夠：上游若只改文本、鍵集不變，鏡像已是新值而 state 仍是
    舊 hash 的組合照樣會被判「已完成」。

    **能力邊界（設計上由寫序負責，不是本函式）**：只變更非鏡像 kind
    （`lua_gettext`／`script_item`／`script_craftRecipe`…）時鏡像內容不變，本函式無從察覺。
    關住那個窗口的是 `cmd_backfill_en` 的**每個 mod state-first 原子落盤**——state 一落地
    就代表該輪全部 record 已記下，中斷不會留下「新 record 只存在於記憶體」的狀態。若改回
    批次 checkpoint 或鏡像先寫，這個失效模式就會回來，而本函式攔不到。
    """
    # `st` 本身也要驗：非 dict 時 `.get()` 直接拋 AttributeError，而本函式在 `cmd_backfill_en`
    # 建 `todo` 時被呼叫——那在 per-mod 失敗處理之前，整批會直接中止。
    if not isinstance(st, dict) or st.get("extractor_schema") != EXTRACTOR_SCHEMA:
        return False
    recs = st.get("records")
    # **形狀壞損一律判「未完成」**：容器非 dict、未知／歷史 kind、缺分隔符、
    # 空路徑或空 key 都不得被當成 schema 10 的完成證據。
    if not isinstance(recs, dict):
        return False
    for rid in recs:
        kind, s1, rest = rid.partition("|")
        relpath, s2, key = rest.partition("|")
        if kind not in CURRENT_EXTRACTOR_KINDS or not s1 or not s2 or not relpath or not key:
            return False
    want = {r for r in recs if r.split("|", 1)[0] in TEXT_BEARING_KINDS}
    if not want:
        # 合法無檔的兩種情形，缺一即會每輪重抓（實測曾有 7 個 mod 卡在第二種）：
        #   1. 語料整個為空（empty_corpus）
        #   2. 語料非空但**全是不進鏡像的 kind**（純 script_item/craftRecipe 的 mod）
        # 兩者都**要求鏡像不存在**：上游把文本全數移除時，若 `unlink` 前中斷或刪檔失敗，
        # 舊鏡像會殘留而 state 已宣告無文本；只看 state 就會永久跳過、鏡像永遠不清。
        return (bool(st.get("empty_corpus")) or bool(recs)) and not mirror.exists()
    if not mirror.is_file():
        return False
    try:
        mir = load_json(mirror)
    except (ValueError, OSError):
        return False
    # 合法 JSON 但頂層非 dict（例如 `null`）→ 下面的 `set(mir)`／`mir[r]` 會拋
    # TypeError，同樣在 per-mod 失敗處理之前中止整批。
    if not isinstance(mir, dict):
        return False
    return want == set(mir) and all(
        isinstance(mir[r], str)
        and value_hash(mir[r]) == recs[r]
        for r in want
    )


# ============================================================
# 命令：backfill-en（一次性全量 EN 落地）
# ============================================================
def cmd_backfill_en(args) -> int:
    """全量補齊 sources/en 並重建 hash baseline；逐 mod state-first，可續跑。"""
    if args.steamcmd is None:
        print("❌ backfill-en 需 --steamcmd 指定 steamcmd 路徑。", file=sys.stderr)
        return 1
    steamcmd = Path(args.steamcmd)
    install_dir = resolve_install_dir(args.install_dir)
    watchlist = load_watchlist()
    corpus_state = load_corpus_hashes()
    attribution = load_attribution_keys()
    items = watchlist.get("items", {})

    wids = [w for w in items if w != AS1_WORKSHOP_ID]
    ts_items = load_timestamps().get("items", {})
    gone = [w for w in wids if ts_items.get(w, {}).get("removed")]
    if gone and not args.only:
        print(f"跳過已下架 {len(gone)} 個（Workshop 已移除，抓不到）：{','.join(gone)}")
        wids = [w for w in wids if w not in gone]
    if args.only:
        wanted = {w.strip() for w in args.only.split(",") if w.strip()}
        wids = [w for w in wids if w in wanted]
    if args.limit:
        wids = wids[:args.limit]

    def is_done(wid: str) -> bool:
        return backfill_done(
            corpus_state.get("mods", {}).get(wid), EN_TEXT_DIR / f"{wid}.json")

    todo = [w for w in wids if args.force or not is_done(w)]
    print(f"backfill-en：watchlist {len(wids)} 個 mod，待處理 {len(todo)}"
          f"（已完成 {len(wids) - len(todo)}）")
    if not todo:
        return 0
    EN_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    pending_plans: list[dict] = []
    pending_updates: dict[str, dict] = {}
    pending_texts: dict[str, dict] = {}
    done = 0
    for i, wid in enumerate(todo, 1):
        mod_ids = items.get(wid, {}).get("mod_ids", [])
        print(f"[{i}/{len(todo)}] {wid} …", flush=True)
        item_dir = None
        try:
            item_dir = steamcmd_download(wid, steamcmd, install_dir)
            if item_dir is None:
                print(f"  ⚠️ 下載失敗，跳過（可重跑）：{wid}", file=sys.stderr)
                failed.append(wid)
                continue
            records = extract_corpus(item_dir)
            plan, new_state = build_layer_a_plan(
                wid, mod_ids, records, corpus_state, attribution)
            if not records:
                new_state["empty_corpus"] = True
            texts = {
                f"{kind}|{relpath}|{key}": value
                for kind, relpath, key, value in sorted(records)
                if kind in TEXT_BEARING_KINDS
            }
            # backfill 不開 issue；plan 與對應 state/mirror 一起持久化。`tracker.py issue`
            # 只在 issue 成功後套用 baseline，故不吞訊號，也不形成永久重試迴圈。
            if plan is not None:
                pending_plans.append(plan)
                pending_updates[wid] = new_state
                pending_texts[wid] = texts
                failed.append(wid)
                print(
                    f"  ⚠️ {wid} 真正上游語料有變，已排入 {BACKFILL_PLANS_JSON}；"
                    "執行 `tracker.py issue --in` 該檔即可完成 issue 與 baseline 遷移。",
                    file=sys.stderr,
                )
                continue

            corpus_state.setdefault("mods", {})[wid] = new_state
            corpus_state["schema_version"] = SCHEMA_VERSION
            corpus_state["extractor_schema"] = EXTRACTOR_SCHEMA
            write_json(EN_CORPUS_HASHES_JSON, corpus_state)
            if texts:
                write_json(EN_TEXT_DIR / f"{wid}.json", texts)
            else:
                (EN_TEXT_DIR / f"{wid}.json").unlink(missing_ok=True)
            kinds: dict[str, int] = {}
            for record in records:
                kinds[record[0]] = kinds.get(record[0], 0) + 1
            print(f"  ✓ {len(records)} 筆（鏡像 {len(texts)}）{kinds}")
            done += 1
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            print(f"  ⚠️ 處理失敗，跳過：{wid}：{type(exc).__name__}: {exc}",
                  file=sys.stderr)
            failed.append(wid)
        finally:
            if item_dir is not None and _within_scratch(item_dir):
                shutil.rmtree(item_dir, ignore_errors=True)

    if pending_plans:
        pending_ids = [plan["workshop_id"] for plan in pending_plans]
        write_json(BACKFILL_PLANS_JSON, {
            "generated_at": now_iso(),
            "plans": pending_plans,
            "ok_ids": pending_ids,
            "removed": [],
            "meta": {},
            "corpus_updates": pending_updates,
            "en_texts": pending_texts,
            "failed_ids": [],
        })
        print(f"待套用 issue plan → {BACKFILL_PLANS_JSON}")

    print(f"\n完成 {done}/{len(todo)}；失敗 {len(failed)}")
    if failed:
        print("失敗清單（重跑本指令即續傳）：" + ",".join(failed))
    return 1 if failed else 0


# ============================================================
# 命令：self-test（十五情境 mock 測試，assert-based）
# ============================================================
def cmd_self_test() -> int:
    print("=" * 60)
    print("self-test：十五情境 mock 測試")
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
    # 否則零 EN 落地日的 git add 會 pathspec 失敗、state 永遠 commit 不出去）。
    # 另驗 manifest 生成物有進 pathspec——排程刷 sources/en 卻不重生／不提交
    # SUPPORTED_MODS.md，「覆寫本體」欄就靜默過期而三道 gate 全綠（c8f5064 實例）。
    prod_paths = state_add_paths()
    for p in prod_paths:
        assert (PROJECT_ROOT / p).exists(), f"情境6b：生產 commit pathspec 不存在：{p}"
    for out in MANIFEST_OUTPUTS:
        assert out in prod_paths, f"情境6b：manifest 生成物未進 state commit pathspec：{out}"
    status = commit_state_with_retry(prod_paths, "test", branch="main",
                                     git=fake_git, sleep=lambda _s: None)
    assert status == COMMIT_OK, "情境6b：生產 pathspec 組合應可 add"
    print("  ✅ 情境6b 生產 commit pathspec（含 sources/en 與 manifest 生成物）存在且可 add")

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
        "corpus_hash": "deadbeef",
        # 寫死 8 而非 `EXTRACTOR_SCHEMA - N`：下次 bump 後相對算式會滑進 9，
        # 那條走 Lua 遷移而非靜默重建，本情境要驗的是「不可比 → 靜默重建」。
        "extractor_schema": 8,
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

    # 情境 11（schema 10）：JSON-only 邊界。Lua-only 變動不得進 corpus，也不得製造
    # 「可能過時」issue；非 JSON 根因由 issue 提交者向 MOD 作者回報。
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        lf = root / "42" / "media" / "lua" / "client" / "Sample.lua"
        lf.parent.mkdir(parents=True)
        lf.write_text('getText("IGUI_Old")\nbtn:setTitle("Old text")\n', encoding="utf-8")
        before = extract_corpus(root)
        lf.write_text('getText("IGUI_New")\nbtn:setTitle("New text")\n', encoding="utf-8")
        after = extract_corpus(root)
    assert before == after == [], f"情境11：Lua-only 變動進入 corpus：{before!r} → {after!r}"
    lua_state = {"mods": {"lua-only": {
        "corpus_hash": corpus_hash(before),
        "extractor_schema": EXTRACTOR_SCHEMA,
        "records": records_to_map(before),
    }}}
    lua_plan, _ = build_layer_a_plan("lua-only", ["LuaOnly"], after, lua_state, set())
    assert lua_plan is None, "情境11：Lua-only 變動不應開可能過時 issue"
    json_rel = "mods/M/42/media/lua/shared/Translate/EN/UI.json"
    legacy_state = {"mods": {"legacy-lua": {
        "corpus_hash": "schema9-hash",
        "extractor_schema": 9,
        "records": {
            f"translate_en|{json_rel}|UI_Test": value_hash("Old JSON"),
            "lua_gettext|mods/M/42/media/lua/client/X.lua|UI_Test": value_hash("UI_Test"),
            "lua_literal|mods/M/42/media/lua/client/X.lua|abc": value_hash("Old Lua"),
        },
    }}}
    same_json = [rec("translate_en", json_rel, "UI_Test", "Old JSON")]
    same_plan, _ = build_layer_a_plan(
        "legacy-lua", ["LegacyLua"], same_json, legacy_state, set())
    assert same_plan is None, "情境11：schema 9 舊 Lua records 被誤報成 removed"
    changed_json = [rec("translate_en", json_rel, "UI_Test", "New JSON")]
    changed_plan, _ = build_layer_a_plan(
        "legacy-lua", ["LegacyLua"], changed_json, legacy_state, set())
    assert changed_plan is not None, "情境11：schema 9→10 遷移吞掉同輪真 JSON 變更"
    print("  ✅ 情境11 JSON-only：Lua-only 變動不進 corpus、不開 issue")

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
    print("  ✅ 情境12 coverage 鍵形正規化（stem/canon/namespace 保留）")

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

    # --- 情境15（schema 9）：script 物品顯示名缺口（#221）---------------------
    # module 沒進 record 時 coverage 完全看不到這一類缺口：受影響的 mod 顯示
    # en_gap=0、甚至不出現在報表裡，而玩家在物品欄看到一整批英文物品名
    # （#184 是玩家附截圖才發現的個案；粗篩下限 6,758 鍵／108 個 mod）。
    with tempfile.TemporaryDirectory() as td:
        sdir = Path(td) / "common" / "media" / "scripts"
        sdir.mkdir(parents=True)
        (sdir / "items.txt").write_text(
            "module Base\n{\n"
            "    item Hammer\n    {\n        DisplayName = Big Hammer,\n    }\n"
            "    craftRecipe Make Hammer\n    {\n        Output { item Base.Hammer, }\n    }\n"
            "}\n"
            "module FrockinSplendor {\n"
            "    imports\n    {\n        Base\n    }\n"
            "    item Hammer {\n        DisplayName = Fancy Hammer,\n    }\n"
            "}\n"
            "item Orphan\n{\n    DisplayName = No Module,\n}\n"
            "module Dangling\n    Something = 1,\n{\n"
            "    item Late\n    {\n        DisplayName = Late Item,\n    }\n"
            "}\n"
            # 行內註解真實存在（`module Rotators /* Legacy */`、`item X /* Spawn */`）：
            # 連註解一起收進 key 會拼出不存在的 fullType＝虛報缺口（實測 67 筆／6 mod）
            "module Rotators /* Legacy */\n{\n"
            "    item Wheel /* Spawn */\n    {\n        DisplayName = Big Wheel,\n    }\n"
            "}\n"
            # `//` 形註解與「名字整個被註解吃掉」兩條路徑
            "module Slashed // legacy\n{\n"
            "    item Bolt // spawn\n    {\n        DisplayName = Steel Bolt,\n    }\n"
            "    item /* nameless */\n    {\n        DisplayName = Nameless,\n    }\n"
            "}\n"
            # `module X` 與 `{` 之間空行是常見寫法，**不得**作廢 pending
            "module Spaced\n\n{\n"
            "    item Nut\n    {\n        DisplayName = Hex Nut,\n    }\n"
            "}\n"
            # 成對 `/* … */` 內的 item 在引擎眼中不存在（ScriptParser.stripComments）；
            # 抽出來且落在 module 內就是**假缺口**（實測 Ahu_Blunt.txt 的 Sledgehammer_Broken）
            "module Ghosted\n{\n"
            "/*\n"
            "    item Commented\n    {\n        DisplayName = Should Not Exist,\n    }\n"
            "*/\n"
            "    item Real\n    {\n        DisplayName = Real Item,\n    }\n"
            "}\n"
            # 未閉合 `/*` 引擎**不刪**（lastIndexOf(\"*/\") == -1 → while 不進、原文保留），
            # 故其後的 item 照樣要抽到——遮到檔尾會憑空吃掉整批真 item
            "/* 這個註解沒有結尾\n"
            "module Unclosed\n{\n"
            "    item Kept\n    {\n        DisplayName = Kept Item,\n    }\n"
            "}\n"
            # 引擎按字元逗號 token、不按行：同列 `item X { … }` 與同列多 property 都合法，
            # 逐行版會整個漏掉（實測 192 筆／3 個 mod 的 item 連 record 都沒有＝假零缺口）
            "module Inline\n{\n"
            "    item Jacket01 { DisplayName = Inline Jacket, Hidden = true }\n"
            "    item Multi\n    {\n        Type = Normal, DisplayName = Multi Prop,\n    }\n"
            # 雙等號：`Item.Load` 取 split(\"=\")[1]（空字串）→ 引擎顯示空白，不是 `= Vepr`
            "    item DoubleEq\n    {\n        DisplayName == Vepr Mag,\n    }\n"
            # 沒有尾逗號＝引擎遇 `}` 直接 return，Value 從未建立 → 該 property 不套用
            "    item NoComma\n    {\n        DisplayName = Never Applied\n    }\n"
            "}\n"
            # 同一行第二個 item（`}item X {`）與巢狀層的 item：前者是真物品、後者不是
            # （ParseScriptPP 只把 module 頂層 token 交給 item bucket），depth gate 分得開
            "module Tight\n{\n"
            "    item First\n    {\n        DisplayName = First Blade,\n    }item Second\n"
            "    {\n        DisplayName = Second Blade,\n    }\n"
            "    craftRecipe Forge\n    {\n"
            "        inputs\n        {\n            item PhantomInput\n            {\n"
            "                DisplayName = Should Not Be A Product,\n            }\n"
            "        }\n    }\n"
            "}\n",
            encoding="utf-8",
        )
        recs = _iter_script_records(Path(td))
        dn = {r[2]: r[3] for r in recs if r[0] == "script_item_dn"}
        # 同名 item 分屬兩個 module＝兩個不同物品；只記裸名會塌成一筆而互相遮蔽
        assert dn.get("Base.Hammer") == "Big Hammer", f"情境15：module 歸屬錯誤：{dn}"
        assert dn.get("FrockinSplendor.Hammer") == "Fancy Hammer", \
            f"情境15：同檔第二個 module 未各自歸屬（不能只取檔內第一個）：{dn}"
        # module 外的 item 標記為不可判定；**不得**回退成裸名——裸名混進 fullType 集後，
        # 「解析漏判」與「該物品真的不存在」就再也分不開＝缺口又隱形
        assert dn.get("?.Orphan") == "No Module", f"情境15：module 外 item 未標記：{dn}"
        # `module Dangling` 沒接區塊 → pending 必須立刻作廢，否則後面第一個頂層 `{`
        # 會被誤認成它的起點，產出**看似有效卻錯誤**的 fullType（比未解出更糟）
        assert dn.get("?.Late") == "Late Item", f"情境15：懸空 module 標頭被誤配：{dn}"
        assert dn.get("Rotators.Wheel") == "Big Wheel", \
            f"情境15：區塊名／module 名的行內註解未剝除（會拼出不存在的 fullType）：{dn}"
        # 同一行第二個 item 必須抽到（行首錨定版會漏；實測 workshop 命中 1 筆）
        assert dn.get("Tight.First") == "First Blade" and dn.get("Tight.Second") == "Second Blade", \
            f"情境15：同一行第二個 item 漏抽（`}}item X {{`）：{dn}"
        # 巢狀層的 item 不是物品定義，拼成 fullType 就是 phantom（無 gate 會多收 6,190 筆）
        assert not any("PhantomInput" in r[2] for r in recs), \
            f"情境15：巢狀層的 item 被誤收成物品：{[r[2] for r in recs if 'Phantom' in r[2]]}"
        # `//` 依 CreateFromTokenPP 屬於名字的一部分，不得剝除
        assert dn.get("Slashed // legacy.Bolt // spawn") == "Steel Bolt", \
            f"情境15：`//` 被當成註解剝掉（引擎不認 `//`，剝了就偏離實際 fullType）：{dn}"
        # 配方名走 getRecipeName(裸區塊名)；加前綴會讓 verify_dist [16] 的上游實據對不上
        assert "Ghosted.Commented" not in dn and "Should Not Exist" not in dn.values(), \
            f"情境15：跨行 /* */ 內的 item 被抽成 record（會變成假缺口）：{dn}"
        assert dn.get("Ghosted.Real") == "Real Item", \
            f"情境15：註解遮蔽把同 module 的真 item 一起吃掉了：{dn}"
        assert dn.get("Unclosed.Kept") == "Kept Item", \
            f"情境15：未閉合 /* 被遮到檔尾（引擎不刪，這裡也不該刪）：{dn}"
        rel = "common/media/scripts/items.txt"
        assert ("script_craftRecipe", rel, "Make Hammer", "Make Hammer") in recs, \
            "情境15：craftRecipe 不得帶 module 前綴"
        assert all("." in r[2] for r in recs if r[0] == "script_item"), \
            "情境15：script_item 一律帶 module 段"
        assert not any(r[2].endswith(".") or r[2] == "?." for r in recs if r[0] == "script_item"), \
            f"情境15：`item /* x */` 解不出名字時不得記成空鍵：{[r[2] for r in recs]}"
        assert dn.get("Spaced.Nut") == "Hex Nut", \
            f"情境15：`module X` 與 `{{` 之間的空行被誤判為作廢：{dn}"
        # 引擎按字元逗號 token、不按行：同列 `{`、同列多 property 都要抽得到
        assert dn.get("Inline.Jacket01") == "Inline Jacket", \
            f"情境15：同列 `item X {{ … }}` 整個被漏掉（假零缺口的來源）：{dn}"
        assert dn.get("Inline.Multi") == "Multi Prop", \
            f"情境15：同列多 property 的 DisplayName 抽不到（regex 錨在行首）：{dn}"
        # `DisplayName == X` 的 split("=")[1] 是空字串 → 引擎顯示空白，不得抽成 `= X`
        assert "Inline.DoubleEq" not in dn, \
            f"情境15：雙等號的空值被誤抽成整段 RHS：{dn.get('Inline.DoubleEq')!r}"
        # 無尾逗號的 property 引擎不套用（遇 `}` 直接 return，Value 從未建立）
        assert "Inline.NoComma" not in dn, \
            f"情境15：無尾逗號的 DisplayName 仍被收錄（引擎其實不套用）：{dn.get('Inline.NoComma')!r}"
        assert ("script_item", rel, "Inline.NoComma", "Inline.NoComma") in recs, \
            "情境15：item 本身仍須有 record（只是沒有 DisplayName）"

    # 大括號配對向上失準（行尾註解／屬性值裡的裸 `{`）：depth 回不到 0 會讓後續 module
    # 標頭永遠不被辨識，其 item 沿用前一個 module 名而拼出**看似有效卻錯誤**的 fullType
    # （錯 module 可能剛好命中另一個已出貨鍵 → 真缺口再次靜默）。必須退化成可見盲區。
    poisoned = _module_by_line([
        "module A",
        "{",
        "    item X",
        "    {",
        "        Tags = Foo, // 這裡有個沒配對的 {",
        "    }",
        "}",
        "module B",
        "{",
        "    item Y",
        "    {",
        "    }",
        "}",
    ])
    assert poisoned[10] is None, \
        f"情境15：大括號失準後 module B 的 item 被錯歸屬（應退化為 UNKNOWN_MODULE）：{poisoned}"

    # record id 的分支 tag：決定同鍵在 common 與版本夾都定義時誰勝出
    assert _branch_tag("script_item_dn|mods/M/common/media/scripts/i.txt|Base.X") == "common"
    assert _branch_tag("script_item_dn|mods/M/42.15/media/scripts/i.txt|Base.X") == "42.15"
    assert _branch_tag("script_item_dn|generated/i.txt|Base.X") == "", "情境15：非分支路徑應回空"

    # 精確比對：前綴死鍵與無 module 段的鍵都不算覆蓋（getItemNameFromFullType 查不到）
    assert _is_runtime_item_key("Base.Dress"), "情境15：裸 fullType 應算覆蓋"
    assert not _is_runtime_item_key("ItemName_Base.Dress"), "情境15：B41 前綴死鍵不算覆蓋"
    assert not _is_runtime_item_key("Dress"), "情境15：無 module 段不可能是 fullType"
    dn_keys = {"Base.Hammer", "Base.Axe", "Base.Dress", "Base.Plain", "?.Orphan", "Base.NoText"}
    dn_text = {"Base.Hammer": "Big Hammer", "Base.Axe": "Fire Axe", "Base.Dress": "Red Dress",
               "Base.Plain": "Plain", "?.Orphan": "Orphan"}
    st = _item_dn_stats(EXTRACTOR_SCHEMA, dn_keys, dn_text, {"Base.Hammer"}, {"Base.Axe"})
    assert st["gap"] == {"Base.Dress"}, f"情境15：缺口判定錯誤（已出貨/vanilla/id-only 未扣）：{st}"
    assert st["idonly"] == 1, f"情境15：DisplayName 等於 item id 未扣除：{st}"
    assert st["blind"] == 2 and st["why"], f"情境15：盲區未計數或無可讀原因：{st}"
    # `kinds` 是 cmd_coverage 分流訊息的依據（schema／鏡像缺值可靠重抽消除，`?.` 不行）；
    # **每條回傳路徑都必須帶它**，缺一即 cmd_coverage 在混合 schema 實跑時 KeyError
    assert st["kinds"] == {"unknown_module", "mirror"}, f"情境15：kinds 分類錯誤：{st}"
    # 已出貨／vanilla 的鍵即使 DisplayName 等於 item id 也不得計入 idonly，否則報表的
    # 「另扣除 N 筆」會虛胖成「所有 id-only 鍵」而失去意義
    same = _item_dn_stats(EXTRACTOR_SCHEMA, {"Base.Same"}, {"Base.Same": "Same"},
                          {"Base.Same"}, set())
    assert same["gap"] == set() and same["idonly"] == 0, f"情境15：idonly 計數虛胖：{same}"
    # 舊 schema 的 key 沒有 module → **全判不可判定**，不得當成零缺口（backfill 會略過
    # 已下架項目、失敗項也保留舊 state，故混合 schema 必然存在）
    for stale in (ITEM_MODULE_SCHEMA - 1, None, "9"):
        old = _item_dn_stats(stale, dn_keys, dn_text, {"Base.Hammer"}, {"Base.Axe"})
        assert old["gap"] == set() and old["blind"] == len(dn_keys), \
            f"情境15：schema={stale} 應全判不可判定：{old}"
        assert old["kinds"] == {"schema"}, f"情境15：舊 schema 的 kinds 缺失：{old}"
    # 沒有 script 物品的舊基準 mod 不是盲區——對它們報「不可判定」會用數百筆雜訊
    # 把真正的 `?.` 與鏡像缺值擠出預覽（混合 schema 是常態，這種 mod 佔多數）
    empty = _item_dn_stats(ITEM_MODULE_SCHEMA - 1, set(), {}, set(), set())
    assert empty["why"] is None and empty["blind"] == 0 and empty["kinds"] == set(), \
        f"情境15：無 script 物品的舊基準 mod 被誤列為盲區：{empty}"
    # 上游 property 沒收尾逗號時，引擎的 split("=")[1] 會把下一欄名稱吃進值——那串垃圾
    # 不能當翻譯來源，須計為不可判定且**不得**被歸類成「重抽即消除」
    bad = _item_dn_stats(EXTRACTOR_SCHEMA, {"Base.Junk"},
                         {"Base.Junk": "junkname\n\t\tIcon"}, set(), set())
    assert bad["gap"] == set() and bad["kinds"] == {"malformed"}, \
        f"情境15：上游 DisplayName 夾帶下一欄未計為 malformed 不可判定：{bad}"
    # 上游把 DisplayName 留空＝沒有真英文名可譯，與「值等於 item id」同一條扣除線；
    # 判定必須留在共用函式，consumer 自行加濾網會讓 dn_gap 與 _gap 分岔。
    blank = _item_dn_stats(EXTRACTOR_SCHEMA, {"Base.Blank"}, {"Base.Blank": "  "},
                           set(), set())
    assert blank["gap"] == set() and blank["idonly"] == 1 and blank["kinds"] == set(), \
        f"情境15：空白 DisplayName 未併入 idonly 扣除：{blank}"
    # backfill 續跑判準：只看「檔案存在」會在鏡像已新、state 仍舊時判成永久完成，
    # 而 coverage 以舊 state 當宇宙 → 新增/改動的 item 既不進 gap 也不進 blind（#221）。
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "1.json"
        rid_a = "translate_en|mods/M/42.20/media/lua/shared/Translate/EN/UI.json|UI_A"
        rid_b = "script_item_dn|mods/M/42.20/media/scripts/i.txt|Base.X"
        texts = {rid_a: "Alpha", rid_b: "Big X"}
        good = {"extractor_schema": EXTRACTOR_SCHEMA, "records": records_to_map([
            ("translate_en", "mods/M/42.20/media/lua/shared/Translate/EN/UI.json", "UI_A", "Alpha"),
            ("script_item_dn", "mods/M/42.20/media/scripts/i.txt", "Base.X", "Big X"),
            ("script_item", "mods/M/42.20/media/scripts/i.txt", "Base.X", "Base.X"),
        ])}
        assert not backfill_done(good, mp), "情境15：鏡像缺檔不得判完成"
        write_json(mp, texts)
        assert backfill_done(good, mp), "情境15：state 與鏡像一致卻判未完成"
        # 值變、鍵集不變——只比鍵集會漏掉這種（上游只改文本的情形佔多數）
        write_json(mp, {**texts, rid_b: "Bigger X"})
        assert not backfill_done(good, mp), "情境15：值 hash 不符仍判完成（只比了鍵集）"
        # 鍵集不符
        write_json(mp, {rid_a: "Alpha"})
        assert not backfill_done(good, mp), "情境15：鏡像少一個 rid 仍判完成"
        assert not backfill_done({**good, "extractor_schema": EXTRACTOR_SCHEMA - 1}, mp), \
            "情境15：舊 schema 不得判完成"
        # 純 script_item/craftRecipe 的 mod 合法無鏡像檔；語料整個為空亦然
        only_ids = {"extractor_schema": EXTRACTOR_SCHEMA,
                    "records": {"script_item|mods/M/42.20/media/scripts/i.txt|Base.X": "aa"}}
        assert backfill_done(only_ids, Path(td) / "nope.json"), \
            "情境15：全是不進鏡像的 kind 時無鏡像檔是合法完成狀態"
        assert backfill_done({"extractor_schema": EXTRACTOR_SCHEMA, "records": {},
                              "empty_corpus": True}, Path(td) / "nope.json"), \
            "情境15：empty_corpus 是合法完成狀態"
        # 上游把文本全數移除時，殘留的舊鏡像必須讓判定退回未完成（否則永遠不會被清）
        assert not backfill_done(only_ids, mp), \
            "情境15：state 宣告無文本卻有殘留舊鏡像，仍被判完成"
        # 新增的容器／rid 守衛：壞損 state 被判「已完成」會鎖死修復路徑——prep 的
        # `_unchecked` 叫人跑 backfill-en，這裡又跳過，不加 `--force` 永遠修不好。
        # **每條的其餘條件都要與「會判完成」的形狀一致**，守衛才是唯一的失敗原因：
        #   * 容器守衛：`records` 非 dict 且**鏡像不存在**——退化成 `recs or {}` 時
        #     `bool(recs)` 為真、`want` 為空，就會回 True（判完成）。
        #   * rid 守衛：壞 rid 是 text-bearing、且**鏡像內容與它完全對齊**——退化成不驗
        #     形狀時 `want == set(mir)` 且 hash 相符，就會回 True。
        # 外層容器也要驗：`st` 非 dict 會在 `.get()` 拋 AttributeError；鏡像頂層為
        # `null` 會在 `set(mir)` 拋 TypeError。兩者都發生在 `cmd_backfill_en` 建 `todo`
        # 時＝per-mod 失敗處理之前，整批直接中止。
        for _bad_st in (None, ["x"], "s", 3):
            assert not backfill_done(_bad_st, mp), f"情境15：st={_bad_st!r} 竟判完成"
        _nulm = Path(td) / "nullmirror.json"
        _nulm.write_text("null", encoding="utf-8")
        assert not backfill_done(good, _nulm), "情境15：鏡像頂層為 null 竟判完成（會拋 TypeError）"
        _nope = Path(td) / "nope2.json"
        assert not backfill_done({"extractor_schema": EXTRACTOR_SCHEMA,
                                  "records": ["not", "a", "dict"]}, _nope), \
            "情境15：records 非 dict 竟判完成（壞損 state 會被永久略過）"
        for _bad_rid in ("translate_en|only-two-segments",
                         f"bogus_kind|mods/M/42.20/media/scripts/i.txt|Base.X",
                         "translate_en|mods/M/42.20/media/lua/shared/Translate/EN/UI.json|"):
            _bp = Path(td) / "badrid.json"
            write_json(_bp, {_bad_rid: "V"})
            assert not backfill_done({"extractor_schema": EXTRACTOR_SCHEMA,
                                      "records": {_bad_rid: value_hash("V")}}, _bp), \
                f"情境15：壞損 rid 竟判完成（{_bad_rid!r}）"
        # schema 10 對歷史 Lua kind fail-closed，即使 state/mirror 彼此一致也必須重抽清理。
        write_json(mp, {**texts, "lua_literal|mods/M/42.20/media/lua/a.lua|abc": "Old Lua"})
        polluted = {"extractor_schema": EXTRACTOR_SCHEMA, "records": {
            **good["records"],
            "lua_literal|mods/M/42.20/media/lua/a.lua|abc": value_hash("Old Lua"),
        }}
        assert not backfill_done(polluted, mp), "情境15：schema 10 Lua 污染被判完成"
        write_json(mp, texts)
        plus_script = {**good, "records": {
            **good["records"],
            "script_item|mods/M/42.20/media/scripts/i.txt|Base.New": "cc",
        }}
        assert backfill_done(plus_script, mp), \
            "情境15：合法非鏡像 script kind 增量被誤判未完成"
        # state↔鏡像 coherence：鏡像領先（backfill 中斷殘跡）會讓宇宙少鍵、缺口低報成零
        assert mirror_incoherent_rids(good["records"], {**texts, "script_item_dn|p|Base.New": "N"}) \
            == {"script_item_dn|p|Base.New"}, "情境15：未偵測到鏡像領先 state"
        assert mirror_incoherent_rids(good["records"], texts) == set(), \
            "情境15：一致的 state/鏡像被誤報為不一致"
        assert mirror_incoherent_rids(plus_script["records"], texts) == set(), \
            "情境15：state 有而鏡像沒有的合法非鏡像 kind 被誤報"
        # **同 rid 值 hash 不符**是 state-first 唯一還開著的窗口（鏡像寫入失敗／人工改檔），
        # 只驗鍵集會放行過期英文當翻譯來源，且 id-only／malformed 判定也會用錯值。
        assert mirror_incoherent_rids(good["records"], {**texts, rid_b: "Bigger X"}) == {rid_b}, \
            "情境15：同 rid 值 hash 不符未被偵測（只比了鍵集）"
        assert mirror_incoherent_rids(good["records"], {**texts, rid_b: 123}) == {rid_b}, \
            "情境15：鏡像值非字串未被偵測"
    # winner 語意：勝出 rid 由 state 決定（同 owner 內 common 先、版本夾後），勝出者缺值
    # 即整鍵不入——**絕不回退 common 舊值**（否則拿低優先序的過期英文當翻譯來源）。
    # coverage 側沒有其他測試碰到這支 helper，改壞了 prep 的 4s/4t 才會紅，太遠。
    _c = "mods/M/common/media/scripts/i.txt"
    _v = "mods/M/42.20/media/scripts/i.txt"
    _recs = {f"script_item_dn|{_c}|Base.X": "h1", f"script_item_dn|{_v}|Base.X": "h2"}
    _eff = resolve_effective_branches(_recs)
    assert winning_dn_text(_recs, {f"script_item_dn|{_c}|Base.X": "Common",
                                   f"script_item_dn|{_v}|Base.X": "Versioned"},
                           _eff) == {("M", "Base.X"): "Versioned"}, \
        "情境15：版本夾未疊在 common 之上"
    assert winning_dn_text(_recs, {f"script_item_dn|{_c}|Base.X": "Common"}, _eff) == {}, \
        "情境15：勝出 rid 缺值卻回退用 common 的舊值"
    assert winning_dn_text(_recs, {f"script_item_dn|{_c}|Base.X": "Common",
                                   f"script_item_dn|{_v}|Base.X": 123}, _eff) == {}, \
        "情境15：勝出 rid 值非字串卻回退"
    # 同 wid 兩個 mod root 各自獨立（跨 root 選單一 winner 會讓 A 遮掉 B 的缺值判定）
    _n = "mods/N/42.20/media/scripts/i.txt"
    assert winning_dn_text({**_recs, f"script_item_dn|{_n}|Base.X": "h3"},
                           {f"script_item_dn|{_v}|Base.X": "V",
                            f"script_item_dn|{_n}|Base.X": "N"},
                           resolve_effective_branches(
                               {**_recs, f"script_item_dn|{_n}|Base.X": "h3"})) == {
        ("M", "Base.X"): "V", ("N", "Base.X"): "N"}, "情境15：owner 未分開"
    print("  ✅ 情境15 script 物品名 fullType（多 module／懸空標頭／盲區計數／精確比對／winner）")

    print("\n✅ self-test 十五情境全通過。")
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
  uv run scripts/tracker.py self-test              # 十五情境 mock 測試
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
