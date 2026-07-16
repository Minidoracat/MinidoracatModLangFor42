# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
tracker.py — MinidoracatModLangFor42 雙上游追蹤器（PZ B42 如一模組翻譯繁中版）

用途：排程（每日）偵測兩層上游變更，確有文本 diff 才開/更新 GitHub issue，跨 cron 保存去重狀態。
  layer-B（主力）：As1 包 3556540080 新 42.19 樹 vs 本 repo sources/ → 有 diff 開「待同步」issue。
  layer-A（品保）：原始 mod 全語料 kind|相對路徑|鍵|英文值 hash vs baseline → 分類新增/刪除/修改，開「可能過時」issue。

設計要點：
  * 純標準函式庫（urllib / subprocess / hashlib）→ 供 `uv run scripts/tracker.py` 直接執行，CI 免裝依賴。
  * API client 免 key 為主（研究實證端點無 key 參數）；STEAM_API_KEY 為設定選項、非 429 解藥（附加而已）。
  * 交易順序：取數 → diff → 開/更 issue → 最後 commit 成功子集 state；--dry-run 保證零 issue 零 commit。
  * 核心邏輯（diff / issue 冪等 / git 重試）皆以可注入依賴實作，供內建 self-test 八情境 mock 驗證。

命令（uv run scripts/tracker.py <命令>）：
  gen-watchlist  由 sources/mods/*/metadata.json 支持清單生成 tracker-state/watchlist.json（固定含 As1；支持清單變動後重跑）
  run            預設：check → diff → issue → commit 全流程（--dry-run 只印計畫）
  check          僅打 API 查時間戳，寫 changed 清單 artifact（workflow check job；無寫權限）
  diff           讀 changed，下載+裁剪+抽取+diff，寫 diffs artifact（workflow download job；無 GitHub 權限）
  issue          讀 diffs，列 open issue 冪等開/更，commit 成功子集 state（workflow issue+state job）
  self-test      內建八情境 mock 測試
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

SOURCES = PROJECT_ROOT / "sources"
ATTRIBUTION_INDEX_JSON = SOURCES / "attribution_index.json"

# schema 版本（狀態格式演進時 bump；讀取時可據此遷移）
SCHEMA_VERSION = 1
# layer-A 抽取器 schema（media/scripts item/recipe 名為 basic 正則版，改抽取規則時 bump）
# =2：record identity 由 basename 改為相對路徑（同 basename 不同目錄不再互撞）
EXTRACTOR_SCHEMA = 2

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


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


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
# PZ script item/recipe 區塊名 basic 正則（extractor_schema=1）：抓 <keyword> <name>
_SCRIPT_BLOCK_RE = re.compile(r"\b(item|craftRecipe|recipe|vehicle|fixing)\s+([\w.]+)")


def _iter_translate_records(mod_dir: Path, lang: str) -> list[tuple[str, str, str, str]]:
    """抽取 media/**/Translate/<lang>/*.json 的 (kind, relpath, key, value)。PZ 為扁平 {鍵:值}。"""
    records: list[tuple[str, str, str, str]] = []
    for jf in sorted(mod_dir.rglob("*.json")):
        if jf.is_symlink():  # 跳過 symlink，避免逸出下載目錄
            continue
        parts = jf.parts
        if "Translate" not in parts:
            continue
        ti = parts.index("Translate")
        if ti + 1 >= len(parts) or parts[ti + 1] != lang:
            continue
        try:
            data = load_json(jf)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  ⚠️ 壞 JSON 跳過：{jf}（{exc}）", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        # record identity 帶相對路徑（同 basename 不同目錄不互撞；EXTRACTOR_SCHEMA=2）
        relpath = jf.relative_to(mod_dir).as_posix()
        for key in sorted(data):
            records.append((f"translate_{lang.lower()}", relpath, key, str(data[key])))
    return records


def _iter_script_records(mod_dir: Path) -> list[tuple[str, str, str, str]]:
    """抽取 media/scripts/**/*.txt 的 item/recipe 區塊名（basic 正則、value=名本身）。"""
    records: list[tuple[str, str, str, str]] = []
    scripts_dir = None
    for cand in mod_dir.rglob("scripts"):
        if cand.is_dir() and cand.parent.name == "media":
            scripts_dir = cand
            break
    if scripts_dir is None:
        return records
    for tf in sorted(scripts_dir.rglob("*.txt")):
        if tf.is_symlink():  # 跳過 symlink，避免逸出下載目錄
            continue
        try:
            text = tf.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        rel = tf.relative_to(scripts_dir).as_posix()
        for kw, name in _SCRIPT_BLOCK_RE.findall(text):
            records.append((f"script_{kw}", rel, name, name))
    return records


def extract_corpus(mod_dir: Path, lang: str = "EN") -> list[tuple[str, str, str, str]]:
    """layer-A 全語料：Translate/<lang> 為主 + media/scripts item/recipe 名（basic）。"""
    return _iter_translate_records(mod_dir, lang) + _iter_script_records(mod_dir)


def records_to_map(records: list[tuple[str, str, str, str]]) -> dict[str, str]:
    """record 清單 → {record_id: value_hash}；record_id = kind|relpath|key。重複 ID 報錯不覆寫。"""
    out: dict[str, str] = {}
    for kind, relpath, key, value in records:
        rid = f"{kind}|{relpath}|{key}"
        if rid in out:
            raise ValueError(f"重複 record ID（拒絕覆寫，恐掩蓋上游變更）：{rid}")
        out[rid] = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
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


def read_repo_sources_cn() -> list[tuple[str, str, str, str]]:
    """讀本 repo sources/mods/*/CN + sources/_unsorted/CN 的 CN 語料（layer-B 基準）。"""
    records: list[tuple[str, str, str, str]] = []
    cn_dirs: list[Path] = []
    mods_dir = SOURCES / "mods"
    if mods_dir.is_dir():
        for mod_dir in sorted(mods_dir.iterdir()):
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
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    out = proc.stdout + proc.stderr
    # 三項全過才算成功；任一不滿足回 None（steamcmd rc 不可靠，故三重把關）
    if proc.returncode != 0:
        return None
    if STEAMCMD_SUCCESS_SIGNAL not in out:
        return None
    if not (content.is_dir() and any(content.iterdir())):
        return None
    return content


def trim_download(item_dir: Path) -> None:
    """裁剪：只留 media/**/Translate/ 與 media/scripts/ 文本，其餘刪除（縮小 artifact）。"""

    def keep(path: Path) -> bool:
        parts = path.parts
        return "Translate" in parts or ("media" in parts and "scripts" in parts)

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
) -> tuple[list[str], list[str], dict[str, dict]]:
    """回傳 (時間戳變動需下載的 ids, 已下架 ids, 每 id 的 meta 更新)。"""
    items = ts.get("items", {})
    changed: list[str] = []
    removed: list[str] = []
    meta: dict[str, dict] = {}
    for wid in ids:
        prev = items.get(wid, {})
        entry = {
            "last_attempt": now_iso(),
            "last_success": prev.get("last_success"),
            "time_updated": prev.get("time_updated"),
            "removed": prev.get("removed", False),
        }
        detail = details.get(wid)
        if detail is None:
            meta[wid] = entry  # 查無回應：僅記 last_attempt
            continue
        result = int(detail.get("result", 0))
        entry["last_result"] = result  # 記錄本輪 API result 供診斷
        if result == RESULT_NOT_FOUND:
            entry["removed"] = True
            meta[wid] = entry
            removed.append(wid)
            continue
        if result != RESULT_OK:
            print(f"  ⚠️ 非預期 API result={result}（id={wid}），本輪略過", file=sys.stderr)
            meta[wid] = entry
            continue
        new_tu = int(detail.get("time_updated", 0))
        entry["removed"] = False
        if prev.get("time_updated") != new_tu:
            changed.append(wid)
        entry["_new_time_updated"] = new_tu  # 成功處理後才寫入 time_updated
        meta[wid] = entry
    return changed, removed, meta


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
    lines = [
        marker,
        f"## 待同步：As1 包更新（Workshop {AS1_WORKSHOP_ID}）",
        "",
        "As1「[B42]統一模組漢化」新 42.19 CN 樹與本 repo `sources/` 現況存在差異，需重跑拆分/build 管線同步。",
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
    changed, removed, meta = classify_changes(ids, details, ts)
    print(f"  時間戳變動：{len(changed)}；已下架：{len(removed)}")

    if args.dry_run:
        print("\n[dry-run] 不下載、不開 issue、不 commit。計畫動作：")
        for wid in changed[:20]:
            print(f"  - 會下載並 diff：{wid}")
        if len(changed) > 20:
            print(f"  ... 另有 {len(changed) - 20} 個")
        for wid in removed[:20]:
            print(f"  - 標記 removed（不下載）：{wid}")
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

    plans, ok_ids, corpus_updates, failed_ids = _diff_changed(
        changed, watchlist, steamcmd, install_dir, corpus_state, attribution
    )
    if changed and not ok_ids:
        print(f"❌ {len(changed)} 個變動全部處理失敗，中止（state 不推進、下輪自癒）。", file=sys.stderr)
        return 1
    if failed_ids:
        print(f"  ⚠️ 部分失敗 {len(failed_ids)}/{len(changed)}：{', '.join(failed_ids[:20])}", file=sys.stderr)
    gh = GhClient()
    index = index_issues(gh.list_tracker_issues())
    for plan in plans:
        action = apply_issue_plan(plan, index, gh, dry_run=False)
        print(f"  issue {plan['type']}/{plan['workshop_id']} → {action}")

    # 提交成功子集 state（僅成功處理者推進 last_success/time_updated）
    _persist_state(ts, meta, ok_ids, removed, corpus_state, corpus_updates)
    status = commit_state_with_retry(
        [str(TIMESTAMPS_JSON.relative_to(PROJECT_ROOT)),
         str(EN_CORPUS_HASHES_JSON.relative_to(PROJECT_ROOT))],
        f"chore(tracker): 更新追蹤器狀態 {now_iso()}",
    )
    if status == COMMIT_FAILED:
        print("❌ state commit/push 失敗（下輪自癒）。", file=sys.stderr)
        return 1
    print(f"\n完成：issue {len(plans)} 筆、state {'已提交' if status == COMMIT_OK else '無變更'}。")
    return 0


def _diff_changed(changed, watchlist, steamcmd, install_dir, corpus_state, attribution):
    """對變動 ids 下載+裁剪+抽取+diff，回 (plans, 成功 ids, corpus 更新, 失敗 ids)。真實模式用。
    下載失敗/偽成功、或抽取語料為空的 ID 皆不進 ok_ids（不推進 time_updated、不建空 baseline）。"""
    plans: list[dict] = []
    ok_ids: list[str] = []
    corpus_updates: dict[str, dict] = {}
    failed_ids: list[str] = []
    items = watchlist.get("items", {})
    for wid in changed:
        item_dir = steamcmd_download(wid, steamcmd, install_dir)
        if item_dir is None:
            print(f"  ⚠️ 下載失敗/已下架/偽成功，跳過（不推進狀態）：{wid}", file=sys.stderr)
            failed_ids.append(wid)
            continue
        trim_download(item_dir)
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
            if not new_records:
                print(f"  ⚠️ 語料解析為空，跳過（不建空 baseline、不推進狀態）：{wid}", file=sys.stderr)
                failed_ids.append(wid)
                continue
            mod_ids = items.get(wid, {}).get("mod_ids", [])
            plan, new_state = build_layer_a_plan(wid, mod_ids, new_records, corpus_state, attribution)
            corpus_updates[wid] = new_state
            if plan:
                plans.append(plan)
        ok_ids.append(wid)
    return plans, ok_ids, corpus_updates, failed_ids


def _persist_state(ts, meta, ok_ids, removed, corpus_state, corpus_updates):
    """把成功子集寫回狀態物件並落盤。"""
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
    changed, removed, meta = classify_changes(ids, details, ts)
    out = {
        "generated_at": now_iso(),
        "changed": changed,
        "removed": removed,
        "meta": meta,
    }
    out_path = Path(args.out) if args.out else TRACKER_STATE / "_changed.json"
    write_json(out_path, out)
    print(f"✅ check：變動 {len(changed)}、下架 {len(removed)} → {out_path}")
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
    plans, ok_ids, corpus_updates, failed_ids = _diff_changed(
        changed_ids, watchlist, Path(args.steamcmd),
        install_dir, corpus_state, attribution,
    )
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
        corpus_state, diffs.get("corpus_updates", {}),
    )
    status = commit_state_with_retry(
        [str(TIMESTAMPS_JSON.relative_to(PROJECT_ROOT)),
         str(EN_CORPUS_HASHES_JSON.relative_to(PROJECT_ROOT))],
        f"chore(tracker): 更新追蹤器狀態 {now_iso()}",
    )
    if status == COMMIT_FAILED:
        print("❌ state commit/push 失敗（下輪自癒）。", file=sys.stderr)
        return 1
    print(f"完成：issue {len(plans)} 筆、state {'已提交' if status == COMMIT_OK else '無變更'}。")
    return 0


# ============================================================
# 命令：self-test（八情境 mock 測試，assert-based）
# ============================================================
def cmd_self_test() -> int:
    print("=" * 60)
    print("self-test：八情境 mock 測試")
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
    corpus_state = {"mods": {"222": {"corpus_hash": "old", "records": records_to_map(
        [rec("translate_en", "Items_EN.json", "Base.Axe", "Axe")]
    )}}}
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

    # 情境 7：空 baseline 已存在（此 workshop_id 曾記錄空語料）＋上游新增 → 應開 issue（非誤判首跑）
    empty_state = {"mods": {"444": {
        "corpus_hash": corpus_hash([]),
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

    print("\n✅ self-test 八情境全通過。")
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
  uv run scripts/tracker.py self-test              # 八情境 mock 測試
  uv run scripts/tracker.py check  --out c.json    # workflow check job
  uv run scripts/tracker.py diff   --in c.json --out d.json --steamcmd <path>
  uv run scripts/tracker.py issue  --in d.json     # workflow issue+state job
        """,
    )
    parser.add_argument(
        "command", nargs="?", default="run",
        choices=["gen-watchlist", "run", "check", "diff", "issue", "self-test"],
        help="執行的命令（預設：run）",
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


if __name__ == "__main__":
    main()
