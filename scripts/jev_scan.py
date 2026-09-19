# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
jev_scan.py — CH corpus 譯文比對雷達（Jev 批次判讀，report-only）

拿 `sources/ch/` 人工繁中 corpus 與上游 EN 第一手鍵證據對齊，逐鍵丟給 Jev
（TypeSafe systemone）問三個獨立的是非題，產出「可疑鍵」清單供人工審查。

**本工具只產報告，絕不修改 `sources/ch`、`sources/en` 或任何真相層。**

三題（皆為 noul，回傳 0..1 機率）：
  s2t_error          `ours_ch` 是否有簡轉繁一簡對多繁誤轉或殘留簡體字
  prc_wording        `ours_ch` 是否用了大陸慣用詞而台灣慣用另一個詞
  meaning_mismatch   `ours_ch` 語意是否與上游 `en` 不一致（漏譯／誤譯／多譯）
（本 repo 為模組翻譯包，沒有官方 CH 對照，故不問 `worse_than_official`。）

資料來源：
  我方 CH  sources/ch/<type>.json（平面 dict，鍵如 AnimalName_cat_breeds_garfield）
  上游 EN  sources/en/<workshopId>.json，record id 形如
           `translate_en|mods/.../EN/AnimalName.json|AnimalName_cat_breeds_garfield`。
           索引鍵＝裸鍵，`title`／`description` 例外走 `(檔名幹, 鍵)` 檔域對；只取
           執行期有效分支，同 owner 內 JSON EN 蓋過 script DisplayName，跨 owner
           英文不同者整鍵跳過（判準全部沿用 tracker／prep_mod_strings）。
           EN 為 `Placeholder`、空白、或純鍵名回填（等於鍵最後一段）者跳過。

環境變數：TYPESAFE_BASE_URL / TYPESAFE_API_KEY / TYPESAFE_DEFAULT_MODEL

使用方式：
  uv run scripts/jev_scan.py --dry-run
  uv run scripts/jev_scan.py --sample 300
  uv run scripts/jev_scan.py --files "ItemName.json" --threshold 0.6
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker  # noqa: E402 — 有效分支／owner／script DN 勝出值同一把尺
# norm_en＝跨 owner 衝突比對的保守正規化；loadable_json＝Translator 白名單死檔判準
from prep_mod_strings import loadable_json, norm_en  # noqa: E402
from split_sources import SCOPED_GENERIC_KEYS, _file_stem  # noqa: E402 — 檔域限定鍵

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CH_DIR = PROJECT_ROOT / "sources" / "ch"
EN_DIR = PROJECT_ROOT / "sources" / "en"

SEED = 42
MAX_QUESTIONS = 32
INPUT_USD_PER_MTOK = 0.042  # 輸出免費

# ---------------------------------------------------------------- 題目定義

Q_S2T = (
    "把 `ours_ch` 逐字讀過，判斷是否存在**寫錯的漢字**。錯字有兩種："
    "(1) 簡轉繁一簡對多繁選錯：乾燥誤寫成幹燥、頭髮誤寫成頭發、麵條誤寫成面條、"
    "裡面誤寫成里面、以後誤寫成以后、複製誤寫成復製、系統誤寫成係統、戰鬥誤寫成戰斗；"
    "(2) 殘留簡體字形：这个东西、开门、发现、义、过、广。"
    "注意：「這」「個」「東西」「裡面」「開門」「以後」「乾淨」本身都是**正確**的台灣正體寫法，"
    "看到它們不算錯。指不出具體某一個字寫錯，就判 false。不評斷翻譯是否貼切。"
)
Q_S2T_TRUE = "能明確指出某個字寫錯了，並說得出它在台灣正體中應該寫成哪個字（例：「幹燥」的「幹」應為「乾」）。"
Q_S2T_FALSE = "逐字看完，每個字都是台灣正體的正確寫法，指不出任何錯字。"

Q_PRC = (
    "只看 `ours_ch` 的**詞彙選用**：是否使用中國大陸慣用詞，而台灣對同一概念慣用另一個詞"
    "（默認→預設、信息→訊息、軟件→軟體、視頻→影片、菜單→選單、界面→介面、兼容→相容、"
    "加載→載入、優化→最佳化、質量→品質、網絡→網路、屏幕→螢幕、內存→記憶體、激活→啟用、"
    "打印→列印、鼠標→滑鼠、缺省→預設、數據→資料）。兩岸通用的詞不算。"
)
Q_PRC_TRUE = "至少有一個詞是大陸慣用而台灣對同一概念慣用另一個詞。"
Q_PRC_FALSE = "所有詞彙在台灣中文都是自然慣用的說法。"

Q_MEANING = (
    "比較 `ours_ch` 與 `en` 的**語意內容**：是否漏掉英文有的資訊、譯錯意思、"
    "或加入英文沒有的內容。純粹的在地化意譯（語序調整、遊戲術語慣用譯法、"
    "省略冠詞、標點差異、把專有名詞保留英文）不算不一致。"
)
Q_MEANING_TRUE = "中文與英文指涉的事物或動作不同，或明顯漏譯／多譯了實質資訊。"
Q_MEANING_FALSE = "中文忠實傳達了英文的意思，差異僅在文體或在地化表達。"

Q_WORSE = (
    "拿 `ours_ch` 與官方譯文 `official_ch` 相比（兩者都對應同一個 `en`）："
    "我方是否**明顯較差**——語意錯得更多、漏譯、用字錯誤、或明顯不如官方通順。"
    "只是用詞選擇不同、或我方更在地化而兩者都正確，不算較差。"
)
Q_WORSE_TRUE = "能說出我方在語意正確性或用字上具體差在哪裡，官方版本明顯較佳。"
Q_WORSE_FALSE = "我方與官方品質相當或更好，挑不出我方明顯較差之處。"


def _noul(instructions: str, yes: str, no: str) -> dict:
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": yes, "false": no},
    }


def questions_for(has_official: bool, prefix: str = "") -> dict:
    """單一鍵的題組；`prefix` 非空時用於 batch 模式（題名 `k3.s2t_error`）。"""
    where = f"（只針對 `items.{prefix}`）" if prefix else ""
    p = f"{prefix}." if prefix else ""
    qs = {
        f"{p}s2t_error": _noul(where + Q_S2T, Q_S2T_TRUE, Q_S2T_FALSE),
        f"{p}prc_wording": _noul(where + Q_PRC, Q_PRC_TRUE, Q_PRC_FALSE),
        f"{p}meaning_mismatch": _noul(where + Q_MEANING, Q_MEANING_TRUE, Q_MEANING_FALSE),
    }
    if has_official:
        qs[f"{p}worse_than_official"] = _noul(where + Q_WORSE, Q_WORSE_TRUE, Q_WORSE_FALSE)
    return qs


METRICS = ("s2t_error", "prc_wording", "meaning_mismatch", "worse_than_official")

# ---------------------------------------------------------------- 資料載入


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是平面 dict")
    return data


def _index_key(stem: str, key: str):
    """索引鍵：一般鍵用裸鍵，`title`／`description` 用 `(檔名幹, 鍵)` 檔域對。

    `stem` 是**去副檔名的檔名**——上游 Translate 檔名或我方 corpus 檔名，兩側同一把尺。
    """
    return (stem, key) if key in SCOPED_GENERIC_KEYS else key


def _runtime_loadable(base: str, key: str) -> bool:
    """這個上游 Translate 檔的這個鍵，`Translator` 執行期真的讀得到嗎？

    兩條路徑（`verify_dist` 的死檔判定同源）：`Translator.BY_NAME` 白名單 31 檔
    （`prep_mod_strings.loadable_json`，同時擋掉 `.txt`），外加每張地圖以自身檔名載入的
    `title`／`description`（`readMapTranslation():392`）。`UI_EN.json`／`Compendium.json`
    這類**是 json 但檔名不在白名單**的死檔——上游有寫、引擎不讀，拿它當錨點就是用一份
    執行期不存在的英文去覆寫同鍵的 script DisplayName。
    `Mod.json` 例外在白名單內卻走 `readModTranslation()`：只填該 mod 自己的清單名稱／
    簡介，不進全域字串表，任何鍵都不該以它當錨點（同 `coverage_survey.target_file`）。
    """
    stem = _file_stem(base)
    if stem == "Mod":
        return False
    return loadable_json(base) or key in SCOPED_GENERIC_KEYS


def build_en_index() -> tuple[dict, dict[str, int]]:
    """tracker state（宇宙）＋ sources/en 鏡像（值）→ ({索引鍵: EN}, 統計)。

    **宇宙一律取自 `tracker.load_corpus_hashes()` 的 `records`，鏡像只供值**：鏡像只存
    text-bearing record（`translate_en`／`script_item_dn`），id-only 的 `script_*` 不在
    裡面。拿鏡像決定有效分支，會在「較新版本夾只出現 id-only 記錄」時看不到那個分支，
    於是把**已被淘汰的舊版本夾**當成最佳分支、讀它的過期英文當錨點。

    三層語意一律沿用引擎口徑的既有 helper，不另寫第二套：
      * **有效分支**：`tracker.resolve_effective_branches`／`is_effective`（`common`
        ＋唯一最佳版本夾；mod 根 `media/` 與舊／未來版本夾不載入，`translate_en`
        只認 `.json`）。拿死分支的英文當錨點＝比對一份執行期不存在的文字。
      * **同 owner 內來源優先序**：`translate_en` 蓋過 `script_item_dn`（引擎先查
        ItemName map，查不到才退回 `Item.getDisplayName()`），空值語意照
        `tryFillMapFromFile():362` 的 put 條件——首見 `""` 抑制同鍵 script 值、
        已有非空值後的 `""` 不覆寫、純空白一律覆寫。與 `prep_mod_strings.converge_owner`
        同一套判準；DN 勝出值直接用 `tracker.winning_dn_text(recs, mirror, eff)`（勝出 rid
        由 state 決定、值查鏡像，勝出 rid 缺值即整鍵不入，絕不回退 common 舊值）。死檔
        （`_runtime_loadable` 為假）整筆不參與，否則 `UI_EN.json` 這種引擎不讀的檔會
        覆寫掉 script DisplayName。
      * **跨 owner**：`norm_en` 正規化後全等才合併，英文不同者**整鍵跳過**並計入
        `en_owner_conflicts`。取第一個＝拿別的 mod 的英文當錨點，整批掃描結論張冠李戴。
        **被抑制成空白的 owner 照樣留在 census**（值記空字串）：直接刪掉它，該鍵就只剩
        另一個 owner 的非空英文而看似無歧義，但那個 owner 的玩家執行期看到的是空白——
        「一邊空白一邊有字」本來就是歧義，要一起算衝突。全部 owner 都空者最後排除。

    **來源不可用一律 fail-closed 計數、不靜默略過**（`en_unusable_wids`；`main()` 在打
    API 前據此拒跑）：state 形狀壞損、有文本 record 卻無鏡像、鏡像壞 JSON、或
    `tracker.mirror_incoherent_rids` 判定鏡像與 state 不一致（中斷殘跡＝過期英文）。
    鏡像缺某筆 rid 的值不在該 helper 的契約內（設計上不驗 state 有→鏡像沒有），故以
    `None` 哨兵記在 census，該鍵整個排除並計入 `en_mirror_gaps`——既不回退舊值，也不讓
    另一個 owner 獨贏。
    """
    if not EN_DIR.is_dir():
        sys.exit(f"找不到上游 EN 目錄：{EN_DIR}")
    state = tracker.load_corpus_hashes(missing_ok=False)["mods"]
    # {索引鍵: {owner: EN}}；owner 帶 wid 前綴——同名 mod root 出現在兩個 wid 時
    # 併成一個 owner 會讓其中一邊靜默覆寫另一邊，那正是這裡要擋的 first-wins。
    census: dict = {}
    unusable = 0
    for wid in sorted(state):
        entry = state[wid]
        recs = entry.get("records") if isinstance(entry, dict) else None
        if not isinstance(recs, dict):
            unusable += 1
            print(f"  ⚠️ {wid}：tracker state 形狀壞損，整個 wid 不入索引", file=sys.stderr)
            continue
        path = EN_DIR / f"{wid}.json"
        mirror: dict = {}
        if path.is_file():
            try:
                mirror = load_json(path)
            except (ValueError, OSError) as exc:
                unusable += 1
                print(f"  ⚠️ {wid}：鏡像無法解析（{type(exc).__name__}）", file=sys.stderr)
                continue
        elif any(r.partition("|")[0] in tracker.TEXT_BEARING_KINDS for r in recs):
            # 無 text-bearing record 時鏡像本來就會被刪，那是合法狀態；有才算缺
            unusable += 1
            print(f"  ⚠️ {wid}：state 有文本 record 卻無 sources/en 鏡像", file=sys.stderr)
            continue
        bad = tracker.mirror_incoherent_rids(recs, mirror)
        if bad:
            unusable += 1
            print(f"  ⚠️ {wid}：{len(bad)} 筆 record 的鏡像與 state 不一致（中斷殘跡）",
                  file=sys.stderr)
            continue

        eff = tracker.resolve_effective_branches(recs)
        owners: dict = {
            (rid.rpartition("|")[2], tracker.owner_of(rid)): None
            for rid in recs
            if rid.startswith("script_item_dn|") and tracker.is_effective(rid, eff)
        }
        for (owner, full_type), text in tracker.winning_dn_text(recs, mirror, eff).items():
            owners[(full_type, owner)] = text
        seen: set = set()
        rids = [r for r in recs
                if r.startswith("translate_en|") and tracker.is_effective(r, eff)]
        for rid in sorted(rids, key=lambda r: tracker._branch_tag(r) != "common"):
            relpath, _, key = rid.partition("|")[2].partition("|")
            base = os.path.basename(relpath)
            if not _runtime_loadable(base, key):
                continue
            slot = (_index_key(_file_stem(base), key), tracker.owner_of(rid))
            if rid not in mirror:
                # 未知的既有 JSON 值不能被後來的 "" 判成確定空白；非空新值仍可覆寫。
                owners[slot] = None
                seen.add(slot)
                continue
            value = mirror[rid]
            if isinstance(value, str) and value.strip():
                owners[slot] = value
            elif value == "" and slot in seen:
                continue        # 已有非空值後的 ""：引擎不覆寫，執行期仍是那個非空值
            else:
                # 首見 ""／純空白／非字串：該 owner 執行期顯示空白（同鍵 script
                # DisplayName 一併被抑制）。記成空字串而非刪除，才進得了跨 owner 歧義判定。
                owners[slot] = ""
            seen.add(slot)
        for (ikey, owner), value in owners.items():
            census.setdefault(ikey, {})[f"{wid}/{owner}"] = value

    index: dict = {}
    conflicts = gaps = 0
    for ikey, by_owner in census.items():
        if None in by_owner.values():
            gaps += 1
            continue
        if len({norm_en(v) for v in by_owner.values()}) > 1:
            conflicts += 1
            continue
        value = by_owner[min(by_owner)]
        if value.strip():   # 全部 owner 都是空白＝執行期沒有可比對的英文，不是衝突
            index[ikey] = value
    return index, {"en_keys": len(index), "en_owner_conflicts": conflicts,
                   "en_mirror_gaps": gaps, "en_unusable_wids": unusable}


def is_backfill_en(key: str, en: str) -> bool:
    """依掃描排除規則略過 `Placeholder`、空白、或與鍵尾相等的 EN。
    最後一段同時看 `.` 後整段（`HMW.H_AcousticBlack`）與 `.`/`_` 後尾段
    （`AnimalName_cat_breeds_garfield` → `Garfield`），不分大小寫。
    鍵尾相等是降噪啟發式，也會排除 Back 等有效短英文，不代表譯文無誤。"""
    s = en.strip()
    if not s or s.lower() == "placeholder":
        return True
    dot_tail = key.rsplit(".", 1)[-1]
    tail = dot_tail.rsplit("_", 1)[-1]
    return s.lower() in (dot_tail.lower(), tail.lower())


def load_pairs(files_glob: str | None) -> tuple[list[dict], dict[str, int]]:
    """回傳 (待掃項目, 統計)。項目形狀 {file,key,en,official_ch,ours_ch}。"""
    if not CH_DIR.is_dir():
        sys.exit(f"找不到 CH corpus 目錄：{CH_DIR}")
    en_index, en_stats = build_en_index()

    items: list[dict] = []
    stats = {"total": 0, "no_en": 0, "skipped_nonstr": 0, "skipped_backfill": 0,
             **en_stats}
    for path in sorted(CH_DIR.glob("*.json")):
        if files_glob and not fnmatch.fnmatch(path.name, files_glob):
            continue
        for key, value in load_json(path).items():
            stats["total"] += 1
            if not isinstance(value, str) or not value.strip():
                stats["skipped_nonstr"] += 1
                continue
            en = en_index.get(_index_key(path.stem, key))
            if not isinstance(en, str):
                stats["no_en"] += 1
                continue
            if is_backfill_en(key, en):
                stats["skipped_backfill"] += 1
                continue
            # 模組翻譯包沒有官方 CH 對照，該欄恆空
            items.append({"file": path.name, "key": key, "en": en,
                          "official_ch": "", "ours_ch": value})
    return items, stats


# ---------------------------------------------------------------- Jev 呼叫


def state_of(item: dict) -> dict:
    st = {"key": item["key"], "en": item["en"], "ours_ch": item["ours_ch"]}
    if item["official_ch"]:
        st["official_ch"] = item["official_ch"]
    return st


def build_request(batch: list[dict], model: str) -> tuple[dict, list[str]]:
    """回傳 (payload, 每個項目的題名前綴)。batch 長度 1 時不加前綴。"""
    if len(batch) == 1:
        return {"model": model, "state": state_of(batch[0]),
                "questions": questions_for(bool(batch[0]["official_ch"]))}, [""]
    prefixes = [f"k{i + 1}" for i in range(len(batch))]
    state = {"items": {p: state_of(it) for p, it in zip(prefixes, batch)}}
    questions: dict = {}
    for prefix, item in zip(prefixes, batch):
        questions.update(questions_for(bool(item["official_ch"]), prefix))
    return {"model": model, "state": state, "questions": questions}, prefixes


def estimate_tokens(payload: dict) -> int:
    """粗估 input token。係數由實測擬合：CJK 約 1.5 tok/字、其餘約 0.4 tok/字元
    （6 次實測 payload 誤差 <1%）。"""
    text = json.dumps(payload, ensure_ascii=False)
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff")
    return round(1.5 * cjk + 0.4 * (len(text) - cjk))


def call_jev(payload: dict, url: str, api_key: str, retries: int = 2) -> dict:
    data = json.dumps(payload).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — 任何失敗都重試，最後照實往上拋
            last = exc
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    last = RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")
                except Exception:  # noqa: BLE001
                    last = RuntimeError(f"HTTP {exc.code}")
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last))


def scan_batch(batch: list[dict], url: str, api_key: str, model: str) -> list[dict]:
    payload, prefixes = build_request(batch, model)
    resp = call_jev(payload, url, api_key)
    answers = resp.get("answers") or {}
    usage = resp.get("usage") or {}
    n = len(batch)
    rows = []
    for prefix, item in zip(prefixes, batch):
        p = f"{prefix}." if prefix else ""
        row = dict(item)
        probs = {}
        for metric in METRICS:
            ans = answers.get(f"{p}{metric}")
            probs[metric] = round(float(ans["noul"]), 4) if ans and "noul" in ans else None
        row.update(probs)
        row["max_prob"] = max((v for v in probs.values() if v is not None), default=0.0)
        row["model"] = resp.get("model", model)
        # batch 模式的 usage 是整批共用，平均攤到每一列以維持總量正確
        row["input_tokens"] = round(usage.get("input_tokens", 0) / n, 2)
        row["output_tokens"] = round(usage.get("output_tokens", 0) / n, 2)
        row["cost_usd"] = round(usage.get("cost", 0.0) / n, 8)
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 輸出

TSV_COLUMNS = (
    "file", "key", "max_prob", "s2t_error", "prc_wording", "meaning_mismatch",
    "worse_than_official", "en", "official_ch", "ours_ch", "model",
    "input_tokens", "output_tokens", "cost_usd",
)


def tsv_cell(value) -> str:
    if value is None:
        return ""
    return str(value).replace("\t", "\\t").replace("\n", "\\n").replace("\r", "")


def sidecar(prefix: Path, ext: str) -> Path:
    return prefix.with_name(prefix.name + ext)


def write_reports(out_prefix: Path, rows: list[dict], errors: list[dict]) -> None:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    # 前綴含時間戳（jev_scan.20260919-215649），with_suffix 會把它當副檔名吃掉
    with sidecar(out_prefix, ".jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with sidecar(out_prefix, ".tsv").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(TSV_COLUMNS) + "\n")
        for row in rows:
            fh.write("\t".join(tsv_cell(row.get(c)) for c in TSV_COLUMNS) + "\n")
    if errors:
        with sidecar(out_prefix, ".errors.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
            for err in errors:
                fh.write(json.dumps(err, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 主流程


def main() -> int:
    ap = argparse.ArgumentParser(description="CH corpus 譯文比對雷達（Jev，report-only）")
    ap.add_argument("--files", help="只掃符合此 glob 的 corpus 檔名，例：'ItemName.json'")
    ap.add_argument("--sample", type=int, help="隨機抽樣 N 鍵（seed 42）")
    ap.add_argument("--threshold", type=float, default=0.5, help="可疑判定機率門檻")
    ap.add_argument("--batch", type=int, default=1, help="每個請求塞幾個鍵（省 token）")
    ap.add_argument("--workers", type=int, default=8, help="並行請求數")
    ap.add_argument("--out", type=Path, help="輸出前綴，預設 reports/jev_scan.<ts>")
    ap.add_argument("--dry-run", action="store_true", help="只算鍵數與估算成本，不打 API")
    args = ap.parse_args()

    if args.batch < 1:
        sys.exit("--batch 至少為 1")
    max_batch = MAX_QUESTIONS // len(METRICS)
    if args.batch > max_batch:
        sys.exit(f"--batch 上限 {max_batch}（每請求最多 {MAX_QUESTIONS} 題）")

    items, stats = load_pairs(args.files)
    if args.sample and args.sample < len(items):
        random.Random(SEED).shuffle(items)
        items = items[: args.sample]

    batches = [items[i : i + args.batch] for i in range(0, len(items), args.batch)]
    est_tokens = sum(estimate_tokens(build_request(b, "m")[0]) for b in batches)
    est_cost = est_tokens / 1_000_000 * INPUT_USD_PER_MTOK

    print(f"EN 索引鍵數         {stats['en_keys']}"
          f"（跨 owner 英文不同而整鍵跳過 {stats['en_owner_conflicts']} 鍵、"
          f"鏡像缺值 {stats['en_mirror_gaps']} 鍵）")
    if stats["en_unusable_wids"]:
        print(f"  ⚠️ EN 來源不可用    {stats['en_unusable_wids']} 個 wid"
              "（上方逐項列出；掃描前必須修好，否則那些 owner 的衝突判定整個消失）")
    print(f"CH corpus 鍵總數    {stats['total']}")
    print(f"  無 EN 錨點（跳過） {stats['no_en']}")
    print(f"  空值／非字串（跳過）{stats['skipped_nonstr']}")
    print(f"  EN 排除規則（跳過） {stats['skipped_backfill']}（Placeholder／空白／鍵尾相等）")
    print(f"待掃鍵數            {len(items)}")
    print(f"請求數              {len(batches)}（batch={args.batch}）")
    print(f"估算 input token    {est_tokens:,}")
    print(f"估算成本            ${est_cost:.4f}")
    if args.dry_run:
        return 0
    if stats["en_unusable_wids"]:
        sys.exit(f"{stats['en_unusable_wids']} 個 wid 的 EN 來源不完整／與 state 不一致，"
                 "拒絕打 API：部分索引會讓盲區 owner 靜默消失，掃描結論不可信。"
                 "先修 tracker-state/en_corpus_hashes 與 sources/en 鏡像（backfill-en）。")

    base_url = os.environ.get("TYPESAFE_BASE_URL")
    api_key = os.environ.get("TYPESAFE_API_KEY")
    model = os.environ.get("TYPESAFE_DEFAULT_MODEL")
    if not (base_url and api_key and model):
        sys.exit("缺少 TYPESAFE_BASE_URL / TYPESAFE_API_KEY / TYPESAFE_DEFAULT_MODEL 環境變數")
    url = base_url.rstrip("/") + "/v1/systemone"

    rows: list[dict] = []
    errors: list[dict] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scan_batch, b, url, api_key, model): b for b in batches}
        done = 0
        for future, batch in futures.items():
            done += 1
            try:
                rows.extend(future.result())
            except Exception as exc:  # noqa: BLE001 — 重試耗盡，記錄後續跑
                errors.append({"keys": [f"{i['file']}|{i['key']}" for i in batch],
                               "error": str(exc)})
                print(f"[跳過] {batch[0]['file']}|{batch[0]['key']} … {exc}", file=sys.stderr)
            if done % 50 == 0:
                print(f"  …{done}/{len(batches)}", file=sys.stderr)
    elapsed = time.time() - started

    rows.sort(key=lambda r: r["max_prob"], reverse=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_prefix = args.out or (PROJECT_ROOT / "reports" / f"jev_scan.{ts}")
    write_reports(out_prefix, rows, errors)

    actual_tokens = sum(r["input_tokens"] for r in rows)
    actual_cost = sum(r["cost_usd"] for r in rows)
    print("\n—— 掃描結果 ——")
    print(f"已判讀              {len(rows)} 鍵 / 失敗跳過 {len(errors)} 批")
    for metric in METRICS:
        asked = sum(1 for r in rows if r.get(metric) is not None)
        if not asked:
            continue
        hits = sum(1 for r in rows if (r.get(metric) or 0) >= args.threshold)
        print(f"  {metric:<20} ≥{args.threshold}: {hits}（有問 {asked} 題）")
    flagged = sum(1 for r in rows if r["max_prob"] >= args.threshold)
    print(f"任一題超過門檻      {flagged}")
    print(f"實際 input token    {actual_tokens:,.0f}")
    print(f"實際成本            ${actual_cost:.4f}")
    print(f"耗時                {elapsed:.1f}s")
    print(f"報告                {out_prefix}.jsonl / .tsv")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
