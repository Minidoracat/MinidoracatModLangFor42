# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""jev_scan.py 的非平凡邏輯回歸測試（stub 回應，不打網路）。

守五件事：
  1. batch 模式的題名前綴要正確配回原鍵（配錯＝整份報告張冠李戴）。
  2. 缺官方 CH 時不得問 `worse_than_official`（該欄留空）。
  3. 輸出檔名不得被 `Path.with_suffix` 吃掉時間戳。
  4. EN 非真英文（Placeholder／空白／鍵名回填）的鍵不得進待掃清單。
  5. EN 錨點配對：檔域鍵不得跨檔（地圖 description 配到別人的 Mod.json）、死分支
     不得當錨點、同 owner 內 JSON EN 勝過 script DisplayName、跨 owner 英文不同
     一律跳過不得 first-wins。

執行：uv run scripts/test_jev_scan.py（或 pytest）
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import jev_scan  # noqa: E402

ITEMS = [
    {"file": "UI.json", "key": "A", "en": "Dry", "official_ch": "乾燥", "ours_ch": "幹燥"},
    {"file": "UI.json", "key": "B", "en": "Open", "official_ch": "", "ours_ch": "開啟"},
]

STUB_ANSWERS = {
    "k1.s2t_error": {"noul": 0.9}, "k1.prc_wording": {"noul": 0.2},
    "k1.meaning_mismatch": {"noul": 0.3}, "k1.worse_than_official": {"noul": 0.7},
    "k2.s2t_error": {"noul": 0.1}, "k2.prc_wording": {"noul": 0.2},
    "k2.meaning_mismatch": {"noul": 0.3},
}


def _stub_call(payload, url, api_key, retries=2):  # noqa: ARG001
    return {"model": "stub-1", "answers": STUB_ANSWERS,
            "usage": {"input_tokens": 100, "output_tokens": 10, "cost": 0.001}}


def test_questions_scoped_to_official() -> None:
    assert "worse_than_official" in jev_scan.questions_for(True)
    assert "worse_than_official" not in jev_scan.questions_for(False)


def test_batch_request_shape() -> None:
    payload, prefixes = jev_scan.build_request(ITEMS, "m")
    assert prefixes == ["k1", "k2"]
    assert set(payload["state"]["items"]) == {"k1", "k2"}
    # k1 有官方 CH（4 題）、k2 沒有（3 題）
    assert set(payload["questions"]) == set(STUB_ANSWERS)


def test_batch_prefix_roundtrip() -> None:
    real = jev_scan.call_jev
    jev_scan.call_jev = _stub_call
    try:
        rows = jev_scan.scan_batch(ITEMS, "http://stub", "key", "m")
    finally:
        jev_scan.call_jev = real
    by_key = {r["key"]: r for r in rows}
    # 機率必須跟著自己的前綴回到自己的鍵，不得錯位
    assert by_key["A"]["s2t_error"] == 0.9
    assert by_key["A"]["worse_than_official"] == 0.7
    assert by_key["B"]["s2t_error"] == 0.1
    assert by_key["B"]["worse_than_official"] is None
    assert by_key["A"]["max_prob"] == 0.9
    # usage 平均攤到每列，總和等於整批用量
    assert sum(r["input_tokens"] for r in rows) == 100


def test_sidecar_keeps_timestamp() -> None:
    prefix = Path("reports/jev_scan.20260919-215649")
    assert jev_scan.sidecar(prefix, ".jsonl").name == "jev_scan.20260919-215649.jsonl"


def test_backfill_en_filtered() -> None:
    f = jev_scan.is_backfill_en
    assert f("STFR.Alicepack_Police_SWAT", "Placeholder")
    assert f("STFR.Alicepack_Police_SWAT", "placeholder ")
    assert f("UI_Foo", "   ")
    assert f("ContextMenu_Back", "Back")
    assert f("AnimalName_cat_breeds_garfield", "Garfield")
    assert f("HMW.H_AcousticBlack", "H_AcousticBlack")
    assert not f("ContextMenu_Back", "Go back")
    assert not f("Base.Sling_Camo", "Camo Sling")
    # 端到端：stub EN 索引＋暫存 corpus，確認 load_pairs 真的把它們踢掉並計數
    real_index, real_dir = jev_scan.build_en_index, jev_scan.CH_DIR
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "UI.json").write_text(
            json.dumps({"A": "佔位", "B": "開啟", "X_Back": "返回", "C": "空白錨點"}),
            encoding="utf-8", newline="\n")
        jev_scan.build_en_index = lambda: (
            {"A": "Placeholder", "B": "Open", "X_Back": "Back", "C": " \t\n"},
            {"en_keys": 4, "en_owner_conflicts": 0})
        jev_scan.CH_DIR = Path(tmp)
        try:
            items, stats = jev_scan.load_pairs(None)
        finally:
            jev_scan.build_en_index, jev_scan.CH_DIR = real_index, real_dir
    assert [i["key"] for i in items] == ["B"]
    assert stats["skipped_backfill"] == 3


# 一個 wid 的鏡像，涵蓋全部配對規則。mod root `MapPack` 的有效分支＝common＋42。
EN_MAPPACK = {
    # 檔域鍵：同檔的 description 才是這張地圖的錨點
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/Brandenburg, KY.json|description":
        "<CENTRE> BRANDENBURG, KENTUCKY",
    # Mod.json 的 description 是**別的東西**（mod 簡介），不得被地圖檔取用
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/Mod.json|description":
        "A pack of small Kentucky towns.",
    # 死分支：舊版本夾／mod 根 media／legacy .txt 都不是執行期存在的定義
    "translate_en|mods/MapPack/41/media/lua/shared/Translate/EN/UI.json|UI_Dead_Old": "Old branch",
    "translate_en|mods/MapPack/media/lua/shared/Translate/EN/UI.json|UI_Dead_Root": "Root branch",
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI_EN.txt|UI_Dead_Txt": "Legacy txt",
    # common → 最佳版本夾覆寫
    "translate_en|mods/MapPack/common/media/lua/shared/Translate/EN/UI.json|UI_Overridden": "Common text",
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI.json|UI_Overridden": "Version text",
    # 已有非空值後的空字串：引擎不覆寫
    "translate_en|mods/MapPack/common/media/lua/shared/Translate/EN/UI.json|UI_Kept": "Kept text",
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI.json|UI_Kept": "",
    # 同 owner：JSON EN 勝過 script DisplayName；JSON 留空則整鍵抑制
    "script_item_dn|mods/MapPack/42/media/scripts/items.txt|Base.Axe": "Script Axe",
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/ItemName.json|Base.Axe": "Json Axe",
    "script_item_dn|mods/MapPack/42/media/scripts/items.txt|Base.Ghost": "Script Ghost",
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/ItemName.json|Base.Ghost": "",
    # 死 JSON（檔名不在 Translator 白名單）：引擎不讀，既不得自成錨點，也不得抑制
    # 同鍵的 script DisplayName
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI_EN.json|UI_Dead_Json":
        "Dead json text",
    "script_item_dn|mods/MapPack/42/media/scripts/items.txt|Base.Saw": "Script Saw",
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI_EN.json|Base.Saw": "",
    # 跨 owner 比對用
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI.json|UI_Agree": "Shared text",
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI.json|UI_Quote": "Don\u2019t panic",
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI.json|UI_Clash": "Our meaning",
    # 一邊被上游留空、一邊有字：該 owner 的玩家看到空白，是歧義不是「另一邊說了算」
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI.json|UI_BlankHere": "",
    # 兩邊都空：沒有可比對的英文，排除即可，不算衝突
    "translate_en|mods/MapPack/42/media/lua/shared/Translate/EN/UI.json|UI_AllBlank": "",
}
EN_OTHER = {
    "translate_en|mods/Other/42/media/lua/shared/Translate/EN/UI.json|UI_Agree": "Shared text",
    "translate_en|mods/Other/42/media/lua/shared/Translate/EN/UI.json|UI_Quote": "Don't panic",
    "translate_en|mods/Other/42/media/lua/shared/Translate/EN/UI.json|UI_Clash": "A different thing",
    "translate_en|mods/Other/42/media/lua/shared/Translate/EN/UI.json|UI_BlankHere": "Other has text",
    "translate_en|mods/Other/42/media/lua/shared/Translate/EN/UI.json|UI_AllBlank": "   ",
}


def _write_sources(root: Path, mirrors: dict, extra_records: dict | None = None) -> Path:
    """寫出 stub 的 `sources/en` 鏡像＋`tracker-state/en_corpus_hashes`，回傳 EN 目錄。

    state 是宇宙（含 id-only 的 `script_*`），鏡像只放 text-bearing 記錄的值——與
    backfill-en 的真實落盤形狀一致，值 hash 用 `tracker.value_hash` 以通過一致性檢查。
    """
    en_dir, state_dir = root / "en", root / "state"
    en_dir.mkdir()
    state_dir.mkdir()
    (state_dir / "_meta.json").write_text(
        json.dumps({"schema_version": 1, "extractor_schema": jev_scan.tracker.EXTRACTOR_SCHEMA}),
        encoding="utf-8", newline="\n")
    for wid, mirror in mirrors.items():
        (en_dir / f"{wid}.json").write_text(json.dumps(mirror, ensure_ascii=False),
                                            encoding="utf-8", newline="\n")
        records = {rid: jev_scan.tracker.value_hash(v) for rid, v in mirror.items()}
        records.update((extra_records or {}).get(wid, {}))
        (state_dir / f"{wid}.json").write_text(
            json.dumps({"records": records}, ensure_ascii=False),
            encoding="utf-8", newline="\n")
    jev_scan.tracker.EN_CORPUS_HASHES_DIR = state_dir
    return en_dir


def test_en_index_matching() -> None:
    real_en, real_ch = jev_scan.EN_DIR, jev_scan.CH_DIR
    real_state = jev_scan.tracker.EN_CORPUS_HASHES_DIR
    with tempfile.TemporaryDirectory() as tmp:
        ch_dir = Path(tmp) / "ch"
        ch_dir.mkdir()
        en_dir = _write_sources(Path(tmp), {"100": EN_MAPPACK, "200": EN_OTHER})
        (ch_dir / "Brandenburg, KY.json").write_text(
            json.dumps({"description": "勃蘭登堡描述"}, ensure_ascii=False),
            encoding="utf-8", newline="\n")
        (ch_dir / "UI.json").write_text(
            json.dumps({"UI_Overridden": "版本文字", "UI_Kept": "保留文字",
                        "UI_Agree": "共用文字", "UI_Quote": "別慌", "UI_Clash": "衝突",
                        "UI_Dead_Old": "舊", "UI_Dead_Root": "根", "UI_Dead_Txt": "死檔",
                        "UI_Dead_Json": "死 JSON", "UI_BlankHere": "一邊空白",
                        "UI_AllBlank": "兩邊都空"},
                       ensure_ascii=False), encoding="utf-8", newline="\n")
        (ch_dir / "ItemName.json").write_text(
            json.dumps({"Base.Axe": "斧頭", "Base.Ghost": "幽靈", "Base.Saw": "鋸子"},
                       ensure_ascii=False), encoding="utf-8", newline="\n")
        jev_scan.EN_DIR, jev_scan.CH_DIR = en_dir, ch_dir
        try:
            index, en_stats = jev_scan.build_en_index()
            items, stats = jev_scan.load_pairs(None)
        finally:
            jev_scan.EN_DIR, jev_scan.CH_DIR = real_en, real_ch
            jev_scan.tracker.EN_CORPUS_HASHES_DIR = real_state

    # 檔域鍵：地圖的 description 只能來自同名檔，Mod.json 那筆不得外洩成任何錨點
    assert index[("Brandenburg, KY", "description")] == "<CENTRE> BRANDENBURG, KENTUCKY"
    assert "description" not in index, "檔域鍵不得同時以裸鍵入索引（會跨檔亂配）"
    # 死分支不得成為錨點；common 被最佳版本夾覆寫；版本夾的空字串不覆寫 common
    assert not {"UI_Dead_Old", "UI_Dead_Root", "UI_Dead_Txt"} & set(index)
    assert index["UI_Overridden"] == "Version text"
    assert index["UI_Kept"] == "Kept text"
    # 同 owner 內 JSON EN 勝出；JSON 留空＝執行期顯示空白，script DisplayName 一併抑制
    assert index["Base.Axe"] == "Json Axe"
    assert "Base.Ghost" not in index
    # 死 JSON（`UI_EN.json`，引擎不讀）：不自成錨點，也不得抑制同鍵的 script DisplayName
    assert "UI_Dead_Json" not in index
    assert index["Base.Saw"] == "Script Saw", "死 JSON 的空值不得抑制 script DisplayName"
    # 跨 owner：全等（含彎引號正規化後全等）可合併，英文不同整鍵跳過並計數
    assert index["UI_Agree"] == "Shared text"
    assert index["UI_Quote"] in ("Don\u2019t panic", "Don't panic")
    assert "UI_Clash" not in index, "跨 owner 英文不同不得 first-wins"
    # 一邊空白一邊有字＝歧義：不得讓有字的那邊獨贏
    assert "UI_BlankHere" not in index, "被抑制成空白的 owner 不得從歧義判定中消失"
    # 兩邊都空：沒有可比對的英文，排除但不算衝突
    assert "UI_AllBlank" not in index
    assert en_stats["en_owner_conflicts"] == 2

    # 端到端：地圖 description 配到同檔英文，死分支／死檔／歧義鍵落 no_en
    paired = {(i["file"], i["key"]): i["en"] for i in items}
    assert paired[("Brandenburg, KY.json", "description")] == "<CENTRE> BRANDENBURG, KENTUCKY"
    assert ("UI.json", "UI_Clash") not in paired
    # UI_Clash／UI_BlankHere（歧義）＋UI_AllBlank＋四個死分支／死檔鍵＋Base.Ghost＝8 鍵無錨點
    assert stats["no_en"] == 8 and stats["en_owner_conflicts"] == 2


def test_state_is_the_branch_universe() -> None:
    """較新版本夾只留下 id-only 記錄時，舊版本夾的英文仍須被淘汰。

    鏡像只存 text-bearing 記錄，所以 `42.20` 只有 `script_craftRecipe` 時鏡像看不到它；
    用鏡像決定有效分支就會把 `42` 當最佳分支、拿它的過期英文當錨點。
    """
    mirror = {
        "translate_en|mods/M/common/media/lua/shared/Translate/EN/UI.json|UI_Example":
            "Common text",
        "translate_en|mods/M/42/media/lua/shared/Translate/EN/UI.json|UI_Example":
            "Stale 42 text",
        # state 有 common＋42.20 兩筆同 fullType 的 DN，鏡像只剩 common 那筆
        "script_item_dn|mods/M/common/media/scripts/i.txt|Base.Old": "Common DN",
        "translate_en|mods/N/42/media/lua/shared/Translate/EN/UI.json|UI_Unknown": "",
    }
    extra = {"300": {
        "script_craftRecipe|mods/M/42.20/media/scripts/recipes.txt|NewRecipe": "deadbeef0000",
        "script_item_dn|mods/M/42.20/media/scripts/i.txt|Base.Old": "deadbeef0001",
        "translate_en|mods/N/common/media/lua/shared/Translate/EN/UI.json|UI_Unknown":
            "deadbeef0002",
    }}
    real_en, real_state = jev_scan.EN_DIR, jev_scan.tracker.EN_CORPUS_HASHES_DIR
    with tempfile.TemporaryDirectory() as tmp:
        other = {
            "script_item_dn|mods/Other/42/media/scripts/i.txt|Base.Old": "Other owner DN",
        }
        jev_scan.EN_DIR = _write_sources(Path(tmp), {"300": mirror, "301": other}, extra)
        try:
            index, stats = jev_scan.build_en_index()
        finally:
            jev_scan.EN_DIR = real_en
            jev_scan.tracker.EN_CORPUS_HASHES_DIR = real_state

    assert index["UI_Example"] == "Common text", \
        "有效分支須由 state 決定（42.20 才是最佳分支，42 的英文已過期）"
    # DN 勝出 rid 在 42.20、鏡像缺該筆值＝執行期值未知，不得回退用 common 的舊 DisplayName
    assert "Base.Old" not in index
    assert stats["en_unusable_wids"] == 0, "state 有、鏡像沒有不算來源不一致（helper 契約）"
    assert "UI_Unknown" not in index
    assert stats["en_mirror_gaps"] == 2, "缺值 owner 與空值不覆寫的未知值都必須保留盲區"



def main() -> int:
    test_questions_scoped_to_official()
    test_batch_request_shape()
    test_batch_prefix_roundtrip()
    test_sidecar_keeps_timestamp()
    test_backfill_en_filtered()
    test_en_index_matching()
    test_state_is_the_branch_universe()
    print("OK — jev_scan 回歸測試全數通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
