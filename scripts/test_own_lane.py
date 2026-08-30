# /// script
# requires-python = ">=3.10"
# ///
"""own-mod lane 負向回歸測試（split 保留/刪除分類、verify own oracle 去重、tracker 歸類）

執行：uv run scripts/test_own_lane.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402
import split_sources  # noqa: E402
import tracker  # noqa: E402
import verify_dist  # noqa: E402


def make_mod(root: Path, wid: str, meta: dict | None, cn: dict[str, dict] | None = None) -> Path:
    d = root / wid
    (d / "CN").mkdir(parents=True)
    if meta is not None:
        (d / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    for fname, data in (cn or {}).items():
        (d / "CN" / fname).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


def run_write_outputs(mods: Path, out: dict[str, bytes]):
    split_sources.SOURCES = mods.parent
    split_sources.MODS_DIR = mods
    split_sources.UNSORTED_CN = mods.parent / "_unsorted" / "CN"
    split_sources.ATTR_INDEX_JSON = mods.parent / "attribution_index.json"
    split_sources.write_outputs(out)


AS1_META = {"workshop_id": "111", "mod_ids": ["A"], "attributed_via": {"map": 1}}
OWN_META = {"workshop_id": "222", "mod_ids": ["B"], "origin": "own"}
AS1_OUT = {"mods/111/CN/UI.json": b"{}", "mods/111/metadata.json": b"{}"}

# 1. own 目錄保留、as1 目錄刪除重寫
with tempfile.TemporaryDirectory() as td:
    mods = Path(td) / "mods"
    make_mod(mods, "111", AS1_META)
    make_mod(mods, "222", OWN_META, {"UI.json": {"k": "v"}})
    run_write_outputs(mods, dict(AS1_OUT))
    assert (mods / "222" / "CN" / "UI.json").exists(), "own 目錄未保留"
    assert (mods / "111" / "CN" / "UI.json").exists(), "as1 目錄未重寫"

# 2. 無法歸類的目錄（缺 metadata）→ SystemExit，且不動任何檔案
with tempfile.TemporaryDirectory() as td:
    mods = Path(td) / "mods"
    make_mod(mods, "333", None, {"UI.json": {"k": "v"}})
    try:
        run_write_outputs(mods, dict(AS1_OUT))
        raise AssertionError("缺 metadata 目錄未觸發 SystemExit")
    except SystemExit:
        pass
    assert (mods / "333" / "CN" / "UI.json").exists(), "拒刪語意破壞：檔案消失"

# 3. metadata 壞損 → SystemExit（來自 _own_mod_wids 或分類守衛皆可）
with tempfile.TemporaryDirectory() as td:
    mods = Path(td) / "mods"
    d = make_mod(mods, "444", None)
    (d / "metadata.json").write_text("{broken", encoding="utf-8")
    try:
        run_write_outputs(mods, dict(AS1_OUT))
        raise AssertionError("壞損 metadata 未觸發 SystemExit")
    except SystemExit:
        pass

# 4. own wid 與 As1 歸屬結果撞名 → SystemExit
with tempfile.TemporaryDirectory() as td:
    mods = Path(td) / "mods"
    make_mod(mods, "111", OWN_META)
    try:
        run_write_outputs(mods, dict(AS1_OUT))
        raise AssertionError("own/As1 撞 wid 未觸發 SystemExit")
    except SystemExit:
        pass

# 5. verify _load_own_mods：同值重複去重、異值報錯；As1 目錄不入 oracle
with tempfile.TemporaryDirectory() as td:
    repo = Path(td)
    mods = repo / "sources" / "mods"
    make_mod(mods, "111", AS1_META, {"UI.json": {"x": "as1"}})
    make_mod(mods, "222", OWN_META, {"UI.json": {"k": "v"}})
    make_mod(mods, "555", {**OWN_META, "workshop_id": "555"}, {"UI.json": {"k": "v"}})
    own = verify_dist._load_own_mods(str(repo))
    assert own == {"UI.json": {"k": {"cn": "v"}}}, f"own oracle 形狀錯誤: {own}"
    (mods / "555" / "CN" / "UI.json").write_text(json.dumps({"k": "different"}), encoding="utf-8")
    try:
        verify_dist._load_own_mods(str(repo))
        raise AssertionError("異值重複鍵未報錯")
    except ValueError:
        pass

# 6. tracker _is_own_mod：own True、as1 False、缺 metadata → SystemExit
with tempfile.TemporaryDirectory() as td:
    mods = Path(td)
    own_dir = make_mod(mods, "222", OWN_META)
    as1_dir = make_mod(mods, "111", AS1_META)
    bad_dir = make_mod(mods, "666", None)
    assert tracker._is_own_mod(own_dir) is True
    assert tracker._is_own_mod(as1_dir) is False
    try:
        tracker._is_own_mod(bad_dir)
        raise AssertionError("缺 metadata 未觸發 SystemExit")
    except SystemExit:
        pass

# 7. build load_own_translations：en/ch/cn 缺欄、空值或非字串 → SystemExit；合規通過
with tempfile.TemporaryDirectory() as td:
    own_json = Path(td) / "own_translations.json"
    orig = build_mod.OWN_TRANSLATIONS_JSON
    build_mod.OWN_TRANSLATIONS_JSON = own_json
    try:
        ok = {"entries": {"UI.json": {"K": {"en": "e", "ch": "譯", "cn": "译"}}}}
        own_json.write_text(json.dumps(ok), encoding="utf-8")
        assert build_mod.load_own_translations() == ok["entries"]
        for bad_spec in (
            {"ch": "譯", "cn": "译"},              # 缺 en
            {"en": "", "ch": "譯", "cn": "译"},    # en 空字串
            {"en": 1, "ch": "譯", "cn": "译"},     # en 非字串
            {"en": "e", "ch": "譯"},               # 缺 cn
        ):
            own_json.write_text(
                json.dumps({"entries": {"UI.json": {"K": bad_spec}}}), encoding="utf-8"
            )
            try:
                build_mod.load_own_translations()
                raise AssertionError(f"未擋下非法條目: {bad_spec}")
            except SystemExit:
                pass
    finally:
        build_mod.OWN_TRANSLATIONS_JSON = orig

# 8. verify check_vanilla_collision：形狀壞損 fail-closed、碰撞偵測、錨點豁免生效/失效
with tempfile.TemporaryDirectory() as td:
    repo = Path(td)
    (repo / "sources").mkdir()
    dist_cn_dir = repo / "dist_cn"
    dist_cn_dir.mkdir()

    def w_vanilla(payload):
        (repo / "sources" / "vanilla_keys.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def w_own(entries):
        (repo / "sources" / "own_translations.json").write_text(
            json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8"
        )

    big = [f"K{i}" for i in range(10001)]
    # 檔域基準（dist 面主閘門與抑制集合的來源）。基準的 fail-closed 檢查要求核心字串檔
    # 齊備、≥30 檔、且 keys == union(scoped_keys)，故補齊；各補位檔的鍵取自 big 以維持聯集。
    CORE = ("ItemName.json", "UI.json", "IG_UI.json", "ContextMenu.json", "Tooltip.json",
            "Recipes.json", "Sandbox.json", "Fluids.json", "Moveables.json", "Moodles.json")
    def mk_scoped(**extra):
        out = {"UI.json": list(big)}
        out.update({f: ["K1"] for f in CORE if f != "UI.json"})
        out.update({f"Pad{i}.json": ["K2"] for i in range(21)})
        out.update(extra)
        return out
    scoped = mk_scoped()
    w_own({"UI.json": {"K0": {"en": "e", "ch": "譯", "cn": "译"}}})
    for bad in (
        {"keys": "K0", "scoped_keys": scoped},               # keys 非清單
        {"keys": ["K0"], "scoped_keys": scoped},             # 量級殘缺
        {"keys": big, "scoped_keys": scoped, "allowlist": {"K0": "散文豁免"}},  # allowlist 無錨點
        {"keys": big, "allowlist": {}},                      # 缺 scoped_keys
        {"keys": big, "scoped_keys": {"UI.json": ["K0"]}, "allowlist": {}},  # 檔域基準殘缺
        {"keys": big, "scoped_keys": mk_scoped(**{"ItemName.json": None}), "allowlist": {}},  # bucket 型別錯
        {"keys": big, "scoped_keys": scoped, "keep": {"UI.json|K0": "散文豁免"}},  # keep 無錨點
    ):
        w_vanilla(bad)
        try:
            verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
            raise AssertionError(f"形狀壞損未 fail-closed: {bad if len(str(bad)) < 80 else '...'}")
        except (ValueError, TypeError, AttributeError):
            pass
    w_vanilla({"keys": big, "scoped_keys": scoped, "allowlist": {}})
    ok, det, _w = verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
    assert not ok and "K0" in det[0], f"碰撞未偵測: {det}"
    import hashlib as _hl
    anchor = _hl.sha256("e|譯|译".encode("utf-8")).hexdigest()[:16]
    w_vanilla({"keys": big, "scoped_keys": scoped, "allowlist": {"K0": {"reason": "r", "own_anchor": anchor}}})
    ok, det, _w = verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
    assert ok and not det, f"錨點豁免未生效: {det}"
    w_own({"UI.json": {"K0": {"en": "e", "ch": "改", "cn": "改"}}})
    ok, det, _w = verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
    assert not ok and "own_anchor 失效" in det[0], f"錨點失效未偵測: {det}"

    # 地圖泛用鍵只在同一檔名算碰撞；跨地圖 `title`/`description` 不是全域覆寫。
    map_keys = big + ["title"]
    map_scoped = mk_scoped(**{"Muldraugh.json": ["title"]})
    w_vanilla({"keys": map_keys, "scoped_keys": map_scoped, "allowlist": {}})
    w_own({"SomeMod.json": {"title": {"en": "e", "ch": "譯", "cn": "译"}}})
    ok, det, _w = verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
    assert ok and not det, f"跨地圖 title 被誤判 vanilla 碰撞: {det}"
    w_own({"Muldraugh.json": {"title": {"en": "e", "ch": "譯", "cn": "译"}}})
    ok, det, _w = verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
    assert not ok and "Muldraugh.json|title" in det[0], f"同地圖 title 碰撞未擋: {det}"

    # 8b. warn 偵測器（As1 lane provenance）：新碰撞/known 靜默/generic 精確對/
    #     own-mod 排除/_unsorted 納入/stale 條目/新欄位 fail-closed
    def w_src(wid, meta, fname, payload):
        base = repo / "sources" / "mods" / wid if wid else repo / "sources" / "_unsorted"
        (base / "CN").mkdir(parents=True, exist_ok=True)
        if meta is not None:
            (base / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (base / "CN" / fname).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    big2 = big + ["title"]
    scoped2 = mk_scoped(**{"Muldraugh.json": ["title"], "SomeMod.json": ["title"]})
    w_own({"UI.json": {"ZOwnOnly": {"en": "e", "ch": "譯", "cn": "译"}}})  # 不撞 vanilla，免干擾 blocking
    w_src("111", {"origin": "as1"}, "IG_UI.json", {"K6": "x"})       # As1 一般鍵 → warn
    w_src("111", None, "SomeMod.json", {"title": "x"})               # generic 非登記對 → 靜默
    w_src("111", None, "Muldraugh.json", {"title": "x"})             # generic 已登記對 → warn
    w_src("222", {"origin": "own"}, "IG_UI.json", {"K7": "x"})       # own-mod → 靜默
    w_src(None, None, "ItemName.json", {"K8": "x"})                  # _unsorted → warn
    w_vanilla({"keys": big2, "scoped_keys": scoped2, "allowlist": {}, "as1_overlap_known": [],
               "vanilla_scoped_pairs": ["Muldraugh.json|title"]})
    _ok, _det, warns = verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
    joined = "\n".join(warns)
    assert "IG_UI.json|K6" in joined and "Muldraugh.json|title" in joined, warns
    assert "ItemName.json|K8" in joined, f"_unsorted 未納入: {warns}"
    assert "IG_UI.json|K7" not in joined, f"own-mod 未排除: {warns}"
    assert "SomeMod.json|title" not in joined, f"generic 笛卡兒積誤報: {warns}"
    w_vanilla({"keys": big2, "scoped_keys": scoped2, "allowlist": {},
               "as1_overlap_known": ["IG_UI.json|K6", "Muldraugh.json|title",
                                     "ItemName.json|K8", "Gone.json|K9"],
               "vanilla_scoped_pairs": ["Muldraugh.json|title"]})
    ok, _det, warns = verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
    joined = "\n".join(warns)
    assert "新增 vanilla 碰撞" not in joined, f"known 未靜默: {warns}"
    assert "陳舊條目：Gone.json|K9" in joined, f"stale 未偵測: {warns}"
    assert ok, "report-only 不得影響 blocking 結果"
    for bad_field in ({"as1_overlap_known": {"a": 1}}, {"vanilla_scoped_pairs": ["nopipe"]}):
        w_vanilla({"keys": big2, "scoped_keys": scoped2, "allowlist": {}, **bad_field})
        try:
            verify_dist.check_vanilla_collision(str(repo), str(dist_cn_dir))
            raise AssertionError(f"新欄位形狀壞損未 fail-closed: {bad_field}")
        except ValueError:
            pass

# 9. tracker _iter_script_records：多 scripts 目錄、dn 後者生效、巢狀子區塊不誤歸屬、
#    item key 帶 module（EXTRACTOR_SCHEMA=9 的完整 fullType）
with tempfile.TemporaryDirectory() as td:
    mod = Path(td)
    s1 = mod / "42.13" / "media" / "scripts"
    s2 = mod / "common" / "media" / "scripts"
    s1.mkdir(parents=True)
    s2.mkdir(parents=True)
    (s1 / "items.txt").write_text(
        "module Base {\n"
        "    item Dup {\n"
        "        DisplayName = First,\n"
        "        component X {\n"
        "            DisplayName = Nested,\n"
        "        }\n"
        # 引擎只刪 `/* */`（ScriptParser.stripComments），**不認 `//`**——所以這裡必須用
        # 區塊註解才能測「註解內的大括號不干擾配對」。用 `//` 的話那個 `}` 在引擎眼中
        # 真的會關掉 item 區塊，後面的 DisplayName 就不屬於它了。
        "        /* } 註解內大括號不干擾 */\n"
        "        DisplayName = Last,\n"
        "    }\n"
        "    item NoName {\n"
        "        Weight = 1.0,\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (s2 / "other.txt").write_text(
        "module Base {\n    item OtherTree {\n        DisplayName = Common,\n    }\n}\n",
        encoding="utf-8",
    )
    recs = tracker._iter_script_records(mod)
    dn = {r[2]: r[3] for r in recs if r[0] == "script_item_dn"}
    assert dn == {"Base.Dup": "Last", "Base.OtherTree": "Common"}, f"dn 抽取錯誤: {dn}"
    rels = {r[1] for r in recs}
    assert any(r.startswith("42.13/") for r in rels) and any(r.startswith("common/") for r in rels), \
        f"多 scripts 目錄未全掃: {rels}"

print("PASS: own-mod lane 9/9 案例通過")
