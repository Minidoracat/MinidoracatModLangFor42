#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""回歸測試：owner 衝突的 `has_json_en`／`en_source` 加註（#245 項目 1）。

裁決 `translate` 還是 `unship` 的承重事實是「抑制後這個 owner 的玩家看到自己 mod 的
英文，還是 `getTextInternal()` 回傳的字面鍵名」。這一步先前靠人逐一翻
`sources/en/<wid>.json` 的 rid 路徑判斷，是最容易判錯的環節——`UI_trait_BloodlustDesc`
就是因為漏看 Dynamic-Traits 只有 `UI_EN.txt` 而先裁成 `translate`，靠三方 review 才翻案。

四個承重不變量，缺任一個這個加註都會反過來製造錯誤裁決：

1. **`census_signature` 不受加註影響**。加註若混進 census 的值，全部既有裁決的
   signature 會一次失效（現況 382 條台帳全部要重簽）。這是本檔最重要的一條。
2. **`loadable_json` 兩個條件都要驗**。只看副檔名會把 `UI_EN.json`（是 json 但檔名不在
   `Translator.BY_NAME`）誤判成有 EN 底層；只看檔名會把 `UI_EN.txt` 誤判成可載入。
3. **script 來源不得與死檔混為一談**。`script_item_dn` 的 `has_json_en` 是 false，但抑制後
   引擎會走 `getItemNameFromFullType()` → `Item.getDisplayName()` fallback、**仍顯示英文**；
   死檔則顯示字面鍵名。兩者後果相反，故 `en_source` 必須一起輸出。
4. **`src` out-param 與 `out` 全程同步**。`converge_owner` 有三處撤銷分支（鏡像缺值、
   首次即空值、純空白），漏 pop 任何一處就會留下已撤銷鍵的來源標記，讓下一個同鍵 owner
   拿到別人的來源。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prep_mod_strings as pms  # noqa: E402

FAIL = 0
CHECKS = 0


def check(cond: bool, msg: str) -> None:
    # 計數由呼叫次數派生，不寫死（寫死支數時加了案例卻漏改，就會輸出騙人的「N 組通過」）
    global FAIL, CHECKS
    CHECKS += 1
    if not cond:
        print(f"❌ {msg}", file=sys.stderr)
        FAIL += 1


# --- 1. loadable_json：兩個條件都要滿足 ------------------------------------- #
for base, want, why in [
    ("UI.json", True, "白名單 stem ＋ .json"),
    ("IG_UI.json", True, "白名單 stem ＋ .json"),
    ("ItemName.json", True, "白名單 stem ＋ .json"),
    ("UI_EN.txt", False, "legacy .txt：Translator 路徑寫死 .json"),
    ("Tooltip_EN.txt", False, "legacy .txt"),
    ("UI_EN.json", False, "是 .json 但 stem 不在 BY_NAME（As1 上游真的這樣出貨過）"),
    ("Sandbox_EN.json", False, "同上"),
    ("Compendium.json", False, "stem 不在 BY_NAME"),
    ("UI", False, "沒有副檔名"),
]:
    check(pms.loadable_json(base) is want, f"loadable_json({base!r}) 應為 {want}（{why}）")


# --- 2. annotate：三態語意 --------------------------------------------------- #
owners = {"A/mod": "Alpha", "B/mod": "Bravo", "C/mod": "Charlie", "D/mod": "Delta"}
srcs = {"A/mod": "UI.json", "B/mod": "UI_EN.txt",
        "C/mod": pms.EN_SOURCE_SCRIPT}          # D 刻意缺席
ann = pms.annotate(owners, srcs)

check(ann["A/mod"] == {"en": "Alpha", "has_json_en": True, "en_source": "UI.json"},
      "可載入 .json → has_json_en=True")
check(ann["B/mod"] == {"en": "Bravo", "has_json_en": False, "en_source": "UI_EN.txt"},
      "死檔 → has_json_en=False 且 en_source 保留檔名（判斷代價要靠它）")
check(ann["C/mod"] == {"en": "Charlie", "has_json_en": False,
                       "en_source": pms.EN_SOURCE_SCRIPT},
      "script 來源 → has_json_en=False，但 en_source 標 script 以別於死檔")
check(ann["D/mod"] == {"en": "Delta", "has_json_en": False, "en_source": None},
      "en_src 與 census 不同步時保守判無 EN 底層，不靜默放行")
check(set(ann) == set(owners), "annotate 不得增刪 owner")
check(all(ann[o]["en"] == owners[o] for o in owners), "annotate 不得改動 en 原值")


# --- 3. census_signature 不受加註影響（本檔最重要的一條）--------------------- #
sig_before = pms.census_signature(owners)
pms.annotate(owners, srcs)
check(pms.census_signature(owners) == sig_before,
      "annotate 不得就地改動 owners（否則 signature 漂移＝全部裁決失效）")
# 加註後的形狀**不可**被當成 census 餵給 signature：值從 str 變 dict，hash 必然不同。
# 這條不是要求「相等」，而是釘住「census 與 artifact 是兩份資料」這個分層。
check(pms.census_signature({o: str(v) for o, v in ann.items()}) != sig_before,
      "加註形狀與 census 形狀的 signature 本就不同——兩者不可混用（分層釘樁）")


# --- 4. converge_owner 的 src out-param 與 out 全程同步 --------------------- #
def rid_en(root: str, branch: str, fname: str, key: str) -> str:
    return f"translate_en|mods/{root}/{branch}/media/lua/shared/Translate/EN/{fname}|{key}"


EFF = {"m": {"common"}}


def run(recs: dict, *, dn_gap=None):
    src: dict[tuple[str, str], str] = {}
    out = pms.converge_owner(recs, recs, EFF, vanilla=set(),
                             dn_gap=dn_gap or {}, src=src)
    return out, src


# 4a. 正常路徑：out 與 src 的鍵集必須一致
r_ok = rid_en("m", "common", "UI.json", "UI_X")
out, src = run({r_ok: "Hello"})
check(set(out) == set(src) and src[("m", "UI|UI_X")] == "UI.json",
      "正常路徑：out 與 src 鍵集一致且來源檔名正確")

# 4b–4d 的撤銷分支**必須用「common 先寫入、版本夾再撤銷」的兩 rid 形狀**：單 rid 時
# `src` 從未被寫入過，pop 與否都是空 dict＝漏 pop 也照樣綠（實測破壞 `src.pop` 後
# 單 rid 版本 24/24 全過）。兩 rid 才對應 `converge_owner` 註解描述的真實情形——
# 「走到這裡的缺值 rid 若是版本夾那筆，它才是 runtime 勝出者」。
EFF_V = {"m": {"common", "42"}}
r_com = rid_en("m", "common", "UI.json", "UI_X")
r_ver = rid_en("m", "42", "UI.json", "UI_X")
OK_X = ("m", "UI|UI_X")


def run_two(mirror: dict):
    src: dict[tuple[str, str], str] = {}
    recs = {r_com: "Hello", r_ver: "whatever"}
    out = pms.converge_owner(recs, mirror, EFF_V, vanilla=set(), dn_gap={}, src=src)
    return out, src


# 4b. 版本夾那筆鏡像缺值 → 整鍵撤銷（執行期值未知，不得回退 common 舊值），src 跟著 pop
out2, src2 = run_two({r_com: "Hello"})
check(out2 == {} and src2 == {},
      "鏡像缺值：已寫入的 out 與 src 都必須撤銷（漏 pop src 會留孤兒來源）")

# 4c. 首次即空值 → 撤銷。**這一支的 `src.pop` 是防禦性的**：`ok not in seen_en` 成立時
#     該鍵從未成功寫入，src 必為空。留著是為了讓三個撤銷分支形狀一致，不是活路徑。
out3, src3 = run({r_com: ""})
check(out3 == {} and src3 == {}, "首次即空值：out 與 src 都撤銷")

# 4d. 版本夾那筆是純空白 → 引擎一律覆寫、執行期顯示空白，故撤銷已寫入的 common 值
out4, src4 = run_two({r_com: "Hello", r_ver: "   "})
check(out4 == {} and src4 == {},
      "純空白覆寫：已寫入的 out 與 src 都必須撤銷（漏 pop src 會留孤兒來源）")

# 4e. 判定粒度是 (owner, 落點檔, key)——同一 owner 可以一個檔可載入、另一個是死檔。
#     用「該 owner 任一 rid 是不是 .json」判就會把 Tooltip 那筆也標成 true。
recs_mixed = {rid_en("m", "common", "UI.json", "UI_A"): "A",
              rid_en("m", "common", "Tooltip_EN.txt", "Tooltip_B"): "B"}
out5, src5 = run(recs_mixed)
ann5 = {fk: pms.annotate({"w/m": out5[("m", fk)]}, {"w/m": src5[("m", fk)]})
        for _, fk in out5}
check(ann5["UI|UI_A"]["w/m"]["has_json_en"] is True
      and ann5["Tooltip|Tooltip_B"]["w/m"]["has_json_en"] is False,
      "判定粒度：同一 owner 的不同落點檔各自判定，不可整個 owner 一起標")

# 4f. 同鍵多來源時 src 必須跟著勝出者：版本夾疊在 common 之上（引擎語意）。
#     `common` 在死檔、版本夾在可載入 json → 勝出者是後者，has_json_en 應為 True。
EFF2 = {"m": {"common", "42"}}
recs_pri = {rid_en("m", "common", "UI_EN.txt", "UI_C"): "old",
            rid_en("m", "42", "UI.json", "UI_C"): "new"}
src6: dict[tuple[str, str], str] = {}
out6 = pms.converge_owner(recs_pri, recs_pri, EFF2, vanilla=set(), dn_gap={}, src=src6)
check(out6[("m", "UI|UI_C")] == "new" and src6[("m", "UI|UI_C")] == "UI.json",
      "分支優先序：src 必須跟著勝出的版本夾那筆，不是先寫入的 common")

# 4g. `src=None`（既有呼叫端）不得改變行為
out7 = pms.converge_owner({r_ok: "Hello"}, {r_ok: "Hello"}, EFF,
                          vanilla=set(), dn_gap={})
check(out7 == out, "src=None 時回傳值與帶 src 時相同（既有呼叫端零影響）")

if FAIL:
    print(f"\n❌ test_owner_json_en：{FAIL}/{CHECKS} 項失敗", file=sys.stderr)
    sys.exit(1)
print(f"✅ test_owner_json_en：{CHECKS} 項全過"
      "（loadable_json 兩條件、annotate 三態、signature 不受影響、src/out 全程同步）")
