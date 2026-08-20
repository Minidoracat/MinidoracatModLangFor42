#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""回歸測試：`backfill-en` 的 **state-first 每 mod 原子落盤** 寫序。

這是唯一關住「只變更非鏡像 kind 的 record 永久遺失」的防線，而該失效模式**事後偵測
不到**——`lua_gettext`／`script_item`／`script_craftRecipe` 不進 `sources/en` 鏡像，
所以 `backfill_done()` 的逐 rid 值 hash 比對從定義上驗不出差異，續跑會判成已完成。

若有人為了「省掉 480 次 30MB 寫入」把它改回 `if done % 10 == 0` 批次 checkpoint，或
把鏡像寫入移到 state 之前，本測試必須紅燈。self-test 情境 15 那條
`assert backfill_done(plus_lua, mp)` 只是路標（斷言的是 `backfill_done` 偵測不到），
改壞寫序它照樣綠，故防線需要這支獨立測試。
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
#   * `lua_gettext` 是**非鏡像 kind**——寫序在守的正是它（state 遺失時 `backfill_done()`
#     的值 hash 比對從定義上驗不出差異）。
#   * `translate_en` 是 text-bearing，**它才會讓 `write_json` 真的去寫鏡像**。少了它
#     production 走 `Path.unlink()`，`boom_mirror` 注入永遠不會觸發＝案例 3 假綠。
CORPUS = {
    "1": [("lua_gettext", f"{EFF}/lua/a.lua", "UI_One", "UI_One"),
          ("translate_en", f"{EFF}/lua/shared/Translate/EN/UI.json", "UI_A", "Alpha")],
    "2": [("lua_gettext", f"{EFF}/lua/b.lua", "UI_Two", "UI_Two"),
          ("translate_en", f"{EFF}/lua/shared/Translate/EN/UI.json", "UI_B", "Bravo")],
}


def run_backfill(*, boom_at: str | None = None, boom_mirror: bool = False,
                 seed_state: dict | None = None) -> tuple[dict, int]:
    """跑 `cmd_backfill_en`（steamcmd／下載／抽取全部注入），回 (磁碟 state, 注入觸發次數)。

    `boom_at` 指定在抽取哪個 wid 時擲例外（`"*"`＝全部失敗）；`boom_mirror` 則讓**鏡像那次
    `write_json` 失敗**——那是唯一能鑑別寫序的注入點。注入在 `extract_corpus` 只證明
    「失敗不落盤」，對「state 先寫還是鏡像先寫」完全無感（兩種寫序在該路徑上輸出相同）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sources" / "en").mkdir(parents=True)
        (root / "tracker-state").mkdir()
        state_p = root / "tracker-state" / "en_corpus_hashes.json"
        io.open(state_p, "w", encoding="utf-8").write(
            json.dumps({"mods": seed_state or {}}))
        io.open(root / "tracker-state" / "watchlist.json", "w", encoding="utf-8").write(
            json.dumps({"items": {w: {"mod_ids": [f"Mod{w}"]} for w in CORPUS}}))

        saved = {k: getattr(tracker, k) for k in
                 ("EN_CORPUS_HASHES_JSON", "EN_TEXT_DIR", "WATCHLIST_JSON", "SOURCES",
                  "steamcmd_download", "extract_corpus", "resolve_install_dir",
                  "load_attribution_keys", "_within_scratch", "load_timestamps",
                  "write_json")}
        real_write = tracker.write_json
        hits: list[str] = []
        try:
            tracker.EN_CORPUS_HASHES_JSON = state_p
            tracker.EN_TEXT_DIR = root / "sources" / "en"
            tracker.WATCHLIST_JSON = root / "tracker-state" / "watchlist.json"
            tracker.SOURCES = root / "sources"
            tracker.resolve_install_dir = lambda _: root / "_dl"
            tracker.load_attribution_keys = lambda: {}
            tracker.load_timestamps = lambda: {"items": {}}
            tracker._within_scratch = lambda _: False   # 別讓 rmtree 碰暫存目錄
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
        finally:
            for k, v in saved.items():
                setattr(tracker, k, v)
        return json.loads(io.open(state_p, encoding="utf-8").read()), len(hits)


# 1. 全部成功：兩個 mod 的 record 都在磁碟 state 上
st, _ = run_backfill()
check(set(st.get("mods", {})) == {"1", "2"},
      f"1. 正常路徑未把兩個 mod 都落盤：{sorted(st.get('mods', {}))}")

# 2. **第二個 mod 抽取失敗**：第一個 mod 的 state 必須已經在磁碟上。
st, _ = run_backfill(boom_at="2")
check("1" in st.get("mods", {}) and "2" not in st.get("mods", {}),
      f"2. 失敗前已完成的 mod 未落盤、或失敗的 mod 被寫入：{sorted(st.get('mods', {}))}")
check("lua_gettext|mods/M/42.20/media/lua/a.lua|UI_One" in st["mods"]["1"]["records"],
      f"2. 落盤的 state 缺該 mod 的非鏡像 record：{st['mods']['1']}")

# 3. **鏡像寫入失敗**＝state 與鏡像兩次寫入之間硬中斷。**這是唯一鑑別寫序的案例**：
#    state-first 時 record 已持久化（本斷言綠）；改成「鏡像先寫」則例外發生在 state
#    落盤之前 → mods 為空 → 紅。而因為 `lua_gettext` 不進鏡像，續跑時
#    `backfill_done()` 的值 hash 比對驗不出差異 → 判成已完成 → record 永久遺失。
st, hit = run_backfill(boom_mirror=True)
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
    st, _ = run_backfill(seed_state={"1": bad})
    assert isinstance(st.get("mods", {}).get("1"), dict) \
        and isinstance(st["mods"]["1"].get("records"), dict), \
        f"5. {label}：重抽後 state 未被修成有效 dict＝永久修不好（{st.get('mods', {}).get('1')!r}）"

# 4. **全部 mod 都失敗**：頂層 `extractor_schema` 不得被推進——沒有任何 mod 真的重抽過，
#    留著標記會讓 `backfill_done()` 對其餘 mod 誤判 schema 相符而永久跳過。
#    （`boom_at="1"` 那種只有部分失敗的寫法是**空斷言**：wid 2 成功就會寫入頂層標記。）
st, _ = run_backfill(boom_at="*")
check(not st.get("mods"), f"4. 全部失敗卻有 mod 落盤：{sorted(st.get('mods', {}))}")
check(st.get("extractor_schema") != tracker.EXTRACTOR_SCHEMA,
      "4. 全部失敗卻把頂層 extractor_schema 推進到新版（迴圈後那次冗餘 write_json 被還原了）")

if FAIL:
    print(f"\nFAIL: {FAIL} 項未通過", file=sys.stderr)
    sys.exit(1)
print("PASS: backfill-en state-first 寫序＋壞損 state 修復 5/5 案例通過")
