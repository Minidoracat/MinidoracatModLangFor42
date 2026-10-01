# /// script
# requires-python = ">=3.10"
# ///
"""`build_mod.own_anchor_drift` 的回歸測試。

背景（2026-10-02）：上游 MOD 改了英文，但 own `en` 錨點沒跟上的鍵，譯文就可能過時。
全量比對時才發現有一大類鍵整批漏掉：英文只寫在 B42 不讀的 `*_EN.txt`，而
`tracker.is_effective` 會把 .txt 判成不載入。這些鍵恰好是本包 .json 譯文唯一能載入的
文字，上游改字時一樣要跟，因此比對必須含有效分支裡的 .txt。

要鎖住的四件事：
  1. 有效分支裡的 .txt 改了英文 → 報出（漏掉就是本測試存在的理由）。
  2. 只在死分支（B41 根目錄、低於 42 的版本夾）的英文不參與比對，不得誤報。
  3. 錨點與上游相符（含另一個 owner 相符）→ 不報。
  4. 上游完全沒有該鍵（配方區塊名等）→ 不報，那是 `report_own_anchor_gaps` 的範圍。

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
h = tracker.value_hash
mods = {
    "1": {"records": {
        f"translate_en|{EN.format(tag='42', file='Sandbox_EN.txt')}|Sandbox_Txt": h("New wording"),
        f"translate_en|{EN.format(tag='41.78', file='Sandbox_EN.txt')}|Sandbox_Dead": h("Dead branch wording"),
        f"translate_en|mods/M/media/lua/shared/Translate/EN/UI_EN.txt|UI_Root": h("B41 root wording"),
        f"translate_en|{EN.format(tag='42', file='UI.json')}|UI_Same": h("Same"),
        f"translate_en|{EN.format(tag='42', file='IG_UI.json')}|IGUI_Shared": h("Owner one"),
    }},
    "2": {"records": {
        f"translate_en|{EN.format(tag='common', file='IG_UI.json')}|IGUI_Shared": h("Owner two"),
    }},
}
own = {
    "Sandbox.json": {"Sandbox_Txt": {"en": "Old wording"}, "Sandbox_Dead": {"en": "Older wording"}},
    "UI.json": {"UI_Root": {"en": "Anything"}, "UI_Same": {"en": "Same"}},
    "IG_UI.json": {"IGUI_Shared": {"en": "Owner two"}},
    "Recipes.json": {"Make Bottle of Vinegar": {"en": "Make Bottle of Vinegar"}},
}

drift = build_mod.own_anchor_drift(own, mods)
assert drift == ["Sandbox.json|Sandbox_Txt"], f"錨點漂移判定錯誤：{drift}"

own["Sandbox.json"]["Sandbox_Txt"]["en"] = "New wording"
assert build_mod.own_anchor_drift(own, mods) == [], "錨點已更新仍被報出"

print("PASS: own_anchor_drift 4 組情境通過")
