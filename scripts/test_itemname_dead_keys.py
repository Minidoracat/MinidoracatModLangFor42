# /// script
# requires-python = ">=3.10"
# ///
"""Regression tests for verify [15] effective-fullType enforcement.

The gate accepts only exact effective `script_item_dn` fullTypes. Missing or
wrong modules are never inferred from suffixes — they fail until a human repairs
the true key or explicitly records an unresolved-module deferral.

Run: uv run scripts/test_itemname_dead_keys.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_dist  # noqa: E402


def run(
    dist_itemname: dict,
    vanilla: list[str],
    allow: object,
    fulltypes: list[str] | None = None,
    *,
    schema: object = 10,
    record_ids: list[str] | None = None,
    records_override: object | None = None,
    state_override: object | None = None,
) -> tuple[list[str], list[str]]:
    """Build a temporary repo/dist and return [15] fail/warn lists."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "sources"
        src.mkdir()
        (src / "vanilla_keys.json").write_text(
            json.dumps({"scoped_keys": {"ItemName.json": vanilla}}, ensure_ascii=False),
            encoding="utf-8")
        (src / "itemname_dead_allowlist.json").write_text(
            json.dumps({"entries": allow}, ensure_ascii=False), encoding="utf-8")
        if records_override is not None:
            records = records_override
        elif record_ids is None:
            records = {
                f"script_item_dn|mods/m/42/media/scripts/items.txt|{full}": "hash"
                for full in (fulltypes or [])
            }
        else:
            records = {rid: "hash" for rid in record_ids}
        state = Path(td) / "tracker-state"
        state.mkdir()
        payload = {"mods": {"1": {"extractor_schema": schema, "records": records}}}
        if state_override is not None:
            payload = state_override
        verify_dist.tracker.write_corpus_hashes(payload, state / "en_corpus_hashes")
        ch = Path(td) / "CH"
        ch.mkdir()
        (ch / "ItemName.json").write_text(json.dumps(dist_itemname, ensure_ascii=False),
                                          encoding="utf-8")
        old_min = verify_dist.ITEM_FULLTYPES_MIN
        verify_dist.ITEM_FULLTYPES_MIN = 0
        try:
            ok, fail, warn = verify_dist.check_itemname_dead_keys(td, str(ch))
        finally:
            verify_dist.ITEM_FULLTYPES_MIN = old_min
        assert ok == (not fail), "ok 與 fail 清單不一致"
        return fail, warn


# 1. Exact effective prefix body, no bare key => FAIL.
fail, _ = run({"ItemName_Foo.Bar": "巴"}, [], {}, ["Foo.Bar"])
assert fail and "Foo.Bar" in fail[0], fail

# 2. Exact effective + shipped bare key => PASS.
fail, _ = run({"ItemName_Foo.Bar": "巴", "Foo.Bar": "巴"}, [], {}, ["Foo.Bar"])
assert not fail, fail

# 3. Vanilla is independent evidence; Base.* alone is not.
fail, _ = run({"ItemName_Base.Axe": "斧頭"}, ["Base.Axe"], {}, [])
assert not fail, fail
fail, _ = run({"ItemName_Base.44Clip20": "44彈匣"}, ["Base.44Clip"], {},
              ["Base.44Clip20"])
assert fail, "mod item in module Base was incorrectly exempted"

# 4. Exact current allowlist defers; resolved exact key makes it stale.
fail, _ = run({"ItemName_Foo.Bar": "巴"}, [], {"Foo.Bar": "reason"}, ["Foo.Bar"])
assert not fail, fail
fail, warn = run({"ItemName_Foo.Bar": "巴", "Foo.Bar": "巴"}, [],
                 {"Foo.Bar": "old"}, ["Foo.Bar"])
assert not fail and warn, (fail, warn)

# 5. Module-less prefix does NOT match a unique Base.* suffix candidate.
fail, _ = run({"ItemName_ClipboardEmpty": "空寫字板"}, [], {},
              ["Base.ClipboardEmpty"])
assert fail and "禁止依 suffix" in fail[0], fail
fail, _ = run({"ItemName_ClipboardEmpty": "空寫字板",
               "ClipboardEmpty": "錯 module 修復"}, [], {}, ["Base.ClipboardEmpty"])
assert fail, "unreachable suffix-only bare key created a false green"
fail, _ = run({"ItemName_ClipboardEmpty": "空寫字板"}, [],
              {"ClipboardEmpty": "owner unresolved"}, ["Base.ClipboardEmpty"])
assert not fail, fail

# 6. Schema <9 never proves a module, even if its key looks like fullType.
for legacy in ("ClipboardEmpty", "Foo.Bar"):
    fail, _ = run({f"ItemName_{legacy}": "舊鍵", legacy: "未證實裸鍵"}, [], {},
                  [legacy], schema=8)
    assert fail, f"schema 8 evidence created a false green: {legacy}"
fail, _ = run({"ItemName_ClipboardEmpty": "舊鍵",
               "ClipboardEmpty": "未證實裸鍵"}, [], {}, ["ClipboardEmpty"])
assert fail, "schema 10 stale module-less evidence created a false green"

# 7. Wrong legacy module remains unresolved even if that wrong bare key ships.
wrong_module_dist = {
    "ItemName_Base.MPoncho": "斗篷",
    "Base.MPoncho": "錯 module 裸鍵",
    "GDMPoncho.MPoncho": "軍用斗篷",
}
fail, _ = run(wrong_module_dist, [], {}, ["GDMPoncho.MPoncho"])
assert fail, "a non-effective bare key must not prove its own module"
fail, warn = run(wrong_module_dist, [],
                 {"Base.MPoncho": "manually repaired as GDMPoncho.MPoncho"},
                 ["GDMPoncho.MPoncho"])
assert not fail and not warn, (fail, warn)

# 8. A real dead-branch bare key cannot prove current provenance.
dead_branch_records = [
    "script_item_dn|mods/m/42.19/media/scripts/items.txt|Base.Rossi92",
    "script_item_dn|mods/m/42.20/media/scripts/items.txt|Other.CurrentItem",
]
dead_dist = {"ItemName_Base.Rossi92": "舊槍", "Base.Rossi92": "舊裸鍵"}
fail, _ = run(dead_dist, [], {}, record_ids=dead_branch_records)
assert fail and "無法精確" in fail[0], fail
fail, warn = run(dead_dist, [], {"Base.Rossi92": "dead branch"},
                 record_ids=dead_branch_records)
assert not fail and not warn, (fail, warn)

# 9. UNKNOWN_MODULE is undecidable evidence, not corruption or exact provenance.
fail, _ = run({"ItemName_ClipboardEmpty": "空寫字板",
               "ClipboardEmpty": "錯 module 修復"}, [], {},
              ["?.ClipboardEmpty"])
assert fail, "UNKNOWN_MODULE evidence created a false green"

# 10. Producer-legal keys may contain `|` and multiple dots.
for full in ("Base.Pack|Mk.2", "Foo.Bar.Baz"):
    fail, _ = run({f"ItemName_{full}": "前綴", full: "裸鍵"}, [], {}, [full])
    assert not fail, (full, fail)
fail, _ = run({"ItemName_Mk.2": "截斷前綴", "Mk.2": "截斷裸鍵"}, [], {},
              ["Base.Pack|Mk.2"])
assert fail, "rpartition-style truncated evidence created a false green"

# 11. Malformed tracker state/evidence fails closed.
bad_states = [
    {"state_override": []},
    {"state_override": {"mods": {"1": []}}},
    {"records_override": []},
    {"record_ids": ["unknown|mods/m/42/x.txt|Foo.Bar"]},
    {"record_ids": ["script_item_dn|mods/m/42/x.txt"]},
    {"record_ids": ["script_item_dn||Foo.Bar"]},
    {"record_ids": ["script_item_dn|mods/m/42/x.txt|"]},
    {"state_override": {"mods": {"1": {"records": {}}}}},
    {"schema": True},
]
for kwargs in bad_states:
    try:
        run({"ItemName_Foo.Bar": "巴"}, [], {}, **kwargs)
    except ValueError:
        pass
    else:
        raise AssertionError(f"壞損 tracker state 未 fail-closed：{kwargs}")

# 12. Malformed allowlist entries fail closed.
for bad_allow in (["Foo.Bar"], {"Foo.Bar": ""}, {"": "reason"}):
    try:
        run({"ItemName_Foo.Bar": "巴"}, [], bad_allow, ["Foo.Bar"])
    except ValueError:
        pass
    else:
        raise AssertionError(f"壞損 allowlist 未 fail-closed：{bad_allow}")

# 13. Prefix removed makes a deferral stale; clean no-prefix input passes.
fail, warn = run({"Other.Key": "其他"}, [], {"Foo.Bar": "old"}, ["Foo.Bar"])
assert not fail and warn, (fail, warn)
fail, warn = run({"Foo.Bar": "巴"}, [], {}, [])
assert not fail and not warn, (fail, warn)

print("✅ test_itemname_dead_keys：13 組 provenance/fail-closed 情境全過")

# --- [13] 改名後繼者抑制（同檔測試，共用 verify_dist import）------------------ #
# 2026-08-10 實測：60 條 [13] 警告裡有 11 條是「上游把 UI_X 改名為 IGUI_X，我方兩個
# 鍵都在，新鍵已出貨」——舊鍵確實死著但零缺口，報它只是噪音、害人重複追查。
# 抑制判準必須**兩個條件同時成立**，少一個都會靜默吞掉真缺口：
S = verify_dist._renamed_successors
assert S("UI_DMD_Assemble") == ("IGUI_DMD_Assemble",), "UI_ → IGUI_ 後繼者推導錯"
assert S("IGUI_DMD_Assemble") == ("UI_DMD_Assemble",), "IGUI_ → UI_ 後繼者推導錯"
assert S("Sandbox_Foo") == (), "非 UI_/IGUI_ 前綴不得亂猜後繼者"
assert S("UI_") == ("IGUI_",) and S("Recipes_X") == (), "邊界"


def _write_upstream_fixture(
    root: Path,
    files: dict[str, str],
    *,
    make_dir: bool = True,
    state_values: dict[str, dict[str, str]] | None = None,
) -> None:
    """建立 expected watchlist/state/mirror exact closure fixture。"""
    parsed: dict[str, dict[str, str]] = {}
    for name, text in files.items():
        if not name.endswith(".json") or not name[:-5].isdigit():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in data.items()
        ):
            parsed[name[:-5]] = data
    if state_values is None:
        state_values = parsed or {
            "1": {
                "translate_en|mods/m/42/media/lua/shared/Translate/EN/UI.json|UI_Sentinel": "e"
            }
        }
    expected = sorted(state_values)
    sources = root / "sources"
    mods = sources / "mods"
    registry_mods = {}
    watch_items = {
        verify_dist.tracker.AS1_WORKSHOP_ID: {
            "mod_ids": [verify_dist.tracker.AS1_MOD_ID], "role": "as1"
        }
    }
    states = {}
    for wid in expected:
        meta_dir = mods / wid
        meta_dir.mkdir(parents=True)
        (meta_dir / "metadata.json").write_text(
            json.dumps({"workshop_id": wid, "mod_ids": [f"Mod{wid}"]}),
            encoding="utf-8",
        )
        registry_mods[wid] = {
            "status": "active", "source": "test", "verified": "2026-08-30",
            "mod_ids": [f"Mod{wid}"],
        }
        watch_items[wid] = {"mod_ids": [f"Mod{wid}"], "role": "mod"}
        values = state_values[wid]
        states[wid] = {
            "extractor_schema": verify_dist.tracker.EXTRACTOR_SCHEMA,
            "records": {
                rid: hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
                for rid, value in values.items()
            },
        }
    (sources / "mod_registry.json").write_text(
        json.dumps({"mods": registry_mods}), encoding="utf-8"
    )
    tracker_state = root / "tracker-state"
    tracker_state.mkdir()
    (tracker_state / "watchlist.json").write_text(json.dumps({
        "schema_version": verify_dist.tracker.SCHEMA_VERSION,
        "count": len(watch_items),
        "items": watch_items,
    }), encoding="utf-8")
    verify_dist.tracker.write_corpus_hashes({
        "extractor_schema": verify_dist.tracker.EXTRACTOR_SCHEMA,
        "mods": states,
    }, tracker_state / "en_corpus_hashes")
    (tracker_state / "timestamps.json").write_text(json.dumps({
        "items": {wid: {"removed": False} for wid in expected}
    }), encoding="utf-8")
    if make_dir:
        en = sources / "en"
        en.mkdir()
        for name, text in files.items():
            (en / name).write_text(text, encoding="utf-8")


def _upstream_result(
    files: dict[str, str],
    make_dir: bool = True,
    state_values: dict[str, dict[str, str]] | None = None,
):
    with tempfile.TemporaryDirectory() as td:
        _write_upstream_fixture(
            Path(td), files, make_dir=make_dir, state_values=state_values
        )
        try:
            return verify_dist._upstream_keys(td)
        except ValueError as exc:
            return str(exc)


def _g13(dist_ch_files, upstream, repo_sources_en):
    """組完整 closure fixture + dist，回 [13] 的 (fail, warn)。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ch = root / "CH"
        ch.mkdir()
        for name, data in dist_ch_files.items():
            (ch / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        records = {
            "translate_en|mods/m/42/media/lua/shared/Translate/EN/x.json|UI_Sentinel": "e",
            **{
                f"translate_en|mods/m/42/media/lua/shared/Translate/EN/x.json|{k}": "e"
                for k in upstream
            },
        }
        _write_upstream_fixture(root, {"1.json": json.dumps(records)})
        ok, fail, warn = verify_dist.check_loadable_files(td, str(ch))
        return fail, [w for w in warn if "→" in w]


# 後繼者在上游且已出貨 → 不報
fail, warn = _g13({"Dead.json": {"UI_X": "舊"}, "IG_UI.json": {"IGUI_X": "新"}},
                  upstream=["IGUI_X"], repo_sources_en=None)
assert not fail and not warn, f"已由改名後繼者涵蓋卻仍報：{fail} {warn}"

# 後繼者已出貨但**上游沒有** → 仍要報（可能是我方自己亂放前綴，不是真改名）
fail, warn = _g13({"Dead.json": {"UI_X": "舊"}, "IG_UI.json": {"IGUI_X": "新"}},
                  upstream=[], repo_sources_en=None)
assert warn, "後繼者無上游佐證時不得抑制——會吞掉真缺口"

# 後繼者在上游但**沒出貨** → 仍要報
fail, warn = _g13({"Dead.json": {"UI_X": "舊"}, "IG_UI.json": {"IGUI_Other": "x"}},
                  upstream=["IGUI_X"], repo_sources_en=None)
assert warn, "後繼者未出貨時不得抑制"

# 同名鍵已在正確檔 → 本來就不報（既有行為不得回歸）
fail, warn = _g13({"Dead.json": {"UI_X": "舊"}, "UI.json": {"UI_X": "活"}},
                  upstream=["UI_X"], repo_sources_en=None)
assert not fail and not warn, f"同名鍵已在正確檔卻仍報：{fail} {warn}"

# [13] 證據缺／空／壞不能退化成「所有鍵都已作廢」；有效分支契約與 split 共用 tracker。
for files, make_dir, needle, why in (
    ({}, False, "不存在", "目錄缺失"),
    ({}, True, "缺 EN mirror", "零鏡像但 state 有文本"),
    ({"1.json": "{}"}, True, "非空物件", "空鏡像"),
    ({"1.json": "[]"}, True, "非空物件", "頂層非物件"),
    ({"1.json": "{"}, True, "無法解析", "壞 JSON"),
    ({"x.json": '{"translate_en|a|K":"v"}'}, True, "wid", "非 wid 檔名"),
    ({"1.json": '{"broken":"v"}'}, True, "record id", "rid 壞損"),
    ({"1.json": '{"lua_literal|a|K":"v"}'}, True, "非法 kind", "未知 kind"),
    ({"1.json": '{"translate_en|a|K":7}'}, True, "非法 kind/value", "非字串值"),
):
    got = _upstream_result(files, make_dir)
    assert isinstance(got, str) and needle in got, f"{why} 未 fail-closed：{got!r}"

# partial set loss：保留合法 wid 1 sentinel，刪掉真正定義目標鍵的 wid 2 mirror。
sentinel_rid = "translate_en|mods/m/42/media/lua/shared/Translate/EN/UI.json|UI_Sentinel"
target_rid = "translate_en|mods/n/42/media/lua/shared/Translate/EN/UI.json|UI_Target"
partial = _upstream_result(
    {"1.json": json.dumps({sentinel_rid: "s"})},
    state_values={"1": {sentinel_rid: "s"}, "2": {target_rid: "target"}},
)
assert isinstance(partial, str) and "wid 2" in partial and "缺 EN mirror" in partial, partial

# 合法 empty corpus：只有非鏡像 script record，不得被逼著生出 `{}` mirror。
script_only = "script_item|mods/m/42/media/scripts/items.txt|Base.X"
assert _upstream_result({}, state_values={"1": {script_only: "Base.X"}}) == set()

# rid 集合相同但值 hash 不符同樣 blocking。
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    _write_upstream_fixture(root, {"1.json": json.dumps({sentinel_rid: "s"})})
    state_path = root / "tracker-state" / "en_corpus_hashes"
    state_doc = verify_dist.tracker.load_corpus_hashes(state_path)
    state_doc["mods"]["1"]["records"][sentinel_rid] = "000000000000"
    verify_dist.tracker.write_corpus_hashes(state_doc, state_path)
    try:
        verify_dist._upstream_keys(td)
        raise AssertionError("state/mirror 值 hash 不符未 fail-closed")
    except ValueError as exc:
        assert "hash 不一致" in str(exc), exc

# partial source mod 目錄缺 metadata 不得同時從 expected watchlist 與 closure 消失。
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    _write_upstream_fixture(root, {"1.json": json.dumps({sentinel_rid: "s"})})
    (root / "sources" / "mods" / "777" / "CN").mkdir(parents=True)
    try:
        verify_dist._upstream_keys(td)
        raise AssertionError("verify 未擋缺 metadata 的 source mod 目錄")
    except ValueError as exc:
        assert "缺 metadata.json" in str(exc), exc

effective_records = {
    "translate_en|mods/m/common/media/lua/shared/Translate/EN/UI.json|UI_Common": "c",
    "translate_en|mods/m/42.19/media/lua/shared/Translate/EN/UI.json|UI_Old": "o",
    "translate_en|mods/m/42.20/media/lua/shared/Translate/EN/UI.json|UI_Current": "n",
    "translate_en|mods/m/42.21/media/lua/shared/Translate/EN/UI.json|UI_Future": "f",
    "translate_en|mods/m/media/lua/shared/Translate/EN/UI.json|UI_Root": "r",
    "translate_en|mods/m/42.20/media/lua/shared/Translate/EN/UI_EN.txt|UI_Txt": "t",
    "script_item_dn|mods/m/42.20/media/scripts/items.txt|Base.Item": "Item",
}
got = _upstream_result({"1.json": json.dumps(effective_records)})
assert got == {"UI_Common", "UI_Current"}, f"[13] 非有效分支／legacy txt 污染 upstream：{got}"

print("✅ test [13] 改名後繼者 5 組＋evidence closure 14 組情境全過")
