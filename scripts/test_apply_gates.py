#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""回歸測試：補譯管線末段兩支消費端的 fail-closed 閘門。

`prep_mod_strings` 對「無法判定的 wid」與「多 owner 同鍵不同英文」是非零退出，但它
**仍然寫出 artifact**（不寫的話舊的成功檔會留在原地被誤用，更糟）。因此真正的防線在
消費端：`apply_wf_result` 必須看得懂那兩個欄位並硬拒。這兩道 gate 先前完全沒有測試——
把 `isinstance` 檢查改回 `src.get(x) or []`、或整段刪掉，12 支回歸測試與 self-test 仍
全綠，而那正是 codex review 抓到的 bug 形狀（舊版 prep 產出的 artifact 根本沒這兩欄，
於是從縫裡走掉＝#221 的管線級重演）。

另驗 `apply_translations` 不得把 `_note` 等人工裁決記錄覆寫掉。
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_translations  # noqa: E402
import apply_wf_result  # noqa: E402

FAIL = 0
CHECKS = 0


def check(cond: bool, msg: str) -> None:
    # 計數由呼叫次數派生，不寫死（寫死支數時加了案例卻漏改，就會輸出騙人的「N 組通過」）
    global FAIL, CHECKS
    CHECKS += 1
    if not cond:
        print(f"❌ {msg}", file=sys.stderr)
        FAIL += 1


# **每個案例都必須帶合格譯文**：`run_gate` 若讓 `translations` 留空，流程會在後面的
# 「漏譯」檢查同樣回傳 1——於是把兩道 gate 整段刪掉，案例照樣綠。測試要有鑑別力，
# 唯一的非零來源必須是被測的那道 gate。
TR = [{"en": "Red Dress", "ch": "紅裙", "cn": "红裙"}]


def run_gate(strings: object, translations: list | None = None, *,
             raw_result: object = None) -> int:
    """把 artifact 寫進暫存檔後跑 `apply_wf_result.main()`，回退出碼。

    `raw_result` 讓測試能寫出**頂層就不是物件**的 result 檔；一律包成
    `{"translations": …}` 只測得到欄位型別，測不到 `isinstance(res, dict)` 那條分支。
    """
    with tempfile.TemporaryDirectory() as td:
        sp, rp = Path(td) / "s.json", Path(td) / "r.json"
        for p, data in ((sp, strings),
                        (rp, raw_result if raw_result is not None
                         else {"translations": TR if translations is None
                               else translations})):
            io.open(p, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))
        old = sys.argv
        try:
            sys.argv = ["apply_wf_result", "--result", str(rp), "--strings", str(sp),
                        "--out-prefix", str(Path(td) / "out")]
            return apply_wf_result.main()
        finally:
            sys.argv = old


OK = {"strings": [{"en": "Red Dress", "keys": 1, "files": ["ItemName"],
                   "key_samples": ["ItemName|Base.Dress"], "wid": ["1"]}],
      "_gap": {"ItemName|Base.Dress": "Red Dress"},
      "_unchecked": [], "_owner_conflicts": {}}

# 0. **控制組先跑**：合格 artifact ＋ 合格譯文必須回 0。這條綠了，下面每一個 1 才能
#    歸因到被測的 gate（否則測的是「一律拒絕」）。
check(run_gate(OK) == 0, "0. 合格 artifact 被誤拒＝其餘案例的非零無法歸因到 gate")

# 1. 缺欄位＝舊版 prep 的陳舊 artifact。**這是最該擋的形狀**：`strings`／`_gap` 長得跟
#    「這個 mod 沒問題」一模一樣，寫成 `src.get(x) or []` 就會判成安全通過。
for miss in ("_unchecked", "_owner_conflicts"):
    check(run_gate({k: v for k, v in OK.items() if k != miss}) == 1,
          f"1. 缺 {miss} 欄位未被拒絕（陳舊 artifact 從縫裡走掉）")

# 2. 欄位存在但型別錯（空容器也不行——空 dict 當 list 一樣是壞 schema）
check(run_gate({**OK, "_unchecked": {}}) == 1, "2. `_unchecked` 型別為 dict 未被拒絕")
check(run_gate({**OK, "_owner_conflicts": []}) == 1, "2. `_owner_conflicts` 型別為 list 未被拒絕")

# 3. 頂層不是物件（合法 JSON 但形狀錯）須受控拒絕，不得拋 AttributeError traceback。
#    `--strings` 與 `--result` 兩側都要驗——同一類不可信 artifact 不該一邊受控一邊裸奔。
for junk in ([], "x", 3):
    for side in ("strings", "result-field", "result-top"):
        try:
            if side == "strings":
                rc = run_gate(junk)
            elif side == "result-field":
                rc = run_gate(OK, junk)          # {"translations": <junk>}
            else:
                rc = run_gate(OK, raw_result=junk)   # result 檔頂層就是 junk
        except (AttributeError, TypeError, KeyError) as exc:
            rc = f"未捕捉例外 {type(exc).__name__}: {exc}"
        check(rc == 1, f"3. --{side} 頂層 {type(junk).__name__} 未受控拒絕，實得 {rc}")

# 4. 非空 `_unchecked`／`_owner_conflicts` 照樣拒絕（原本就有的行為，一併釘住）
check(run_gate({**OK, "_unchecked": ["1：無 tracker 基準"]}) == 1, "4. 非空 `_unchecked` 未被拒絕")
check(run_gate({**OK, "_owner_conflicts": {"ItemName|Base.X": {"1": "A", "2": "B"}}}) == 1,
      "4. 非空 `_owner_conflicts` 未被拒絕")

# 6. `apply_translations` 不得覆寫 `_note`：那是多 owner 中性譯法／型號依據的人工裁決
#    記錄，覆寫成三欄會把裁決依據靜默清掉。
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "sources").mkdir()
    own = root / "sources" / "own_translations.json"
    io.open(own, "w", encoding="utf-8").write(json.dumps({"entries": {"ItemName.json": {
        "Base.Clip": {"en": "Clip", "ch": "彈匣", "cn": "弹匣", "_note": "多 owner 中性譯法"},
    }}}, ensure_ascii=False))
    # `main()` 無條件讀 vanilla 基準，缺檔會在待測邏輯前 FileNotFound
    io.open(root / "sources" / "vanilla_keys.json", "w", encoding="utf-8").write(
        json.dumps({"keys": [], "scoped_keys": {"ItemName.json": []}}, ensure_ascii=False))
    inp = root / "in.json"
    io.open(inp, "w", encoding="utf-8").write(json.dumps({"ItemName.json": {
        "Base.Clip": {"en": "Clip", "ch": "彈匣 (改)", "cn": "弹匣 (改)"},
    }}, ensure_ascii=False))
    old_root, old_base, old_argv = (apply_translations.ROOT,
                                    apply_translations.BASE_GAME, sys.argv)
    try:
        apply_translations.ROOT = root
        # 隔離本機遊戲安裝：測的是 `_note` 保留，不該受本機 vanilla 語料影響
        apply_translations.BASE_GAME = root / "no_such_base_game"
        sys.argv = ["apply_translations", str(inp)]
        rc = apply_translations.main()
    finally:
        (apply_translations.ROOT, apply_translations.BASE_GAME,
         sys.argv) = old_root, old_base, old_argv
    entry = json.loads(io.open(own, encoding="utf-8").read())["entries"]["ItemName.json"]["Base.Clip"]
    check(rc == 0, f"6. apply_translations 非零退出：{rc}")
    check(entry.get("_note") == "多 owner 中性譯法",
          f"6. `_note` 人工裁決記錄被覆寫掉：{entry}")
    check(entry["ch"] == "彈匣 (改)", f"6. 譯文未更新：{entry}")

if FAIL:
    print(f"\nFAIL: {FAIL} 項未通過", file=sys.stderr)
    sys.exit(1)
print(f"PASS: apply 管線 fail-closed 閘門 {CHECKS} 組斷言通過")
