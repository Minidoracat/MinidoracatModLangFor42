# /// script
# requires-python = ">=3.10"
# ///
"""收尾閘門 ⑦ [4]（本包不撞本體翻譯包的鍵）的回歸測試；不讀本機安裝，CI 可跑。

⑦ 本身要本機遊戲與 LangFor42 才能跑，這裡用合成資料鎖住兩件事：
  1. 撞鍵判定：未登記的交集一律列出、登記可共存的放行、登記但已不再撞的列為可移除。
  2. `langfor42_shared_keys.json` 壞形（缺 entries、鍵不是「檔名.json|鍵」、理由空白）一律擋下。

執行：uv run scripts/test_langfor42_shared.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_vanilla_no_override as gate  # noqa: E402

clash, gone = gate.shared_with_base_pack(
    {"ItemName.json|Base.A", "ItemName.json|Base.B", "UI.json|UI_Mod"},
    {"ItemName.json|Base.A", "ItemName.json|Base.B", "UI.json|UI_Base"},
    {"ItemName.json|Base.B": "原版不顯示", "Recipes.json|Recipe_Gone": "舊條目"},
)
assert clash == ["ItemName.json|Base.A"], clash
assert gone == ["Recipes.json|Recipe_Gone"], gone

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "langfor42_shared_keys.json"
    for bad in ({}, {"entries": []}, {"entries": {"UI.json|UI_X": " "}},
                {"entries": {"UI_X": "理由"}}, {"entries": {"UI.json|": "理由"}}):
        p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        try:
            gate.load_shared_allow(p)
        except ValueError:
            continue
        raise AssertionError(f"壞形沒擋下：{bad}")
    p.write_text(json.dumps({"entries": {"UI.json|UI_X": "理由"}}, ensure_ascii=False), encoding="utf-8")
    assert gate.load_shared_allow(p) == {"UI.json|UI_X": "理由"}

# 本體翻譯包讀取（⑦ [4] 與 prep 共用）：目錄缺、量級不對都 raise，足量時回 CH∪CN 聯集。
with tempfile.TemporaryDirectory() as td:
    b = Path(td)
    for case in ("缺目錄", "量級不對"):
        try:
            gate.base_pack_pairs(b)
        except ValueError:
            pass
        else:
            raise AssertionError(f"base_pack_pairs {case}沒擋下")
        for lang in ("CH", "CN"):
            (b / lang).mkdir(exist_ok=True)
    filler = {f"UI_F{i}": "x" for i in range(gate.MIN_BASE_PACK_KEYS)}
    (b / "CH" / "UI.json").write_text(json.dumps(filler), encoding="utf-8")
    (b / "CN" / "IG_UI.json").write_text(json.dumps({"IGUI_OnlyCN": "x"}), encoding="utf-8")
    got = gate.base_pack_pairs(b)
    assert "IG_UI.json|IGUI_OnlyCN" in got and "UI.json|UI_F0" in got, sorted(got)[:3]
    assert len(got) == gate.MIN_BASE_PACK_KEYS + 1, len(got)

print("✅ test_langfor42_shared：撞鍵判定、可共存清單形狀與本體翻譯包讀取檢查全過")
