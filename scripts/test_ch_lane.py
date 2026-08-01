# /// script
# requires-python = ">=3.10"
# ///
"""CH corpus lane 負向回歸測試（斷絕 OpenCC 後的新 gate 體系）

覆蓋：split 的 worklist 差異登記/合併/對帳、build 的 corpus 鍵集 gate、
worklist/review_state fail-closed 載入、registry 背書 gate、CH 值層 gate、
verify 的 corpus parity / worklist 對帳 / 標籤 multiset / 例外鍵 CH 安全。

執行：uv run scripts/test_ch_lane.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402
import split_sources  # noqa: E402
import verify_dist  # noqa: E402


def wjson(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def h16(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


# 1. update_sync_worklist：added/changed/removed 判定 + _comment
with tempfile.TemporaryDirectory() as td:
    src = Path(td)
    split_sources.SOURCES = src
    split_sources.WORKLIST_JSON = src / "ch_sync_worklist.json"
    old = {("UI.json", "kChanged"): "旧", ("UI.json", "kRemoved"): "走", ("UI.json", "kSame"): "同"}
    new = {("UI.json", "kChanged"): "新", ("UI.json", "kAdded"): "来", ("UI.json", "kSame"): "同"}
    n = split_sources.update_sync_worklist(old, new)
    doc = json.loads(split_sources.WORKLIST_JSON.read_text(encoding="utf-8"))
    assert n == 3, f"delta 數錯誤: {n}"
    assert doc["UI.json|kChanged"] == {"kind": "changed", "old_cn": "旧", "new_cn": "新"}
    assert doc["UI.json|kAdded"] == {"kind": "added", "new_cn": "来"}
    assert doc["UI.json|kRemoved"] == {"kind": "removed", "old_cn": "走"}
    assert "UI.json|kSame" not in doc and "_comment" in doc

# 2. update_sync_worklist：既有條目合併＋自動對帳＋說明欄保留
with tempfile.TemporaryDirectory() as td:
    src = Path(td)
    split_sources.SOURCES = src
    split_sources.WORKLIST_JSON = src / "ch_sync_worklist.json"
    wjson(src / "ch" / "UI.json", {"kDone": "已翻"})  # 對帳依據
    wjson(split_sources.WORKLIST_JSON, {
        "_note": "human note",
        "UI.json|kDone": {"kind": "added", "new_cn": "x"},      # 已落 corpus → 清除
        "UI.json|kGone": {"kind": "removed", "old_cn": "y"},    # corpus 已無 → 清除
        "UI.json|kPending": {"kind": "changed", "old_cn": "a", "new_cn": "b"},  # 保留
    })
    same = {("UI.json", "kSame"): "同"}
    n = split_sources.update_sync_worklist(same, same)
    doc = json.loads(split_sources.WORKLIST_JSON.read_text(encoding="utf-8"))
    assert n == 0
    assert doc["_note"] == "human note", "人工說明欄未保留"
    assert "UI.json|kDone" not in doc and "UI.json|kGone" not in doc, "已滿足條目未清除"
    assert "UI.json|kPending" in doc, "changed 條目不得自動清除"

# 3. update_sync_worklist：old 為空跳過且不落檔
with tempfile.TemporaryDirectory() as td:
    src = Path(td)
    split_sources.SOURCES = src
    split_sources.WORKLIST_JSON = src / "ch_sync_worklist.json"
    n = split_sources.update_sync_worklist({}, {("UI.json", "k"): "v"})
    assert n == 0 and not split_sources.WORKLIST_JSON.exists()

# 4. cn_from_outputs / load_existing_cn：路徑解析、own 排除、metadata 排除
out = {
    "mods/111/CN/UI.json": json.dumps({"k1": "v1"}).encode(),
    "_unsorted/CN/UI.json": json.dumps({"k1": "v1", "k2": "v2"}).encode(),
    "mods/111/metadata.json": b"{}",
    "attribution_index.json": b"{}",
}
got = split_sources.cn_from_outputs(out)
assert got == {("UI.json", "k1"): "v1", ("UI.json", "k2"): "v2"}, f"cn_from_outputs: {got}"
with tempfile.TemporaryDirectory() as td:
    src = Path(td)
    split_sources.SOURCES = src
    split_sources.MODS_DIR = src / "mods"
    split_sources.UNSORTED_CN = src / "_unsorted" / "CN"
    wjson(src / "mods" / "111" / "metadata.json", {"attributed_via": {"map": 1}})
    wjson(src / "mods" / "111" / "CN" / "UI.json", {"a": "1"})
    wjson(src / "mods" / "222" / "metadata.json", {"origin": "own"})
    wjson(src / "mods" / "222" / "CN" / "UI.json", {"own": "x"})
    wjson(src / "_unsorted" / "CN" / "UI.json", {"b": "2"})
    got = split_sources.load_existing_cn()
    assert got == {("UI.json", "a"): "1", ("UI.json", "b"): "2"}, f"own 未排除或漏檔: {got}"

# 5. build corpus_gate：缺檔/孤兒檔/缺鍵/孤兒鍵
merged = {"UI.json": {"k1": "v1", "k2": "v2"}, "Only.json": {"x": "y"}}
corpus = {"UI.json": {"k1": "覆", "k3": "孤"}, "Orphan.json": {"z": "w"}}
errors = build_mod.corpus_gate(merged, corpus)
text = "\n".join(errors)
assert "corpus 缺檔：sources/ch/Only.json" in text
assert "corpus 孤兒檔：sources/ch/Orphan.json" in text
assert "k2 待翻譯" in text and "'v2'" in text, "缺鍵須附 CN 值"
assert "k3 為 corpus 孤兒鍵" in text
assert build_mod.corpus_gate({"A.json": {"k": "v"}}, {"A.json": {"k": "任意值"}}) == []

# 6. build loaders fail-closed（worklist / review_state 缺檔即 SystemExit）
_orig_wl, _orig_rs = build_mod.WORKLIST_JSON, build_mod.REVIEW_STATE_JSON
with tempfile.TemporaryDirectory() as td:
    build_mod.WORKLIST_JSON = Path(td) / "no_such.json"
    build_mod.REVIEW_STATE_JSON = Path(td) / "no_such2.json"
    for fn in (build_mod.load_sync_worklist, build_mod.load_review_state):
        try:
            fn()
            raise AssertionError(f"{fn.__name__} 缺檔未 fail")
        except SystemExit:
            pass
    # 說明欄（無 |）過濾、條目保留
    wjson(build_mod.WORKLIST_JSON, {"_comment": "x", "UI.json|k": {"kind": "changed"}})
    assert set(build_mod.load_sync_worklist()) == {"UI.json|k"}
build_mod.WORKLIST_JSON, build_mod.REVIEW_STATE_JSON = _orig_wl, _orig_rs

# 7. check_registry_ack：未登記/hash 不符 → error；一致 → 通過
mcn = {"UI.json": {"k": "有效值"}}
assert len(build_mod.check_registry_ack(mcn, {"UI.json|k"}, {})) == 1, "未登記須擋"
assert len(build_mod.check_registry_ack(mcn, {"UI.json|k"}, {"UI.json|k": "0" * 16})) == 1
assert build_mod.check_registry_ack(mcn, {"UI.json|k"}, {"UI.json|k": h16("有效值")}) == []

# 8. ch_value_gate：簡體專用字/空值/非字串
errs = build_mod.ch_value_gate(
    {"UI.json": {"a": "内容", "b": "有文", "c": "ok"}},
    {"UI.json": {"a": "简体残留说明", "b": "", "c": "正常繁中"}},
)
text = "\n".join(errs)
assert "簡體專用字" in text and "CH 空值但 CN 有內容" in text and len(errs) == 2, errs
assert build_mod.ch_value_gate({"A.json": {"k": "干草"}}, {"A.json": {"k": "乾草"}}) == []

# 9. verify loaders fail-closed 與 schema 驗證
with tempfile.TemporaryDirectory() as td:
    repo = str(Path(td))
    for fn in (verify_dist._load_worklist, verify_dist._load_review_state):
        try:
            fn(repo)
            raise AssertionError(f"{fn.__name__} 缺檔未擲例外")
        except ValueError:
            pass
    wjson(Path(td) / "sources" / "ch_review_state.json", {"_comment": "x", "UI.json|k": None})
    try:
        verify_dist._load_review_state(repo)
        raise AssertionError("非字串 hash 未擲例外")
    except ValueError:
        pass
    wjson(Path(td) / "sources" / "ch_review_state.json", {"UI.json|k": "ZZZ"})
    try:
        verify_dist._load_review_state(repo)
        raise AssertionError("非 16 位 hex 未擲例外")
    except ValueError:
        pass

# 10. verify check_sync_worklist：自動對帳（added 滿足/removed 滿足/changed 恆列）
with tempfile.TemporaryDirectory() as td:
    repo = str(Path(td))
    wjson(Path(td) / "sources" / "ch" / "UI.json", {"kA": "x"})
    wjson(Path(td) / "sources" / "ch_sync_worklist.json", {
        "_comment": "c",
        "UI.json|kA": {"kind": "added", "new_cn": "x"},
        "UI.json|kB": {"kind": "removed", "old_cn": "y"},
        "UI.json|kC": {"kind": "changed", "old_cn": "a", "new_cn": "b"},
    })
    ok, details = verify_dist.check_sync_worklist(repo)
    assert not ok and len(details) == 1 and "kC" in details[0], details

# 11. verify check_ch_corpus_parity：值不符/無真相源/未落地/own fallback
with tempfile.TemporaryDirectory() as td:
    repo = str(Path(td))
    dist_ch = Path(td) / "dist"
    wjson(Path(td) / "sources" / "ch" / "UI.json", {"k1": "corpus值", "k2": "未落地"})
    wjson(dist_ch / "UI.json", {"k1": "different", "kOwn": "own譯", "kNone": "?"})
    own = {"UI.json": {"kOwn": {"en": "e", "ch": "own譯", "cn": "c"}}}
    ok, details = verify_dist.check_ch_corpus_parity(repo, str(dist_ch), own)
    text = "\n".join(details)
    assert not ok
    assert "值不符 corpus" in text and "無真相源" in text and "未落地 dist CH" in text, details
    assert "kOwn" not in text, "own ch fallback 誤報"

# 12. verify placeholder：標籤 multiset＋例外鍵 CH 安全不豁免
with tempfile.TemporaryDirectory() as td:
    cn_d, ch_d = Path(td) / "CN", Path(td) / "CH"
    wjson(cn_d / "UI.json", {"t": "A<LINE>B", "x": "%1%%."})
    wjson(ch_d / "UI.json", {"t": "AB", "x": "%1%."})
    ok, fail, _ = verify_dist.check_placeholder(
        str(cn_d), str(ch_d), {"UI.json|x": {"cn_safe_value": "%1%%.", "reason": "t"}}
    )
    text = "\n".join(fail)
    assert not ok
    assert "標籤不符" in text, "ASCII 標籤 multiset 未檢"
    assert "CH 值含 format token" in text, "例外鍵 CH crash 簽名被豁免"

# 13. verify check_review_drift：漂移 WARN、恆不 FAIL
with tempfile.TemporaryDirectory() as td:
    repo = str(Path(td))
    dist_cn = Path(td) / "distCN"
    wjson(dist_cn / "UI.json", {"k": "現值"})
    wjson(Path(td) / "sources" / "ch_review_state.json",
          {"UI.json|k": "0" * 16, "UI.json|gone": h16("x")})
    ok, details, warn = verify_dist.check_review_drift(repo, str(dist_cn))
    assert ok and not details and len(warn) == 2, (details, warn)

print("PASS: CH corpus lane 13/13 案例通過")
