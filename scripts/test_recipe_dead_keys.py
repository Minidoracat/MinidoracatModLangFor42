# /// script
# requires-python = ">=3.10"
# ///
"""verify [16] Recipes 死鍵棘輪的回歸測試。

背景：`Recipe_<X>` 是 B41 `Recipes_EN.txt` 時代的鍵形，`craftRecipe_<X>` 是 B42 端多加了
script 類型名當前綴。兩者結果一樣——B42 的配方顯示名走 `Translator.getRecipeName(name)`
→ `recipe.get(name)`，`name` 是裸的 craftRecipe 區塊名（`CraftRecipe.java:362`，
`ScriptBucket` 只 trim、不去空格）。前綴鍵永遠不會被查到，譯得再好也顯示英文，而
build／CH parity／lint／verify 其餘 14 項全綠——2026-08-16 的 #170 SVRP ClassicBows 就是
這樣讓 4 個 `Recipe_*_from_Plank` 溜過所有機械防線，靠人工 review 才攔下；同批盤點另發現
69 個既有同類缺口。

要鎖住的六件事：
  1. 前綴鍵對得上上游現行區塊名、卻沒出貨裸鍵 → FAIL。這是本檢查存在的理由。
  2. **無上游實據不得亂報**。上游沒有同名區塊時，那個前綴鍵可能只是上游 Translate 檔
     自帶的閒置鍵（無從還原成有效鍵），報它只是噪音。
  3. 還原不得用 `body.replace("_", " ")`。上游區塊名會**混用**空格與底線
     （`SVRP_CB_Pack Metal Arrows`），而 legacy 鍵一律把空格寫成底線；全換空格會把區塊
     本來就有的底線也換掉，混用形一律漏報。正確方向是把區塊名底線化後當索引。
  4. 裸名屬 vanilla 者放行——依 vanilla 出貨抑制鐵律，補了會全域改寫本體配方名。
  5. 反向棘輪：裸鍵已補好、前綴鍵已消失、或已由 vanilla 基準自動放行時，allowlist 條目
     要出 WARN 提醒移除，否則清單會爛掉沒人發現（漏掉 vanilla 那條，基準日後移除該鍵時
     過時豁免會靜默接手放行）。
  6. **實據殘缺一律 fail-closed**。`blocks` 空集合會讓判定全部回空、gate 綠燈、整道防線
     靜默關閉，那是最危險的失效模式。故 `mods` 形狀壞損、任一 mod 的 `records` 非 dict、
     濾後區塊名量級不足、allowlist `entries` 形狀壞損，都必須擲例外（由 `run_all()` 轉
     FAIL），不得靜默視為「零死鍵」。**只計有效版本分支**：tracker 記錄所有分支，引擎只
     載入 `common/` ＋唯一最佳版本夾；不濾會把上游早就改名的舊區塊當現行實據。

執行：uv run scripts/test_recipe_dead_keys.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_dist  # noqa: E402

# fixture 路徑必須落在**有效版本分支**。`tracker._version_int()` 只取前兩段
# （`major*1000+minor`），門檻是 `42000 <= v <= PZ_GAME_VERSION_INT`（預設 42020），
# 而有效版本夾＝合格者中的**最大值**。所以 `42.12`(42012) 會勝過 `42`(42000)——死分支
# fixture 必須讓活分支的版本夾更高（這裡 `42.20`＝42020），否則會測反。
# mod 根 `media/` 是 B41 遺留、引擎不載入，`tracker.is_effective()` 一律判 False。
EFF = "mods/M/42.20/media/scripts/x.txt"
DEAD = "mods/M/42.12/media/scripts/x.txt"  # 低於 EFF 的版本夾，同 sub_mod 下不入選
# 湊過 RECIPE_BLOCKS_MIN 完整性門檻；filler 名稱刻意不與任何測試鍵相關。
# filler 恆掛 EFF，讓 `42.20` 成為該 sub_mod 的最佳版本夾。
FILLER = [f"ZzFiller{i}" for i in range(verify_dist.RECIPE_BLOCKS_MIN)]


def _records(blocks, relpath=EFF, filler=True):
    recs = {f"script_craftRecipe|{relpath}|{b}": "deadbeef" for b in blocks}
    if filler:
        recs.update({f"script_craftRecipe|{EFF}|{b}": "deadbeef" for b in FILLER})
    return recs


def run(dist_recipes: dict, blocks: list[str], vanilla: list[str], allow: dict,
        *, state=None, allow_raw=None, relpath: str = EFF, filler: bool = True,
        schema: object = verify_dist.CRAFT_SCHEMA_MIN):
    """組臨時 repo + dist（含 tracker 狀態），回 (ok, fail, warn)；例外原樣拋出。"""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "sources"
        src.mkdir()
        (src / "vanilla_keys.json").write_text(
            json.dumps({"scoped_keys": {"Recipes.json": vanilla}}, ensure_ascii=False),
            encoding="utf-8")
        (src / "recipe_dead_allowlist.json").write_text(
            json.dumps(allow_raw if allow_raw is not None else {"entries": allow},
                       ensure_ascii=False), encoding="utf-8")
        st = Path(td) / "tracker-state"
        st.mkdir()
        if state is None:
            # `extractor_schema` 必須帶：缺席／低於 CRAFT_SCHEMA_MIN 會被判 stale 而多出
            # 一條 WARN，把「預期零 WARN」的情境全部打壞。
            state = {"mods": {"1": {"extractor_schema": schema,
                                    "records": _records(blocks, relpath, filler)}}}
        verify_dist.tracker.write_corpus_hashes(state, st / "en_corpus_hashes")
        ch = Path(td) / "CH"
        ch.mkdir()
        (ch / "Recipes.json").write_text(json.dumps(dist_recipes, ensure_ascii=False),
                                         encoding="utf-8")
        ok, fail, warn = verify_dist.check_recipe_dead_keys(td, str(ch))
        assert ok is (not fail), "ok 與 fail 清單不一致"
        return ok, fail, warn


def raises(fn) -> str:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — 這裡就是要斷言「有擲例外」
        return f"{type(exc).__name__}: {exc}"
    raise AssertionError("預期擲例外卻正常返回——fail-closed 已失守")


# 1. 前綴鍵有上游區塊名、無裸鍵 → FAIL
ok, fail, _ = run({"Recipe_MakeBeeSmoker": "製作蜂煙器"}, ["MakeBeeSmoker"], [], {})
assert not ok and fail, "有上游實據的死鍵未被抓到"
assert "MakeBeeSmoker" in fail[0], f"失敗訊息應指名裸鍵：{fail[0]}"

# 2. 裸鍵已出貨 → PASS（前綴鍵只是無害重複）
ok, fail, _ = run({"Recipe_MakeBeeSmoker": "製作蜂煙器", "MakeBeeSmoker": "製作蜂煙器"},
                  ["MakeBeeSmoker"], [], {})
assert ok and not fail, f"已有裸鍵仍誤報：{fail}"

# 3. 上游查無同名區塊 → 不得報。上游 Translate 檔自帶的閒置前綴鍵無從還原，
#    亂報只會逼人往 allowlist 塞垃圾。
ok, fail, _ = run({"Recipe_SomethingUpstreamNeverHad": "隨便"}, ["OtherBlock"], [], {})
assert ok and not fail, f"無上游實據卻誤報：{fail}"

# 4. **關鍵回歸**：區塊名含空格（#170 那 4 鍵正是這形狀）
ok, fail, _ = run({"Recipe_Craft_Metal_Arrows_from_Plank": "製作金屬箭矢 (木板)"},
                  ["Craft Metal Arrows from Plank"], [], {})
assert not ok, "含空格的區塊名未被還原——#170 的 blocking 會再次溜過"
assert "Craft Metal Arrows from Plank" in fail[0], f"還原結果不對：{fail[0]}"

# 4b. **關鍵回歸**：底線與空格**混用**的區塊名。`body.replace("_"," ")` 在此必漏
#     （會得到 `SVRP CB Pack Metal Arrows`，把區塊本來就有的底線也換掉）。
ok, fail, _ = run({"Recipe_SVRP_CB_Pack_Metal_Arrows": "金屬箭矢裝包"},
                  ["SVRP_CB_Pack Metal Arrows"], [], {})
assert not ok, "混用底線與空格的區塊名未被還原"
assert "SVRP_CB_Pack Metal Arrows" in fail[0], f"還原結果不對：{fail[0]}"

# 4c. 直接去前綴的形狀（無空格）同樣要抓，且 `craftRecipe_` 前綴要處理
ok, fail, _ = run({"craftRecipe_SVRP_CB_PackMetalArrows": "金屬箭矢裝包"},
                  ["SVRP_CB_PackMetalArrows"], [], {})
assert not ok, "craftRecipe_ 前綴未被處理"

# 4d. 精確命中優先：上游同時有 `Foo Bar` 與 `Foo_Bar` 時，legacy body `Foo_Bar` 精確
#     對上後者，不得因底線化索引撞在一起而判歧義。
ok, fail, warn = run({"Recipe_Foo_Bar": "甲乙"}, ["Foo Bar", "Foo_Bar"], [], {})
assert not ok and "`Foo_Bar`" in fail[0], f"精確命中未優先：{fail} {warn}"
assert not warn, f"精確命中不該報歧義：{warn}"

# 4e. body 本身含空格（JSON 鍵允許空格，legacy 鍵不保證把空格換成底線）→ 索引須收原形
ok, fail, _ = run({"Recipe_Craft Metal Arrows": "製作金屬箭矢"},
                  ["Craft Metal Arrows"], [], {})
assert not ok and "Craft Metal Arrows" in fail[0], f"含空格的 body 未被還原：{fail}"

# 4e2. **真歧義會自然發生**：`Foo Bar_Baz` 與 `Foo_Bar Baz` 底線化後都是 `Foo_Bar_Baz`，
#      而 body `Foo_Bar_Baz` 不精確等於任一。此時兩個裸鍵都沒出貨＝真的有活配方顯示
#      英文，**必須 FAIL**（只記 WARN 會讓真缺口綠燈放行）。歧義不可機械消解——prefix
#      鍵沒帶 owner 資訊，只能人工裁決。
ok, fail, warn = run({"Recipe_Foo_Bar_Baz": "甲乙丙"}, ["Foo Bar_Baz", "Foo_Bar Baz"], [], {})
assert not ok, f"自然發生的歧義未 fail-closed：fail={fail} warn={warn}"
assert "可還原成多個上游區塊名" in fail[0] and "人工裁決" in fail[0], f"訊息不 actionable：{fail}"

# 4e3. 歧義但候選全部已滿足（都已出貨）→ 不報。歧義本身不是缺陷，缺口才是。
ok, fail, warn = run({"Recipe_Foo_Bar_Baz": "甲乙丙",
                      "Foo Bar_Baz": "甲乙丙", "Foo_Bar Baz": "甲乙丙"},
                     ["Foo Bar_Baz", "Foo_Bar Baz"], [], {})
assert ok and not fail, f"候選全已出貨仍誤報：{fail}"

# 4e4. 歧義且僅部分候選滿足 → 仍要 FAIL（另一個候選還是顯示英文）
ok, fail, _ = run({"Recipe_Foo_Bar_Baz": "甲乙丙", "Foo Bar_Baz": "甲乙丙"},
                  ["Foo Bar_Baz", "Foo_Bar Baz"], [], {})
assert not ok and "Foo_Bar Baz" in fail[0], f"部分滿足的歧義被放行：{fail}"

# 4e5. helper 契約：多候選一律回全部，不得靜默任選
assert verify_dist._recipe_bare_names("Recipe_X_Y", {"X_Y": ["X Y", "X-Y"]}) \
    == ["X Y", "X-Y"], "多候選未回全部——會靜默任選一個"

# 4f. 空 body（裸 `Recipe_`）不得亂猜
ok, fail, _ = run({"Recipe_": "空"}, ["MakeBeeSmoker"], [], {})
assert ok and not fail, f"空 body 被誤判：{fail}"

# 5. 裸名屬 vanilla → 放行（補了會全域改寫本體配方名，見 gate [12] 與 vanilla 出貨抑制）
ok, fail, _ = run({"Recipe_Dismantle_Headphones": "拆解頭戴式耳機"},
                  ["Dismantle Headphones"], ["Dismantle Headphones"], {})
assert ok and not fail, f"vanilla 裸名被誤報：{fail}"

# 6. 已登記 allowlist → 放行
ok, fail, _ = run({"Recipe_MakeBeeSmoker": "製作蜂煙器"}, ["MakeBeeSmoker"], [],
                  {"MakeBeeSmoker": "查證後暫緩"})
assert ok and not fail, f"已登記豁免仍誤報：{fail}"

# 7. 反向棘輪：裸鍵已補好，allowlist 條目該出 WARN
ok, fail, warn = run({"Recipe_MakeBeeSmoker": "製作蜂煙器", "MakeBeeSmoker": "製作蜂煙器"},
                     ["MakeBeeSmoker"], [], {"MakeBeeSmoker": "舊理由"})
assert ok, "已補裸鍵不該 FAIL"
assert warn and "MakeBeeSmoker" in warn[0], f"過時 allowlist 條目未出 WARN：{warn}"

# 7b. 前綴鍵整個消失（上游改名/移除），allowlist 條目也該出 WARN
ok, fail, warn = run({"OtherRecipe": "其他"}, ["MakeBeeSmoker"], [], {"MakeBeeSmoker": "舊理由"})
assert ok and warn, f"前綴鍵已不存在時應出 WARN：fail={fail} warn={warn}"

# 7c. 裸名已屬 vanilla（基準自動放行）時，allowlist 條目是重複登記，也該出 WARN——
#     否則基準日後移除該鍵，過時豁免會靜默接手繼續放行。
ok, fail, warn = run({"Recipe_Dismantle_Headphones": "拆解頭戴式耳機"},
                     ["Dismantle Headphones"], ["Dismantle Headphones"],
                     {"Dismantle Headphones": "撞 vanilla"})
assert ok and warn and "Dismantle Headphones" in warn[0], f"vanilla 重複登記未報 WARN：{warn}"

# 8. 乾淨輸入（只有裸鍵）→ PASS 且零 WARN
ok, fail, warn = run({"MakeBeeSmoker": "製作蜂煙器"}, ["MakeBeeSmoker"], [], {})
assert ok and not fail and not warn, f"乾淨輸入被誤報：{fail} {warn}"

# 9. **有效版本分支過濾**：只存在死分支的區塊名不算現行實據，不得逼人補死鍵。
#    2026-08-16 實測：8,816 個區塊名有 1,889 個只在死分支，未濾時 Firearms 的
#    `ConvertAmmo`／`DetractStock`／`ExtendStock`（現行已改名 `ToggleStock`）被誤判為缺口。
ok, fail, _ = run({"Recipe_ConvertAmmo": "轉換彈藥"}, ["ConvertAmmo"], [], {}, relpath=DEAD)
assert ok and not fail, f"死分支區塊名被當成現行實據：{fail}"
ok, fail, _ = run({"Recipe_ConvertAmmo": "轉換彈藥"}, ["ConvertAmmo"], [], {}, relpath=EFF)
assert not ok, "有效分支的區塊名反而沒抓到——過濾把實據也濾掉了"

# 10. **fail-closed**：實據殘缺不得靜默視為「零死鍵」。以下每種都必須擲例外。
DEAD_KEY_DIST = {"Recipe_MakeBeeSmoker": "製作蜂煙器"}
for label, state in (
    ("mods 缺席", {"extractor_schema": 8}),
    ("mods 空 dict", {"mods": {}}),
    ("mods 是 list", {"mods": []}),
    ("mods 是 null", {"mods": None}),
    ("整檔空物件", {}),
):
    msg = raises(lambda st=state: run(DEAD_KEY_DIST, [], [], {}, state=st))
    assert "mods 形狀壞損" in msg, f"{label} 的例外訊息不 actionable：{msg}"

msg = raises(lambda: run(DEAD_KEY_DIST, [], [], {},
                         state={"mods": {"1": {"records": ["not", "a", "dict"]}}}))
assert "records 形狀壞損" in msg, f"records 壞損未 fail-closed：{msg}"

# 濾後區塊名量級不足（extractor schema 改版使記錄改名／state 被清空的典型形狀）
msg = raises(lambda: run(DEAD_KEY_DIST, ["MakeBeeSmoker"], [], {}, filler=False))
assert "下限" in msg, f"量級門檻未 fail-closed：{msg}"

for label, raw in (
    ("entries 缺席", {}),
    ("entries 是 null", {"entries": None}),
    ("entries 是 list", {"entries": ["Foo"]}),
    ("entries 是字串", {"entries": "Foo"}),
    ("理由為空字串", {"entries": {"Foo": ""}}),
    ("鍵為空字串", {"entries": {"": "理由"}}),
):
    msg = raises(lambda r=raw: run(DEAD_KEY_DIST, ["MakeBeeSmoker"], [], {}, allow_raw=r))
    assert "entries 形狀壞損" in msg, f"allowlist {label} 未 fail-closed：{msg}"

# 10b. **per-mod schema 落後是局部漏報盲區**：`tracker.EXTRACTOR_SCHEMA=5` 起才掃全部
#      `media/scripts` 目錄，低於此者的區塊名清單可能殘缺，本項對它們的 legacy 鍵會漏報。
#      總量門檻（RECIPE_BLOCKS_MIN）抓不到這種局部殘缺，故另出 WARN 讓盲區可見。
#      刻意不判 FAIL——schema 落後是正常狀態（mod 沒更新就不會重抽）。
for label, sch in (("低於下限", verify_dist.CRAFT_SCHEMA_MIN - 1), ("缺席", None),
                   ("非整數", "8")):
    ok, fail, warn = run({"MakeBeeSmoker": "製作蜂煙器"}, ["MakeBeeSmoker"], [], {},
                         schema=sch)
    assert ok and not fail, f"schema {label} 不該 FAIL：{fail}"
    assert any("extractor_schema <" in w for w in warn), f"schema {label} 未出 WARN：{warn}"
ok, fail, warn = run({"MakeBeeSmoker": "製作蜂煙器"}, ["MakeBeeSmoker"], [], {},
                     schema=verify_dist.CRAFT_SCHEMA_MIN)
assert ok and not warn, f"schema 達標卻出 WARN：{warn}"

# 11. 還原函式的邊界（直接測 helper，索引由 `_block_index` 建）
IDX = verify_dist._block_index({"MakeBeeSmoker", "Craft Metal Arrows from Plank",
                                "SVRP_CB_Pack Metal Arrows"})
B = verify_dist._recipe_bare_names
assert B("Recipe_MakeBeeSmoker", IDX) == ["MakeBeeSmoker"]
assert B("Recipe_Craft_Metal_Arrows_from_Plank", IDX) == ["Craft Metal Arrows from Plank"]
assert B("Recipe_SVRP_CB_Pack_Metal_Arrows", IDX) == ["SVRP_CB_Pack Metal Arrows"]
assert B("MakeBeeSmoker", IDX) == [], "無前綴鍵不該被還原"
assert B("Recipe_", IDX) == [], "空 body 不該匹配"
assert B("UI_MakeBeeSmoker", IDX) == [], "非配方前綴不該處理"

# 12. 多個前綴 alias 映到同一裸名時，FAIL 只出一項且訊息列出全部 alias
ok, fail, _ = run({"Recipe_MakeBeeSmoker": "製作蜂煙器",
                   "craftRecipe_MakeBeeSmoker": "製作蜂煙器"}, ["MakeBeeSmoker"], [], {})
assert not ok and len(fail) == 1, f"同一裸名應只出一項 FAIL：{fail}"
assert "Recipe_MakeBeeSmoker" in fail[0] and "craftRecipe_MakeBeeSmoker" in fail[0], \
    f"FAIL 訊息未列出全部 alias：{fail[0]}"

# 13. **對 checked-in dist 實跑一次**。上面全部是 synthetic fixture——只有它們的話，
#     真實 dist 新增死鍵時 CI 仍會全綠（[16] 不依賴 As1 快照，CI 上跑得動，不像
#     verify 的 [8]）。這一項讓 CI 直接守住出貨物本身。
REPO = Path(__file__).resolve().parent.parent
dist_dirs = sorted(REPO.glob("MOD/*/Contents/mods/*/42/media/lua/shared/Translate/CH"))
assert len(dist_dirs) == 1, f"預期恰好一個 dist CH 目錄，實得 {dist_dirs}"
ok, fail, warn = verify_dist.check_recipe_dead_keys(str(REPO), str(dist_dirs[0]))
assert ok, "checked-in dist 有未裁決的 Recipes 死鍵：\n  " + "\n  ".join(fail)
# 盲區提示（schema 落後）不是失敗——真實 tracker-state 恆有幾個未更新的 mod。
# 只把 allowlist 過時類當成該修的東西。
stale_allow = [w for w in warn if verify_dist.RECIPE_DEAD_ALLOWLIST in w]
assert not stale_allow, "recipe_dead_allowlist.json 有過時條目：\n  " + "\n  ".join(stale_allow)

print("✅ test_recipe_dead_keys：30 組情境全過（含對 checked-in dist 實跑）")
