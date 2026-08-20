# /// script
# requires-python = ">=3.10"
# ///
"""`prep_mod_strings.py` 物品名（`script_item_dn`）缺口抽取的回歸測試。

背景（#221）：物品名走 `Translator.getItemNameFromFullType()`，出貨鍵是 `ItemName.json`
的裸 `Module.Item`。這條抽取路徑是補譯管線的入口，它一旦把缺口靜默算成零，玩家就會在
物品欄看到一整批英文而報表全綠——#184 Frockin Splendor 的 37 個服裝名正是這樣漏掉的。

要鎖住的四件事：
  1. **宇宙取自 tracker state，值才取自 `sources/en` 鏡像**。若 `dn_keys` 也從鏡像建，
     鏡像少一個 rid 時該鍵會同時從宇宙消失，`_item_dn_stats` 的 missing 永遠是空集合＝
     盲區偵測整條失效。
  2. **wid 級跳過必須 fail-closed**：缺 tracker 基準／缺鏡像時 artifact 長得跟「這個 mod
     沒缺口」一模一樣，故須寫入 `_unchecked` 並以非零退出碼收場（`apply_wf_result` 另有
     一道 `_unchecked` 拒絕，兩道都要在）。
  3. 缺口須扣除已出貨（dist 裸 fullType）、vanilla 檔域基準、DisplayName 等於 item id
     三者；`?.`（module 未解出）、schema 落後、上游 DisplayName 夾帶下一欄（值含換行）
     都計為不可判定而非缺口。
  4. **vanilla 基準欄位缺失一律炸**（fail-closed 慣例）：靜默退化成空集合會讓本體鍵被
     當成缺口送進補譯管線，違反「不得覆寫本體」鐵律。

執行：uv run scripts/test_prep_item_dn.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prep_mod_strings  # noqa: E402
import tracker  # noqa: E402

# fixture 路徑落在有效版本分支（`tracker._version_int` 只取前兩段，門檻 42000..42020）。
EFF = "mods/M/42.20/media/scripts/items.txt"
DEAD = "mods/M/42.12/media/scripts/items.txt"  # 低於 EFF，同 sub_mod 下不入選


# **計數由 `run()` 呼叫次數派生，不寫死**：寫死支數時加了案例卻漏改，就會輸出騙人的
# 「N 組通過」（同 `.github/workflows/tests.yml` 用 `${#tests[@]}` 的理由）。
CASES = 0


def run(*, records: dict, mirror: dict, dist_items: dict, vanilla: list[str],
        wids: list[str] | None = None, schema: object = tracker.ITEM_MODULE_SCHEMA,
        vanilla_json: dict | None = None, write_mirror: bool = True,
        second_wid: str | None = None, second_records: dict | None = None,
        second_mirror: dict | None = None, bad_hash: set[str] | None = None,
        decisions: dict | None = None, dist_cn: dict | None = None,
        bad_json: bool = False, want_err: bool = False,
        records_raw: object = None, bad_mirror_top: bool = False,
        bad_ledger: str | None = None, state_entry_raw: object = None):
    """組臨時 repo + dist，跑 `prep_mod_strings.main()`，回 (rc, artifact, stdout)。"""
    bad_hash = bad_hash or set()
    global CASES
    CASES += 1
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sources" / "en").mkdir(parents=True)
        (root / "tracker-state").mkdir()
        if bad_ledger is not None:
            (root / "sources" / "owner_conflict_decisions.json").write_text(
                bad_ledger, encoding="utf-8")
        if decisions is not None:
            (root / "sources" / "owner_conflict_decisions.json").write_text(
                json.dumps({"entries": decisions}, ensure_ascii=False), encoding="utf-8")
        (root / "sources" / "vanilla_keys.json").write_text(
            json.dumps(vanilla_json if vanilla_json is not None
                       else {"keys": [], "scoped_keys": {"ItemName.json": vanilla}},
                       ensure_ascii=False), encoding="utf-8")
        # **state 的 record 值就是鏡像值的 hash**（`records_to_map` 口徑）。fixture 若用
        # 假 hash，prep 的 coherence gate 會把每個案例都判成不一致而全部落 `_unchecked`，
        # 測不到原本要測的行為。故一律由鏡像實值回填；要專測不一致就顯式傳 `bad_hash`。
        def mk(recs: dict, mir: dict) -> dict:
            return {"extractor_schema": schema,
                    "records": {r: (tracker.value_hash(mir[r])
                                    if isinstance(mir.get(r), str) and r not in bad_hash
                                    else v) for r, v in recs.items()}}

        if state_entry_raw is not None:
            mods = {"1": state_entry_raw}          # state 條目本身壞損（非 dict）
        elif records_raw is not None:
            mods = {"1": {"extractor_schema": schema, "records": records_raw}}
        else:
            mods = {"1": mk(records, mirror)}
        if second_wid:
            mods[second_wid] = mk(second_records or {}, second_mirror or {})
        (root / "tracker-state" / "en_corpus_hashes.json").write_text(
            json.dumps({"mods": mods}, ensure_ascii=False), encoding="utf-8")
        if write_mirror:
            (root / "sources" / "en" / "1.json").write_text(
                "{ this is not json" if bad_json
                else json.dumps(["not", "a", "dict"] if bad_mirror_top else mirror,
                                ensure_ascii=False), encoding="utf-8")
            if second_wid:
                (root / "sources" / "en" / f"{second_wid}.json").write_text(
                    json.dumps(second_mirror or {}, ensure_ascii=False), encoding="utf-8")
        dist = root / "Translate" / "CH"
        dist.mkdir(parents=True)
        # CN 是 dist 的 sibling（prep 由 `DIST_CH.parent / "CN"` 推導），裁決台帳兩側都錨定
        (root / "Translate" / "CN").mkdir(parents=True)
        (root / "Translate" / "CN" / "ItemName.json").write_text(
            json.dumps(dist_cn or {}, ensure_ascii=False), encoding="utf-8")
        (dist / "ItemName.json").write_text(json.dumps(dist_items, ensure_ascii=False),
                                            encoding="utf-8")
        out = root / "out.json"
        old_root, old_dist, old_argv = (prep_mod_strings.ROOT, prep_mod_strings.DIST_CH,
                                        sys.argv)
        err, old_err = io.StringIO(), sys.stderr
        try:
            sys.stderr = err
            prep_mod_strings.ROOT = root
            prep_mod_strings.DIST_CH = dist
            sys.argv = ["prep", *(wids or ["1"]), "--out", str(out)]
            rc = prep_mod_strings.main()
        finally:
            sys.stderr = old_err
            (prep_mod_strings.ROOT, prep_mod_strings.DIST_CH,
             sys.argv) = old_root, old_dist, old_argv
        art = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
        return (rc, art, err.getvalue()) if want_err else (rc, art)


def raises(fn) -> str:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — 這裡就是要斷言「有擲例外」
        return f"{type(exc).__name__}: {exc}"
    raise AssertionError("預期擲例外卻正常返回——fail-closed 已失守")


# 1. 基本缺口判定：扣已出貨、扣 vanilla、扣 id-only、`?.` 與死分支不入缺口
recs = {
    f"script_item_dn|{EFF}|Base.Dress": "h1",     # 真缺口
    f"script_item_dn|{EFF}|Base.Hammer": "h2",    # 已出貨
    f"script_item_dn|{EFF}|Base.Axe": "h3",       # vanilla
    f"script_item_dn|{EFF}|Base.Plain": "h4",     # DisplayName == item id
    f"script_item_dn|{EFF}|?.Ghost": "h5",        # module 未解出 → 不可判定
    f"script_item_dn|{DEAD}|Base.Old": "h6",      # 死分支 → 不在宇宙內
}
mir = {
    f"script_item_dn|{EFF}|Base.Dress": "Red Dress",
    f"script_item_dn|{EFF}|Base.Hammer": "Big Hammer",
    f"script_item_dn|{EFF}|Base.Axe": "Fire Axe",
    f"script_item_dn|{EFF}|Base.Plain": "Plain",
    f"script_item_dn|{EFF}|?.Ghost": "Ghost Item",
    f"script_item_dn|{DEAD}|Base.Old": "Old Item",
}
rc, art = run(records=recs, mirror=mir, dist_items={"Base.Hammer": "大鎚"},
              vanilla=["Base.Axe"])
assert rc == 0, f"1. 正常情境應退出 0，實得 {rc}"
assert set(art["_gap"]) == {"ItemName|Base.Dress"}, f"1. 缺口判定錯誤：{art['_gap']}"
assert art["_undecidable"]["1"]["kinds"] == ["unknown_module"], \
    f"1. `?.` 應計為 unknown_module 不可判定：{art['_undecidable']}"
assert art["_unchecked"] == [], f"1. 不該有 wid 級跳過：{art['_unchecked']}"

# 2. **宇宙取自 state**：鏡像少一個 rid 時該鍵要落 missing（不可判定），不得靜默消失
thin = {k: v for k, v in mir.items() if "Base.Dress" not in k}
rc, art = run(records=recs, mirror=thin, dist_items={"Base.Hammer": "大鎚"},
              vanilla=["Base.Axe"])
assert art["_gap"] == {}, f"2. 鏡像缺值的鍵不該當成缺口（無 EN 原文可譯）：{art['_gap']}"
assert "mirror" in art["_undecidable"]["1"]["kinds"], \
    f"2. 鏡像缺值未計為不可判定＝宇宙被鏡像決定，盲區偵測失效：{art['_undecidable']}"

# 2b. 上游 DisplayName 夾帶下一欄（無尾逗號→引擎 split("=")[1] 吞進下一欄名）：值含換行，
#     不能當翻譯來源，須落 malformed 不可判定而非進 _gap
bad_recs = {**recs, f"script_item_dn|{EFF}|Base.Junk": "h7"}
bad_mir = {**mir, f"script_item_dn|{EFF}|Base.Junk": "junkname\n\t\tIcon"}
rc, art = run(records=bad_recs, mirror=bad_mir, dist_items={"Base.Hammer": "大鎚"},
              vanilla=["Base.Axe"])
assert "ItemName|Base.Junk" not in art["_gap"], \
    f"2b. 夾帶下一欄的壞值被當成可補缺口：{art['_gap']}"
assert "malformed" in art["_undecidable"]["1"]["kinds"], \
    f"2b. 壞值未計為 malformed 不可判定：{art['_undecidable']}"

# 3. wid 級跳過 fail-closed：缺 tracker 基準／缺鏡像都要非零退出且寫入 `_unchecked`
rc, art = run(records=recs, mirror=mir, dist_items={}, vanilla=[], wids=["999"])
assert rc == 1, f"3. 缺 tracker 基準應非零退出，實得 {rc}"
assert art["_unchecked"] and "999" in art["_unchecked"][0], \
    f"3. artifact 未標記未檢查的 wid：{art['_unchecked']}"
rc, art = run(records=recs, mirror=mir, dist_items={}, vanilla=[], write_mirror=False)
assert rc == 1, f"3. 缺 sources/en 鏡像應非零退出，實得 {rc}"
assert art["_unchecked"] and "鏡像" in art["_unchecked"][0], \
    f"3. artifact 未標記缺鏡像：{art['_unchecked']}"

# 4. schema 落後 → 全判不可判定（key 沒有 module，無從精確比對），不得報零缺口
rc, art = run(records=recs, mirror=mir, dist_items={}, vanilla=[],
              schema=tracker.ITEM_MODULE_SCHEMA - 1)
assert art["_gap"] == {}, f"4. 舊 schema 不得產生缺口：{art['_gap']}"
assert art["_undecidable"]["1"]["kinds"] == ["schema"], \
    f"4. 舊 schema 未計為不可判定：{art['_undecidable']}"
# 4b. `script_item_dn` 是 schema 5 才加的 kind；schema 3/4 的舊基準只有 `script_item`。
#     只看 dn_keys 會把那些 mod 判成「沒有 script 物品」而完全不列出＝#221 的靜默。
#     **鏡像必須真的不存在**（`write_mirror=False`）：producer 在無 text-bearing record 時
#     會刪掉鏡像檔，人工塞一個空 `{}` 測不到真實 contract（會被「缺鏡像」早退截斷）。
rc, art = run(records={f"script_item|{EFF}|OldStyleItem": "h9"}, mirror={},
              dist_items={}, vanilla=[], schema=3, write_mirror=False)
assert art["_unchecked"] == [], \
    f"4b. 無 text-bearing record 時鏡像不存在是合法狀態，不該早退：{art['_unchecked']}"
assert art["_undecidable"].get("1", {}).get("kinds") == ["schema"], \
    f"4b. 舊 schema 只有 script_item 時仍須列為不可判定：{art['_undecidable']}"

# 4d. **state 落後於鏡像**（backfill 中斷殘跡）：宇宙取自 state，缺的那些鍵會靜默低報成
#     零缺口——#221 的失效模式。須列 `_unchecked` 並非零退出，不得當成「沒缺口」。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Dress": "h1"},
              mirror={f"script_item_dn|{EFF}|Base.Dress": "Red Dress",
                      f"script_item_dn|{EFF}|Base.New": "New Thing"},
              dist_items={}, vanilla=[])
assert rc == 1, f"4d. state 落後於鏡像應非零退出，實得 {rc}"
assert art["_unchecked"] and "state" in art["_unchecked"][0], \
    f"4d. 未標記 state 落後：{art['_unchecked']}"
assert art["_gap"] == {}, f"4d. 不可套用的 wid 不該產生缺口：{art['_gap']}"

# 4e. **同一個 wid** 的 script DisplayName 與 Translate/EN ItemName 鍵同名不同值：那是引擎
#     的正常優先序（先查 ItemName map、查不到才退回 DisplayName），**不是** owner 衝突。
#     誤報會白白阻斷整批 prep（實例 wid 3600616323）。
EN_ITEMNAME = "mods/M/42.20/media/lua/shared/Translate/EN/ItemName.json"
rc, art = run(records={f"script_item_dn|{EFF}|Base.Thermos": "hC",
                       f"translate_en|{EN_ITEMNAME}|Base.Thermos": "hD"},
              mirror={f"script_item_dn|{EFF}|Base.Thermos": "Termo vacio",
                      f"translate_en|{EN_ITEMNAME}|Base.Thermos": "Empty thermos"},
              dist_items={}, vanilla=[])
assert rc == 0, f"4e. 同 wid 雙來源不該判成 owner 衝突，實得 rc={rc}"
assert art["_owner_conflicts"] == {}, \
    f"4e. 同 wid 的正常優先序被誤報成 owner 衝突：{art['_owner_conflicts']}"
assert art["_gap"].get("ItemName|Base.Thermos") == "Empty thermos", \
    f"4e. ItemName map 應優先於 script DisplayName：{art['_gap']}"

# 4f. **同 rid 值 hash 不符**（鏡像寫入失敗／人工改檔）：鍵集一模一樣，只比 membership
#     驗不出來，於是拿**過期英文**當翻譯來源，且 id-only／malformed 判定也用錯值。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Dress": "h1"},
              mirror={f"script_item_dn|{EFF}|Base.Dress": "Red Dress"},
              dist_items={}, vanilla=[],
              bad_hash={f"script_item_dn|{EFF}|Base.Dress"})
assert rc == 1, f"4f. 同 rid 值 hash 不符應非零退出，實得 {rc}"
assert art["_unchecked"] and "不一致" in art["_unchecked"][0], \
    f"4f. 未標記值 hash 不一致：{art['_unchecked']}"
assert art["_gap"] == {}, f"4f. 不可套用的 wid 不該產生缺口：{art['_gap']}"

# 4g. **分支層優先序**：引擎 common 恆載入、最佳版本夾疊在其上，同鍵兩邊都有時版本夾
#     的值才是實際顯示值。**fixture 必須把 EFF 排在 COMMON 之前**：production 的鏡像出自
#     `write_json(sort_keys=True)`，`"4" < "c"` 使 42.20 排在 common 前面；若 fixture 順著
#     COMMON→EFF 寫，dict 保序會讓「拿掉排序」也照樣得到正確結果＝案例不鑑別。
COMMON = "mods/M/common/media/scripts/items.txt"
rc, art = run(records={f"script_item_dn|{EFF}|Base.Dual": "hF",
                       f"script_item_dn|{COMMON}|Base.Dual": "hE"},
              mirror={f"script_item_dn|{EFF}|Base.Dual": "Versioned Name",
                      f"script_item_dn|{COMMON}|Base.Dual": "Common Name"},
              dist_items={}, vanilla=[])
assert art["_gap"].get("ItemName|Base.Dual") == "Versioned Name", \
    f"4g. 版本夾應疊在 common 之上：{art['_gap']}"

# 4h. `translate_en` 的宇宙同樣取自 state：鏡像少一筆時那個鍵不得靜默消失，須落
#     `_undecidable` 的 mirror 盲區（物品名分支早就這樣，EN 分支漏掉就是半邊防線）。
EN_UI = "mods/M/42.20/media/lua/shared/Translate/EN/UI.json"
rc, art = run(records={f"translate_en|{EN_UI}|UI_Has": "hG",
                       f"translate_en|{EN_UI}|UI_Lost": "hH"},
              mirror={f"translate_en|{EN_UI}|UI_Has": "Present"},
              dist_items={}, vanilla=[])
assert art["_gap"] == {"UI|UI_Has": "Present"}, \
    f"4h. 鏡像有值的 EN 鍵應入缺口、缺值者不得入：{art['_gap']}"
assert "mirror" in art["_undecidable"].get("1", {}).get("kinds", []), \
    f"4h. translate_en 鏡像缺值未計為不可判定＝靜默消失：{art['_undecidable']}"

# 4c. 同一 fullType 被多個 mod 定義成不同英文：`ItemName` 是全域表、後載入者覆寫，
#     first-wins 會靜默丟掉另一方語意。須列入 `_owner_conflicts`、**自 `_gap` 移除**、
#     並非零退出（`apply_wf_result` 另有一道拒絕）。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Shared": "hA"},
              mirror={f"script_item_dn|{EFF}|Base.Shared": "Owner A Name"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{EFF}|Base.Shared": "hB"},
              second_mirror={f"script_item_dn|{EFF}|Base.Shared": "Owner B Name"},
              wids=["1", "2"])
assert rc == 1, f"4c. owner 衝突應非零退出，實得 {rc}"
assert "ItemName|Base.Shared" in art["_owner_conflicts"], \
    f"4c. 未列入 _owner_conflicts：{art.get('_owner_conflicts')}"
assert "ItemName|Base.Shared" not in art["_gap"], \
    f"4c. 衝突鍵仍留在 _gap（first-wins 會照樣落地）：{art['_gap']}"
assert not any("Owner" in r["en"] for r in art["strings"]), \
    f"4c. 衝突鍵的 en 仍留在 strings（下游會拿到無落點的孤兒字串）：{art['strings']}"

# 4i. **只選一個 WID，state 另有衝突 owner**：census 必須掃全庫。只比本批 wid 會讓
#     「先 apply A、日後才處理 B」的衝突永久消失（B 的鍵屆時已 shipped 而被過濾掉）。
#     實例：`Base.ShotgunShells_Casing` 在 3225267257 是 Empty Buckshot Shell、
#     在 3630196063 是 Empty Shotgun Shell。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Shared": "hA"},
              mirror={f"script_item_dn|{EFF}|Base.Shared": "Owner A Name"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{EFF}|Base.Shared": "hB"},
              second_mirror={f"script_item_dn|{EFF}|Base.Shared": "Owner B Name"},
              wids=["1"])          # 刻意只跑 wid 1
assert rc == 1, f"4i. 只選一個 WID 時 census 未掃全庫，衝突逃掉了：rc={rc}"
assert "ItemName|Base.Shared" in art["_owner_conflicts"], \
    f"4i. 未列入 _owner_conflicts：{art.get('_owner_conflicts')}"

# 4j. **同一個 WID 底下兩個可獨立啟用的 mod root**：owner 是引擎的**mod ID**，不是
#     workshop id。把整個 wid 壓成單一 owner 會把真衝突當成「自己的疊加」吃掉——實例
#     wid 2791656602 的 `fhqwhgads' Motorious Zone` 與 `... - Real Names Adddon`，同鍵
#     `IGUI_VehicleNamefhq250GTO` 一邊 Ferrari、一邊 Impennarsi，只啟用 base mod 的
#     玩家會拿到 addon 的譯名。
ROOT_B = "mods/N/42.20/media/scripts/items.txt"
rc, art = run(records={f"script_item_dn|{EFF}|Base.Twin": "hI",
                       f"script_item_dn|{ROOT_B}|Base.Twin": "hJ"},
              mirror={f"script_item_dn|{EFF}|Base.Twin": "Root M Name",
                      f"script_item_dn|{ROOT_B}|Base.Twin": "Root N Name"},
              dist_items={}, vanilla=[])
assert rc == 1, f"4j. 同 WID 兩個 mod root 的衝突被當成自身疊加吃掉：rc={rc}"
assert "ItemName|Base.Twin" in art["_owner_conflicts"], \
    f"4j. 未列入 _owner_conflicts：{art.get('_owner_conflicts')}"

# 4k. **完全不涉及本批 owner 的歷史衝突**：report-only（寫進 artifact 供追蹤），不阻斷
#     本批——那些鍵本來就不在本批範圍，硬擋會讓工具不可用。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Mine": "hK"},
              mirror={f"script_item_dn|{EFF}|Base.Mine": "My Own Item"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{ROOT_B}|Base.Other": "hL",
                              f"script_item_dn|{EFF}|Base.Other": "hM"},
              second_mirror={f"script_item_dn|{ROOT_B}|Base.Other": "Other A",
                             f"script_item_dn|{EFF}|Base.Other": "Other B"},
              wids=["1"])
assert rc == 0, f"4k. 本批外的歷史衝突不該阻斷本批：rc={rc}"
assert "ItemName|Base.Other" in art["_owner_conflicts_other"], \
    f"4k. 本批外衝突未寫進 artifact（只印 stdout＝下一個人看不到）：{art}"
assert art["_owner_conflicts"] == {}, \
    f"4k. 本批外衝突被誤列為 blocking：{art['_owner_conflicts']}"

# 4l. **census 不扣 shipped**：本批 owner 的鍵已出貨、非本批 wid 是新 owner 且英文不同時，
#     衝突必須照樣浮現。若 census 改成吃本批 stats（有扣 shipped），該 owner 不進 census、
#     `len(...)<2` → rc=0，衝突整個消失（AGENTS.md 用 `Base.ShotgunShells_Casing` 舉的正
#     是這個假陰性）。**fixture 一定要 `dist_items` 命中**，否則測不到這半邊。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Ship": "hN"},
              mirror={f"script_item_dn|{EFF}|Base.Ship": "Shipped A"},
              dist_items={"Base.Ship": "已出貨"},      # 本批的鍵已出貨
              vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{EFF}|Base.Ship": "hO"},
              second_mirror={f"script_item_dn|{EFF}|Base.Ship": "Shipped B"},
              wids=["1"])
assert rc == 1, f"4l. census 扣了 shipped → 已出貨鍵的新 owner 衝突消失：rc={rc}"
assert "ItemName|Base.Ship" in art["_owner_conflicts"], \
    f"4l. 未列入 _owner_conflicts：{art.get('_owner_conflicts')}"

# 4m. **非本批 wid load 失敗 → fail-closed**：census 少了它的 owner，若它剛好也定義本批
#     的鍵，衝突判定就是假陰性。身分只靠 state 就算得出來，須列 `_unchecked` 非零退出。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Both": "hP"},
              mirror={f"script_item_dn|{EFF}|Base.Both": "Mine"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{EFF}|Base.Both": "hQ"},
              second_mirror={f"script_item_dn|{EFF}|Base.Both": "Theirs",
                             f"script_item_dn|{EFF}|Base.Extra": "Ahead"},  # 鏡像領先
              wids=["1"])
assert rc == 1, f"4m. 非本批 wid load 失敗未 fail-closed：rc={rc}"
assert any("非本批" in u for u in art["_unchecked"]), \
    f"4m. 未把跳過的 wid 記進 _unchecked：{art['_unchecked']}"

# 4m2. **mirror-only 的共鍵**：非本批 wid 因「鏡像領先」load 失敗時，領先的那批 rid 只
#      存在於鏡像。身分集只掃 state 會漏掉它——若那個 rid 正好就是與本批共鍵的新 owner，
#      交集為空＝靜默放行。4m 的固定 fixture 抓不到這格（共鍵在 state、額外 rid 無關）。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Mine2": "hV"},
              mirror={f"script_item_dn|{EFF}|Base.Mine2": "Mine Two"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={},                                     # state 沒有它
              second_mirror={f"script_item_dn|{EFF}|Base.Mine2": "Their Two"},  # 只在鏡像
              wids=["1"])
assert rc == 1, f"4m2. mirror-only 共鍵未 fail-closed：rc={rc}"
assert any("非本批" in u for u in art["_unchecked"]), \
    f"4m2. 未把跳過的 wid 記進 _unchecked：{art['_unchecked']}"

# 4m3. **壞損 rid**：合法 JSON 裡的 rid 缺分隔符／未知 kind，會被寬鬆 partition 吃掉、
#      解析成空鍵或錯落點，既不進 census 也無從交集。一律 load 失敗；本批即 `_unchecked`。
rc, art = run(records={"translate_en|mods/M/42.20/UI.json": "hW"},   # 缺 key 段
              mirror={}, dist_items={}, vanilla=[], write_mirror=False)
assert rc == 1, f"4m3. 壞損 rid 未 fail-closed：rc={rc}"
assert art["_unchecked"] and "壞損 rid" in art["_unchecked"][0], \
    f"4m3. 未標記壞損 rid：{art['_unchecked']}"

# 4n. **上游留白的 translate_en 抑制同鍵 script DisplayName**：`tryFillMapFromFile():362`
#     首次即空值時仍會 put，而 `getItemNameFromFullType():601` 只對 `null` fallback，故
#     空字串會讓玩家看到空白、script 名不生效 → 該鍵不是缺口。
EN_IN = "mods/M/42.20/media/lua/shared/Translate/EN/ItemName.json"
rc, art = run(records={f"script_item_dn|{EFF}|Base.Muted": "hR",
                       f"translate_en|{EN_IN}|Base.Muted": "hS"},
              mirror={f"script_item_dn|{EFF}|Base.Muted": "Script Name",
                      f"translate_en|{EN_IN}|Base.Muted": ""},
              dist_items={}, vanilla=[])
assert "ItemName|Base.Muted" not in art["_gap"], \
    f"4n. 上游留白未抑制 script DisplayName（會造出無據譯文）：{art['_gap']}"
assert "upstream_blank" in art["_undecidable"].get("1", {}).get("kinds", []), \
    f"4n. 上游留白未計數通報：{art['_undecidable']}"

# 4o. 反向：**已有非空值後才遇到空值**（common 非空、版本夾留白）→ 引擎不覆寫，執行期
#     仍是非空值，故該鍵**照樣是缺口**。與 4n 是同一條 put 條件的兩個分支，一律 pop 就錯。
EN_COMMON = "mods/M/common/media/lua/shared/Translate/EN/ItemName.json"
rc, art = run(records={f"translate_en|{EN_COMMON}|Base.Keep": "hT",
                       f"translate_en|{EN_IN}|Base.Keep": "hU"},
              mirror={f"translate_en|{EN_COMMON}|Base.Keep": "Real Name",
                      f"translate_en|{EN_IN}|Base.Keep": ""},
              dist_items={}, vanilla=[])
assert art["_gap"].get("ItemName|Base.Keep") == "Real Name", \
    f"4o. 版本夾留白把 common 的非空值誤刪＝真缺口消失：{art['_gap']}"

# 4p. **裁決台帳背書後放行**：census 刻意不扣 shipped，若沒有可機讀的完成狀態，同一組
#     owner/value 會永遠報衝突，相關 wid 連無關的新缺口都無法 apply（工具實質不可用）。
SHARED = {"1/M": "Owner A Name", "2/M": "Owner B Name"}
SIG = prep_mod_strings.census_signature(SHARED)
CONFLICT_FIXTURE = dict(
    records={f"script_item_dn|{EFF}|Base.Shared": "hA"},
    mirror={f"script_item_dn|{EFF}|Base.Shared": "Owner A Name"},
    vanilla=[], second_wid="2",
    second_records={f"script_item_dn|{EFF}|Base.Shared": "hB"},
    second_mirror={f"script_item_dn|{EFF}|Base.Shared": "Owner B Name"},
    wids=["1", "2"])
D = {"signature": SIG, "reason": "中性譯名", "ch": "共用譯名", "cn": "共用译名"}
rc, art = run(**CONFLICT_FIXTURE, dist_items={"Base.Shared": "共用譯名"},
              dist_cn={"Base.Shared": "共用译名"},
              decisions={"ItemName|Base.Shared": D})
assert rc == 0, f"4p. 已背書的衝突仍阻斷＝裁決無完成狀態，wid 永久卡住：rc={rc}"
assert "ItemName|Base.Shared" in art["_owner_conflicts_resolved"], \
    f"4p. 放行未記進 artifact（無從稽核放行了哪些）：{art}"
assert art["_owner_conflicts"] == {}, f"4p. 已背書仍列 blocking：{art['_owner_conflicts']}"
assert "ItemName|Base.Shared" not in art["_gap"], \
    f"4p. 已背書的鍵仍在 _gap（會被當缺口再翻一次）：{art['_gap']}"

# 4q. 台帳的六種過時形狀都必須維持 blocking——少任何一項，裁決就變成永久放行通道
for label, dist, dist_cn, dec in (
    ("signature 不符（owner 增減／上游改值）", {"Base.Shared": "共用譯名"},
     {"Base.Shared": "共用译名"}, {**D, "signature": "0" * 16}),
    ("缺 reason", {"Base.Shared": "共用譯名"}, {"Base.Shared": "共用译名"},
     {**D, "reason": "  "}),
    ("reason 非字串", {"Base.Shared": "共用譯名"}, {"Base.Shared": "共用译名"},
     {**D, "reason": 123}),
    ("譯文尚未出貨", {}, {}, D),
    ("出貨 CH 值已漂移", {"Base.Shared": "偏向某 owner"}, {"Base.Shared": "共用译名"}, D),
    ("出貨 CN 值已漂移", {"Base.Shared": "共用譯名"}, {"Base.Shared": "偏向某 owner"}, D),
    # **缺欄那一列是最該釘死的**：台帳缺 `cn` 而該鍵又不在 CN dist 時，`None == None`
    # 會把從未裁決過的東西放行——這正是 codex lane 抓到的洞。
    ("缺 ch 欄", {"Base.Shared": "共用譯名"}, {"Base.Shared": "共用译名"},
     {k: v for k, v in D.items() if k != "ch"}),
    ("缺 cn 欄且鍵不在 CN dist", {"Base.Shared": "共用譯名"}, {},
     {k: v for k, v in D.items() if k != "cn"}),
    ("cn 為 null 且鍵不在 CN dist", {"Base.Shared": "共用譯名"}, {},
     {**D, "cn": None}),
    ("條目形狀壞（非 dict）", {"Base.Shared": "共用譯名"}, {"Base.Shared": "共用译名"},
     "just a string"),
):
    rc, art = run(**CONFLICT_FIXTURE, dist_items=dist, dist_cn=dist_cn,
                  decisions={"ItemName|Base.Shared": dec})
    assert rc == 1, f"4q. {label} 未維持 blocking：rc={rc}"
    assert "ItemName|Base.Shared" in art["_owner_conflicts"], \
        f"4q. {label} 未列入 _owner_conflicts：{art.get('_owner_conflicts')}"

# 4o2. **純空白 ≠ 空字串**：引擎 `isNullOrEmpty` 只認長度零（`StringUtils.java:11`），
#      `"  "` 是非空值、**一律 put／覆寫**——common 非空、版本夾 `"  "` 時執行期顯示
#      空白，該鍵不是缺口。用 `.strip()` 判空會走成「不覆寫」＝與引擎相反。
rc, art = run(records={f"translate_en|{EN_COMMON}|Base.Blanked": "hX",
                       f"translate_en|{EN_IN}|Base.Blanked": "hY"},
              mirror={f"translate_en|{EN_COMMON}|Base.Blanked": "Real Name",
                      f"translate_en|{EN_IN}|Base.Blanked": "  "},
              dist_items={}, vanilla=[])
assert "ItemName|Base.Blanked" not in art["_gap"], \
    f"4o2. 純空白覆寫後仍被當缺口（引擎顯示空白，譯了也看不到）：{art['_gap']}"
# **診斷要分開講**：`""` 與純空白的引擎語意相反（前者「已有值則不覆寫」、後者一律覆寫），
# 合併成一個數字再配「若同鍵另有非空值則不影響」的文案就是錯的（純空白一定影響）。
assert "純空白" in art["_undecidable"].get("1", {}).get("why", ""), \
    f"4o2. 純空白未與空字串分開通報：{art['_undecidable']}"
rc2, art2 = run(records={f"translate_en|{EN_COMMON}|Base.EmptyOnly": "hF1"},
                mirror={f"translate_en|{EN_COMMON}|Base.EmptyOnly": ""},
                dist_items={}, vanilla=[])
assert "空字串" in art2["_undecidable"].get("1", {}).get("why", "") \
    and "純空白" not in art2["_undecidable"].get("1", {}).get("why", ""), \
    f"4o2. 空字串被混報成純空白：{art2['_undecidable']}"

# 4o3. **純空白被後載入的非空值蓋掉時，該鍵仍是缺口**：Counter 計的是 raw rows、不是勝出
#      者，所以診斷文案不能寫「一定不是缺口」。與 4o2 是相反順序（那邊 common 非空、版本夾
#      純空白 → 覆寫成空白＝不是缺口）。
rc, art = run(records={f"translate_en|{EN_COMMON}|Base.Revived": "hL1",
                       f"translate_en|{EN_IN}|Base.Revived": "hL2"},
              mirror={f"translate_en|{EN_COMMON}|Base.Revived": "  ",
                      f"translate_en|{EN_IN}|Base.Revived": "Real Name"},
              dist_items={}, vanilla=[])
assert art["_gap"].get("ItemName|Base.Revived") == "Real Name", \
    f"4o3. 純空白被非空值蓋掉後該鍵仍應是缺口：{art['_gap']}"
assert "勝出者" in art["_undecidable"].get("1", {}).get("why", ""), \
    f"4o3. 純空白診斷仍宣稱『一定不是缺口』：{art['_undecidable']}"

# 4r. **簽名必須隨 owner 值變動而失效**：4p/4q 的 SIG 由被測函式自己算，若
#     `census_signature` 退化成常數或忽略值，那兩組案例照樣綠。這裡固定登記「舊值的簽名」
#     再改變上游值——退化實作會讓舊簽名仍然相符而放行，本案例即紅。
OLD_SIG = prep_mod_strings.census_signature({"1/M": "Owner A Name", "2/M": "Owner B Name"})
rc, art = run(records={f"script_item_dn|{EFF}|Base.Shared": "hA"},
              mirror={f"script_item_dn|{EFF}|Base.Shared": "Owner A Name"},
              dist_items={"Base.Shared": "共用譯名"}, dist_cn={"Base.Shared": "共用译名"},
              vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{EFF}|Base.Shared": "hB"},
              second_mirror={f"script_item_dn|{EFF}|Base.Shared": "Owner B CHANGED"},
              wids=["1", "2"],
              decisions={"ItemName|Base.Shared": {"signature": OLD_SIG, "reason": "舊裁決",
                                                  "ch": "共用譯名", "cn": "共用译名"}})
assert rc == 1, f"4r. 上游值變了、舊簽名仍放行＝簽名沒有錨定值：rc={rc}"
assert "ItemName|Base.Shared" in art["_owner_conflicts"], \
    f"4r. 未重新列為 blocking：{art.get('_owner_conflicts')}"

# 4s. **勝出 rid 缺值不得回退 common 舊值**：state 有 common＋版本夾同 fullType，鏡像只
#     剩 common 那筆（backfill 中斷殘跡；`mirror_incoherent_rids` 依設計不驗 state 有→
#     鏡像沒有）。runtime 勝出者是版本夾那筆、值未知——回退用 common 的舊英文就是拿低
#     優先序過期值當翻譯來源，census 也會用它比 owner 衝突。該鍵應落 mirror 盲區。
COMMON_S = "mods/M/common/media/scripts/items.txt"
rc, art = run(records={f"script_item_dn|{COMMON_S}|Base.Masked": "hZ",
                       f"script_item_dn|{EFF}|Base.Masked": "hZZ"},
              mirror={f"script_item_dn|{COMMON_S}|Base.Masked": "Common Name"},
              dist_items={}, vanilla=[])   # 目標 rid 不在鏡像＝勝出者缺值
assert art["_gap"] == {}, \
    f"4s. 版本夾缺值卻回退用 common 舊值當缺口英文：{art['_gap']}"
# 該鍵應落 mirror 盲區、且不得整個 wid 早退（否則測不到「勝出者缺值」那半句）
assert art["_unchecked"] == [], f"4s. 不該整個 wid 早退：{art['_unchecked']}"
assert "mirror" in art["_undecidable"].get("1", {}).get("kinds", []), \
    f"4s. 勝出者缺值未落 mirror 盲區：{art['_undecidable']}"

# 4t. `translate_en` 同形：勝出（版本夾）rid 缺值時，先前寫入的 common 值必須撤銷。
rc, art = run(records={f"translate_en|{EN_COMMON}|Base.Shadow": "hA1",
                       f"translate_en|{EN_IN}|Base.Shadow": "hA2"},
              mirror={f"translate_en|{EN_COMMON}|Base.Shadow": "Common EN"},
              dist_items={}, vanilla=[])   # 目標 rid 不在鏡像＝勝出者缺值
assert "ItemName|Base.Shadow" not in art["_gap"], \
    f"4t. 版本夾缺值卻保留 common 的低優先值：{art['_gap']}"

# 4u. **非本批 wid 的壞損 rid**：身分不可還原時不能推論「無交集」。缺 key 段的 rid 會被
#     寬鬆 partition 解析成 `ItemName|`（空鍵），與任何本批鍵都不相交＝靜默放行。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Shared": "hB1"},
              mirror={f"script_item_dn|{EFF}|Base.Shared": "Mine"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={"script_item_dn|mods/M/42.20/media/scripts/items.txt": "hB2"},
              second_mirror={}, wids=["1"])
assert rc == 1, f"4u. 非本批壞損 rid 未 fail-closed：rc={rc}"
assert any("身分不可還原" in u for u in art["_unchecked"]), \
    f"4u. 未標記身分不可還原：{art['_unchecked']}"

# 4v. **空 key 的兩面**：`script_item_dn`／`translate_en` 的空 key 會被推導成 `ItemName|`
#     （與任何真鍵不相交）＝身分不可還原，須 fail-closed；但 `lua_gettext` 的空 key 是
#     **合法上游寫法**（`getText("")`，實測 3 筆／2 個 mod），且不參與身分推導，一律判
#     壞損會把正常 mod 誤卡。
#     （fixture 必須**給鏡像**，否則會先被「state 有文本 record 卻無鏡像」那條擋住，
#     測不到空 key 這條。）
rc, art = run(records={f"script_item_dn|{EFF}|": "hC1"},
              mirror={f"script_item_dn|{EFF}|": "Nameless"},
              dist_items={}, vanilla=[])
assert rc == 1 and any("壞損 rid" in u for u in art["_unchecked"]), \
    f"4v. 空 key 的 dn rid 未 fail-closed：rc={rc} unchecked={art['_unchecked']}"
rc, art = run(records={f"script_item_dn|{EFF}|Base.Ok": "hC2",
                       "lua_gettext|mods/M/42.20/media/lua/a.lua|": "hC3"},
              mirror={f"script_item_dn|{EFF}|Base.Ok": "Fine Item"},
              dist_items={}, vanilla=[])
assert art["_unchecked"] == [], \
    f"4v. `getText(\"\")` 的空 key 被誤判壞損而卡住正常 mod：{art['_unchecked']}"
assert art["_gap"].get("ItemName|Base.Ok") == "Fine Item", \
    f"4v. 正常鍵未入缺口：{art['_gap']}"
# **豁免只給 `lua_gettext`**：其餘 kind 的空 key 也要擋——它們並非惰性（空 `script_item`
# 進 schema 盲區計數、空 `lua_literal` 進 coverage、空 `script_craftRecipe` 進
# verify_dist [16] 實據）。少了這幾格，把規則放寬回「只擋 dn／en」時 4v 照樣綠。
for k in ("script_item", "script_craftRecipe", "lua_literal", "script_recipe"):
    rc, art = run(records={f"script_item_dn|{EFF}|Base.Ok2": "hG1",
                           f"{k}|{EFF}|": "hG2"},
                  mirror={f"script_item_dn|{EFF}|Base.Ok2": "Fine Two"},
                  dist_items={}, vanilla=[])
    assert rc == 1 and any("壞損 rid" in u for u in art["_unchecked"]), \
        f"4v. `{k}` 的空 key 未被擋（豁免應只給 lua_gettext）：rc={rc} {art['_unchecked']}"

# 4w. **`rid_ids` 的空 key 收窄要有獨立鑑別力**：4v 走的是本批 `load_wid`，不經
#     `rid_ids`。這裡讓**非本批** wid 只帶一個空 key 的 dn rid——它會被推導成 `ItemName|`
#     （空鍵），與任何本批鍵都不相交＝靜默放行。須回 `None` sentinel 而 fail-closed。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Solo": "hD1"},
              mirror={f"script_item_dn|{EFF}|Base.Solo": "Solo Item"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{EFF}|": "hD2"},
              second_mirror={f"script_item_dn|{EFF}|": "Nameless",
                             f"script_item_dn|{EFF}|Base.Extra2": "Ahead2"},  # 鏡像領先→load 失敗
              wids=["1"])
assert rc == 1, f"4w. 非本批的空 key dn rid 未 fail-closed：rc={rc}"
assert any("身分不可還原" in u for u in art["_unchecked"]), \
    f"4w. 未走 rid_ids 的 sentinel 路徑：{art['_unchecked']}"

# 4x. **鏡像 JSON 壞損必須轉成 `_unchecked`，不得讓例外逃出 `main()`**：例外會讓 artifact
#     根本不被重寫，**舊的成功檔留在原地**——下游 `apply_wf_result` 讀到那份安全形狀的
#     artifact 會判「機械檢查全過」rc=0，整個 fail-closed contract 被繞過。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Broke": "hE1"},
              mirror={}, dist_items={}, vanilla=[], bad_json=True)
assert rc == 1, f"4x. 鏡像 JSON 壞損未 fail-closed：rc={rc}"
assert art is not None, "4x. artifact 未被重寫＝舊的成功檔會留在原地被誤用"
assert any("無法解析" in u for u in art["_unchecked"]), \
    f"4x. 未標記鏡像無法解析：{art['_unchecked']}"

# 4y. **台帳條目為明確 `null`**：`.get()` 會把它與「沒登記」混為一談而靜默；須具名報出
#     「條目形狀壞損（NoneType）」。這是 membership 判定唯一能鑑別的形狀。
rc, art, err = run(**CONFLICT_FIXTURE, dist_items={"Base.Shared": "共用譯名"},
                   dist_cn={"Base.Shared": "共用译名"},
                   decisions={"ItemName|Base.Shared": None}, want_err=True)
assert rc == 1, f"4y. null 條目未維持 blocking：rc={rc}"
assert "NoneType" in err, f"4y. 未具名報出 null 條目的形狀壞損：{err!r}"

# 4z. **harness 先前結構性排除的 fail-closed 分支**：records 容器非 dict（本批／非本批）、
#     鏡像頂層非 dict。四條都是「例外逃出 main() → artifact 不重寫 → 舊成功檔被誤用」同族。
rc, art = run(records={}, records_raw=["not", "a", "dict"], mirror={},
              dist_items={}, vanilla=[], write_mirror=False)
assert rc == 1 and any("壞損" in u for u in art["_unchecked"]), \
    f"4z. 本批 records 非 dict 未 fail-closed：rc={rc} {art['_unchecked']}"
# **state 條目本身非 dict** 是另一條路（`state[wid].get()` 會拋 AttributeError）
rc, art = run(records={}, state_entry_raw=["bad", "entry"], mirror={},
              dist_items={}, vanilla=[], write_mirror=False)
assert rc == 1 and any("條目形狀壞損" in u for u in art["_unchecked"]), \
    f"4z. state 條目非 dict 未 fail-closed：rc={rc} {art['_unchecked']}"
rc, art = run(records={f"script_item_dn|{EFF}|Base.Top": "hH1"},
              mirror={f"script_item_dn|{EFF}|Base.Top": "Top Item"},
              dist_items={}, vanilla=[], bad_mirror_top=True)
assert rc == 1 and any("頂層形狀壞損" in u for u in art["_unchecked"]), \
    f"4z. 鏡像頂層非 dict 未 fail-closed：rc={rc} {art['_unchecked']}"

# 4aa. **裁決台帳壞損不得 raise**：它是人工手編的真相檔，手滑一個逗號就壞。raise 會讓
#      artifact 不被重寫、上一輪的成功檔留在原地被 `apply_wf_result` 判「機械檢查全過」。
for label, payload in (("非法 JSON", "{ oops"),
                       ("頂層非 dict", '["a"]'),
                       ("entries 非 dict", '{"entries": []}'),
                       ("缺 entries", '{}')):
    rc, art = run(records={f"script_item_dn|{EFF}|Base.Led": "hI1"},
                  mirror={f"script_item_dn|{EFF}|Base.Led": "Led Item"},
                  dist_items={}, vanilla=[], bad_ledger=payload)
    assert art is not None, f"4aa. {label}：artifact 未被重寫（舊成功檔會被誤用）"
    assert rc == 1 and any("裁決台帳不可用" in u for u in art["_unchecked"]), \
        f"4aa. {label} 未列 _unchecked：rc={rc} {art['_unchecked']}"

# 4bb. **`norm_en` 的兩個退化方向**：拿掉正規化 → 變體 mod 因排版級漂移恆非零退出（工具
#      實質不可用）；改用 NFKC → 型號／單位的真 owner 衝突被靜默合併（與 census 的
#      fail-closed 取向相反）。兩邊都要有案例釘住。
rc, art = run(records={f"script_item_dn|{EFF}|Base.Quote": "hJ1"},
              mirror={f"script_item_dn|{EFF}|Base.Quote": "Dr. Venter\u2019s Kit"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{EFF}|Base.Quote": "hJ2"},
              second_mirror={f"script_item_dn|{EFF}|Base.Quote": "Dr. Venter's Kit"},
              wids=["1", "2"])
assert rc == 0 and art["_owner_conflicts"] == {}, \
    f"4bb. 只差彎引號被判成 owner 衝突（變體 mod 會恆非零退出）：{art['_owner_conflicts']}"
rc, art = run(records={f"script_item_dn|{EFF}|Base.Model": "hK1"},
              mirror={f"script_item_dn|{EFF}|Base.Model": "Mark \u2163 Rifle"},
              dist_items={}, vanilla=[], second_wid="2",
              second_records={f"script_item_dn|{EFF}|Base.Model": "hK2"},
              second_mirror={f"script_item_dn|{EFF}|Base.Model": "Mark IV Rifle"},
              wids=["1", "2"])
assert rc == 1 and "ItemName|Base.Model" in art["_owner_conflicts"], \
    f"4bb. 型號的相容字元差異被 NFKC 靜默合併（真衝突消失）：{art['_owner_conflicts']}"

# 5. B41 前綴死鍵不算已出貨——`ItemName_Base.X` 在 B42 完全不讀（verify_dist [15]）
rc, art = run(records={f"script_item_dn|{EFF}|Base.Dress": "h1"},
              mirror={f"script_item_dn|{EFF}|Base.Dress": "Red Dress"},
              dist_items={"ItemName_Base.Dress": "紅裙"}, vanilla=[])
assert set(art["_gap"]) == {"ItemName|Base.Dress"}, \
    f"5. 只出貨前綴死鍵被誤判為已覆蓋：{art['_gap']}"

# 6. vanilla 基準欄位缺失一律炸（不得靜默退化成空集合而把本體鍵當缺口）
for bad in ({"keys": []}, {"scoped_keys": {}}, {"keys": [], "scoped_keys": {"UI.json": []}}):
    msg = raises(lambda b=bad: run(records=recs, mirror=mir, dist_items={}, vanilla=[],
                                   vanilla_json=b))
    assert "KeyError" in msg, f"6. vanilla 基準殘缺應炸，實得：{msg}"

print(f"PASS: prep_mod_strings 物品名缺口 {CASES} 個情境通過")
