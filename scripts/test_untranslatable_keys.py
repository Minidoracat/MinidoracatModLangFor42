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

# canonical identity：UI/Tooltip 等 prefix key 去檔名前綴；ItemName fullType 保留 raw。
with tempfile.TemporaryDirectory() as td:
    q = Path(td) / "canonical.json"
    q.write_text(json.dumps({"entries": {
        "UI.json|UI_Foo": "理由",
        "Tooltip.json|Tooltip_Bar": "理由",
        "ItemName.json|Base.X": "理由",
    }}), encoding="utf-8", newline="\n")
    cpairs, citems = tracker.load_untranslatable(q)
check(cpairs == {("UI", "Foo"), ("Tooltip", "Bar"), ("ItemName", "Base.X")},
      f"檔域身分使用與 coverage 相同的 _key_stem/_canon_key：{cpairs}")
check(citems == {"Base.X"}, "ItemName 口徑保留 raw fullType，不去前綴")

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

# 真正玩家可見物品不得被 pattern 誤扣：registry 是逐鍵人工清單，不是 regex。

# 兩個 consumer 不能只「共用 loader」卻沒真的使用結果：直接跑 coverage 的最小臨時 state，
# 同時守 `script_item_dn`（raw fullType）與 `translate_en`（canonical prefix）兩口徑。
with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    src = t / "sources"
    en_dir = src / "en"
    state_dir = t / "tracker-state"
    en_dir.mkdir(parents=True)
    state_dir.mkdir()
    rid_dn = "script_item_dn|mods/M/common/media/scripts/items.txt|Base.Hidden"
    rid_en = "translate_en|mods/M/common/media/lua/shared/Translate/EN/UI.json|UI_Internal"
    mirror = {rid_dn: "Hidden Item", rid_en: "Internal"}
    state = {"mods": {"1": {"extractor_schema": tracker.ITEM_MODULE_SCHEMA,
                             "records": {r: tracker.value_hash(v)
                                         for r, v in mirror.items()}}}}
    (state_dir / "en_corpus_hashes.json").write_text(
        json.dumps(state), encoding="utf-8", newline="\n")
    (en_dir / "1.json").write_text(json.dumps(mirror), encoding="utf-8", newline="\n")
    (src / "vanilla_keys.json").write_text(
        json.dumps({"keys": [], "scoped_keys": {"ItemName.json": []}}),
        encoding="utf-8", newline="\n")
    (src / "untranslatable_keys.json").write_text(
        json.dumps({"entries": {"ItemName.json|Base.Hidden": "內部",
                                "UI.json|UI_Internal": "內部"}}),
        encoding="utf-8", newline="\n")
    old = (tracker.SOURCES, tracker.EN_TEXT_DIR, tracker.EN_CORPUS_HASHES_JSON)
    try:
        tracker.SOURCES, tracker.EN_TEXT_DIR = src, en_dir
        tracker.EN_CORPUS_HASHES_JSON = state_dir / "en_corpus_hashes.json"
        out = t / "coverage.json"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = tracker.cmd_coverage(SimpleNamespace(limit=1, out=str(out)))
        artifact = json.loads(out.read_text(encoding="utf-8"))
    finally:
        tracker.SOURCES, tracker.EN_TEXT_DIR, tracker.EN_CORPUS_HASHES_JSON = old
check(rc == 0, f"coverage 最小 state 應 rc=0，實得 {rc}")
check(artifact["totals"]["dn_gap"] == 0, "coverage 有使用 untr_items 扣 script_item_dn")
check(artifact["totals"]["en_gap"] == 0,
      "coverage 有使用 canonical untr_pairs 扣 UI.json|UI_Internal")
check("Base.AxleModernTire2" not in items, "正常車零件未被扣除")
check("Base.9mmG17RMagazine" not in items, "正常彈匣未被扣除")

if FAIL:
    print(f"\n❌ test_untranslatable_keys：{FAIL}/{CHECKS} 項失敗", file=sys.stderr)
    sys.exit(1)
print(f"✅ test_untranslatable_keys：{CHECKS} 項全過"
      f"（{len(entries)} 條、雙口徑、壞形狀 fail-closed）")
