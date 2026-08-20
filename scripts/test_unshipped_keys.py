# /// script
# requires-python = ">=3.10"
# ///
"""`unshipped_keys.json`（已裁決不出貨登記）的回歸測試。

背景：有些鍵落在 PZ 不載入的檔名（見 verify_dist.TRANSLATOR_WHITELIST），而我方又
找不到正確落點——通常是無法指認所屬 mod、無從得知上游現行鍵名。這種鍵留在 dist 只是
死重量，但**真相層不能刪**：`sources/_unsorted/CN` 是 As1 lane 的忠實鏡像，刪掉會讓
tracker 的 layer-B 永遠報差異、每次 As1 更新都開假的「待同步」issue。故抑制只發生在
出貨那一步，語意與 vanilla 出貨抑制相同。

要鎖住的四件事：
  1. 登記的鍵不出貨，且 CN/CH 對稱剔除（否則 [2] 鍵集鏡像會炸）。
  2. **清空的檔照樣寫出成空 JSON**——[1]/[9] 逐「檔」比對檔案集合，少一個檔就 FAIL。
     （實作時一度加了「空檔就不寫」，直接炸掉被 vanilla 抑制清空的 6 個既有檔。）
  3. `as1_value` 錨點漂移要報——那是「上游動過這個鍵、該重查 mod」的唯一訊號，
     沒有它這批登記會靜默腐爛。
  4. 登記了但合併結果查無的條目要報「可退役」，避免清單爛掉。

執行：uv run scripts/test_unshipped_keys.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402


def run(entries: dict, merged_cn: dict, merged_ch: dict):
    """把 entries 寫成臨時 unshipped_keys.json，回 (剔除數, drift, unused, cn, ch)。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "unshipped_keys.json"
        p.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
        orig = build_mod.UNSHIPPED_KEYS_JSON
        build_mod.UNSHIPPED_KEYS_JSON = p
        try:
            n, drift, unused = build_mod.suppress_unshipped(merged_cn, merged_ch)
        finally:
            build_mod.UNSHIPPED_KEYS_JSON = orig
        return n, drift, unused, merged_cn, merged_ch


A = {"as1_value": "原值", "reason": "測試"}

# 1. 登記鍵不出貨，CN/CH 對稱剔除
n, drift, unused, cn, ch = run(
    {"Dead.json|K": A},
    {"Dead.json": {"K": "原值", "Other": "留著"}},
    {"Dead.json": {"K": "原值CH", "Other": "留著CH"}})
assert n == 1 and not drift and not unused, f"{n} {drift} {unused}"
assert cn["Dead.json"] == {"Other": "留著"}, cn
assert ch["Dead.json"] == {"Other": "留著CH"}, "CH 未對稱剔除——[2] 鍵集鏡像會炸"

# 2. **關鍵回歸**：清空的檔仍必須留在 merged（寫出成空 JSON），不得整檔消失
n, _, _, cn, ch = run({"Dead.json|K": A},
                      {"Dead.json": {"K": "原值"}}, {"Dead.json": {"K": "原值CH"}})
assert "Dead.json" in cn and cn["Dead.json"] == {}, "清空檔被整個移除——[1]/[9] 檔案集合會 FAIL"
assert "Dead.json" in ch and ch["Dead.json"] == {}, "CH 側同上"

# 3. 錨點漂移要報，但仍照樣剔除（不出貨的裁決不因上游改值而失效）
n, drift, _, cn, _ = run({"Dead.json|K": A},
                         {"Dead.json": {"K": "上游改過的新值"}}, {"Dead.json": {"K": "x"}})
assert n == 1 and cn["Dead.json"] == {}, "漂移時仍應剔除"
assert drift and "K" in drift[0] and "上游改過的新值" in drift[0], f"漂移未報或訊息不足：{drift}"

# 4. 登記但查無 → 報可退役，且不影響其他條目
n, drift, unused, _, _ = run(
    {"Dead.json|K": A, "Nope.json|Gone": A},
    {"Dead.json": {"K": "原值"}}, {"Dead.json": {"K": "x"}})
assert n == 1, f"其他條目不該被未命中條目影響：{n}"
assert unused == ["Nope.json|Gone"], f"未命中未報：{unused}"

# 5. 無 as1_value 錨點者仍剔除、不報漂移（錨點為選用欄）
n, drift, _, cn, _ = run({"Dead.json|K": {"reason": "無錨點"}},
                         {"Dead.json": {"K": "任意值"}}, {"Dead.json": {"K": "x"}})
assert n == 1 and not drift, f"{n} {drift}"

# 6. 空登記 / 檔案不存在 → no-op
n, drift, unused, _, _ = run({}, {"Dead.json": {"K": "v"}}, {"Dead.json": {"K": "v"}})
assert (n, drift, unused) == (0, [], []), "空登記應為 no-op"

# 7. verify 的 suppressed_pairs 必須納入本登記，否則 [1]/[9]/[11] 會把不出貨當成缺鍵
import verify_dist  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    src = Path(td) / "sources"
    src.mkdir()
    # 直接沿用真實 vanilla_keys.json——_load_vanilla_basis 對殘缺基準 fail-closed
    # （核心字串檔缺一即拒，見 verify_dist:454），假造一份反而在測不相干的東西
    (src / "vanilla_keys.json").write_bytes(
        (Path(__file__).resolve().parent.parent / "sources" / "vanilla_keys.json").read_bytes())
    (src / "unshipped_keys.json").write_text(
        json.dumps({"entries": {"Dead.json|K": A}}, ensure_ascii=False), encoding="utf-8")
    pairs = verify_dist.suppressed_pairs(td)
    assert "Dead.json|K" in pairs, f"suppressed_pairs 未納入 unshipped_keys：{pairs}"

# 8. own 原創鍵被 unshipped 抑制時，oracle warning 不得誤稱「撞 vanilla、建議退役」
#    ——owner conflict 的真相層刻意保留，退役會讓上游追蹤與裁決錨點失效。
with tempfile.TemporaryDirectory() as td:
    dist = Path(td) / "CN"
    dist.mkdir()
    ok, details, warn, _, _ = verify_dist.check_cn_parity(
        "", str(dist), {}, {"Dead.json": {"K": {"cn": "原創值"}}},
        as1_available=False, suppressed={"Dead.json|K"}, unshipped={"Dead.json|K"})
    assert ok and not details, details
    joined = "\n".join(warn)
    assert "unshipped_keys" in joined and "人工裁決不出貨" in joined, joined
    assert "vanilla 出貨抑制" not in joined and "建議退役" not in joined, \
        f"人工不出貨被誤報成 vanilla 碰撞／應退役：{joined}"

    _, _, vanilla_warn, _, _ = verify_dist.check_cn_parity(
        "", str(dist), {}, {"Dead.json": {"K": {"cn": "原創值"}}},
        as1_available=False, suppressed={"Dead.json|K"}, unshipped=set())
    assert "vanilla 出貨抑制" in "\n".join(vanilla_warn), vanilla_warn
print("✅ test_unshipped_keys：8 組情境全過")
