# /// script
# requires-python = ">=3.10"
# ///
"""`split_sources.py` evidence-first 歸屬 ＋ `mod_registry.py` schema 的回歸測試。

執行：uv run scripts/test_split_attribution.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。

守住的不變量（每一條都對應一種「產出看起來完全正常」的靜默失效）：

1. **owner 只能來自 `sources/en` 第一手鍵證據**，且多 owner 一律複製到全部 owner
   目錄（去重延後至 build）。少了聯集就會依 dict 迭代序隨機掉 owner。
1b. **泛用鍵 `title`/`description` 是檔域限定，不吃 key-only 聯集**。它們在上游是
   「每個地圖／描述檔各有一份」的裸鍵名，key-only 會把「定義過任一張地圖 title 的
   wid」交叉灌給**每一張**地圖檔（實測 3781428012 只在 `Mod.json` 定義 description，
   卻被灌進 30+ 個地圖檔而讓 manifest 摘要失真）。兩張表刻意互斥：泛用鍵只在
   `(檔名幹, 鍵)` 表、其餘鍵只在 key-only 表，讓 key-only 後門在結構上不存在。
2. **`script_item_dn` 只作用於 `ItemName.json`**。引擎僅在此以裸 `Module.Item` 查
   物品名；讓它跨檔生效等於把「某 mod 有這個物品」誤讀成「某 mod 定義了這個
   UI/Tooltip 鍵」，歸屬會大面積污染而 parity 全綠。
3. **legacy `ItemName_<fullType>` 精確去前綴**，且**不猜 module**（`?.X` 不是證據）。
   兩者任一失守，B41 前綴形鍵就會整批失去 owner 或亂掛。
4. **vanilla 以 (檔名, 鍵) 檔域對優先壓過 owner**，且**只在該檔生效**。用扁平鍵集會
   把 mod 自有的同名鍵一起剝奪歸屬；不做壓制則本體鍵被掛給 mod、覆寫全體玩家譯文。
5. **證據規模不足須 fail-closed**：「EN 鏡像幾乎全滅」與「上游真的沒東西」在產出上
   長得一模一樣（全樹落 `_unsorted`），沒有閘門就會靜默清空整棵樹。壞 JSON／壞
   schema **不吃** `--allow-low-evidence`（放行形狀壞損＝把爛證據當事實）。
6. **registry 是 metadata facts，不是歸屬證據，但缺檔／schema 壞損一律 fail-closed**：
   名冊是人工真相，也是 registry-only 監看的唯一保底——缺檔回空集會讓「被誤刪／路徑
   寫錯」與「真的一個 mod 都沒有」不可區分（watchlist 靜默縮回純衍生集、新 MOD 從此
   不再抽語料，且所有 gate 全綠）。schema 壞損須帶具體 wid/欄位炸掉（靜默丟棄條目會讓
   「名冊裡有」與「真的在追」無聲脫鉤）；`retired` 條目照樣回傳但不供 split metadata。
7. **完整性與排序冪等**：owner ∪ `_unsorted` 去重後 == As1 快照，且重跑 byte-identical。
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402
import mod_registry  # noqa: E402
import split_sources  # noqa: E402

FAILED: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILED.append(msg)


def wjson(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")


EN_TR = "mods/M/42.20/media/lua/shared/Translate/EN/UI.json"
EN_SCRIPT = "mods/M/42/media/scripts/items.txt"


def rid_tr(key: str, relpath: str = EN_TR) -> str:
    return f"translate_en|{relpath}|{key}"


def rid_dn(full: str, relpath: str = EN_SCRIPT) -> str:
    return f"script_item_dn|{relpath}|{full}"


def load_en(mirrors: dict[str, dict[str, str]]):
    """以臨時 sources/en 跑 load_en_evidence()，回 (key_owners, dn_owners, pair_owners, n)。"""
    with tempfile.TemporaryDirectory() as td:
        en = Path(td) / "en"
        en.mkdir()
        for wid, recs in mirrors.items():
            wjson(en / f"{wid}.json", recs)
        orig = split_sources.EN_DIR
        try:
            split_sources.EN_DIR = en
            return split_sources.load_en_evidence()
        finally:
            split_sources.EN_DIR = orig


def load_en_raw(files: dict[str, str], make_dir: bool = True):
    """以原始檔內容（可為壞 JSON）跑 load_en_evidence()，回 SystemExit 訊息或 None。"""
    with tempfile.TemporaryDirectory() as td:
        en = Path(td) / "en"
        if make_dir:
            en.mkdir()
            for name, text in files.items():
                (en / name).write_text(text, encoding="utf-8", newline="\n")
        orig = split_sources.EN_DIR
        try:
            split_sources.EN_DIR = en
            split_sources.load_en_evidence()
            return None
        except SystemExit as exc:
            return str(exc)
        finally:
            split_sources.EN_DIR = orig


def load_vanilla(doc, write_text: str | None = None):
    """以臨時 vanilla_keys.json 跑 load_vanilla_scoped()；回 pairs 或 SystemExit 訊息。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "vanilla_keys.json"
        if write_text is not None:
            p.write_text(write_text, encoding="utf-8", newline="\n")
        elif doc is not None:
            wjson(p, doc)
        orig = split_sources.VANILLA_KEYS_JSON
        try:
            split_sources.VANILLA_KEYS_JSON = p
            return split_sources.load_vanilla_scoped()
        except SystemExit as exc:
            return str(exc)
        finally:
            split_sources.VANILLA_KEYS_JSON = orig

def valid_vanilla_doc() -> dict:
    """最小但完整的 vanilla 基準：30 檔、10k+ unique pairs、keys 聯集一致。"""
    names = sorted(build_mod.VANILLA_CORE_FILES) + [
        f"Extra{i:02}.json" for i in range(20)
    ]
    scoped = {name: [f"{name}|sentinel"] for name in names}
    scoped["UI.json"].extend(f"UI_Bulk_{i:05}" for i in range(10_000))
    keys = sorted({key for values in scoped.values() for key in values})
    return {"scoped_keys": scoped, "keys": keys}


def edge_losses(
    old: object,
    new: dict[str, object],
    snap: dict[str, dict[str, str]],
    *,
    exists: bool = True,
    allow_missing: bool = False,
):
    """以臨時 attribution baseline 跑 owner_edge_losses；回 losses 或 SystemExit 訊息。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "attribution_index.json"
        if exists:
            wjson(p, old)
        try:
            return split_sources.owner_edge_losses(
                new, snap, baseline_path=p, allow_missing=allow_missing
            )
        except SystemExit as exc:
            return str(exc)

def load_registry(doc, write_text: str | None = None, exists: bool = True):
    """以臨時 mod_registry.json 跑 load_mod_registry()；回 dict 或 ValueError 訊息。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "mod_registry.json"
        if not exists:
            pass
        elif write_text is not None:
            p.write_text(write_text, encoding="utf-8", newline="\n")
        else:
            wjson(p, doc)
        try:
            return mod_registry.load_mod_registry(p)
        except ValueError as exc:
            return str(exc)


# ============================================================
# 1. translate_en 證據：單 owner / 多 owner 聯集、不依來源檔名
# ============================================================
keys, dns, epairs, n = load_en({
    "111": {rid_tr("UI_Solo"): "Solo", rid_tr("UI_Shared"): "Shared"},
    # 同鍵在不同上游檔名／有效分支：owner 仍須聯集（As1 落點與上游檔名非一對一）
    "222": {rid_tr(
        "UI_Shared", "mods/N/common/media/lua/shared/Translate/EN/Sandbox.json"
    ): "Shared"},
})
check(n == 2, f"1. 鏡像檔數應為 2，實得 {n}")
check(keys == {"UI_Solo": {"111"}, "UI_Shared": {"111", "222"}},
      f"1. translate_en 鍵→wids 聯集錯誤（可能誤用來源檔名分群）：{keys}")
check(dns == {}, f"1. 無 script 記錄時 dn_owners 應為空：{dns}")

snap = {"UI.json": {"UI_Solo": "獨", "UI_Shared": "共", "UI_None": "無"}}
r = split_sources.attribute(snap, keys, dns, epairs, set())
check(r.owners["111"]["UI.json"] == {"UI_Solo": "獨", "UI_Shared": "共"},
      f"1. 單/多 owner 內容錯誤：{dict(r.owners['111'])}")
check(r.owners["222"]["UI.json"] == {"UI_Shared": "共"},
      f"1. 多 owner 複製份缺失：{dict(r.owners['222'])}")
check(r.index["UI.json|UI_Shared"] == ["111", "222"],
      f"1. 多 owner index 未排序聯集：{r.index['UI.json|UI_Shared']}")
check(r.unsorted["UI.json"] == {"UI_None": "無"},
      f"1. 無證據鍵未落 _unsorted：{dict(r.unsorted)}")
check(r.index["UI.json|UI_None"] == split_sources.UNSORTED,
      "1. 無證據鍵的 index 未標 _unsorted")
check((r.stats["attributed"], r.stats["copies"], r.stats["unattributed"]) == (2, 3, 1),
      f"1. 統計錯誤：{dict(r.stats)}")
check(r.via["111"]["en_translate"] == 2 and r.via["111"]["en_item_dn"] == 0,
      f"1. attributed_via 分類錯誤：{dict(r.via['111'])}")

# runtime-effective 契約：common＋唯一最佳版本夾；root/dead/future/legacy txt 都不可當 owner。
EFFECTIVE_MIRROR = {
    rid_tr("UI_Common", "mods/E/common/media/lua/shared/Translate/EN/UI.json"): "C",
    rid_tr("UI_Old", "mods/E/42.19/media/lua/shared/Translate/EN/UI.json"): "O",
    rid_tr("UI_Current", "mods/E/42.20/media/lua/shared/Translate/EN/UI.json"): "N",
    rid_tr("UI_Future", "mods/E/42.21/media/lua/shared/Translate/EN/UI.json"): "F",
    rid_tr("UI_Root", "mods/E/media/lua/shared/Translate/EN/UI.json"): "R",
    rid_tr("UI_Txt", "mods/E/42.20/media/lua/shared/Translate/EN/UI_EN.txt"): "T",
}
effective_keys, _, _, _ = load_en({"777": EFFECTIVE_MIRROR})
check(effective_keys == {"UI_Common": {"777"}, "UI_Current": {"777"}},
      f"1. 非有效分支／legacy txt 被誤當 owner 證據：{effective_keys}")

# ============================================================
# 1b. 泛用鍵 title/description 檔域限定（key-only 會交叉污染每一張地圖檔）
# ============================================================
MAP_A = "mods/M/common/media/lua/shared/Translate/EN/Brandenburg, KY.json"
MAP_B = "mods/N/common/media/lua/shared/Translate/EN/Challenge Spawns.json"
MOD_JSON = "mods/P/42/media/lua/shared/Translate/EN/Mod.json"
keys, dns, epairs, _ = load_en({
    "111": {rid_tr("title", MAP_A): "Brandenburg", rid_tr("description", MAP_A): "A desc"},
    "222": {rid_tr("title", MAP_B): "Challenge Spawns"},
    # 只在 Mod.json 定義 description（實例：3781428012「Zero to Chad」）——
    # 它一個地圖檔都不該擁有
    "333": {rid_tr("description", MOD_JSON): "Mod desc"},
})
check("title" not in keys and "description" not in keys,
      f"1b. 泛用鍵仍留在 key-only 表裡（key-only 後門）：{sorted(keys)}")
check(epairs == {
          ("Brandenburg, KY", "title"): {"111"},
          ("Brandenburg, KY", "description"): {"111"},
          ("Challenge Spawns", "title"): {"222"},
          ("Mod", "description"): {"333"},
      }, f"1b. 檔域證據以 (檔名幹, 鍵) 建表錯誤：{epairs}")

snap = {
    "Brandenburg, KY.json": {"title": "布蘭登堡", "description": "甲敘述"},
    "Challenge Spawns.json": {"title": "挑戰出生點"},
    "Mod.json": {"description": "模組敘述"},
}
r = split_sources.attribute(snap, keys, dns, epairs, set())
check(r.owners["111"] == {"Brandenburg, KY.json": {"title": "布蘭登堡",
                                                  "description": "甲敘述"}},
      "1b. A 地圖 title/description 未精確歸給同名檔 owner："
      f"{ {k: dict(v) for k, v in r.owners['111'].items()} }")
check(r.owners["222"] == {"Challenge Spawns.json": {"title": "挑戰出生點"}},
      "1b. B 地圖 owner 被灌進 A 地圖檔（交叉污染）："
      f"{ {k: dict(v) for k, v in r.owners['222'].items()} }")
check(r.owners["333"] == {"Mod.json": {"description": "模組敘述"}},
      "1b. 只在 Mod.json 定義 description 的 wid 被灌進地圖檔："
      f"{ {k: dict(v) for k, v in r.owners['333'].items()} }")
check(r.index["Brandenburg, KY.json|title"] == ["111"]
      and r.index["Challenge Spawns.json|title"] == ["222"],
      f"1b. index 交叉歸屬：{ {k: v for k, v in r.index.items() if 'title' in k} }")
# 無同名檔證據的地圖檔泛用鍵必須落 _unsorted，不得靠別張地圖的證據補上
snap_orphan = {"Ekron, KY.json": {"title": "艾克隆"}}
r_orphan = split_sources.attribute(snap_orphan, keys, dns, epairs, set())
check(r_orphan.owners == {} and r_orphan.unsorted["Ekron, KY.json"] == {"title": "艾克隆"},
      f"1b. 無同名檔證據的 title 被誤歸屬：{ {k: dict(v) for k, v in r_orphan.owners.items()} }")
# 副檔名不同（上游 .txt / As1 .json）仍屬同一檔域；跨檔名一律不算
check(split_sources._file_stem("Brandenburg, KY.json") == "Brandenburg, KY"
      and split_sources._file_stem("Mod") == "Mod",
      "1b. _file_stem 去副檔名錯誤")

# ============================================================
# 2. script_item_dn 只對 ItemName.json 生效
# ============================================================
keys, dns, epairs, _ = load_en({"333": {rid_dn("Base.Widget"): "Widget"}})
check(dns == {"Base.Widget": {"333"}}, f"2. script_item_dn 證據抽取錯誤：{dns}")
check(keys == {}, f"2. script_item_dn 不得混進 translate 鍵證據：{keys}")

snap = {
    "ItemName.json": {"Base.Widget": "小工具"},
    "Tooltip.json": {"Base.Widget": "提示"},      # 同名鍵在別的檔 → 不得歸屬
    "ItemName_EN.json": {"Base.Widget": "英"},    # 近似檔名不算 ItemName.json
}
r = split_sources.attribute(snap, keys, dns, epairs, set())
check(r.owners["333"] == {"ItemName.json": {"Base.Widget": "小工具"}},
      f"2. script_item_dn 跨檔外溢：{ {k: dict(v) for k, v in r.owners['333'].items()} }")
check(r.unsorted["Tooltip.json"] == {"Base.Widget": "提示"}
      and r.unsorted["ItemName_EN.json"] == {"Base.Widget": "英"},
      f"2. 非 ItemName.json 的同名鍵未落 _unsorted：{ {k: dict(v) for k, v in r.unsorted.items()} }")
check(r.via["333"]["en_item_dn"] == 1 and r.via["333"]["en_translate"] == 0,
      f"2. en_item_dn 未計數：{dict(r.via['333'])}")

# ============================================================
# 3. legacy ItemName_<fullType> 精確去前綴；不猜 module
# ============================================================
check(split_sources._dn_fulltype("ItemName.json", "ItemName_Base.X") == "Base.X",
      "3. 前綴形未去前綴")
check(split_sources._dn_fulltype("ItemName.json", "Base.X") == "Base.X",
      "3. 裸 fullType 形被改寫")
check(split_sources._dn_fulltype("ItemName.json", "ItemName_") is None,
      "3. 空前綴殘體不得當 fullType")
check(split_sources._dn_fulltype("Tooltip.json", "Base.X") is None,
      "3. 非 ItemName.json 仍回傳 fullType")

keys, dns, epairs, _ = load_en({"444": {rid_dn("Base.Prefixed"): "P", rid_dn("?.Ghost"): "G"}})
check(dns == {"Base.Prefixed": {"444"}},
      f"3. module 未解出（?.X）不得當證據：{dns}")
snap = {"ItemName.json": {
    "ItemName_Base.Prefixed": "前綴",
    "?.Ghost": "幽靈",
    "ItemName_Other.Prefixed": "異 module",   # 不得靠 suffix 猜 module
}}
r = split_sources.attribute(snap, keys, dns, epairs, set())
check(r.owners["444"] == {"ItemName.json": {"ItemName_Base.Prefixed": "前綴"}},
      f"3. 前綴形歸屬錯誤或 suffix 猜 module：{ {k: dict(v) for k, v in r.owners['444'].items()} }")
check(set(r.unsorted["ItemName.json"]) == {"?.Ghost", "ItemName_Other.Prefixed"},
      f"3. 不可判定鍵未落 _unsorted：{sorted(r.unsorted['ItemName.json'])}")

# ============================================================
# 4. vanilla 檔域對優先於 owner 證據，且只在該檔生效
# ============================================================
vanilla_doc = valid_vanilla_doc()
vanilla_doc["scoped_keys"]["UI.json"].append("UI_Vanilla")
vanilla_doc["keys"].append("UI_Vanilla")
vanilla_doc["keys"].sort()
pairs = load_vanilla(vanilla_doc)
check(("UI.json", "UI_Vanilla") in pairs and len(pairs) > 10_000,
      f"4. 完整 scoped_keys 解析錯誤：{type(pairs).__name__}")

keys, dns, epairs, _ = load_en({"555": {
    rid_tr("UI_Vanilla"): "V", rid_dn("Base.VanillaItem"): "VI",
}})
snap = {
    "UI.json": {"UI_Vanilla": "本體"},
    "Tooltip.json": {"UI_Vanilla": "同名不同檔"},
    "ItemName.json": {"Base.VanillaItem": "本體物品"},
}
r = split_sources.attribute(
    snap, keys, dns, epairs,
    {("UI.json", "UI_Vanilla"), ("ItemName.json", "Base.VanillaItem")},
)
check("555" not in r.owners or "UI.json" not in r.owners["555"],
      "4. vanilla 命中鍵仍被歸屬（本體譯文會被 mod 覆寫）")
check(r.unsorted["UI.json"] == {"UI_Vanilla": "本體"}
      and r.unsorted["ItemName.json"] == {"Base.VanillaItem": "本體物品"},
      f"4. vanilla 命中鍵未落 _unsorted：{ {k: dict(v) for k, v in r.unsorted.items()} }")
check(r.owners["555"]["Tooltip.json"] == {"UI_Vanilla": "同名不同檔"},
      "4. vanilla 壓制外溢到別的檔（扁平鍵集語意），mod 自有同名鍵被剝奪歸屬")
check(r.stats["vanilla_excluded"] == 2, f"4. vanilla 計數錯誤：{dict(r.stats)}")

# ============================================================
# 5. 證據面 fail-closed：規模閘門可明示放行，形狀壞損不可
# ============================================================
check(split_sources.check_evidence_scale(
          split_sources.EN_FILES_MIN, 1, [], False) == [],
      "5. 正常規模被誤擋")
low = split_sources.check_evidence_scale(
    split_sources.EN_FILES_MIN - 1, 1, [], False)
check(len(low) == 1 and "下限" in low[0], f"5. 檔數不足未擋：{low}")
zero = split_sources.check_evidence_scale(
    split_sources.EN_FILES_MIN, 0, [], False)
check(len(zero) == 1 and "owner" in zero[0], f"5. 零 owner 未擋：{zero}")
lost = split_sources.check_evidence_scale(
    split_sources.EN_FILES_MIN, 1, [("UI.json|K", "111")], False)
check(len(lost) == 1 and "owner edge" in lost[0],
      f"5. 既有 owner edge 縮水未擋：{lost}")
check(split_sources.check_evidence_scale(
          1, 0, [("UI.json|K", "111")], True) == [],
      "5. --allow-low-evidence 未放行規模／owner-edge 縮水")

check(load_en_raw({}, make_dir=False) is not None,
      "5. sources/en 缺席未 fail-closed")
bad = load_en_raw({"666.json": '{"translate_en|a|K": "v",}'})   # 結尾多餘逗號
check(bad is not None and "無法解析" in bad, f"5. 壞 JSON 鏡像未 fail-closed：{bad}")
bad = load_en_raw({"666.json": '["translate_en|a|K"]'})
check(bad is not None and "頂層" in bad, f"5. 頂層形狀壞損未 fail-closed：{bad}")
bad = load_en_raw({"666.json": '{}'})
check(bad is not None and "非空物件" in bad, f"5. 空鏡像未 fail-closed：{bad}")
bad = load_en_raw({"notawid.json": '{}'})
check(bad is not None and "wid" in bad, f"5. 非 wid 檔名未 fail-closed：{bad}")
for raw, needle, why in (
    ('{"broken": "v"}', "record id", "rid 缺分隔欄"),
    ('{"translate_en||K": "v"}', "record id", "rid 空 relpath"),
    ('{"lua_literal|mods/M/42/media/x.lua|K": "v"}', "未知 kind", "未知 kind"),
    ('{"translate_en|mods/M/42.20/media/lua/shared/Translate/EN/UI.json|K": 7}',
     "值須為字串", "record 值非字串"),
):
    got = load_en_raw({"666.json": raw})
    check(got is not None and needle in got, f"5. {why} 未 fail-closed：{got}")
# 空字串是合法上游值；它仍證明 key 身分，不能與鏡像壞損混為一談。
empty_keys, _, _, empty_n = load_en({"666": {rid_tr("UI_Empty"): ""}})
check(empty_keys == {"UI_Empty": {"666"}} and empty_n == 1,
      f"5. 合法空字串值被誤判為鏡像壞損：{empty_keys}, n={empty_n}")
# 壞 JSON/rid 走 loader（無旗標參數）——`--allow-low-evidence` 架構上無法放行。
check("allow" not in (bad or ""), "5. loader 訊息不該提供形狀壞損的豁免出口")

snap_edge = {"UI.json": {"K": "值"}}
losses = edge_losses(
    {"UI.json|K": ["111", "222"], "UI.json|Retired": ["999"]},
    {"UI.json|K": ["111"]},
    snap_edge,
)
check(losses == [("UI.json|K", "222")],
      f"5. owner-edge 比對應忽略已離開 As1 的 pair、只抓仍在快照的縮水：{losses}")
check(isinstance(edge_losses({}, {}, snap_edge, exists=False), str),
      "5. attribution baseline 缺失未 fail-closed")
check(edge_losses({}, {}, snap_edge, exists=False, allow_missing=True) == [],
      "5. --allow-empty-baseline 未只放行真正缺 baseline")
check(isinstance(edge_losses({"UI.json|K": []}, {}, snap_edge), str),
      "5. attribution baseline owner 形狀壞損未 fail-closed")

valid_vanilla = valid_vanilla_doc()
invalid_vanilla: list[tuple[object, str]] = []
for missing_doc, why in (
    (None, "檔案缺失"),
    ({"keys": []}, "scoped_keys 缺失"),
    ({"scoped_keys": {}}, "scoped_keys 為空"),
):
    invalid_vanilla.append((missing_doc, why))
bad_bucket = copy.deepcopy(valid_vanilla)
bad_bucket["scoped_keys"]["UI.json"] = []
invalid_vanilla.append((bad_bucket, "核心 bucket 空陣列"))
bad_type = copy.deepcopy(valid_vanilla)
bad_type["scoped_keys"]["UI.json"] = "notalist"
invalid_vanilla.append((bad_type, "bucket 非陣列"))
bad_key = copy.deepcopy(valid_vanilla)
bad_key["scoped_keys"]["UI.json"] = [123]
invalid_vanilla.append((bad_key, "bucket 含非字串鍵"))
duplicate = copy.deepcopy(valid_vanilla)
duplicate["scoped_keys"]["UI.json"].append(duplicate["scoped_keys"]["UI.json"][0])
invalid_vanilla.append((duplicate, "bucket 內重複鍵"))
missing_core = copy.deepcopy(valid_vanilla)
missing_core["scoped_keys"].pop("ItemName.json")
invalid_vanilla.append((missing_core, "核心檔缺失"))
few_files = copy.deepcopy(valid_vanilla)
few_files["scoped_keys"] = {
    k: v for k, v in few_files["scoped_keys"].items()
    if k in build_mod.VANILLA_CORE_FILES
}
invalid_vanilla.append((few_files, "檔案數不足"))
few_pairs = valid_vanilla_doc()
few_pairs["scoped_keys"]["UI.json"] = ["UI.json|sentinel"]
few_pairs["keys"] = sorted({
    key for values in few_pairs["scoped_keys"].values() for key in values
})
invalid_vanilla.append((few_pairs, "pair 量級不足"))
keys_drift = copy.deepcopy(valid_vanilla)
keys_drift["keys"].pop()
invalid_vanilla.append((keys_drift, "keys 聯集漂移"))
for doc, why in invalid_vanilla:
    got = load_vanilla(doc)
    check(isinstance(got, str), f"5. vanilla {why} 未 fail-closed：{got!r}")
got = load_vanilla(None, write_text='{"scoped_keys": {,}}')
check(isinstance(got, str) and "無法解析" in got, f"5. vanilla 壞 JSON 未 fail-closed：{got!r}")

# ============================================================
# 6. registry schema ＋ serialize 只吃 active 的 metadata facts
# ============================================================
GOOD = {
    "_comment": "說明",
    "mods": {
        "111": {"status": "active", "source": "人工登記", "verified": "2026-08-30",
                "name": "Alpha", "mod_ids": ["AlphaMod"], "note": "備註"},
        "222": {"status": "retired", "source": "人工登記", "verified": "2026-08-30",
                "name": "Beta", "mod_ids": ["BetaMod"]},
        "333": {"status": "active", "source": "人工登記", "verified": "2026-08-30",
                "future_field": {"any": "shape"}},   # 未知欄位放行
    },
}
reg = load_registry(GOOD)
check(isinstance(reg, dict) and set(reg) == {"111", "222", "333"},
      f"6. 合法名冊解析錯誤（retired 須照樣回傳）：{reg}")
check(reg["111"] == GOOD["mods"]["111"] and reg["333"] == GOOD["mods"]["333"],
      f"6. entry 未原樣回傳（欄位被改名／未知欄位被丟）：{reg}")
# 缺檔 fail-closed：名冊已是人工真相＋registry-only 監看的唯一保底，回空集會讓
# 「被誤刪／路徑寫錯」與「真的一個 mod 都沒有」不可區分（watchlist 靜默縮回衍生集）
missing = load_registry(None, exists=False)
check(isinstance(missing, str), f"6. 缺檔未 fail-closed（回了 {missing!r}）")
if isinstance(missing, str):
    check("缺檔" in missing and "mod_registry.json" in missing,
          f"6. 缺檔訊息未帶路徑／缺檔字樣（tracker 直接轉印它）：{missing}")

for doc, needle, why in (
    ({"mods": {"abc": {"status": "active", "source": "s", "verified": "v"}}},
     "abc", "wid 非純數字"),
    ({"mods": {"111": ["notadict"]}}, "111", "entry 非物件"),
    ({"mods": {"111": {"status": "active", "verified": "v"}}}, "source", "缺 source"),
    ({"mods": {"111": {"status": "active", "source": "s"}}}, "verified", "缺 verified"),
    ({"mods": {"111": {"status": "active", "source": " ", "verified": "v"}}},
     "source", "source 空白"),
    ({"mods": {"111": {"status": "unknown", "source": "s", "verified": "v"}}},
     "status", "status 非法值"),
    ({"mods": {"111": {"status": "active", "source": "s", "verified": "v", "name": 5}}},
     "name", "name 非字串"),
    ({"mods": {"111": {"status": "active", "source": "s", "verified": "v",
                       "mod_ids": "A"}}}, "mod_ids", "mod_ids 非陣列"),
    ({"mods": {"111": {"status": "active", "source": "s", "verified": "v",
                       "mod_ids": [""]}}}, "mod_ids", "mod_ids 含空項"),
    ({"mods": {}}, "mods", "mods 空物件"),
    ({"mods": []}, "mods", "mods 非物件"),
    ([], "頂層", "頂層非物件"),
):
    got = load_registry(doc)
    check(isinstance(got, str), f"6. {why} 未 raise ValueError：{got!r}")
    if isinstance(got, str):
        check(needle in got, f"6. {why} 的錯誤訊息未指出 `{needle}`：{got}")
got = load_registry(None, write_text='{"mods": {,}}')
check(isinstance(got, str) and "無法解析" in got, f"6. 壞 JSON 未 raise ValueError：{got!r}")

keys, dns, epairs, _ = load_en({
    "111": {rid_tr("UI_A"): "A"},
    "222": {rid_tr("UI_B"): "B"},
    "333": {rid_tr("UI_C"): "C"},
    "999": {rid_tr("UI_D"): "D"},
})
snap = {"UI.json": {"UI_A": "甲", "UI_B": "乙", "UI_C": "丙", "UI_D": "丁"}}
r = split_sources.attribute(snap, keys, dns, epairs, set())
out = split_sources.serialize(r, reg)
meta111 = json.loads(out["mods/111/metadata.json"].decode("utf-8"))
check(meta111["name"] == "Alpha" and meta111["mod_ids"] == ["AlphaMod"],
      f"6. active 條目的 name/mod_ids 未進 metadata：{meta111}")
check(meta111["attributed_via"] == {"en_translate": 1, "en_item_dn": 0},
      f"6. attributed_via 欄位名/計數錯誤：{meta111['attributed_via']}")
check(set(meta111) == {"workshop_id", "mod_ids", "key_count", "files",
                       "attributed_via", "name"},
      f"6. metadata 欄位集漂移：{sorted(meta111)}")
meta222 = json.loads(out["mods/222/metadata.json"].decode("utf-8"))
check("name" not in meta222 and meta222["mod_ids"] == [],
      f"6. retired 條目不得供 split metadata：{meta222}")
meta333 = json.loads(out["mods/333/metadata.json"].decode("utf-8"))
check("name" not in meta333 and meta333["mod_ids"] == [],
      f"6. active 但缺 name/mod_ids 未安全降級：{meta333}")
meta999 = json.loads(out["mods/999/metadata.json"].decode("utf-8"))
check("name" not in meta999 and meta999["mod_ids"] == [],
      f"6. 名冊未收錄的 owner 未安全降級：{meta999}")

# ============================================================
# 7. 完整性自檢 ＋ 排序冪等
# ============================================================
keys, dns, epairs, _ = load_en({
    "111": {rid_tr("UI_Shared"): "S", rid_dn("Base.Item"): "I"},
    "222": {rid_tr("UI_Shared"): "S"},
})
snap = {
    "UI.json": {"UI_Shared": "共", "UI_Free": "無"},
    "ItemName.json": {"Base.Item": "物", "ItemName_Base.Item": "前綴物"},
    "Empty.json": {},                        # As1 佔位空檔須仍產出
    "Sandbox.json": {"Sandbox_V": "本體"},
}
vanilla = {("Sandbox.json", "Sandbox_V")}
r1 = split_sources.attribute(snap, keys, dns, epairs, vanilla)
out1 = split_sources.serialize(r1, reg)
check(split_sources.check_completeness(out1, snap) == [],
      f"7. 完整性自檢誤報：{split_sources.check_completeness(out1, snap)}")
check("_unsorted/CN/Empty.json" in out1, "7. As1 佔位空檔未產出（逐檔 parity 會破）")

r2 = split_sources.attribute(snap, keys, dns, epairs, vanilla)
out2 = split_sources.serialize(r2, reg)
check(out1 == out2, "7. 兩次拆分 byte 不一致（存在非確定性迭代）")
check(split_sources.outputs_hash(out1) == split_sources.outputs_hash(out2),
      "7. outputs_hash 非冪等")
# 打亂輸入 dict 的插入序：歸屬與序列化必須逐 byte 不變（全程 sorted 迭代）
shuffled_snap = {k: {kk: snap[k][kk] for kk in reversed(list(snap[k]))}
                 for k in reversed(list(snap))}
shuffled_keys = {k: set(keys[k]) for k in reversed(list(keys))}
out3 = split_sources.serialize(
    split_sources.attribute(shuffled_snap, shuffled_keys, dns, epairs, vanilla), reg)
check(out1 == out3, "7. 產出對輸入插入序敏感（定序 bug）")

# 完整性自檢必須真的抓得到缺鍵／多鍵／值不一致
broken = dict(out1)
broken["_unsorted/CN/UI.json"] = b'{}'
check(any("缺少" in e for e in split_sources.check_completeness(broken, snap)),
      "7. 完整性自檢抓不到缺鍵")
broken = dict(out1)
broken["_unsorted/CN/UI.json"] = json.dumps(
    {"UI_Free": "無", "UI_Extra": "多"}, ensure_ascii=False).encode("utf-8")
check(any("多出" in e for e in split_sources.check_completeness(broken, snap)),
      "7. 完整性自檢抓不到多鍵")
broken = dict(out1)
broken["mods/222/CN/UI.json"] = json.dumps(
    {"UI_Shared": "歧異"}, ensure_ascii=False).encode("utf-8")
check(any("不一致" in e for e in split_sources.check_completeness(broken, snap)),
      "7. 完整性自檢抓不到複製份值歧異")

# ============================================================
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：")
    for m in FAILED:
        print(f"  - {m}")
    sys.exit(1)
print("✅ test_split_attribution：evidence-first 歸屬 + registry schema 全部通過")
