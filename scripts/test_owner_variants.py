# /// script
# requires-python = ">=3.11"
# ///
"""條件譯文（`sources/owner_variants.json` → 注入器資料檔）管線的回歸測試。

注入器繞過 JSON 載入、直接寫 `Translator.BY_NAME`，所以資料檔的值與欄位格式沒有引擎幫忙
兜底；本包又承諾「JSON 出貨零本體鍵、本體鍵的條件譯文逐案核准才出貨」。要鎖住的事：
  1. formatFixer：`%N`→`%N$s`、`%%` 原樣，builder 與 oracle 兩份實作同語意。
  2. 欄位跳脫往返：`\\`、TAB、LF、CR 跳脫後逆轉回原值；未知跳脫 fail-loud。
  3. build `variant_gate`：本體鍵逐 group 核准（條目層級 approved＝全組；部分核准時未核准組與
     skip owner 出空值列；全未核准整鍵不出貨）；
     token 不符、簡體字、空值、白名單外檔名、刷新不到的鍵（特質／職業名稱、液體名；說明鍵
     `*desc` 放行）、conflict 撞本體鍵都擋下。
  4. prep `--check-decisions`：簽名過時與 owner 分組不符非零退出（列 `_stale_decisions`），
     並在 `_stale_variants` 給新簽名與重新分組；壞形狀列 `_unchecked`；本體鍵只在
     vanilla-inclusive census 裡；`--owner-report` 寫出的 `owner_conflicts.tsv` 含本體鍵衝突。
  5. verify [18]／[19]：dist 資料檔或本包 Lua 被竄改即 FAIL。

執行：uv run scripts/test_owner_variants.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402
import prep_mod_strings  # noqa: E402
import tracker  # noqa: E402
import verify_dist  # noqa: E402

os.environ.pop(prep_mod_strings.OWNER_VARIANTS_ENV, None)   # 測試一律讀臨時 repo 的檔
CASES = 0


def case(label: str) -> str:
    global CASES
    CASES += 1
    return label


# --- 1. formatFixer ------------------------------------------------------------------- #
case("formatFixer")
for raw, want in (("%1 個", "%1$s 個"), ("%%1", "%%1"), ("%%%1", "%%%1$s"), ("%10", "%1$s0"),
                  ("%1%%", "%1$s%%"), ("%s／%d／%.1f", "%s／%d／%.1f"), ("無", "無"),
                  ("%1 與 %2", "%1$s 與 %2$s")):
    assert build_mod.format_fixer(raw) == want, (raw, build_mod.format_fixer(raw))
    assert verify_dist.format_fixer_expectation(raw) == want, (raw, "oracle 分岔")

# --- 2. 跳脫往返 ------------------------------------------------------------------------ #
case("跳脫往返")
for raw in ("a\\b", "x\ty", "第一行\n第二行", "cr\r", "\\t 字面", "\\\\n", "平常"):
    esc = prep_mod_strings.tsv_escape(raw)
    assert "\t" not in esc and "\n" not in esc and "\r" not in esc, esc
    assert verify_dist._tsv_unescape(esc) == raw, (raw, esc)
try:
    verify_dist._tsv_unescape("壞\\x")
    raise AssertionError("未知跳脫未 fail-loud")
except ValueError:
    pass

# --- 3. build variant_gate ----------------------------------------------------------- #
SCOPED = {"ItemName.json": {"Base.Axe"}, "IG_UI.json": {"IGUI_Vanilla"}}


def grp(owners, en, ch, cn):
    return {"owners": owners, "en": en, "ch": ch, "cn": cn}


GOOD = {
    "IG_UI|IGUI_Car": {"kind": "conflict", "signature": "s", "groups": [
        grp(["1/A"], "Car %1", "車 %1", "车 %1"), grp(["2/B"], "Truck %1", "卡車 %1", "卡车 %1")]},
    "ItemName|Base.Axe": {"kind": "vanilla", "signature": "s", "vanilla_en": "Axe",
                          "skip_owners": ["3/C"], "approved": "2026-10-23 使用者核准",
                          "groups": [grp(["1/A"], "Fire Axe", "消防斧", "消防斧")]},
}
case("gate 綠＋出貨列")
errs, rows, n_van = build_mod.variant_gate(GOOD, SCOPED)
assert not errs, errs
assert n_van == 1
assert rows["CH"] == [
    ("IG_UI", "IGUI_Car", "1", "A", "車 %1$s"), ("IG_UI", "IGUI_Car", "2", "B", "卡車 %1$s"),
    ("ItemName", "Base.Axe", "1", "A", "消防斧"), ("ItemName", "Base.Axe", "3", "C", ""),
], rows["CH"]
assert rows["CN"][1] == ("IG_UI", "IGUI_Car", "2", "B", "卡车 %1$s")

case("未核准本體鍵不出貨")
unapproved = json.loads(json.dumps(GOOD))
unapproved["ItemName|Base.Axe"]["approved"] = "  "
errs, rows, n_van = build_mod.variant_gate(unapproved, SCOPED)
assert not errs and n_van == 0
assert all(r[1] != "Base.Axe" for r in rows["CH"] + rows["CN"]), "未核准本體鍵出貨了"
del unapproved["ItemName|Base.Axe"]["approved"]
assert all(r[1] != "Base.Axe" for r in build_mod.variant_gate(unapproved, SCOPED)[1]["CH"])

# 本體鍵逐 MOD（逐 group）核准：1/A 核准、2/B 未核准、3/C 與本體同英文（skip）
PARTIAL = {"ItemName|Base.Axe": {
    "kind": "vanilla", "signature": "s", "vanilla_en": "Axe", "skip_owners": ["3/C"],
    "groups": [grp(["1/A"], "Fire Axe", "消防斧", "消防斧") | {"approved": "2026-10-23 核准 A"},
               grp(["2/B", "2/B2"], "Wood Axe", "木斧", "木斧")]}}
case("部分 group 核准：核准組出值、未核准組與 skip 出空值列（勝出規則不變，每個 owner 都有列）")
errs, rows, n_van = build_mod.variant_gate(PARTIAL, SCOPED)
assert not errs and n_van == 1, (errs, n_van)
assert rows["CH"] == [("ItemName", "Base.Axe", "1", "A", "消防斧"), ("ItemName", "Base.Axe", "2", "B", ""),
                      ("ItemName", "Base.Axe", "2", "B2", ""), ("ItemName", "Base.Axe", "3", "C", "")], rows

case("條目層級核准＝全組核准")
whole = json.loads(json.dumps(PARTIAL))
whole["ItemName|Base.Axe"]["approved"] = "2026-10-23 全部核准"
_, rows, _ = build_mod.variant_gate(whole, SCOPED)
assert [r[4] for r in rows["CH"]] == ["消防斧", "木斧", "木斧", ""], rows

case("全未核准（group 的 approved 空白）整鍵不出貨、連空值列都不寫")
none_ok = json.loads(json.dumps(PARTIAL))
none_ok["ItemName|Base.Axe"]["groups"][0]["approved"] = " "
errs, rows, n_van = build_mod.variant_gate(none_ok, SCOPED)
assert not errs and n_van == 0 and rows == {"CH": [], "CN": []}, rows

case("未核准 group 照樣跑逐值 gate")
bad_unapproved = json.loads(json.dumps(PARTIAL))
bad_unapproved["ItemName|Base.Axe"]["groups"][1]["ch"] = "木斧 50%"
errs, _, _ = build_mod.variant_gate(bad_unapproved, SCOPED)
assert any("必炸" in e for e in errs), errs

case("conflict 的 group 帶 approved 是形狀錯誤（prep 形狀檢查，build loader 共用）")
bad_conflict = json.loads(json.dumps(GOOD["IG_UI|IGUI_Car"]))
bad_conflict["groups"][0]["approved"] = "x"
assert "approved" in (prep_mod_strings._variant_shape_problem("IG_UI|IGUI_Car", bad_conflict) or "")
bad_type = json.loads(json.dumps(PARTIAL["ItemName|Base.Axe"]))
bad_type["groups"][0]["approved"] = True
assert prep_mod_strings._variant_shape_problem("ItemName|Base.Axe", bad_type), "非字串 approved 未擋"
assert prep_mod_strings._variant_shape_problem("ItemName|Base.Axe", PARTIAL["ItemName|Base.Axe"]) is None

case("conflicts.tsv V 列已涵蓋數只算核准組與（有核准時）skip 的 wid")
with tempfile.TemporaryDirectory() as tdn:
    k_src = Path(tdn) / "owner_conflicts.tsv"
    k_src.write_text("# h\n", encoding="utf-8", newline="\n")
    saved = build_mod.OWNER_CONFLICTS_TSV, build_mod.vanilla_override_counts
    try:
        build_mod.OWNER_CONFLICTS_TSV = k_src
        build_mod.vanilla_override_counts = lambda: {"1": 3, "2": 4, "3": 5, "4": 0}
        v = [ln for ln in build_mod.render_conflicts_tsv(PARTIAL).split("\n") if ln.startswith("V")]
        assert v == ["V\t1\t3\t1", "V\t2\t4\t0", "V\t3\t5\t1"], v
        v = [ln for ln in build_mod.render_conflicts_tsv(none_ok).split("\n") if ln.startswith("V")]
        assert v == ["V\t1\t3\t0", "V\t2\t4\t0", "V\t3\t5\t0"], v
    finally:
        build_mod.OWNER_CONFLICTS_TSV, build_mod.vanilla_override_counts = saved

for label, fk, mutate, needle in (
    ("token 不符", "IG_UI|IGUI_Car", lambda e: e["groups"][0].update(ch="車"), "format token"),
    ("標記不符", "IG_UI|IGUI_Car", lambda e: e["groups"][0].update(
        en="Car <br> %1", cn="车 <br> %1"), "format token"),
    ("裸 %", "IG_UI|IGUI_Car", lambda e: e["groups"][0].update(ch="車 %1 50%"), "必炸"),
    ("簡體字", "IG_UI|IGUI_Car", lambda e: e["groups"][0].update(ch="车 %1"), "簡體"),
    ("空值", "IG_UI|IGUI_Car", lambda e: e["groups"][1].update(cn=""), "空值"),
    ("白名單外", "Compendium|IGUI_Car", None, "VARIANT_FILES"),
    ("刷新不到的特質名稱", "UI|UI_trait_X", None, "載入期已快取"),
    ("刷新不到的職業名稱", "UI|UI_prof_X", None, "載入期已快取"),
    ("刷新不到的液體名", "Fluids|Fluid_Name_X", None, "載入期已快取"),
    ("conflict 撞本體鍵", "IG_UI|IGUI_Vanilla", None, "kind=vanilla"),
):
    case(f"gate 擋 {label}")
    ents = json.loads(json.dumps(GOOD))
    if mutate:
        mutate(ents[fk])
    else:
        ents[fk] = ents.pop("IG_UI|IGUI_Car")
    errs, _, _ = build_mod.variant_gate(ents, SCOPED)
    assert any(needle in e for e in errs), (label, errs)

case("特質／職業說明鍵（desc 結尾）放行，builder 與 oracle 同語意")
for key, blocked in (("UI_trait_XDesc", False), ("UI_trait_xdesc", False), ("UI_prof_XDESC", False),
                     ("UI_trait_X", True), ("UI_prof_X", True), ("UI_trait_Description", True),
                     ("UI_profdesc_X", False), ("Fluid_Name_XDesc", True), ("EC_Energy_X", True)):
    assert build_mod.variant_key_unrefreshable(key) is blocked, key
    ents = {f"UI|{key}": GOOD["IG_UI|IGUI_Car"]}
    errs, rows, _ = build_mod.variant_gate(ents, SCOPED)
    assert any("載入期已快取" in e for e in errs) is blocked, (key, errs)
    assert bool(rows["CH"]) is not blocked, key
    with tempfile.TemporaryDirectory() as tdn:
        (Path(tdn) / "sources").mkdir()
        (Path(tdn) / "sources" / "owner_variants.json").write_text(
            json.dumps({"entries": ents}, ensure_ascii=False), encoding="utf-8")
        _, fail, _ = verify_dist.check_variants(tdn, tdn)   # 資料檔不存在：只看前綴判定
        assert any("刷新不到" in f for f in fail) is blocked, (key, fail)

case("資料檔渲染")
text = build_mod.render_variant_tsv([("UI", "UI_X", "1", "A\tB", "一\n二")])
lines = text.split("\n")
assert lines[0].startswith("#") and lines[-1] == "" and lines[1] == "UI\tUI_X\t1\tA\\tB\t一\\n二", lines

# --- 4. prep --check-decisions ------------------------------------------------------- #
EFF_A = "mods/A/42.20/media/scripts/items.txt"
EFF_B = "mods/B/42.20/media/scripts/items.txt"
MIRROR = {f"script_item_dn|{EFF_A}|Mod.Gun": "Gun A", f"script_item_dn|{EFF_B}|Mod.Gun": "Gun B",
          f"script_item_dn|{EFF_A}|Base.Axe": "Fire Axe", f"script_item_dn|{EFF_B}|Base.Axe": "Felling Axe"}
GUN = {"1/A": "Gun A", "1/B": "Gun B"}
AXE = {"1/A": "Fire Axe", "1/B": "Felling Axe"}


def prep(variants: dict | None, *, report: bool = False, raw: str | None = None):
    """臨時 repo 跑 `prep --check-decisions`（report=True 另跑 --owner-report），回 (rc, artifact, root 讀出的 tsv)。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sources" / "en").mkdir(parents=True)
        (root / "sources" / "vanilla_keys.json").write_text(json.dumps(
            {"keys": ["Base.Axe"], "scoped_keys": {"ItemName.json": ["Base.Axe"]}}), encoding="utf-8")
        (root / "sources" / "en" / "1.json").write_text(json.dumps(MIRROR), encoding="utf-8")
        tracker.write_corpus_hashes({"mods": {"1": {
            "extractor_schema": tracker.ITEM_MODULE_SCHEMA,
            "records": {r: tracker.value_hash(v) for r, v in MIRROR.items()}}}},
            root / "tracker-state" / "en_corpus_hashes")
        if raw is not None or variants is not None:
            (root / "sources" / "owner_variants.json").write_text(
                raw if raw is not None else json.dumps({"entries": variants}, ensure_ascii=False),
                encoding="utf-8")
        dist = root / "Translate" / "CH"
        for d in (dist, root / "Translate" / "CN"):
            d.mkdir(parents=True)
            (d / "ItemName.json").write_text("{}", encoding="utf-8")
        out = root / "out.json"
        saved = (prep_mod_strings.ROOT, prep_mod_strings.DIST_CH,
                 prep_mod_strings.OWNER_CONFLICTS_MD, sys.argv, sys.stderr)
        try:
            sys.stderr = io.StringIO()
            prep_mod_strings.ROOT, prep_mod_strings.DIST_CH = root, dist
            prep_mod_strings.OWNER_CONFLICTS_MD = root / "OWNER_CONFLICTS.md"
            sys.argv = ["prep", "--out", str(out),
                        "--owner-report" if report else "--check-decisions"]
            rc = prep_mod_strings.main()
        finally:
            (prep_mod_strings.ROOT, prep_mod_strings.DIST_CH,
             prep_mod_strings.OWNER_CONFLICTS_MD, sys.argv, sys.stderr) = saved
        tsv = root / "sources" / "owner_conflicts.tsv"
        return (rc, json.loads(out.read_text(encoding="utf-8")),
                tsv.read_text(encoding="utf-8") if tsv.exists() else None)


SIG_GUN = prep_mod_strings.census_signature(GUN)
SIG_AXE = prep_mod_strings.census_signature(AXE)
V_GUN = {"kind": "conflict", "signature": SIG_GUN,
         "groups": [grp(["1/A"], "Gun A", "甲槍", "甲枪"), grp(["1/B"], "Gun B", "乙槍", "乙枪")]}
V_AXE = {"kind": "vanilla", "signature": SIG_AXE, "vanilla_en": "Felling Axe", "skip_owners": ["1/B"],
         "groups": [grp(["1/A"], "Fire Axe", "消防斧", "消防斧")]}

case("prep 衝突＋本體鍵條件譯文全符 → rc 0（Mod.Gun 未裁決的 owner 衝突另計，不在此斷言）")
rc, art, _ = prep({"ItemName|Base.Axe": V_AXE})
assert not art["_unchecked"] and not art["_stale_decisions"], art

case("prep 報告：owner_conflicts.tsv 含本體鍵衝突（census_v）")
rc, art, tsv = prep(None, report=True)
k_rows = [ln for ln in tsv.split("\n") if ln.startswith("K\t")]
assert k_rows == ["K\tItemName|Base.Axe\t1:1/A\t2:1/B", "K\tItemName|Mod.Gun\t1:1/A\t2:1/B"], k_rows
assert "ItemName|Base.Axe" not in art["_owner_conflicts_other"], "本體鍵不該進原 census"

for label, entry, needle in (
    ("簽名過時", {**V_GUN, "signature": "0" * 16}, "條件譯文過時"),
    ("owner 分組錯", {**V_GUN, "groups": [grp(["1/A", "1/B"], "Gun A", "槍", "枪")]}, "分組與 census 不符"),
    ("少一個 owner", {**V_GUN, "groups": [V_GUN["groups"][0]]}, "owner 集合不符"),
):
    case(f"prep 擋 {label}")
    rc, art, _ = prep({"ItemName|Mod.Gun": entry})
    assert rc == 1 and any(needle in s for s in art["_stale_decisions"]), (label, art["_stale_decisions"])

case("prep `_stale_variants`：簽名錯 → 給正確新簽名與分組，全符者不列")
rc, art, _ = prep({"ItemName|Mod.Gun": {**V_GUN, "signature": "0" * 16}, "ItemName|Base.Axe": V_AXE})
assert set(art["_stale_variants"]) == {"ItemName|Mod.Gun"}, art["_stale_variants"]
prop = art["_stale_variants"]["ItemName|Mod.Gun"]
assert prop["signature"] == SIG_GUN and prop["kind"] == "conflict" and prop["vanilla_en"] is None
assert prop["groups"] == [{"owners": ["1/A"], "en": "Gun A"}, {"owners": ["1/B"], "en": "Gun B"}]
assert prop["skip_owners"] == [] and "條件譯文過時" in prop["reason"], prop

case("prep 擋 本體鍵 skip owner 英文與 vanilla_en 不同（建議分組改由 vanilla_en 重拆）")
rc, art, _ = prep({"ItemName|Base.Axe": {**V_AXE, "vanilla_en": "Wood Axe"}})
assert rc == 1 and any("分組與英文異同不符" in s for s in art["_stale_decisions"]), art["_stale_decisions"]
prop = art["_stale_variants"]["ItemName|Base.Axe"]
assert prop["kind"] == "vanilla" and prop["signature"] == SIG_AXE and prop["skip_owners"] == [], prop
assert [g["owners"] for g in prop["groups"]] == [["1/A"], ["1/B"]], prop

case("prep 擋 conflict 用在本體鍵")
rc, art, _ = prep({"ItemName|Base.Axe": {k: v for k, v in V_AXE.items()
                                         if k not in ("vanilla_en", "skip_owners")}
                   | {"kind": "conflict", "groups": [grp(["1/A"], "Fire Axe", "消防斧", "消防斧"),
                                                     grp(["1/B"], "Felling Axe", "伐木斧", "伐木斧")]}})
assert rc == 1 and any("kind=vanilla" in s for s in art["_stale_decisions"]), art["_stale_decisions"]

for label, kwargs in (("壞形狀條目", {"variants": {"ItemName|Mod.Gun": {"kind": "conflict"}}}),
                      ("壞 JSON", {"variants": None, "raw": "{ not json"})):
    case(f"prep 列 _unchecked：{label}")
    rc, art, _ = prep(**kwargs)
    assert rc == 1 and art["_unchecked"], (label, art)

# --- 5. verify [18]／[19] 抓竄改 ---------------------------------------------------------- #
def verify_repo(td: Path, entries: dict) -> Path:
    """組臨時 repo＋dist（資料檔由 builder 渲染），回 media 路徑。"""
    (td / "sources" / "pack_lua" / "shared").mkdir(parents=True)
    (td / "sources" / "pack_lua" / "shared" / "Inj.lua").write_bytes(b"-- inj\n")
    (td / "sources" / "owner_variants.json").write_text(
        json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    k_tsv = "# head\nK\tIG_UI|IGUI_Car\t1:1/A\t2:2/B\n"
    (td / "sources" / "owner_conflicts.tsv").write_text(k_tsv, encoding="utf-8", newline="\n")
    media = td / "media"
    (media / "CatModLang").mkdir(parents=True)
    (media / "lua" / "shared" / "CatModLang").mkdir(parents=True)
    (media / "lua" / "shared" / "CatModLang" / "Inj.lua").write_bytes(b"-- inj\n")
    _, rows, _ = build_mod.variant_gate(entries, SCOPED)
    for lang, r in rows.items():
        (media / "CatModLang" / f"variants_{lang}.tsv").write_text(
            build_mod.render_variant_tsv(r), encoding="utf-8", newline="\n")
    (media / "CatModLang" / "conflicts.tsv").write_text(
        k_tsv + "V\t1\t5\t1\nV\t3\t2\t1\n", encoding="utf-8", newline="\n")
    return media


with tempfile.TemporaryDirectory() as tdn:
    td = Path(tdn)
    media = verify_repo(td, GOOD)
    case("verify 原樣 PASS")
    ok, fail, _ = verify_dist.check_variants(str(td), str(media))
    assert ok, fail
    assert verify_dist.check_pack_lua(str(td), str(media))[0]

    ch = media / "CatModLang" / "variants_CH.tsv"
    original = ch.read_text(encoding="utf-8")
    for label, tampered in (
        ("改值", original.replace("消防斧", "斧")),
        ("值沒套 formatFixer", original.replace("%1$s", "%1")),
        ("多一列（未核准／無真相源）", original + "UI\tUI_X\t9\tZ\t偷渡\n"),
        ("CRLF", original.replace("\n", "\r\n")),
    ):
        case(f"verify 抓 {label}")
        ch.write_bytes(tampered.encode("utf-8"))
        ok, fail, _ = verify_dist.check_variants(str(td), str(media))
        assert not ok, (label, fail)
    ch.write_text(original, encoding="utf-8", newline="\n")

    case("verify 抓 未核准本體鍵出貨")
    unapproved = json.loads(json.dumps(GOOD))
    unapproved["ItemName|Base.Axe"]["approved"] = ""
    (td / "sources" / "owner_variants.json").write_text(
        json.dumps({"entries": unapproved}, ensure_ascii=False), encoding="utf-8")
    ok, fail, _ = verify_dist.check_variants(str(td), str(media))
    assert not ok and any("Base.Axe" in f for f in fail), fail
    (td / "sources" / "owner_variants.json").write_text(
        json.dumps({"entries": GOOD}, ensure_ascii=False), encoding="utf-8")

    conflicts = media / "CatModLang" / "conflicts.tsv"
    for label, tampered in (("K 列漂移", "# h\nK\tIG_UI|IGUI_Car\t1:1/A\t1:2/B\nV\t1\t5\t1\nV\t3\t2\t1\n"),
                            ("V 列已涵蓋數錯", "# h\nK\tIG_UI|IGUI_Car\t1:1/A\t2:2/B\nV\t1\t5\t0\n")):
        case(f"verify 抓 conflicts {label}")
        conflicts.write_text(tampered, encoding="utf-8", newline="\n")
        assert not verify_dist.check_variants(str(td), str(media))[0], label

    case("verify 抓 本包 Lua 竄改")
    (media / "lua" / "shared" / "CatModLang" / "Inj.lua").write_bytes(b"-- evil\n")
    ok, fail, _ = verify_dist.check_pack_lua(str(td), str(media))
    assert not ok and any("bytes" in f for f in fail), fail

with tempfile.TemporaryDirectory() as tdn:
    td = Path(tdn)
    media = verify_repo(td, PARTIAL)
    conflicts = media / "CatModLang" / "conflicts.tsv"
    k_head = "# head\nK\tIG_UI|IGUI_Car\t1:1/A\t2:2/B\n"
    conflicts.write_text(k_head + "V\t1\t3\t1\nV\t2\t4\t0\nV\t3\t5\t1\n", encoding="utf-8", newline="\n")
    case("verify 部分 group 核准：獨立重算同規則 PASS")
    ok, fail, _ = verify_dist.check_variants(str(td), str(media))
    assert ok, fail
    ch = media / "CatModLang" / "variants_CH.tsv"
    original = ch.read_text(encoding="utf-8")
    case("verify 抓 未核准 group 被寫進譯文")
    ch.write_text(original.replace("2\tB\t\n", "2\tB\t木斧\n"), encoding="utf-8", newline="\n")
    ok, fail, _ = verify_dist.check_variants(str(td), str(media))
    assert not ok and any("木斧" in f for f in fail), fail
    case("verify 抓 未核准 group 的空值列被拿掉")
    ch.write_text(original.replace("ItemName\tBase.Axe\t2\tB2\t\n", ""), encoding="utf-8", newline="\n")
    assert not verify_dist.check_variants(str(td), str(media))[0]
    ch.write_text(original, encoding="utf-8", newline="\n")
    case("verify 抓 V 列把未核准 group 的 wid 算進已涵蓋")
    conflicts.write_text(k_head + "V\t1\t3\t1\nV\t2\t4\t1\nV\t3\t5\t1\n", encoding="utf-8", newline="\n")
    ok, fail, _ = verify_dist.check_variants(str(td), str(media))
    assert not ok and any("wid 2" in f for f in fail), fail
    case("verify 抓 conflict 的 group 帶 approved")
    bad = json.loads(json.dumps(GOOD))
    bad["IG_UI|IGUI_Car"]["groups"][0]["approved"] = "x"
    (td / "sources" / "owner_variants.json").write_text(
        json.dumps({"entries": bad}, ensure_ascii=False), encoding="utf-8")
    ok, fail, _ = verify_dist.check_variants(str(td), str(media))
    assert not ok and any("group 帶 approved" in f for f in fail), fail

print(f"✅ test_owner_variants：{CASES} 組情境全過")
