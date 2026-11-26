# /// script
# requires-python = ">=3.10"
# ///
"""verify_dist 出貨字元代換（oracle 端）回歸測試。

覆蓋：fold_expectation 表格案例與冪等、_load_glyph_fold fail-closed、
[21] 殘留來源字 FAIL／識別欄不報、[1]／[9]／[18] 帶 glyph 時期望值走代換。
全部在暫存目錄造資料，不碰 repo 的 dist；只讀 repo 的 sources/glyph_fold.json。

執行：uv run scripts/test_glyph_fold_verify.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_dist  # noqa: E402

N_CASES = 0


def case() -> None:
    global N_CASES
    N_CASES += 1


def wjson(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def wtsv(p: Path, rows: list[list[str]]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    body = "".join("\t".join(r) + "\n" for r in rows)
    p.write_text("# head\n" + body, encoding="utf-8", newline="\n")


GLYPH = verify_dist._load_glyph_fold(str(REPO))
fold = verify_dist.fold_expectation

# 1. 表格案例（`—`、`“”` 的期望取表的值，不寫死）
CASES = {
    "Lil’ Sparky": "Lil' Sparky",
    "Italia ’90": "Italia '90",
    "‘那內襯呢? ’‘戰術的. ’": "『那內襯呢? 』『戰術的. 』",
    "15–30°": "15～30°",
    "%2–%3": "%2～%3",
    "1%%–500%%": "1%%～500%%",
    "0‑23": "0～23",
    "<BR>– 增加": "<BR>- 增加",
    "A–Z": "A-Z",
    "莫辛–納甘": "莫辛-納甘",
    "–5": "-5",
    "5–": "5-",
    "…": "...",
    "第6天 — 我": f"第6天 {GLYPH['—']} 我",
    "——": GLYPH["—"] * 2,
    "“好”": f"{GLYPH['“']}好{GLYPH['”']}",
    "無來源字": "無來源字",
}
for src, want in CASES.items():
    case()
    assert fold(src, GLYPH) == want, (src, fold(src, GLYPH), want)
case()
assert fold("…", None) == "…" and fold(None, GLYPH) is None and fold(3, GLYPH) == 3

# 冪等：fold(fold(x)) == fold(x)，含表裡每個鍵
case()
for x in [*CASES, "".join(GLYPH), "‘’–‑" + "".join(GLYPH)]:
    once = fold(x, GLYPH)
    assert fold(once, GLYPH) == once, (x, once)
    assert not set(once) & (set(GLYPH) | set("‘’–‑")), (x, once)

# 2. 壞表 fail-closed
BAD = {
    "值含來源字": {"…": "...", "—": "…"},
    "值含 %": {"…": "%"},
    "值含 <": {"→": "<-"},
    "值含 ’": {"…": "’"},
    "鍵多字元": {"——": "－"},
    "鍵是漢字": {"漢": "x"},
    "鍵是 ASCII": {"a": "b"},
    "鍵是 ‘": {"‘": "『"},
    "值非字串": {"…": 3},
    "缺 map": None,
}
for label, table in BAD.items():
    case()
    with tempfile.TemporaryDirectory() as td:
        wjson(Path(td) / "sources" / "glyph_fold.json", {"_comment": ["t"]} | ({} if table is None else {"map": table}))
        try:
            verify_dist._load_glyph_fold(td)
        except ValueError:
            pass
        else:
            raise AssertionError(f"壞表未擋：{label}")
case()
with tempfile.TemporaryDirectory() as td:
    try:
        verify_dist._load_glyph_fold(td)
    except OSError:
        pass
    else:
        raise AssertionError("缺檔未擋")

# 3. [21]：植入來源字 FAIL；JSON 鍵與 TSV 識別欄不報
with tempfile.TemporaryDirectory() as tdn:
    td = Path(tdn)
    cn_d, ch_d, media = td / "CN", td / "CH", td / "media"
    clean_row = ["c", "UI", "UI_X", "1", "A", "%1$s～%2$s..."]
    wjson(cn_d / "UI.json", {"k": "等待...", "k…鍵": "x"})
    wjson(ch_d / "UI.json", {"k": "等待...", "k…鍵": "x"})
    for lang in ("CH", "CN"):
        wtsv(media / "CatModLang" / f"variants_{lang}.tsv", [clean_row, ["c", "UI", "UI_…", "2", "B…", "ok"]])
    case()
    ok, fail, _ = verify_dist.check_glyph_fold(str(cn_d), str(ch_d), str(media), GLYPH)
    assert ok, fail

    wjson(cn_d / "UI.json", {"k": "等待…", "k…鍵": "x"})
    wjson(ch_d / "UI.json", {"k": "15–30", "k…鍵": "x"})
    wtsv(media / "CatModLang" / "variants_CN.tsv", [["c", "UI", "UI_X", "1", "A", "前往→"]])
    case()
    ok, fail, _ = verify_dist.check_glyph_fold(str(cn_d), str(ch_d), str(media), GLYPH)
    text = "\n".join(fail)
    assert not ok and len(fail) == 3, fail
    assert "CN UI.json|k：" in text and "CH UI.json|k：" in text and "variants_CN.tsv" in text, fail
    assert "variants_CH.tsv" not in text, "TSV 識別欄被誤報"

    case()
    (media / "CatModLang" / "variants_CH.tsv").unlink()
    ok, fail, _ = verify_dist.check_glyph_fold(str(cn_d), str(ch_d), str(media), GLYPH)
    assert not ok and any("variants_CH.tsv 無法讀取" in s for s in fail), fail

# 4. [1] 帶 glyph：As1／own／例外／cn_overrides 的期望都走代換；dist 留 `…` 要 FAIL
G = {"…": "...", "—": "－"}
with tempfile.TemporaryDirectory() as tdn:
    td = Path(tdn)
    as1_d, dist_d = td / "as1", td / "dist"
    wjson(as1_d / "UI.json", {"kA": "等待…", "kE": "x", "kO": "y"})
    own = {"UI.json": {"kOwn": {"cn": "原創—值"}}}
    exc = {"UI.json|kE": {"cn_safe_value": "5%—安全…", "reason": "t"}}
    cov = {"UI.json|kO": {"value": "修正…"}}
    good = {"kA": "等待...", "kE": "5%%－安全...", "kO": "修正...", "kOwn": "原創－值"}
    wjson(dist_d / "UI.json", good)
    case()
    ok, det, *_ = verify_dist.check_cn_parity(str(as1_d), str(dist_d), exc, own, cov, glyph=G)
    assert ok, det
    case()
    ok, det, *_ = verify_dist.check_cn_parity(str(as1_d), str(dist_d), exc, own, cov)
    assert not ok and len(det) == 4, det   # 不帶 glyph＝舊口徑，代換後的 dist 四處都不符
    case()
    wjson(dist_d / "UI.json", {k: v.replace("...", "…") for k, v in good.items()})
    ok, det, *_ = verify_dist.check_cn_parity(str(as1_d), str(dist_d), exc, own, cov, glyph=G)
    assert not ok and len(det) == 3, det   # kA／kE／kO 留 `…`

# 5. [9] 帶 glyph：corpus 與 own ch
with tempfile.TemporaryDirectory() as tdn:
    td = Path(tdn)
    wjson(td / "sources" / "ch" / "UI.json", {"k": "等待…"})
    own = {"UI.json": {"kOwn": {"ch": "原創—值"}}}
    dist_ch = td / "distCH"
    wjson(dist_ch / "UI.json", {"k": "等待...", "kOwn": "原創－值"})
    case()
    ok, det = verify_dist.check_ch_corpus_parity(str(td), str(dist_ch), own, glyph=G)
    assert ok, det
    case()
    wjson(dist_ch / "UI.json", {"k": "等待…", "kOwn": "原創—值"})
    ok, det = verify_dist.check_ch_corpus_parity(str(td), str(dist_ch), own, glyph=G)
    assert not ok and len(det) == 2, det

# 6. [18] 帶 glyph：TSV 期望＝format_fixer(fold(真相值))＝`%1$s～%2$s...`
with tempfile.TemporaryDirectory() as tdn:
    td = Path(tdn)
    wjson(td / "sources" / "owner_variants.json", {"entries": {"UI|UI_X": {"kind": "conflict", "groups": [
        {"owners": ["1/A"], "en": "%1-%2...", "ch": "%1–%2…", "cn": "%1–%2…"}]}}})
    (td / "sources" / "owner_conflicts.tsv").write_text("# head\n", encoding="utf-8", newline="\n")
    media = td / "media"
    (media / "CatModLang").mkdir(parents=True)
    (media / "CatModLang" / "conflicts.tsv").write_text("# head\n", encoding="utf-8", newline="\n")
    for lang in ("CH", "CN"):
        wtsv(media / "CatModLang" / f"variants_{lang}.tsv", [["c", "UI", "UI_X", "1", "A", "%1$s～%2$s..."]])
    case()
    ok, fail, _ = verify_dist.check_variants(str(td), str(media), GLYPH)
    assert ok, fail
    case()
    for lang in ("CH", "CN"):
        wtsv(media / "CatModLang" / f"variants_{lang}.tsv", [["c", "UI", "UI_X", "1", "A", "%1$s–%2$s…"]])
    ok, fail, _ = verify_dist.check_variants(str(td), str(media), GLYPH)
    assert not ok and any("缺列" in s and "%1$s～%2$s..." in s for s in fail), fail
    case()
    ok, fail, _ = verify_dist.check_variants(str(td), str(media))
    assert ok, fail   # 不帶 glyph＝舊口徑

print(f"PASS: 出貨字元代換（verify 端）{N_CASES}/{N_CASES} 案例通過")
