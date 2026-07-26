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

print("PASS: own-mod lane 6/6 案例通過")
