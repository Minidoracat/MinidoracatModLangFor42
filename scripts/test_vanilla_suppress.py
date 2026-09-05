# /// script
# requires-python = ">=3.10"
# ///
"""vanilla 出貨抑制的負向回歸測試（build 抑制 + verify [12] dist 閘門）

背景：PZ 的 `Translator.tryFillMapFromFile()` 把每個 mod 的 Translate 檔 `map.put()`
進同一張全域字串表、後載入者覆寫，故出貨任何 vanilla 同 (檔,鍵) 都會改寫本體譯文，
**連沒裝任何模組的玩家都受影響**（2026-08-10 玩家回報：原版 JS-2000 霰彈槍被改名為
Remington M870）。本檔守兩件事：build 真的剔除、verify 真的攔得住漏網。

執行：uv run scripts/test_vanilla_suppress.py
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
import lint_ch  # noqa: E402
import verify_dist  # noqa: E402

# 基準的 fail-closed 檢查要求：核心字串檔齊備、≥30 檔、≥10000 鍵、無檔內重複、
# 且 keys == union(scoped_keys)。fixture 須全數滿足，否則測的是 fail-closed 而非功能。
FILLER = [f"Base.Filler{i}" for i in range(10001)]
CORE_FILES = (
    "ItemName.json", "UI.json", "IG_UI.json", "ContextMenu.json", "Tooltip.json",
    "Recipes.json", "Sandbox.json", "Fluids.json", "Moveables.json", "Moodles.json",
)
VAN_SCOPED = {
    "ItemName.json": ["Base.Shotgun", "Base.Pistol", *FILLER],
    "IG_UI.json": ["IGUI_Vanilla"],
    # 湊足 30 檔門檻；核心檔一律列入
    **{f: [f"Pad_{f}"] for f in CORE_FILES if f not in ("ItemName.json", "IG_UI.json")},
    **{f"Pad{i}.json": [f"PadKey{i}"] for i in range(22)},
}


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def write_vanilla_keys(
    path: Path,
    keep: dict | None = None,
    scoped=VAN_SCOPED,
    allow: dict | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flat = sorted({k for ks in scoped.values() for k in ks})
    path.write_text(
        json.dumps(
            {
                "keys": flat,
                "scoped_keys": scoped,
                "allowlist": allow or {},
                "keep": keep or {},
            },
        ),
        encoding="utf-8",
    )


def keep_spec(anchor: str) -> dict:
    """keep 條目：anchor 與 reason 皆為必填非空。"""
    return {"anchor": anchor, "reason": "測試用豁免"}


def fresh_maps():
    """(merged_cn, merged_ch)：兩個 vanilla 同名鍵 + 一個模組自有鍵。"""
    cn = {
        "ItemName.json": {"Base.Shotgun": "雷明顿M870", "Base.Pistol": "伯莱塔", "Mod.Gun": "模组枪"},
        "IG_UI.json": {"IGUI_Vanilla": "本体", "IGUI_ModOnly": "模组"},
    }
    ch = {
        "ItemName.json": {"Base.Shotgun": "雷明頓M870", "Base.Pistol": "貝瑞塔", "Mod.Gun": "模組槍"},
        "IG_UI.json": {"IGUI_Vanilla": "本體", "IGUI_ModOnly": "模組"},
    }
    return cn, ch


# --- 1. build：vanilla 同 (檔,鍵) 自 CN/CH 對稱剔除，模組自有鍵不動 ---------- #
with tempfile.TemporaryDirectory() as td:
    vk = Path(td) / "sources" / "vanilla_keys.json"
    write_vanilla_keys(vk)
    build_mod.VANILLA_KEYS_JSON = vk
    cn, ch = fresh_maps()
    dropped, kept, anchor_errors = build_mod.suppress_vanilla(cn, ch)

    assert dropped == 3, f"應剔除 3 個 vanilla 同名鍵，實得 {dropped}"
    assert not kept and not anchor_errors, "無 keep 登記時不該有豁免或錨點錯誤"
    for label, m in (("CN", cn), ("CH", ch)):
        assert "Base.Shotgun" not in m["ItemName.json"], f"{label} 未剔除 Base.Shotgun"
        assert "Base.Pistol" not in m["ItemName.json"], f"{label} 未剔除 Base.Pistol"
        assert "IGUI_Vanilla" not in m["IG_UI.json"], f"{label} 未剔除 IGUI_Vanilla"
        assert "Mod.Gun" in m["ItemName.json"], f"{label} 誤刪模組自有鍵 Mod.Gun"
        assert "IGUI_ModOnly" in m["IG_UI.json"], f"{label} 誤刪模組自有鍵 IGUI_ModOnly"
    assert set(cn["ItemName.json"]) == set(ch["ItemName.json"]), "CN/CH 剔除不對稱（會破 [2] 鏡像）"

# --- 2/3. keep 不再是放行通道：非空即 fail-closed（2026-08-12 使用者裁決）------- #
# 「MOD 翻譯不得覆蓋本體任何一個現有 EN/CH/CN 鍵，一個都不行」。keep 欄位保留只為了
# 讓舊資料讀得動，但 build 與 oracle 都不再據它放行——留著豁免通道，原則就只是口號。
for label, spec in (("錨點相符", keep_spec(sha16("雷明頓M870"))), ("錨點漂移", keep_spec(sha16("舊值")))):
    with tempfile.TemporaryDirectory() as td:
        vk = Path(td) / "sources" / "vanilla_keys.json"
        write_vanilla_keys(vk, keep={"ItemName.json|Base.Shotgun": spec})
        build_mod.VANILLA_KEYS_JSON = vk
        try:
            build_mod.suppress_vanilla(*fresh_maps())
            raise AssertionError(f"build 對非空 keep（{label}）未 fail-closed——豁免通道還開著")
        except SystemExit as exc:
            assert exc.code == 1, f"應以 exit 1 中止，實得 {exc.code}"
        try:
            verify_dist._load_vanilla_basis(str(Path(td)))
            raise AssertionError(f"oracle 對非空 keep（{label}）未 fail-closed")
        except ValueError as exc:
            assert "keep" in str(exc), f"錯誤訊息未指出 keep：{exc}"

# --- 4. build/verify：基準不可信 → fail-closed 的各種形態 --------------------- #
# 純量級門檻是**假的 fail-closed**：2026-08-10 review 實測，拿掉整個 ItemName.json
# bucket 後仍有 42,364 鍵、同鍵重複萬次也能湊數，兩者都讓抑制整批靜默失效。
NO_ITEMNAME = {f: v for f, v in VAN_SCOPED.items() if f != "ItemName.json"}
BAD_BASES = {
    "量級殘缺": {"ItemName.json": ["Base.Shotgun"]},
    "核心檔整個消失": NO_ITEMNAME,
    "核心檔空 bucket": {**VAN_SCOPED, "ItemName.json": []},
    "同鍵重複灌水": {**VAN_SCOPED, "ItemName.json": ["Base.Shotgun"] * 10001},
    "檔數過少": {f: ["K"] for f in CORE_FILES},
}
for label, bad in BAD_BASES.items():
    with tempfile.TemporaryDirectory() as td:
        vk = Path(td) / "sources" / "vanilla_keys.json"
        write_vanilla_keys(vk, scoped=bad)
        build_mod.VANILLA_KEYS_JSON = vk
        try:
            build_mod.suppress_vanilla(*fresh_maps())
            raise AssertionError(f"基準「{label}」未觸發 SystemExit——fail-open")
        except SystemExit as exc:
            assert exc.code == 1, f"「{label}」應以 exit 1 中止，實得 {exc.code}"
        try:
            verify_dist._load_vanilla_basis(str(Path(td)))
            raise AssertionError(f"oracle 對基準「{label}」未 fail-closed")
        except ValueError:
            pass

# keys 與 scoped_keys 聯集不一致（只重生一半）→ 兩邊都 fail-closed
with tempfile.TemporaryDirectory() as td:
    vk = Path(td) / "sources" / "vanilla_keys.json"
    vk.parent.mkdir(parents=True)
    vk.write_text(
        json.dumps({"keys": ["只有這個"], "scoped_keys": VAN_SCOPED, "allowlist": {}, "keep": {}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    build_mod.VANILLA_KEYS_JSON = vk
    try:
        build_mod.suppress_vanilla(*fresh_maps())
        raise AssertionError("keys/scoped_keys 不一致未 fail-closed")
    except SystemExit:
        pass
    try:
        verify_dist._load_vanilla_basis(str(Path(td)))
        raise AssertionError("oracle 對 keys/scoped_keys 不一致未 fail-closed")
    except ValueError:
        pass

# keep 缺 reason → fail-closed（豁免影響全體玩家，必須寫明理由）
with tempfile.TemporaryDirectory() as td:
    vk = Path(td) / "sources" / "vanilla_keys.json"
    write_vanilla_keys(vk, keep={"ItemName.json|Base.Shotgun": {"anchor": sha16("雷明頓M870")}})
    build_mod.VANILLA_KEYS_JSON = vk
    try:
        build_mod.suppress_vanilla(*fresh_maps())
        raise AssertionError("keep 缺 reason 未 fail-closed")
    except SystemExit:
        pass
    try:
        verify_dist._load_vanilla_basis(str(Path(td)))
        raise AssertionError("oracle 對 keep 缺 reason 未 fail-closed")
    except ValueError:
        pass


# --- 5. verify [12]：dist 殘留 vanilla 同名鍵 → FAIL ------------------------- #
def make_repo(td: str, dist_itemname: dict, keep: dict | None = None) -> tuple[str, str, str]:
    repo = Path(td)
    write_vanilla_keys(repo / "sources" / "vanilla_keys.json", keep=keep)
    (repo / "sources" / "own_translations.json").write_text(
        json.dumps({"entries": {}}, ensure_ascii=False), encoding="utf-8"
    )
    (repo / "sources" / "mods").mkdir(parents=True, exist_ok=True)
    for lang in ("CN", "CH"):
        d = repo / "dist" / lang
        d.mkdir(parents=True, exist_ok=True)
        # CN/CH 刻意寫不同值：keep 錨點只對 CH 值驗，同值會讓「拿 CN 當 CH 掃」的錯誤隱形
        payload = {k: (v if lang == "CH" else v + "_CN") for k, v in dist_itemname.items()}
        (d / "ItemName.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(repo), str(repo / "dist" / "CN"), str(repo / "dist" / "CH")


with tempfile.TemporaryDirectory() as td:
    repo, dcn, dch = make_repo(td, {"Base.Shotgun": "雷明頓M870", "Mod.Gun": "模組槍"})
    ok, details, _ = verify_dist.check_vanilla_collision(repo, dcn, dch)
    assert not ok, "dist 殘留 vanilla 同名鍵卻判 PASS——閘門形同虛設"
    joined = "\n".join(details)
    assert "Base.Shotgun" in joined, f"未指出洩漏的鍵：{joined}"
    assert "Mod.Gun" not in joined, f"誤報模組自有鍵：{joined}"
    assert sum("Base.Shotgun" in d for d in details) == 2, "CN/CH 兩側都應各報一次"

# --- 6. verify [12]：抑制乾淨的 dist → PASS；有 keep 登記一律 FAIL ------------- #
with tempfile.TemporaryDirectory() as td:
    repo, dcn, dch = make_repo(td, {"Mod.Gun": "模組槍"})
    ok, details, _ = verify_dist.check_vanilla_collision(repo, dcn, dch)
    assert ok, f"乾淨 dist 誤判 FAIL：{details}"

with tempfile.TemporaryDirectory() as td:
    repo, dcn, dch = make_repo(
        td,
        {"Base.Shotgun": "雷明頓M870"},
        keep={"ItemName.json|Base.Shotgun": keep_spec(sha16("雷明頓M870"))},
    )
    # 基準不可信一律擲 ValueError 由 verify 主流程轉 FAIL（同其他 fail-closed 形態）
    try:
        verify_dist.check_vanilla_collision(repo, dcn, dch)
        raise AssertionError("有 keep 登記卻沒擋——豁免通道還開著")
    except ValueError as exc:
        assert "keep" in str(exc), f"未指出是 keep 問題：{exc}"

# --- 6b. 泛用地圖鍵的 allowlist 必須精確到檔名，不能裸 title 一次放行全地圖 --- #
with tempfile.TemporaryDirectory() as td:
    repo = Path(td)
    scoped = {k: list(v) for k, v in VAN_SCOPED.items()}
    scoped["MapA.json"] = ["title"]
    scoped["MapB.json"] = ["title"]
    a = {"en": "Map A", "ch": "地圖甲", "cn": "地图甲"}
    b = {"en": "Map B", "ch": "地圖乙", "cn": "地图乙"}
    write_vanilla_keys(
        repo / "sources" / "vanilla_keys.json",
        scoped=scoped,
        allow={"MapA.json|title": {"own_anchor": sha16("Map A|地圖甲|地图甲")}},
    )
    (repo / "sources" / "own_translations.json").write_text(
        json.dumps({"entries": {"MapA.json": {"title": a}, "MapB.json": {"title": b}}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    (repo / "sources" / "mods").mkdir(parents=True)
    for lang in ("CN", "CH"):
        d = repo / "dist" / lang
        d.mkdir(parents=True)
        (d / "ItemName.json").write_text("{}", encoding="utf-8")
    ok, details, _ = verify_dist.check_vanilla_collision(
        str(repo), str(repo / "dist" / "CN"), str(repo / "dist" / "CH")
    )
    joined = "\n".join(details)
    assert not ok and "MapB.json|title" in joined, f"未攔未登記的第二張地圖：{joined}"
    assert "MapA.json|title" not in joined, f"精確檔域 allowlist 未放行 MapA：{joined}"

# --- 7. verify：suppressed_pairs 涵蓋全部 vanilla 鍵（不再有 keep 例外）------- #
with tempfile.TemporaryDirectory() as td:
    repo = Path(td)
    write_vanilla_keys(repo / "sources" / "vanilla_keys.json")
    pairs = verify_dist.suppressed_pairs(str(repo))
    assert "ItemName.json|Base.Shotgun" in pairs, "vanilla 鍵未納入抑制集合"
    assert "ItemName.json|Base.Pistol" in pairs, "vanilla 鍵未納入抑制集合"
    assert "IG_UI.json|IGUI_Vanilla" in pairs, "跨檔 vanilla 鍵未納入抑制集合"
    # 檔域語意：同名鍵只在同檔算撞（vanilla 多張地圖檔各帶 title/description 而不互撞）
    assert "IG_UI.json|Base.Shotgun" not in pairs, "抑制集合洩漏成跨檔比對"

# --- 8. verify [13]：目標檔的缺席是刻意抑制時，不得誤報成「受困鍵」 ------------ #
with tempfile.TemporaryDirectory() as td:
    repo = Path(td)
    write_vanilla_keys(repo / "sources" / "vanilla_keys.json")
    en_dir = repo / "sources" / "en"
    en_dir.mkdir(parents=True)
    rid = "translate_en|mods/m/42/media/lua/shared/Translate/EN/UI.json|UI_Sentinel"
    (en_dir / "1.json").write_text(json.dumps({rid: "x"}), encoding="utf-8")
    meta_dir = repo / "sources" / "mods" / "1"
    meta_dir.mkdir(parents=True)
    (meta_dir / "metadata.json").write_text(
        json.dumps({"workshop_id": "1", "mod_ids": ["Mod1"]}), encoding="utf-8"
    )
    (repo / "sources" / "mod_registry.json").write_text(json.dumps({"mods": {
        "1": {
            "status": "active", "source": "test", "verified": "2026-08-30",
            "mod_ids": ["Mod1"],
        }
    }}), encoding="utf-8")
    state = repo / "tracker-state"
    state.mkdir()
    (state / "watchlist.json").write_text(json.dumps({
        "schema_version": verify_dist.tracker.SCHEMA_VERSION,
        "count": 2,
        "items": {
            "1": {"mod_ids": ["Mod1"], "role": "mod"},
            verify_dist.tracker.AS1_WORKSHOP_ID: {
                "mod_ids": [verify_dist.tracker.AS1_MOD_ID], "role": "as1"
            },
        },
    }), encoding="utf-8")
    verify_dist.tracker.write_corpus_hashes({
        "extractor_schema": verify_dist.tracker.EXTRACTOR_SCHEMA,
        "mods": {"1": {
            "extractor_schema": verify_dist.tracker.EXTRACTOR_SCHEMA,
            "records": {rid: hashlib.sha256(b"x").hexdigest()[:12]},
        }},
    }, state / "en_corpus_hashes")
    (state / "timestamps.json").write_text(
        json.dumps({"items": {"1": {"removed": False}}}), encoding="utf-8"
    )
    dist_ch = repo / "dist" / "CH"
    dist_ch.mkdir(parents=True)
    # IG_UI.json 是白名單活檔但已抑制掉 IGUI_Vanilla；死檔 UI_EN.json 仍留著同鍵
    (dist_ch / "IG_UI.json").write_text(json.dumps({"IGUI_Mod": "x"}), encoding="utf-8")
    (dist_ch / "UI_EN.json").write_text(
        json.dumps({"IGUI_Vanilla": "本體", "IGUI_Orphan": "孤兒"}, ensure_ascii=False),
        encoding="utf-8",
    )
    sup = verify_dist.suppressed_pairs(str(repo))
    ok, stranded, obsolete = verify_dist.check_loadable_files(str(repo), str(dist_ch), sup)
    joined = "\n".join(stranded + obsolete)
    assert "IGUI_Vanilla" not in joined, f"抑制鍵被誤報成受困鍵：{joined}"
    assert "IGUI_Orphan" in joined, f"真正的受困鍵漏報：{joined}"

# --- 9. lint_ch 的抑制感知：抑制鍵不進掃描域，基準壞損 fail-loud ---------------- #
# 這條是踩過才補的：lint [C] 的 adjudicated() 以 dist CN 值查 ch_review_state 台帳，
# 抑制鍵不在 dist ⇒ 已裁決的鍵一律查不到 ⇒ 全部退回「待裁決」把棘輪炸掉。
with tempfile.TemporaryDirectory() as td:
    vk = Path(td) / "vanilla_keys.json"
    write_vanilla_keys(vk)          # keep 恆空——build/verify 已擋掉非空的情形
    lint_ch.VANILLA_KEYS_JSON = vk
    sup = lint_ch._load_suppressed()
    assert "Base.Shotgun" in sup["ItemName.json"], "抑制鍵未納入 lint 排除集合"
    assert "Base.Pistol" in sup["ItemName.json"], "抑制鍵未納入 lint 排除集合"
    assert "IGUI_Vanilla" in sup["IG_UI.json"], "跨檔抑制鍵未納入"

    vk.write_text(json.dumps({"keys": []}), encoding="utf-8")  # 基準壞損
    try:
        lint_ch._load_suppressed()
        raise AssertionError("lint 對壞損基準未 fail-loud（會靜默把抑制鍵放回掃描域）")
    except ValueError:
        pass

print("✅ vanilla 出貨抑制回歸測試全部通過（10 組，含 6 種基準 fail-closed 形態）")
