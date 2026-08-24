#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""回歸測試：`untranslatable_keys.json` 讓內部／佔位／淘汰物品不虛胖缺口（#231）。

執行：uv run scripts/test_untranslatable_keys.py
不依賴測試框架，任一項失敗即非零退出。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FAIL = 0
CHECKS = 0


def check(cond: bool, msg: str) -> None:
    global FAIL, CHECKS
    CHECKS += 1
    if not cond:
        print(f"❌ {msg}", file=sys.stderr)
        FAIL += 1


p = ROOT / "sources/untranslatable_keys.json"
pairs, items = tracker.load_untranslatable(p)
data = json.loads(p.read_text(encoding="utf-8"))
entries = data["entries"]

check(len(entries) == 398, f"registry 應有 398 條人工裁決，實得 {len(entries)}")
# 其餘兩項一律**相對 `entries` 表述**：登記是漸進成長的，寫死三份數字會讓每次新增都得改三處。
check(len(pairs) == len(entries), "檔域身分不得因正規化互相塌縮")
check(len(entries) - len(items) == 2,
      f"非 ItemName 的登記只應有 2 條（IG_UI 1、Recipes 1），實得 {len(entries) - len(items)}")
check(("ItemName", "MirageWardrobeRender.JacketBulky01") in pairs,
      "幻裝衣櫥渲染載體有登記")
check("MirageWardrobeRender.JacketBulky01" in items, "ItemName fullType 正確抽取")
check(("IG_UI", "HEADER_IG_UI_EN_90fordF350ambulance") in pairs,
      "workshop id 標頭鍵有登記（非玩家文本）")
check(all(isinstance(v, str) and v.strip() for v in entries.values()), "每條理由非空")

# 缺檔＝空集合（漸進登記）。
with tempfile.TemporaryDirectory() as td:
    missing = Path(td) / "missing.json"
    check(tracker.load_untranslatable(missing) == (set(), set()), "缺檔合法退化為空集合")

# canonical identity：UI/Tooltip 等 prefix key 去檔名前綴；ItemName 口徑**同樣 canonical**
# ——B41 前綴形 `ItemName_Base.Foo` 一律落成 runtime 的裸 `Base.Foo`（bare 形不動）。
with tempfile.TemporaryDirectory() as td:
    q = Path(td) / "canonical.json"
    q.write_text(json.dumps({"entries": {
        "UI.json|UI_Foo": "理由",
        "Tooltip.json|Tooltip_Bar": "理由",
        "ItemName.json|Base.X": "理由",
        "ItemName.json|ItemName_Base.Foo": "理由",
    }}), encoding="utf-8", newline="\n")
    cpairs, citems = tracker.load_untranslatable(q)
check(cpairs == {("UI", "Foo"), ("Tooltip", "Bar"),
                 ("ItemName", "Base.X"), ("ItemName", "Base.Foo")},
      f"檔域身分使用與 coverage 相同的 _key_stem/_canon_key：{cpairs}")
check(citems == {"Base.X", "Base.Foo"},
      "ItemName 口徑須是 canonical runtime fullType——留 raw 前綴形時 prep 靠 untr_pairs "
      f"扣得掉、coverage 靠這個集合扣不掉，同一筆裁決兩支工具結論相反：{citems}")

# 壞形狀必須 fail-closed：若退化成空集合，coverage/prep 會無聲重現 398 個雜訊。
for payload, why in [
    ([], "頂層 list"),
    ({}, "缺 entries"),
    ({"entries": []}, "entries 非 dict"),
    ({"entries": {"no-separator": "理由"}}, "key 缺 |"),
    ({"entries": {"ItemName|Base.X": "理由"}}, "檔名漏 .json"),
    ({"entries": {"|Base.X": "理由"}}, "檔名空值"),
    ({"entries": {"ItemName.json|": "理由"}}, "key 空值"),
    ({"entries": {"ItemName.json|Base.X": ""}}, "理由空值"),
    ({"entries": {1: "理由"}}, "非字串 key（JSON 落地成「1」）"),
]:
    with tempfile.TemporaryDirectory() as td:
        q = Path(td) / "u.json"
        q.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
        try:
            tracker.load_untranslatable(q)
            raised = False
        except ValueError:
            raised = True
        check(raised, f"{why} 應 ValueError，不得靜默退化")


def run_coverage(mirrors: dict[str, dict], *, registry: dict | None = None):
    """在臨時 repo 跑 `tracker.cmd_coverage()`，回 `(rc, artifact, stdout)`。

    state 由鏡像實值推導：record 值就是鏡像值的 hash（`records_to_map` 口徑），否則
    coherence gate 會把案例整批擋掉而測不到原本要測的行為。

    stdout 一併回傳：行動分類（「重抽即消除」vs「重抽無效」）只存在於人讀輸出裡，
    只看 artifact 的 `kinds` 測不到「某個 kind 一項指示都不落」這種失效。
    """
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        src = t / "sources"
        en_dir = src / "en"
        state_dir = t / "tracker-state"
        en_dir.mkdir(parents=True)
        state_dir.mkdir()
        mods = {wid: {"extractor_schema": tracker.ITEM_MODULE_SCHEMA,
                      "records": {r: tracker.value_hash(v) for r, v in m.items()}}
                for wid, m in mirrors.items()}
        (state_dir / "en_corpus_hashes.json").write_text(
            json.dumps({"mods": mods}), encoding="utf-8", newline="\n")
        for wid, m in mirrors.items():
            (en_dir / f"{wid}.json").write_text(json.dumps(m), encoding="utf-8", newline="\n")
        (src / "vanilla_keys.json").write_text(
            json.dumps({"keys": [], "scoped_keys": {"ItemName.json": []}}),
            encoding="utf-8", newline="\n")
        if registry is not None:
            (src / "untranslatable_keys.json").write_text(
                json.dumps({"entries": registry}, ensure_ascii=False),
                encoding="utf-8", newline="\n")
        old = (tracker.SOURCES, tracker.EN_TEXT_DIR, tracker.EN_CORPUS_HASHES_JSON)
        buf = io.StringIO()
        try:
            tracker.SOURCES, tracker.EN_TEXT_DIR = src, en_dir
            tracker.EN_CORPUS_HASHES_JSON = state_dir / "en_corpus_hashes.json"
            out = t / "coverage.json"
            with contextlib.redirect_stdout(buf):
                rc = tracker.cmd_coverage(SimpleNamespace(limit=1, out=str(out)))
            return rc, json.loads(out.read_text(encoding="utf-8")), buf.getvalue()
        finally:
            tracker.SOURCES, tracker.EN_TEXT_DIR, tracker.EN_CORPUS_HASHES_JSON = old


# 兩個 consumer 不能只「共用 loader」卻沒真的使用結果：直接跑 coverage 的最小臨時 state，
# 同時守 `script_item_dn`（canonical runtime fullType）與 `translate_en`（canonical prefix）
# 兩口徑。
SCRIPTS = "mods/M/common/media/scripts/items.txt"
rid_dn = f"script_item_dn|{SCRIPTS}|Base.Hidden"
rid_pre = f"script_item_dn|{SCRIPTS}|Base.Prefixed"
rid_en = "translate_en|mods/M/common/media/lua/shared/Translate/EN/UI.json|UI_Internal"
mirror = {rid_dn: "Hidden Item", rid_pre: "Prefixed Item", rid_en: "Internal"}
rc, artifact, _ = run_coverage(
    {"1": mirror},
    registry={"ItemName.json|Base.Hidden": "內部",
              # **以 B41 前綴形登記的同一個物品**：coverage 的 gap 鍵恆是引擎查表用的裸
              # `Base.Prefixed`，這條登記若留 raw `ItemName_Base.Prefixed` 就扣不掉，
              # 而 prep 走 `untr_pairs`（早已 canonical）照樣扣得掉＝同一筆人工裁決在
              # 兩支工具給出相反結論。prep 側的對應案例是 test_prep_item_dn 4c4。
              "ItemName.json|ItemName_Base.Prefixed": "內部",
              "UI.json|UI_Internal": "內部"})
check(rc == 0, f"coverage 最小 state 應 rc=0，實得 {rc}")
check(artifact["totals"]["dn_gap"] == 0,
      "coverage 有使用 untr_items 扣 script_item_dn（含以 B41 前綴形登記的那筆）："
      f"dn_gap={artifact['totals']['dn_gap']} mods={artifact['mods']}")
check(artifact["totals"]["en_gap"] == 0,
      "coverage 有使用 canonical untr_pairs 扣 UI.json|UI_Internal")

# `stale_schema`（號稱現行 schema 卻仍是裸 key）必須與 schema／mirror／stale_state 同屬
# 「重抽即消除」桶。漏掉它時 `kinds == {"stale_schema"}` 的 mod 一項行動分類都不落：
# 它只出現在總數與明細列表裡，讀者看得到數字卻拿不到任何指示，`_pri` 還會把它排在
# 「要修 parser／回報上游」那批之前，把真正要動手的擠出預覽。artifact 的 `kinds` 兩種
# 實作下都一樣，故**必須驗人讀輸出**。
bare_mirror = {f"script_item_dn|{SCRIPTS}|ClassicTire1": "Classic Tire"}
rc, artifact, out = run_coverage({"1": bare_mirror})
check(rc == 0, f"coverage 裸 key state 應 rc=0，實得 {rc}")
check(artifact["undecidable"]["1"]["kinds"] == ["stale_schema"],
      f"現行 schema 的裸 key 未列 stale_schema：{artifact['undecidable']}")
check("重抽即消除" in out,
      f"stale_schema 未歸進「重抽即消除」桶＝該 mod 一項行動指示都沒有：{out!r}")
check("裸 key 殘留" in out,
      f"「重抽即消除」的文案未涵蓋 stale_schema（分類名不符實）：{out!r}")

# 真正玩家可見物品不得被 pattern 誤扣：registry 是逐鍵人工清單，不是 regex。
check("Base.AxleModernTire2" not in items, "正常車零件未被扣除")
check("Base.9mmG17RMagazine" not in items, "正常彈匣未被扣除")

if FAIL:
    print(f"\n❌ test_untranslatable_keys：{FAIL}/{CHECKS} 項失敗", file=sys.stderr)
    sys.exit(1)
print(f"✅ test_untranslatable_keys：{CHECKS} 項全過"
      f"（{len(entries)} 條、雙口徑、壞形狀 fail-closed）")
