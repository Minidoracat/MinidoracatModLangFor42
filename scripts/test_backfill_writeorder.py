#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""回歸測試：backfill-en 的 state-first 寫序與 schema 遷移訊號保留。

`script_item`／`script_craftRecipe` 不進 `sources/en` 鏡像；若 state 未先落盤，
`backfill_done()` 無法事後偵測這類 record 遺失。本測試也守住 schema 9→10 遷移：
同輪真正的 JSON diff 必須保留舊 baseline，不能被 backfill 靜默吸收。
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker  # noqa: E402

FAIL = 0


def check(cond: bool, msg: str) -> None:
    global FAIL
    if not cond:
        print(f"❌ {msg}", file=sys.stderr)
        FAIL += 1


EFF = "mods/M/42.20/media"
# 兩種 kind 都要：
#   * `script_item` 是**非鏡像 kind**——寫序在守的正是它。
#   * `translate_en` 是 text-bearing，**它才會讓 `write_json` 真的去寫鏡像**。
CORPUS = {
    "1": [("script_item", f"{EFF}/scripts/a.txt", "Base.One", "Base.One"),
          ("translate_en", f"{EFF}/lua/shared/Translate/EN/UI.json", "UI_A", "Alpha")],
    "2": [("script_item", f"{EFF}/scripts/b.txt", "Base.Two", "Base.Two"),
          ("translate_en", f"{EFF}/lua/shared/Translate/EN/UI.json", "UI_B", "Bravo")],
}


def run_backfill(*, boom_at: str | None = None, boom_mirror: bool = False,
                 seed_state: dict | None = None) -> tuple[dict, int, dict | None]:
    """跑 backfill，回 (磁碟 state, 鏡像失敗注入次數, pending issue artifact)。

    `boom_at` 指定抽取失敗 wid；`boom_mirror` 讓鏡像寫入失敗，以鑑別 state-first 寫序。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sources" / "en").mkdir(parents=True)
        mods_root = root / "sources" / "mods"
        for wid in CORPUS:
            tracker.write_json(
                mods_root / wid / "metadata.json",
                {"workshop_id": wid, "mod_ids": [f"Mod{wid}"]},
            )
        registry = root / "sources" / "mod_registry.json"
        tracker.write_json(registry, {"mods": {
            wid: {
                "status": "active", "source": "test", "verified": "2026-08-30",
                "mod_ids": [f"Mod{wid}"],
            }
            for wid in CORPUS
        }})
        (root / "tracker-state").mkdir()
        watchlist = root / "tracker-state" / "watchlist.json"
        assert tracker.gen_watchlist(mods_root, registry, watchlist) == 0
        state_p = root / "tracker-state" / "en_corpus_hashes"
        tracker.write_corpus_hashes({"mods": seed_state or {}}, state_p)

        saved = {k: getattr(tracker, k) for k in
                 ("EN_CORPUS_HASHES_DIR", "EN_TEXT_DIR", "WATCHLIST_JSON", "SOURCES",
                  "BACKFILL_PLANS_JSON", "steamcmd_download", "extract_corpus",
                  "resolve_install_dir", "load_attribution_keys", "_within_scratch",
                  "load_timestamps", "write_json")}
        real_write = tracker.write_json
        hits: list[str] = []
        plans_p = root / "_dl" / "backfill_plans.json"
        try:
            tracker.EN_CORPUS_HASHES_DIR = state_p
            tracker.EN_TEXT_DIR = root / "sources" / "en"
            tracker.WATCHLIST_JSON = watchlist
            tracker.SOURCES = root / "sources"
            tracker.BACKFILL_PLANS_JSON = plans_p
            tracker.resolve_install_dir = lambda _: root / "_dl"
            tracker.load_attribution_keys = lambda: {}
            tracker.load_timestamps = lambda: {"items": {}}
            tracker._within_scratch = lambda _: False
            tracker.steamcmd_download = lambda wid, *a, **k: root / "_dl" / wid

            def fake_extract(item_dir: Path):
                wid = item_dir.name
                if boom_at in ("*", wid):
                    raise OSError(f"injected extract failure at {wid}")
                return CORPUS[wid]

            def guarded_write(path: Path, data: dict) -> None:
                if boom_mirror and path.parent.name == "en":
                    hits.append(path.name)
                    raise OSError(f"injected mirror write failure: {path.name}")
                real_write(path, data)

            tracker.extract_corpus = fake_extract
            tracker.write_json = guarded_write
            tracker.cmd_backfill_en(types.SimpleNamespace(
                steamcmd=str(root / "steamcmd"), install_dir=None, force=True,
                limit=None, only=None))
            result = tracker.load_corpus_hashes(state_p)
            # 頂層標記要讀磁碟原文：loader 會補預設 EXTRACTOR_SCHEMA，讀它等於恆真
            result["extractor_schema"] = json.loads(
                (state_p / tracker.EN_CORPUS_META).read_text(encoding="utf-8")).get("extractor_schema")
            pending = json.loads(plans_p.read_text(encoding="utf-8")) if plans_p.is_file() else None
        finally:
            for k, v in saved.items():
                setattr(tracker, k, v)
        return result, len(hits), pending


# 1. 全部成功：兩個 mod 的 record 都在磁碟 state 上
st, _, _ = run_backfill()
check(set(st.get("mods", {})) == {"1", "2"},
      f"1. 正常路徑未把兩個 mod 都落盤：{sorted(st.get('mods', {}))}")
# 2. **第二個 mod 抽取失敗**：第一個 mod 的 state 必須已經在磁碟上。
st, _, _ = run_backfill(boom_at="2")
check("1" in st.get("mods", {}) and "2" not in st.get("mods", {}),
      f"2. 失敗前已完成的 mod 未落盤、或失敗的 mod 被寫入：{sorted(st.get('mods', {}))}")
check("script_item|mods/M/42.20/media/scripts/a.txt|Base.One" in st["mods"]["1"]["records"],
      f"2. 落盤的 state 缺該 mod 的非鏡像 record：{st['mods']['1']}")

# 3. **鏡像寫入失敗**＝state 與鏡像兩次寫入之間硬中斷。state-first 時 record 已持久化；
#    改成鏡像先寫則例外發生在 state 落盤之前。非鏡像 kind 不進鏡像，續跑無法事後補救。
st, hit, _ = run_backfill(boom_mirror=True)
# 先驗注入真的觸發過：若 CORPUS 全是非鏡像 kind，production 走 `Path.unlink()`，
# 這個注入永遠不會執行，下面那條斷言就變成恆綠的假保證。
check(hit == len(CORPUS), f"3. 鏡像寫入注入未觸發（案例無鑑別力）：觸發 {hit} 次")
check(set(st.get("mods", {})) == {"1", "2"},
      "3. 鏡像寫入失敗時 state 未持久化＝寫序被改成鏡像先寫，非鏡像 kind 的 record "
      f"會永久遺失：{sorted(st.get('mods', {}))}")

# 5. **壞損 state 必須能被重抽修好**：`backfill_done` 判它未完成 → 進 todo → 但若
#    `build_layer_a_plan` 拿同一份壞 state 去 diff，會在寫回新 state **之前**拋
#    AttributeError／TypeError（那在 per-mod 失敗處理之前），於是每次重跑都中止＝永久修不
#    好，prep 的 `_unchecked` 叫人「重抽該 mod」就成了空指示。
for label, bad in (("state 條目非 dict", ["not", "a", "dict"]),
                   ("records 非 dict", {"extractor_schema": tracker.EXTRACTOR_SCHEMA,
                                        "records": ["bad"]}),
                   ("records 為 null", {"extractor_schema": tracker.EXTRACTOR_SCHEMA,
                                        "records": None})):
    st, _, _ = run_backfill(seed_state={"1": bad})
    assert isinstance(st.get("mods", {}).get("1"), dict) \
        and isinstance(st["mods"]["1"].get("records"), dict), \
        f"5. {label}：重抽後 state 未被修成有效 dict＝永久修不好（{st.get('mods', {}).get('1')!r}）"

# 4. **全部 mod 都失敗**：頂層 `extractor_schema` 不得被推進——沒有任何 mod 真的重抽過，
#    留著標記會讓 `backfill_done()` 對其餘 mod 誤判 schema 相符而永久跳過。
#    （`boom_at="1"` 那種只有部分失敗的寫法是**空斷言**：wid 2 成功就會寫入頂層標記。）
st, _, _ = run_backfill(boom_at="*")
check(not st.get("mods"), f"4. 全部失敗卻有 mod 落盤：{sorted(st.get('mods', {}))}")
check(st.get("extractor_schema") != tracker.EXTRACTOR_SCHEMA,
      "4. 全部失敗卻把頂層 extractor_schema 推進到新版（迴圈後那次冗餘 write_json 被還原了）")

# 6. schema 9→10 若同輪有真 JSON diff，backfill 不得覆寫 baseline 吃掉本該開的 issue。
legacy = {
    "extractor_schema": 9,
    "corpus_hash": "old",
    "records": {
        f"translate_en|{EFF}/lua/shared/Translate/EN/UI.json|UI_A": tracker.value_hash("Old"),
        f"lua_gettext|{EFF}/lua/a.lua|UI_Old": tracker.value_hash("UI_Old"),
    },
}
st, _, pending = run_backfill(seed_state={"1": legacy})
check(st["mods"]["1"]["extractor_schema"] == 9,
      "6. backfill 吞掉 schema 9→10 同輪真 JSON diff，baseline 被錯誤推進")
check(isinstance(pending, dict) and "1" in pending.get("corpus_updates", {})
      and "1" in pending.get("en_texts", {}),
      "6. 真 JSON diff artifact 缺 state/mirror，issue 套用後會永久重試")
if isinstance(pending, dict) and "1" in pending.get("corpus_updates", {}):
    with tempfile.TemporaryDirectory() as td:
        mirror = Path(td) / "1.json"
        tracker.write_json(mirror, pending["en_texts"]["1"])
        check(tracker.backfill_done(pending["corpus_updates"]["1"], mirror),
              "6. pending artifact 套用後仍不能完成 schema10 baseline")
if FAIL:
    print(f"\nFAIL: {FAIL} 項未通過", file=sys.stderr)
    sys.exit(1)
print("PASS: backfill-en state-first／壞損修復／JSON diff 保留 6/6 案例通過")
