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


def write_vanilla_keys(path: Path, keep: dict | None = None, scoped=VAN_SCOPED) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flat = sorted({k for ks in scoped.values() for k in ks})
    path.write_text(
        json.dumps(
            {"keys": flat, "scoped_keys": scoped, "allowlist": {}, "keep": keep or {}},
            ensure_ascii=False,
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

# --- 2. build：keep 登記的鍵保留；錨點相符無錯 -------------------------------- #
with tempfile.TemporaryDirectory() as td:
    vk = Path(td) / "sources" / "vanilla_keys.json"
    write_vanilla_keys(vk, keep={"ItemName.json|Base.Shotgun": keep_spec(sha16("雷明頓M870"))})
    build_mod.VANILLA_KEYS_JSON = vk
    cn, ch = fresh_maps()
    dropped, kept, anchor_errors = build_mod.suppress_vanilla(cn, ch)

    assert dropped == 2, f"keep 一鍵時應剔除 2 個，實得 {dropped}"
    assert kept == ["ItemName.json|Base.Shotgun"], f"keep 豁免未回報：{kept}"
    assert not anchor_errors, f"錨點相符卻報錯：{anchor_errors}"
    assert ch["ItemName.json"]["Base.Shotgun"] == "雷明頓M870", "keep 鍵被誤刪"
    assert cn["ItemName.json"]["Base.Shotgun"] == "雷明顿M870", "keep 鍵 CN 側被誤刪"

# --- 3. build：keep 錨點漂移 → 阻斷錯誤（豁免是對「當時那個值」的背書） -------- #
with tempfile.TemporaryDirectory() as td:
    vk = Path(td) / "sources" / "vanilla_keys.json"
    write_vanilla_keys(vk, keep={"ItemName.json|Base.Shotgun": keep_spec(sha16("舊值"))})
    build_mod.VANILLA_KEYS_JSON = vk
    cn, ch = fresh_maps()
    _, kept, anchor_errors = build_mod.suppress_vanilla(cn, ch)

    assert kept == ["ItemName.json|Base.Shotgun"], "keep 鍵仍應被視為豁免"
    assert len(anchor_errors) == 1, f"錨點漂移未阻斷：{anchor_errors}"
    assert "keep 錨點失效" in anchor_errors[0], f"錯誤訊息不對：{anchor_errors[0]}"

# --- 4. build/verify：基準不可信 → fail-closed 的各種形態 --------------------- #
# 純量級門檻是**假的 fail-closed**：2026-08-10 review 實測，拿掉整個 ItemName.json
# bucket 後仍有 42,364 鍵、同鍵重複萬次也能湊數，兩者都讓抑制整批靜默失效。
NO_ITEMNAME = {f: v for f, v in VAN_SCOPED.items() if f != "ItemName.json"}
BAD_BASES = {
    "量級殘缺": {"ItemName.json": ["Base.Shotgun"]},
    "核心檔整個消失": NO_ITEMNAME,
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

# --- 6. verify [12]：抑制乾淨的 dist → PASS；keep 登記者放行 ------------------ #
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
    ok, details, _ = verify_dist.check_vanilla_collision(repo, dcn, dch)
    assert ok, f"keep 登記鍵不該被 [12] 攔下：{details}"

# --- 6b. verify [12]：keep 錨點對出貨 CH 值漂移 → FAIL（oracle 獨立於 build 再驗一次） - #
with tempfile.TemporaryDirectory() as td:
    repo, dcn, dch = make_repo(
        td,
        {"Base.Shotgun": "改過的名字"},
        keep={"ItemName.json|Base.Shotgun": keep_spec(sha16("雷明頓M870"))},
    )
    ok, details, _ = verify_dist.check_vanilla_collision(repo, dcn, dch)
    assert not ok, "keep 錨點漂移卻判 PASS——dist 被手改也不會被發現"
    joined = "\n".join(details)
    assert "keep 錨點失效" in joined, f"錯誤訊息不對：{joined}"
    assert sum("keep 錨點失效" in d for d in details) == 1, f"錨點只對 CH 值驗一次：{details}"

# --- 7. verify：suppressed_pairs 扣除 keep（dist 面期望的共同基礎） ----------- #
with tempfile.TemporaryDirectory() as td:
    repo = Path(td)
    write_vanilla_keys(
        repo / "sources" / "vanilla_keys.json",
        keep={"ItemName.json|Base.Pistol": keep_spec("deadbeefdeadbeef")},
    )
    pairs = verify_dist.suppressed_pairs(str(repo))
    assert "ItemName.json|Base.Shotgun" in pairs, "vanilla 鍵未納入抑制集合"
    assert "IG_UI.json|IGUI_Vanilla" in pairs, "跨檔 vanilla 鍵未納入抑制集合"
    assert "ItemName.json|Base.Pistol" not in pairs, "keep 登記鍵不該進抑制集合"
    # 檔域語意：同名鍵只在同檔算撞（vanilla 多張地圖檔各帶 title/description 而不互撞）
    assert "IG_UI.json|Base.Shotgun" not in pairs, "抑制集合洩漏成跨檔比對"

# --- 8. verify [13]：目標檔的缺席是刻意抑制時，不得誤報成「受困鍵」 ------------ #
with tempfile.TemporaryDirectory() as td:
    repo = Path(td)
    write_vanilla_keys(repo / "sources" / "vanilla_keys.json")
    (repo / "sources" / "en").mkdir(parents=True)
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
    write_vanilla_keys(vk, keep={"ItemName.json|Base.Pistol": keep_spec("deadbeefdeadbeef")})
    lint_ch.VANILLA_KEYS_JSON = vk
    sup = lint_ch._load_suppressed()
    assert "Base.Shotgun" in sup["ItemName.json"], "抑制鍵未納入 lint 排除集合"
    assert "Base.Pistol" not in sup["ItemName.json"], "keep 鍵不該自 lint 掃描域排除（它會出貨）"
    assert "IGUI_Vanilla" in sup["IG_UI.json"], "跨檔抑制鍵未納入"

    vk.write_text(json.dumps({"keys": []}), encoding="utf-8")  # 基準壞損
    try:
        lint_ch._load_suppressed()
        raise AssertionError("lint 對壞損基準未 fail-loud（會靜默把抑制鍵放回掃描域）")
    except ValueError:
        pass

print("✅ vanilla 出貨抑制回歸測試全部通過（10 組，含 6 種基準 fail-closed 形態）")
