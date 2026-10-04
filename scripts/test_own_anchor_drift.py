# /// script
# requires-python = ">=3.10"
# ///
"""`build_mod.own_anchor_drift` 的回歸測試。

背景（2026-10-02）：上游 MOD 改了英文，但 own `en` 錨點沒跟上的鍵，譯文就可能過時。
全量比對時才發現有一大類鍵整批漏掉：英文只寫在 B42 不讀的 `*_EN.txt`，而
`tracker.is_effective` 會把 .txt 判成不載入。這些鍵恰好是本包 .json 譯文唯一能載入的
文字，上游改字時一樣要跟，因此比對必須含有效分支裡的 .txt。

要鎖住的事：
  1. 有效分支裡的 .txt 改了英文 → 報出（漏掉就是本測試存在的理由）。
  2. 只在死分支（B41 根目錄、低於 42 的版本夾）的英文不參與比對，不得誤報。
  3. 錨點與上游相符（含另一個 owner 相符）→ 不報。
  4. 上游完全沒有該鍵（配方區塊名等）→ 不報，那是 `report_own_anchor_gaps` 的範圍。
  5. 同 owner 同分支同時有 .json 與舊 .txt：只比執行期的 .json，舊 .txt 相符不算數
     （2026-10-03 Marriage Companion 漏報 8 鍵的形狀）。
  6. 同 owner 的 common 與版本夾都有 .json：版本夾蓋過 common，common 舊值不算數。
  7. ItemName：同 owner 有 ItemName.json 時 script DisplayName 不算數；只有 B41 前綴鍵
     （引擎不查）時改比 script DisplayName。
  8. 錨點跟上執行期勝出值後不報。
  9. 地圖 `title`／`description` 只比同檔名的上游值：別張地圖的標題不得讓這張地圖誤報
     （2026-10-04 收 18 張地圖標題時，裸鍵比對把 36 鍵全數誤報成過時）。

執行：uv run scripts/test_own_anchor_drift.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402
import tracker  # noqa: E402

EN = "mods/M/{tag}/media/lua/shared/Translate/EN/{file}"
SCRIPT = "mods/M/42/media/scripts/items.txt"
h = tracker.value_hash
mods = {
    "1": {"records": {
        f"translate_en|{EN.format(tag='42', file='Sandbox_EN.txt')}|Sandbox_Txt": h("New wording"),
        f"translate_en|{EN.format(tag='41.78', file='Sandbox_EN.txt')}|Sandbox_Dead": h("Dead branch wording"),
        f"translate_en|mods/M/media/lua/shared/Translate/EN/UI_EN.txt|UI_Root": h("B41 root wording"),
        f"translate_en|{EN.format(tag='42', file='UI.json')}|UI_Same": h("Same"),
        f"translate_en|{EN.format(tag='42', file='IG_UI.json')}|IGUI_Shared": h("Owner one"),
        # 5：同分支 json 已改字、.txt 仍是舊文
        f"translate_en|{EN.format(tag='42', file='Sandbox.json')}|Sandbox_Both": h("JSON new"),
        f"translate_en|{EN.format(tag='42', file='Sandbox_EN.txt')}|Sandbox_Both": h("TXT old"),
        # 6：版本夾蓋過 common
        f"translate_en|{EN.format(tag='common', file='IG_UI.json')}|IGUI_Layer": h("Common old"),
        f"translate_en|{EN.format(tag='42', file='IG_UI.json')}|IGUI_Layer": h("Version new"),
        # 7：ItemName.json 勝過 script DisplayName；只有 B41 前綴鍵時比 script
        f"translate_en|{EN.format(tag='42', file='ItemName.json')}|Base.Gun": h("Gun JSON"),
        f"script_item_dn|{SCRIPT}|Base.Gun": h("Gun script"),
        f"translate_en|{EN.format(tag='42', file='ItemName.json')}|ItemName_Base.Old": h("Prefixed dead"),
        f"script_item_dn|{SCRIPT}|Base.Old": h("Old script"),
    }},
    "2": {"records": {
        f"translate_en|{EN.format(tag='common', file='IG_UI.json')}|IGUI_Shared": h("Owner two"),
        # 9：地圖檔域鍵
        f"translate_en|{EN.format(tag='42', file='Greenleaf.json')}|title": h("Greenleaf,KY"),
        f"translate_en|{EN.format(tag='42', file='Greenleaf.json')}|description": h("Map desc"),
    }},
}
own = {
    "Sandbox.json": {"Sandbox_Txt": {"en": "Old wording"}, "Sandbox_Dead": {"en": "Older wording"},
                     "Sandbox_Both": {"en": "TXT old"}},
    "UI.json": {"UI_Root": {"en": "Anything"}, "UI_Same": {"en": "Same"}},
    "IG_UI.json": {"IGUI_Shared": {"en": "Owner two"}, "IGUI_Layer": {"en": "Common old"}},
    "ItemName.json": {"Base.Gun": {"en": "Gun script"}, "Base.Old": {"en": "Prefixed dead"}},
    "Recipes.json": {"Make Bottle of Vinegar": {"en": "Make Bottle of Vinegar"}},
    "Greenleaf.json": {"title": {"en": "Greenleaf,KY"}, "description": {"en": "Old map desc"}},
    "Other Map.json": {"title": {"en": "Other Map"}, "description": {"en": "Other desc"}},
}

drift = build_mod.own_anchor_drift(own, mods)
assert drift == [
    "Greenleaf.json|description",
    "IG_UI.json|IGUI_Layer", "ItemName.json|Base.Gun", "ItemName.json|Base.Old",
    "Sandbox.json|Sandbox_Both", "Sandbox.json|Sandbox_Txt",
], f"錨點漂移判定錯誤：{drift}"

own["Sandbox.json"]["Sandbox_Txt"]["en"] = "New wording"
own["Sandbox.json"]["Sandbox_Both"]["en"] = "JSON new"
own["IG_UI.json"]["IGUI_Layer"]["en"] = "Version new"
own["ItemName.json"]["Base.Gun"]["en"] = "Gun JSON"
own["ItemName.json"]["Base.Old"]["en"] = "Old script"
own["Greenleaf.json"]["description"]["en"] = "Map desc"
assert build_mod.own_anchor_drift(own, mods) == [], "錨點已更新仍被報出"

print("PASS: own_anchor_drift 9 組情境通過")
