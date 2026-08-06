# /// script
# requires-python = ">=3.10"
# ///
"""As1 快照樹缺席時的 verify 降級行為回歸測試。

背景：As1 快照樹是 Steam 管理的 Workshop 目錄，Valve 改版時直接覆蓋版本資料夾
（2026-08-05 實例：42.19/ 被 42.20/ 取代，舊版無法重新下載＝永久消失）。

要鎖住的三件事：
  1. 快照缺席不得讓整個 verify 停擺——只有 [8] 判 SKIP，其餘照跑。
  2. [1] **不可整個跳過**：own CN 值／placeholder 例外／cn_overrides／原創鍵落地
     都不依賴 As1，一起跳掉會讓 `--allow-missing-as1` 在真相層損壞時仍 exit 0。
  3. SKIP≠PASS：預設退出碼仍為 1；`--allow-missing-as1` 只豁免 SKIP，**不豁免 FAIL**。

執行：uv run scripts/test_verify_as1_skip.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERIFY = Path(__file__).resolve().parent / "verify_dist.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_dist  # noqa: E402


def run(snapshot: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VERIFY), "--snapshot", str(snapshot), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def row_status(out: str, num: str) -> str | None:
    """自報表列取該項狀態（PASS/FAIL/SKIP）——分開搜尋 `[1]` 與 `SKIP` 會漏掉錯配。"""
    m = re.search(rf"^ \[{re.escape(num)}\] .*?\.* (PASS|FAIL|SKIP)", out, re.M)
    return m.group(1) if m else None


def make_missing_snapshot(tmp: Path) -> Path:
    """複製現行 snapshot.json，把 source_tree 改成不存在的版本目錄。"""
    real = json.loads((REPO / "sources" / "snapshot.json").read_text(encoding="utf-8-sig"))
    real["as1"]["source_tree"] = "42.__nonexistent__"
    p = tmp / "snapshot.json"
    p.write_text(json.dumps(real, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


with tempfile.TemporaryDirectory() as td:
    snap = make_missing_snapshot(Path(td))

    # 情境 1：快照缺席 → [8] SKIP、[1] 仍判定、其餘照跑、退出碼 1
    r = run(snap)
    out = r.stdout
    assert row_status(out, "8") == "SKIP", f"[8] 應為 SKIP，實得 {row_status(out, '8')}\n{out[-1200:]}"
    assert row_status(out, "1") in ("PASS", "FAIL"), \
        f"[1] 不得整個跳過（own/例外/override 不依賴 As1），實得 {row_status(out, '1')}"
    for num in ("2", "3", "4", "9", "10", "12"):
        assert row_status(out, num) in ("PASS", "FAIL"), f"As1 缺席時 [{num}] 應照跑"
    assert "SKIP 1" in out, f"SKIP 計數應為 1（僅 [8]）:\n{out[-1200:]}"
    assert " 結果：FAIL" in out, "SKIP 竟判 PASS（release gate 會被靜默放行）"
    assert r.returncode == 1, f"預設退出碼應為 1，實得 {r.returncode}"
    # [1] 降級後仍實際核對了東西（原創鍵數 > 0），不是空跑
    m = re.search(r"原創鍵 (\d+) 個已依 own cn 核對", out)
    assert m and int(m.group(1)) > 0, f"[1] 降級後應仍核對 own 鍵:\n{out[-1200:]}"

    # 情境 2：--allow-missing-as1 明示接受降級才放行
    r2 = run(snap, "--allow-missing-as1")
    assert " 結果：PASS" in r2.stdout, f"明示降級仍判 FAIL:\n{r2.stdout[-1200:]}"
    assert "As1 端未驗證" in r2.stdout, "降級放行未印警語"
    assert r2.returncode == 0, f"--allow-missing-as1 退出碼應為 0，實得 {r2.returncode}"

# 情境 3：As1 缺席時 own 值錯誤仍必須 FAIL——證明 flag 只豁免 SKIP、不豁免 FAIL。
# 直接單元測 check_cn_parity（跑整條 verify 需造完整 dist，成本不成比例）。
with tempfile.TemporaryDirectory() as td:
    dist = Path(td) / "CN"
    dist.mkdir()
    (dist / "UI.json").write_text(
        json.dumps({"UI_OwnKey": "正確值", "UI_As1Key": "隨便"}, ensure_ascii=False),
        encoding="utf-8",
    )
    own_ok = {"UI.json": {"UI_OwnKey": {"cn": "正確值", "ch": "正確值", "en": "x"}}}
    ok, det, _w, _n_exc, n_own = verify_dist.check_cn_parity(
        "__no_such_as1__", str(dist), {}, own_ok, {}, as1_available=False
    )
    assert n_own == 1, f"As1 缺席時 own 鍵仍應被核對，實得 {n_own}"

    own_bad = {"UI.json": {"UI_OwnKey": {"cn": "錯誤值", "ch": "x", "en": "x"}}}
    ok_bad, det_bad, *_ = verify_dist.check_cn_parity(
        "__no_such_as1__", str(dist), {}, own_bad, {}, as1_available=False
    )
    assert not ok_bad, "As1 缺席時 own 值不符竟然過關——flag 會連真錯誤一起放行"
    assert any("值不符" in x for x in det_bad), f"未列出 own 值不符明細：{det_bad}"

    # 未落地的原創鍵同樣要抓
    own_missing = {"UI.json": {"UI_NotInDist": {"cn": "a", "ch": "a", "en": "x"}}}
    ok_m, det_m, *_ = verify_dist.check_cn_parity(
        "__no_such_as1__", str(dist), {}, own_missing, {}, as1_available=False
    )
    assert not ok_m and any("未落地" in x for x in det_m), f"未落地原創鍵應 FAIL：{det_m}"

# 情境 4：快照存在時不得誤判 SKIP（避免降級路徑吃掉正常驗證）
r3 = run(REPO / "sources" / "snapshot.json")
if "As1 快照 CN 目錄不存在" not in r3.stdout:
    assert "SKIP" not in r3.stdout, f"快照存在卻出現 SKIP:\n{r3.stdout[-1200:]}"
    print("  （情境 4：快照存在，已驗證無誤判 SKIP）")
else:
    print("  （情境 4：本機快照亦缺席，跳過——非測試失敗）")

print("PASS: verify As1 缺席降級 4/4 情境通過")
