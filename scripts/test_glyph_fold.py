# /// script
# requires-python = ">=3.10"
# ///
"""出貨字元代換（builder 端）回歸測試。

覆蓋：build_mod.fold_glyphs 表格案例、load_glyph_fold 壞表 fail-closed、
builder 與 verify_dist 兩份獨立實作對真實 sources 值對拍（含冪等、無殘留、sanitize 穩定、
format token／標籤多重集合不變、不變空），reanchor_registries.glyph_fold_anchors 三種情形。

執行：uv run scripts/test_glyph_fold.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import build_mod  # noqa: E402
import reanchor_registries  # noqa: E402
import verify_dist  # noqa: E402

fold = build_mod.fold_glyphs
DASH = build_mod.load_glyph_fold()[0]["—"]


def test_cases() -> None:
    cases = {
        "Lil’ Sparky": "Lil' Sparky",
        "Italia ’90": "Italia '90",
        "‘那內襯呢? ’‘戰術的. ’": "『那內襯呢? 』『戰術的. 』",
        "15–30°": "15～30°",
        "%2–%3": "%2～%3",
        "1%%–500%%": "1%%～500%%",
        "0‑23": "0～23",
        "<BR>– 增加": "<BR>- 增加",
        "莫辛–納甘": "莫辛-納甘",
        "等一下……我“剛才”": "等一下......我「剛才」",
        "注意——村莊": f"注意{DASH * 2}村莊",
        "右鍵 → 全域": "右鍵 ￫ 全域",
        "30℃ ≈ 1 β™": "30°C ~ 1 beta",
        "Русский": "Russkiy",
        "沒有要換的字 %1": "沒有要換的字 %1",
    }
    for src, want in cases.items():
        assert fold(src) == want, (src, fold(src), want)
        assert fold(want) == want, want
    assert fold(None) is None and fold(3) == 3


def test_bad_table() -> None:
    real = build_mod.GLYPH_FOLD_JSON
    bad_maps = [
        {"…": "…."},          # 值含來源字
        {"…": "%"},           # 值含 %
        {"…": "<"},           # 值含標籤字元
        {"ab": "x"},          # 鍵多字元
        {"闻": "聞"},          # 鍵是漢字
        {"–": "-"},           # 前後文字不進表
        {"～": "~"},          # 前後文規則的輸出字
        {},                   # 空表
    ]
    with tempfile.TemporaryDirectory() as td:
        try:
            for i, m in enumerate(bad_maps + [None]):
                p = Path(td) / f"g{i}.json"
                if m is not None:
                    p.write_text(json.dumps({"map": m}, ensure_ascii=False), encoding="utf-8")
                build_mod.GLYPH_FOLD_JSON = p
                build_mod.load_glyph_fold.cache_clear()
                try:
                    build_mod.load_glyph_fold()
                except SystemExit:
                    continue
                raise AssertionError(f"壞表沒擋：{m!r}")
        finally:
            build_mod.GLYPH_FOLD_JSON = real
            build_mod.load_glyph_fold.cache_clear()


def _source_values():
    files = [*(REPO / "sources/ch").glob("*.json"), *(REPO / "sources/_unsorted/CN").glob("*.json"),
             *(REPO / "sources/mods").glob("**/*.json")]
    for p in files:
        data = build_mod.load_json(p)
        if isinstance(data, dict):
            yield from (v for v in data.values() if isinstance(v, str))
    for bucket in build_mod.load_json(REPO / "sources/own_translations.json")["entries"].values():
        for spec in bucket.values():
            yield from (spec.get(side) for side in ("ch", "cn") if isinstance(spec.get(side), str))
    # 也會被代換、且出貨後沒有別的 gate 再看 token 的來源（variants TSV 直接寫進翻譯表）
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("ch", "cn", "value", "cn_safe_value") and isinstance(v, str):
                    yield v
                else:
                    yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)
    for name in ("owner_variants.json", "pack_ui.json", "cn_overrides.json", "placeholder_exceptions.json"):
        yield from walk(build_mod.load_json(REPO / "sources" / name))


def test_parity_on_sources() -> int:
    glyph = verify_dist._load_glyph_fold(REPO)
    _, pattern = build_mod.load_glyph_fold()
    n = 0
    for raw in _source_values():
        if not pattern.search(raw):
            continue
        val = build_mod.sanitize_format_tokens(raw)
        got = fold(val)
        n += 1
        assert got == verify_dist.fold_expectation(val, glyph), (val, got)
        assert fold(got) == got and not pattern.search(got), (val, got)
        assert build_mod.sanitize_format_tokens(got) == got, (val, got)
        assert build_mod.token_multiset(got) == build_mod.token_multiset(val), (val, got)
        assert got, val
    assert n > 5000, n  # 2026-11-26 約 1.5 萬個；掉到這麼少代表沒讀到 sources
    return n


def test_reanchor() -> None:
    h = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]
    base_cn = {"UI.json": {"ok": "等一下…", "stale": "舊…", "other": "改過…", "plain": "沒有"}}
    base_st = {"_keep_rationale": "x", "UI.json|ok": h("等一下…"), "UI.json|stale": "0" * 16,
               "UI.json|other": h("改過…"), "UI.json|plain": h("沒有")}
    st = dict(base_st, **{"UI.json|other": "f" * 16})
    n, refused = reanchor_registries.glyph_fold_anchors(st, base_st, base_cn)
    assert (n, len(refused)) == (1, 1), (n, refused)
    assert st["UI.json|ok"] == h("等一下...")          # 背書有效 → 重錨
    assert st["UI.json|stale"] == "0" * 16             # base 就無效 → 不代為背書
    assert st["UI.json|other"] == "f" * 16             # 工作樹另改過 → 拒絕、不動
    assert reanchor_registries.glyph_fold_anchors(st, base_st, base_cn) == (0, refused)  # 重跑無變化


if __name__ == "__main__":
    test_cases()
    test_bad_table()
    n = test_parity_on_sources()
    test_reanchor()
    print(f"✅ test_glyph_fold：4 組全綠（對拍 {n} 個含來源字的真實值）")
