# /// script
# requires-python = ">=3.10"
# ///
"""verify [15] ItemName 死鍵棘輪的回歸測試。

背景：`ItemName_<Module>.<Item>` 是 B41 `ItemName_EN.txt` 時代的鍵形，**B42 不讀它**——
`Translator.tryFillMapFromFile()` 把 JSON 鍵原封不動存進 map，`getItemNameFromFullType()`
只以裸 `Module.Item` 查表（42.20.2 反編譯實證）。前綴鍵若沒有對應裸鍵，該物品名等於沒翻譯，
而 build／CH parity／lint 三道全綠——2026-08-10 就是這樣漏了 1,034 鍵。

要鎖住的四件事：
  1. 只有前綴鍵、無裸鍵 → FAIL。這是本檢查存在的理由。
  2. **`Base.` 開頭不得整批放行**。MOD 同樣能往 `module Base` 加物品（實例 `Base.44Clip20`
     是 mod 的高容量彈匣，vanilla 只有 `Base.44Clip`）。當初就是誤判「Base.* ＝ vanilla」
     才漏了 843 鍵，只認 vanilla scoped 基準。
  3. 已登記 allowlist 者放行——但 allowlist 是「查證後的暫緩」，不是「不用管」。
  4. 反向棘椪：裸鍵已補好或前綴鍵已消失時，allowlist 條目要出 WARN 提醒移除，
     否則清單會爛掉沒人發現。

執行：uv run scripts/test_itemname_dead_keys.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_dist  # noqa: E402


def run(dist_itemname: dict, vanilla: list[str], allow: dict) -> tuple[list[str], list[str]]:
    """組臨時 repo + dist，回 ([15] 的 fail, warn)。"""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "sources"
        src.mkdir()
        (src / "vanilla_keys.json").write_text(
            json.dumps({"scoped_keys": {"ItemName.json": vanilla}}, ensure_ascii=False),
            encoding="utf-8")
        (src / "itemname_dead_allowlist.json").write_text(
            json.dumps({"entries": allow}, ensure_ascii=False), encoding="utf-8")
        ch = Path(td) / "CH"
        ch.mkdir()
        (ch / "ItemName.json").write_text(json.dumps(dist_itemname, ensure_ascii=False),
                                          encoding="utf-8")
        ok, fail, warn = verify_dist.check_itemname_dead_keys(td, str(ch))
        assert ok == (not fail), "ok 與 fail 清單不一致"
        return fail, warn


# 1. 只有前綴鍵、無裸鍵 → FAIL
fail, _ = run({"ItemName_Foo.Bar": "巴"}, [], {})
assert fail, "無裸鍵的前綴鍵未被抓到"
assert "Foo.Bar" in fail[0], f"失敗訊息應指名裸鍵：{fail[0]}"

# 2. 有裸鍵 → PASS（前綴鍵是重複但無害）
fail, _ = run({"ItemName_Foo.Bar": "巴", "Foo.Bar": "巴"}, [], {})
assert not fail, f"已有裸鍵仍誤報：{fail}"

# 3. 裸鍵屬 vanilla → 放行（本體已自帶，補了會撞名，見 gate [12]）
fail, _ = run({"ItemName_Base.Axe": "斧頭"}, ["Base.Axe"], {})
assert not fail, f"vanilla 鍵被誤報：{fail}"

# 4. **關鍵回歸**：`Base.` 開頭但不在 vanilla 基準 → 仍須 FAIL
#    （2026-08-10 的漏判就是把整個 Base.* 當成 vanilla）
fail, _ = run({"ItemName_Base.44Clip20": "44彈匣(20發)"}, ["Base.44Clip"], {})
assert fail, "mod 塞進 module Base 的物品被誤放行——這正是當初漏 843 鍵的原因"

# 5. 已登記 allowlist → 放行
fail, _ = run({"ItemName_Foo.Bar": "巴"}, [], {"Foo.Bar": "上游查無此 item，wid 不明"})
assert not fail, f"已登記豁免仍誤報：{fail}"

# 6. 反向棘輪：裸鍵已補好，allowlist 條目該出 WARN
fail, warn = run({"ItemName_Foo.Bar": "巴", "Foo.Bar": "巴"}, [], {"Foo.Bar": "舊理由"})
assert not fail, "已補裸鍵不該 FAIL"
assert warn and "Foo.Bar" in warn[0], f"過時 allowlist 條目未出 WARN：{warn}"

# 6b. 前綴鍵整個消失（上游改名/移除），allowlist 條目也該出 WARN
fail, warn = run({"Other.Key": "其他"}, [], {"Foo.Bar": "舊理由"})
assert not fail and warn, f"前綴鍵已不存在時應出 WARN：fail={fail} warn={warn}"

# 7. 空 dist、無前綴鍵 → PASS 且零 WARN
fail, warn = run({"Foo.Bar": "巴"}, [], {})
assert not fail and not warn, f"乾淨輸入被誤報：{fail} {warn}"

print("✅ test_itemname_dead_keys：7 組情境全過")
