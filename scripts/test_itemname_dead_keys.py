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
        (state / "en_corpus_hashes.json").write_text(
            json.dumps(payload), encoding="utf-8")
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


def _g13(dist_ch_files, upstream, repo_sources_en):
    """組臨時 dist + sources/en，回 [13] 的 (fail, warn)。"""
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "CH"
        ch.mkdir()
        for name, data in dist_ch_files.items():
            (ch / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        en = Path(td) / "sources" / "en"
        en.mkdir(parents=True)
        (en / "1.json").write_text(json.dumps(
            {f"translate_en|mods/m/42/media/lua/shared/Translate/EN/x.json|{k}": "e"
             for k in upstream}, ensure_ascii=False), encoding="utf-8")
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

print("✅ test [13] 改名後繼者抑制：5 組情境全過")
