#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""回歸測試：owner 衝突的 `has_json_en`／`en_source` 加註與 `OWNER_CONFLICTS.md`
渲染（#245 項目 1、2）。

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
5. **`OWNER_CONFLICTS.md` 的表格不得被值裡的 `|` 拆欄**。落點鍵本身就是
   `IG_UI|IGUI_X` 這種形狀，而 GFM 的表格切欄發生在 inline 解析之前——**code span
   不保護 `|`**。漏轉義會讓整列往右錯位一格，而 Markdown 不會報錯。
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

# 4f'. **反方向**：`common` 在可載入 json、有效版本夾只有死檔 `_EN.txt`。
#      `out` 的值仍照分支優先序取版本夾那筆（引擎語意），但 `src` 不得被降級成死檔
#      ——錯標死檔會讓 OWNER_CONFLICTS.md 渲染 `_(死檔 …)_`、錯告「unship 後看到字面
#      鍵名」，實際上 common 的可載入 json 仍會顯示該 mod 英文（unship 代價被高估）。
#      實例：`3437429771/Injectors` 的 ContextMenu_Inject（common/ContextMenu.json
#      ＋ 42/ContextMenu_EN.txt）曾因此在 OWNER_CONFLICTS.md 被標成死檔。
#      **兩筆 EN 刻意給不同值**：值相同時測不到「誤把 `_src_rank` 套到 out」——那會讓
#      out 停在 common 的舊值而測試照樣綠。out 必須仍是版本夾那筆。
recs_rev = {rid_en("m", "common", "ContextMenu.json", "ContextMenu_Inject"): "Inject",
            rid_en("m", "42", "ContextMenu_EN.txt", "ContextMenu_Inject"): "Inject Serum"}
src6b: dict[tuple[str, str], str] = {}
out6b = pms.converge_owner(recs_rev, recs_rev, EFF2, vanilla=set(), dn_gap={}, src=src6b)
OK_INJ = ("m", "ContextMenu|ContextMenu_Inject")
check(out6b[OK_INJ] == "Inject Serum" and src6b[OK_INJ] == "ContextMenu.json",
      "src 優先序：死檔不得覆蓋同鍵的可載入 json，但 out 仍取版本夾那筆（Injectors 形狀）")

# 4f''. 同一分支內同時有 json 與死檔（`3650035249/CAExtendedCategories` 形狀：
#       common 下並存 IG_UI.json 與 IG_UI_EN.txt）→ src 必須是 json，與迭代順序無關。
for order in (("IG_UI.json", "IG_UI_EN.txt"), ("IG_UI_EN.txt", "IG_UI.json")):
    recs_same = {rid_en("m", "common", order[0], "IGUI_ItemCat_AmmoBox"): "Ammo - Box",
                 rid_en("m", "common", order[1], "IGUI_ItemCat_AmmoBox"): "Ammo - Box"}
    s: dict[tuple[str, str], str] = {}
    pms.converge_owner(recs_same, recs_same, EFF2, vanilla=set(), dn_gap={}, src=s)
    check(s[("m", "IG_UI|IGUI_ItemCat_AmmoBox")] == "IG_UI.json",
          f"src 優先序：同分支 json 勝過死檔，與迭代順序無關（{order[0]} 先）")

# 4f'''. script 已寫入 src 後，遇到同鍵的死檔 translate_en。值層 translate_en 勝
#        （引擎先查 ItemName map），但 src 不得從 script 降級成死檔——script 走
#        `Item.getDisplayName()` fallback **仍會顯示英文**，死檔則顯示字面鍵名。
#        兩個構造陷阱，踩到任一個這條就是空轉的假保護：
#          * `dn_gap` 那條路徑要有 `script_item_dn` rid 才會寫入 script 來源
#            （`dn_val` 取自 `tracker.winning_dn_text`），只給 translate_en 會讓
#            script 那筆從未寫入。
#          * 死檔的 **stem 必須仍在白名單**。裸 fullType 鍵沒有前綴可路由，
#            `target_file()` 只能靠 stem——`ItemName_EN` 不在白名單會回 None，
#            那筆 translate_en 直接 `continue`，修正前後 src 都是 script（實測空轉）。
#            用 `ItemName.txt`：stem 在白名單、副檔名非 json ⇒ 進得了迴圈且仍是死檔。
rid_dn = "script_item_dn|mods/m/common/media/scripts/items.txt|Base.X"
rid_dead = rid_en("m", "common", "ItemName.txt", "Base.X")
check(pms.target_file("ItemName", "Base.X") == "ItemName"
      and not pms.loadable_json("ItemName.txt"),
      "構造前提：ItemName.txt 進得了迴圈（stem 在白名單）且仍是死檔（非 json）")
recs_sc = {rid_dn: "Thing", rid_dead: "Thing"}
src8: dict[tuple[str, str], str] = {}
out8 = pms.converge_owner(recs_sc, recs_sc, EFF2, vanilla=set(),
                          dn_gap={"m": {"Base.X"}}, src=src8)
OK_DN = ("m", "ItemName|Base.X")
check(out8.get(OK_DN) == "Thing" and src8.get(OK_DN) == pms.EN_SOURCE_SCRIPT,
      "src 優先序：死檔不得把 script 來源降級（script 仍顯示英文, 死檔顯示字面鍵名）")

# 4g. `src=None`（既有呼叫端）不得改變行為
out7 = pms.converge_owner({r_ok: "Hello"}, {r_ok: "Hello"}, EFF,
                          vanilla=set(), dn_gap={})
check(out7 == out, "src=None 時回傳值與帶 src 時相同（既有呼叫端零影響）")


# --- 5. OWNER_CONFLICTS.md 渲染 ------------------------------------------- #
check(pms._md_pipe("IG_UI|IGUI_X") == "IG_UI\\|IGUI_X", "_md_pipe 轉義 |")
check(pms._md_cell("a|b") == "a\\|b", "_md_cell 轉義 |")
check(pms._md_cell("<br>x") == "&lt;br&gt;x", "_md_cell 轉義角括號（避免被當 HTML）")
check(pms._md_cell("a\nb") == "a b", "_md_cell 把換行折成空白以維持單列")
check(pms._md_cell("x" * 20, 10).endswith("…") and len(pms._md_cell("x" * 20, 10)) == 10,
      "_md_cell 依 limit 截斷並標示省略")

DEC = {
    "ItemName|Base.Glock23": {"action": "unship", "reason": "不同槍|不同口徑",
                              "signature": "x"},
    "UI|UI_trait_X": {"action": "translate", "reason": "取中性譯名",
                      "ch": "甲", "cn": "甲", "signature": "y",
                      "upstream_report": "https://example/1"},
    "UI|UI_bad_shape": "壞掉的條目",
}
CEN = {"ItemName|Base.Glock23": {"1/A": "Glock 23", "2/B": "USP-45"},
       "UI|UI_trait_X": {"3/C": "Desc <br> here", "4/D": "Other"}}
SRC = {"ItemName|Base.Glock23": {"1/A": "ItemName.json", "2/B": pms.EN_SOURCE_SCRIPT},
       "UI|UI_trait_X": {"3/C": "UI.json", "4/D": "UI_EN.txt"}}
page = pms.render_owner_report(DEC, CEN, SRC)

# 5a. 主表每列必須恰好 4 欄（＝5 個未轉義的 `|`）。這條是本節的承重點：漏轉義時
#     Markdown 不會報錯，只會靜默錯位，肉眼看渲染結果才發現。
# 只取兩個資料節內的列——檔頭另有兩張 2 欄的說明表（處理方式、標記意義），
# 用「`| ` 開頭」寬篩會把它們一起算進來而誤報。
body = []
in_section = False
for ln in page.split("\n"):
    if ln.startswith("## "):
        in_section = ln.startswith(("## 不出貨的鍵", "## 採中性譯名的鍵"))
    elif in_section and ln.startswith("| ") and not ln.startswith(("| 鍵 |", "|---")):
        body.append(ln)
# `\|` 是轉義過的，先剝掉再數才是真正的欄位分隔符。**不可寫進 f-string 的 expression**
# ——Python 3.11 不允許 f-string 運算式含反斜線（本檔宣告 requires-python >=3.11）。
n_bad = sum(1 for ln in body if ln.replace("\\|", "").count("|") != 5)
check(len(body) == 2 and n_bad == 0,
      f"主表每列 4 欄（實測 {len(body)} 列、應為 2，異常 {n_bad}）")
check("`ItemName\\|Base.Glock23`" in page, "鍵名的 | 已轉義（backtick 內也要）")

# 5b. 分節與內容
check("## 不出貨的鍵（1）" in page and "## 採中性譯名的鍵（1）" in page,
      "依 action 分兩節並標數量")
check("_(json)_" in page and "_(script)_" in page and "死檔 UI_EN.txt" in page,
      "三態標記都渲染出來（json／script／死檔）")
check("https://example/1" in page, "upstream_report 選配欄有渲染")
check("壞掉的條目" not in page, "形狀壞損的台帳條目跳過，不得讓渲染整個炸掉")
check(page.endswith("\n") and "\r" not in page, "輸出為 LF ＋尾端換行（受版控生成物）")

# 5c. 確定性：同輸入必須同輸出（否則 --owner-report-check 會恆紅）
check(pms.render_owner_report(DEC, CEN, SRC) == page, "渲染具確定性")

if FAIL:
    print(f"\n❌ test_owner_json_en：{FAIL}/{CHECKS} 項失敗", file=sys.stderr)
    sys.exit(1)
print(f"✅ test_owner_json_en：{CHECKS} 項全過"
      "（loadable_json 兩條件、annotate 三態、signature 不受影響、"
      "src/out 全程同步、OWNER_CONFLICTS.md 表格不被 | 拆欄）")
