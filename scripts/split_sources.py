# /// script
# requires-python = ">=3.10"
# ///
"""
MinidoracatModLangFor42 拆分管線（PZ B42 如一模組翻譯繁中版）

用途：把 As1 CN 快照（釘定於 sources/snapshot.json）依 **repo 自有第一手鍵證據**，
      拆成「每 MOD 一目錄」的受版控衍生佈局：
        sources/mods/<workshop_id>/CN/<原檔名>.json + metadata.json
        sources/_unsorted/CN/<原檔名>.json（無證據 → 未歸屬）
        sources/attribution_index.json（(檔|鍵) → owner ids 或 "_unsorted"）
        sources/ch_sync_worklist.json（CN 樹新增/變更/移除鍵 → CH 翻譯待辦，翻譯後移除）

真相模型：
  - As1 CN 快照 = canonical import（唯一內容事實）。
  - **歸屬證據只有 `sources/en/<wid>.json`**（追蹤器自上游 MOD 本體抽出的第一手語料）：
      * runtime-effective `.json` `translate_en|<相對路徑>|<鍵>` → 該 wid 的現行 B42
        Translate 檔定義此鍵；B41 `.txt`、mod 根 `media/`、舊版／未來分支一律不是證據。
        一般鍵取 `鍵 → {wid}` 聯集，不依來源檔名（As1 落點與上游檔名並非一對一）。
        **例外：`SCOPED_GENERIC_KEYS`（`title`/`description`）是檔域限定**——它們是
        「每個地圖／描述檔各有一份」的泛用鍵名，key-only 聯集會把「定義過任一張地圖
        title 的 wid」交叉灌給每一張地圖檔，故只認來源 Translate 檔名（去副檔名）與
        As1 落點檔名相同的證據。
      * `script_item_dn|<script 路徑>|<fullType>` → 該 wid 的 script 定義過這個物品；
        **僅對 `ItemName.json` 生效**（引擎只在此以裸 `Module.Item` 查物品名），
        並精確支援 legacy `ItemName_<fullType>` 去前綴。module 未解出（`?.X`）不算證據。
  - `sources/mod_registry.json` **不是鍵歸屬證據**，只提供 metadata facts（name/mod_ids）；
    但它是人工真相，缺檔／壞 schema 一律 fail-closed（`mod_registry.load_mod_registry`
    raise ValueError，本腳本印訊息後退出 1，不以空名冊繼續）。
  - `sources/vanilla_keys.json` 的 `scoped_keys` 以 **(檔名, 鍵) 檔域對**優先壓過 owner：
    命中即遊戲本體鍵，一律落 `_unsorted`，不得掛給任何 mod。
  - 歸屬 identity = (相對檔名, 鍵, CN值)；多重歸屬 = 複製到全部 owner 目錄，
    去重延後至 build（消除定序敏感性）。
  - 最終 gate 是逐檔 parity（verify_dist.py）；本腳本內建完整性自檢確保
    owner + _unsorted 聯集去重後 == As1 快照，一個不多一個不少、值逐字一致。

演算法確定性且冪等：所有迭代排序後進行、owner 清單排序、序列化以 sort_keys 正規化，
重跑 byte-identical。

證據面 fail-closed：`sources/en` 缺席、空鏡像、壞 JSON/rid/kind/value，
`vanilla_keys.json` 完整 schema 壞損、CH corpus 缺／空一律拒跑（無豁免旗標）；
鏡像檔數低於 EN_FILES_MIN、歸屬 owner 為零、或仍在本次 As1 快照的既有 owner edge
縮水，須以 `--allow-low-evidence` 明示接受。後者區分「上游真的退場」與「證據靜默消失」；
沒有閘門時兩者都只會留下看似完整、其實大量落 `_unsorted` 的綠燈產物。

使用方式：uv run scripts/split_sources.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import mod_registry
from build_mod import _vanilla_basis_problem
from tracker import is_effective, resolve_effective_branches

# ============================================================
# 路徑配置
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES = PROJECT_ROOT / "sources"
SNAPSHOT_JSON = SOURCES / "snapshot.json"
MODS_DIR = SOURCES / "mods"
UNSORTED_CN = SOURCES / "_unsorted" / "CN"
ATTR_INDEX_JSON = SOURCES / "attribution_index.json"
WORKLIST_JSON = SOURCES / "ch_sync_worklist.json"
WORKLIST_COMMENT = (
    "As1 同步 worklist：split_sources.py 於 CN 樹有新增/變更/移除鍵時寫入。"
    "逐條翻譯落 sources/ch 後移除條目；本檔含未處理條目時 build/verify 拒絕出貨。"
)

# 歸屬證據面（repo 自有，非外部 helper）
EN_DIR = SOURCES / "en"
VANILLA_KEYS_JSON = SOURCES / "vanilla_keys.json"

# EN 鏡像檔數下限。低於此值＝證據面大規模缺失，須明示放行。
EN_FILES_MIN = 400

# script_item_dn 證據只作用於這個落點檔（引擎以裸 fullType 查此表）
ITEMNAME_FILE = "ItemName.json"
ITEMNAME_PREFIX = "ItemName_"  # B41 遺留前綴形，去前綴後才是 fullType

# **檔域限定鍵**：地圖／mod 描述檔用的裸鍵 `title`／`description` 在上游是「每個
# Translate 檔各有一份」的泛用鍵名，key-only 聯集會把「定義過任一張地圖 title 的 wid」
# 交叉灌給**每一張**地圖檔（實測 3781428012「Zero to Chad」只在 Mod.json 定義
# description，卻被灌進 30+ 個地圖檔而讓 manifest 摘要失真）。故這兩鍵只認
# 「來源 Translate 檔名（去副檔名）與 As1 落點檔名精確相同」的檔域證據。
SCOPED_GENERIC_KEYS = frozenset({"title", "description"})

UNSORTED = "_unsorted"  # attribution_index 中未歸屬的標記值


# ============================================================
# 通用 I/O：讀容忍 BOM；寫確定性正規化（與 build_mod.py write_json 同語意）
# ============================================================
def load_json(path: Path) -> dict:
    """讀 JSON（容忍 utf-8-sig BOM）。"""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def dumps_canonical(data) -> str:
    """確定性序列化：UTF-8（呼叫端 encode）、indent 2、鍵排序、LF、尾端換行。"""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ============================================================
# 讀入 As1 CN 快照
# ============================================================
def load_as1_snapshot() -> tuple[dict[str, dict[str, str]], Path]:
    """依 snapshot.json 釘定的 As1 路徑讀 CN/*.json。回傳 ({原檔名: {鍵: CN值}}, As1 CN 目錄)。"""
    snap = load_json(SNAPSHOT_JSON)
    as1 = snap["as1"]
    cn_dir = (
        Path(as1["local_path"])
        / as1["source_tree"]
        / "media"
        / "lua"
        / "shared"
        / "Translate"
        / "CN"
    )
    if not cn_dir.is_dir():
        print(f"❌ As1 CN 目錄不存在：{cn_dir}", file=sys.stderr)
        sys.exit(1)

    out: dict[str, dict[str, str]] = {}
    for jf in sorted(cn_dir.glob("*.json")):
        data = load_json(jf)
        # 只保留字串值（PZ 翻譯檔為 flat {鍵: 字串}）；值逐字保留不動。
        out[jf.name] = {str(k): v for k, v in data.items()}
    return out, cn_dir


# ============================================================
# 快照釘定：As1 逐檔 sha256 manifest
# ============================================================
def write_as1_manifest(cn_dir: Path) -> Path:
    """寫出 sources/as1_manifest.json：As1 CN 來源逐檔 raw sha256（供獨立 oracle 驗 As1 漂移）。"""
    manifest = {
        jf.name: hashlib.sha256(jf.read_bytes()).hexdigest()
        for jf in sorted(cn_dir.glob("*.json"))
    }
    path = SOURCES / "as1_manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


# ============================================================
# 讀入歸屬證據（sources/en 第一手鍵證據 + vanilla 檔域基準）
# ============================================================
def _file_stem(name: str) -> str:
    """`Brandenburg, KY.json` → `Brandenburg, KY`（去單層副檔名；無副檔名原樣回）。"""
    return name.rsplit(".", 1)[0] if "." in name else name


def load_en_evidence() -> tuple[
    dict[str, set[str]], dict[str, set[str]], dict[tuple[str, str], set[str]], int
]:
    """讀 `sources/en/<wid>.json`，回 (鍵→wids, fullType→wids, (檔名幹,鍵)→wids, 鏡像檔數)。

    三張證據表**互斥**，讓誤用在結構上不可能發生：
      * 鍵→wids       — runtime-effective `.json` 的 `translate_en`，排除泛用鍵；
      * (檔名幹,鍵)→wids — 上述 `translate_en` 中只有 `SCOPED_GENERIC_KEYS`；
      * fullType→wids  — runtime-effective `script_item_dn`（只作用於 `ItemName.json`）。

    fail-closed（無豁免）：目錄缺席、檔名非數字 wid、JSON/頂層壞形、空鏡像、
    rid 非 `kind|relpath|key`、未知 kind、非字串值一律拒跑。合法無 text-bearing
    corpus 由 tracker 表達為「沒有鏡像檔」，不是 `{}`。
    """
    if not EN_DIR.is_dir():
        raise SystemExit(
            f"❌ 歸屬證據目錄不存在：{EN_DIR}——先跑 tracker 刷新 sources/en 鏡像"
        )
    key_owners: dict[str, set[str]] = defaultdict(set)
    dn_owners: dict[str, set[str]] = defaultdict(set)
    pair_owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    n_files = 0
    for jf in sorted(EN_DIR.glob("*.json")):
        wid = jf.stem
        if not wid.isdigit():
            raise SystemExit(f"❌ sources/en/{jf.name} 檔名非純數字 wid——證據來源不明")
        try:
            recs = load_json(jf)
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"❌ sources/en/{jf.name} 無法解析：{exc}") from exc
        if not isinstance(recs, dict) or not recs:
            raise SystemExit(
                f"❌ sources/en/{jf.name} 頂層須為非空物件，實得 "
                f"{type(recs).__name__}（合法空語料不應保留鏡像檔）"
            )
        n_files += 1
        effective = resolve_effective_branches(recs)
        for rid, value in recs.items():
            if not isinstance(rid, str):
                raise SystemExit(f"❌ sources/en/{jf.name} 含非字串 record id：{rid!r}")
            parts = rid.split("|", 2)
            if len(parts) != 3 or not all(parts):
                raise SystemExit(f"❌ sources/en/{jf.name} record id 形狀壞損：{rid!r}")
            kind, relpath, key = parts
            if kind not in {"translate_en", "script_item_dn"}:
                raise SystemExit(f"❌ sources/en/{jf.name} 含未知 kind `{kind}`：{rid!r}")
            if not isinstance(value, str):
                raise SystemExit(
                    f"❌ sources/en/{jf.name} 的 {rid!r} 值須為字串，"
                    f"實得 {type(value).__name__}"
                )
            if not is_effective(rid, effective):
                continue
            if kind == "translate_en":
                if key in SCOPED_GENERIC_KEYS:
                    stem = _file_stem(relpath.rsplit("/", 1)[-1])
                    if not stem:
                        raise SystemExit(f"❌ sources/en/{jf.name} 泛用鍵缺來源檔名：{rid!r}")
                    pair_owners[(stem, key)].add(wid)
                else:
                    key_owners[key].add(wid)
            elif not key.startswith("?."):
                # module 未解出不是證據；禁止依 suffix 猜 module。
                dn_owners[key].add(wid)
    return dict(key_owners), dict(dn_owners), dict(pair_owners), n_files


def load_vanilla_scoped() -> set[tuple[str, str]]:
    """`vanilla_keys.json` 的 `scoped_keys` → {(檔名, 鍵)}。schema 不符即 fail-closed。

    用檔域對而非扁平鍵集：扁平集會把「某 mod 的 Tooltip 鍵與本體某檔同名」誤判成
    本體鍵而剝奪歸屬。本體鍵不得掛給任何 mod，故它優先於一切 owner 證據。
    """
    if not VANILLA_KEYS_JSON.is_file():
        raise SystemExit(
            f"❌ vanilla 檔域基準不存在：{VANILLA_KEYS_JSON}"
            "——先跑 scripts/extract_vanilla_keys.py"
        )
    try:
        doc = load_json(VANILLA_KEYS_JSON)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"❌ {VANILLA_KEYS_JSON.name} 無法解析：{exc}") from exc
    if not isinstance(doc, dict):
        raise SystemExit(
            f"❌ {VANILLA_KEYS_JSON.name} 頂層須為物件，實得 {type(doc).__name__}"
        )
    if problem := _vanilla_basis_problem(doc):
        raise SystemExit(
            f"❌ {VANILLA_KEYS_JSON.name} 基準不可信：{problem}。"
            "遊戲更新後請跑 scripts/extract_vanilla_keys.py 重生"
        )
    scoped = doc["scoped_keys"]
    pairs: set[tuple[str, str]] = set()
    for fname in sorted(scoped):
        pairs.update((fname, key) for key in scoped[fname])
    return pairs


def check_evidence_scale(
    n_en_files: int, n_owners: int, lost_edges: list[tuple[str, str]], allow_low: bool
) -> list[str]:
    """證據規模閘門：回傳阻斷原因（空＝放行）。

    壞 JSON/rid/schema 在 loader 已無豁免地炸掉；本函式只處理可由
    `--allow-low-evidence` 明示接受的規模／既有 owner-edge 縮水。
    """
    reasons: list[str] = []
    if n_en_files < EN_FILES_MIN:
        reasons.append(
            f"sources/en 只有 {n_en_files} 檔（下限 {EN_FILES_MIN}）"
            "——證據面大規模缺失，歸屬結果不可信"
        )
    if n_owners == 0:
        reasons.append("零個 owner 目錄——全樹將落 _unsorted，與「證據全滅」不可區分")
    if lost_edges:
        sample = ", ".join(f"{pair}→{wid}" for pair, wid in lost_edges[:5])
        reasons.append(
            f"{len(lost_edges)} 條既有 owner edge 將消失（例：{sample}）"
            "——上游退場或證據縮水都屬 destructive attribution 變更"
        )
    if reasons and allow_low:
        return []
    return reasons


def owner_edge_losses(
    new_index: dict[str, object],
    snap: dict[str, dict[str, str]],
    baseline_path: Path = ATTR_INDEX_JSON,
    allow_missing: bool = False,
) -> list[tuple[str, str]]:
    """比較仍在本次 As1 快照內的既有 `(pair,wid)`；任何縮水需明示接受。"""
    if not baseline_path.is_file():
        if allow_missing:
            return []
        raise SystemExit(
            f"❌ 缺少既有 attribution baseline：{baseline_path}——"
            "無法判斷本次是否會靜默刪除 owner；真正首次拆分才可搭配 --allow-empty-baseline"
        )
    old = load_json(baseline_path)
    if not isinstance(old, dict):
        raise SystemExit(f"❌ {baseline_path} 頂層須為物件")
    valid_pairs = {f"{fname}|{key}" for fname, values in snap.items() for key in values}

    def edges(index: dict[str, object]) -> set[tuple[str, str]]:
        out: set[tuple[str, str]] = set()
        for pair, owners in index.items():
            if not isinstance(pair, str) or not all(pair.partition("|")[::2]):
                raise SystemExit(f"❌ attribution_index 的 pair 形狀壞損：{pair!r}")
            if owners == UNSORTED:
                continue
            if not (
                isinstance(owners, list) and owners
                and all(isinstance(w, str) and w.isdigit() for w in owners)
                and len(set(owners)) == len(owners)
            ):
                raise SystemExit(f"❌ attribution_index 的 {pair!r} owner 形狀壞損：{owners!r}")
            if pair in valid_pairs:
                out.update((pair, wid) for wid in owners)
        return out

    return sorted(edges(old) - edges(new_index))


# ============================================================
# 歸屬演算法（確定性）
# ============================================================
class Attribution:
    """一次拆分的邏輯結果（純資料，序列化前）。"""

    def __init__(self) -> None:
        # ws → 檔名 → {鍵: 值}
        self.owners: dict[str, dict[str, dict[str, str]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        # 檔名 → {鍵: 值}
        self.unsorted: dict[str, dict[str, str]] = defaultdict(dict)
        # "檔名|鍵" → [ws...] 或 "_unsorted"
        self.index: dict[str, object] = {}
        # ws → Counter(en_translate/en_item_dn)
        self.via: dict[str, Counter] = defaultdict(Counter)
        self.stats: Counter = Counter()


def _dn_fulltype(fname: str, key: str) -> str | None:
    """把 As1 落點 (檔名, 鍵) 還原成 script_item_dn 的 fullType；不適用回 None。

    只有 `ItemName.json` 會被引擎以裸 `Module.Item` 查詢；legacy `ItemName_<fullType>`
    是 B41 遺留前綴形，去前綴後才對得上證據。兩種形都精確比對，絕不猜 module。
    """
    if fname != ITEMNAME_FILE:
        return None
    if key.startswith(ITEMNAME_PREFIX):
        bare = key[len(ITEMNAME_PREFIX):]
        return bare or None
    return key


def attribute(
    snap: dict[str, dict[str, str]],
    en_key_owners: dict[str, set[str]],
    en_dn_owners: dict[str, set[str]],
    en_pair_owners: dict[tuple[str, str], set[str]],
    vanilla_pairs: set[tuple[str, str]],
) -> Attribution:
    """對每個 (檔名, 鍵, 值) 依第一手 EN 證據決定 owner 集合。排序後迭代，確定性。

    `SCOPED_GENERIC_KEYS`（`title`/`description`）走 `en_pair_owners` 的檔域證據
    （來源 Translate 檔名去副檔名須與 As1 落點檔名相同）；其餘鍵維持 key-only 聯集。
    """
    r = Attribution()
    for fname in sorted(snap):
        fmap = snap[fname]
        # As1 佔位空檔（0 鍵）也須保留檔案本身，維持 dist 的逐檔 parity
        if not fmap:
            _ = r.unsorted[fname]  # defaultdict：登記為空檔輸出
            continue
        for key in sorted(fmap):
            val = fmap[key]
            idx_key = f"{fname}|{key}"
            r.stats["total"] += 1

            # vanilla 檔域命中 → 本體鍵，強制 _unsorted（優先於一切 owner 證據）
            if (fname, key) in vanilla_pairs:
                r.unsorted[fname][key] = val
                r.index[idx_key] = UNSORTED
                r.stats["vanilla_excluded"] += 1
                continue

            if key in SCOPED_GENERIC_KEYS:
                # 泛用鍵名：只認同名檔的證據，不吃 key-only 聯集（交叉污染來源）
                tr = en_pair_owners.get((_file_stem(fname), key)) or set()
            else:
                tr = en_key_owners.get(key) or set()
            ft = _dn_fulltype(fname, key)
            dn = (en_dn_owners.get(ft) or set()) if ft else set()
            cands = tr | dn

            if not cands:
                r.unsorted[fname][key] = val
                r.index[idx_key] = UNSORTED
                r.stats["unattributed"] += 1
                continue

            owner_list = sorted(cands)
            for ws in owner_list:
                r.owners[ws][fname][key] = val
                # 逐 ws 分類：translate_en 勝過 script_item_dn（引擎先查 ItemName map，
                # 查不到才退回 Item.getDisplayName()，同 prep_mod_strings 的來源優先序）
                r.via[ws]["en_translate" if ws in tr else "en_item_dn"] += 1
            r.index[idx_key] = owner_list
            r.stats["attributed"] += 1
            r.stats["copies"] += len(owner_list)

            # filekey 層級來源歸類（報告用；同優先序）
            r.stats["fk_en_translate" if tr else "fk_en_item_dn"] += 1
    return r


# ============================================================
# 序列化為 {sources 下相對路徑: bytes}（純函式，冪等自檢用）
# ============================================================
def serialize(r: Attribution, registry: dict[str, dict]) -> dict[str, bytes]:
    """產出 {sources 下相對路徑: bytes}。

    metadata 的 name/mod_ids 取自 mod_registry 的 **active** 條目（純 metadata facts，
    非歸屬證據）；缺條目／缺欄位安全降級為空，不影響歸屬與 parity。
    """
    out: dict[str, bytes] = {}
    for ws in sorted(r.owners):
        files = r.owners[ws]
        for fname in sorted(files):
            rel = f"mods/{ws}/CN/{fname}"
            out[rel] = dumps_canonical(files[fname]).encode("utf-8")
        key_count = sum(len(m) for m in files.values())
        entry = registry.get(ws) or {}
        active = entry.get("status") == "active"
        mod_ids = entry.get("mod_ids") if active else None
        meta = {
            "workshop_id": ws,
            "mod_ids": list(mod_ids) if isinstance(mod_ids, list) else [],
            "key_count": key_count,
            "files": sorted(files),
            "attributed_via": {
                "en_translate": r.via[ws]["en_translate"],
                "en_item_dn": r.via[ws]["en_item_dn"],
            },
        }
        name = entry.get("name") if active else None
        if isinstance(name, str) and name:
            meta["name"] = name
        out[f"mods/{ws}/metadata.json"] = dumps_canonical(meta).encode("utf-8")

    for fname in sorted(r.unsorted):
        out[f"_unsorted/CN/{fname}"] = dumps_canonical(r.unsorted[fname]).encode("utf-8")

    out["attribution_index.json"] = dumps_canonical(r.index).encode("utf-8")
    return out


# ============================================================
# 硬性自檢：完整性（parity 前哨）
# ============================================================
def check_completeness(
    out: dict[str, bytes], snap: dict[str, dict[str, str]]
) -> list[str]:
    """owner + _unsorted 的所有 CN (檔,鍵,值) 聯集去重後須 == As1 快照。回傳錯誤清單。"""
    errors: list[str] = []
    recon: dict[tuple[str, str], str] = {}
    for rel, data in out.items():
        parts = rel.split("/")
        if rel.startswith("mods/") and len(parts) == 4 and parts[2] == "CN":
            fname = parts[3]
        elif rel.startswith("_unsorted/CN/") and len(parts) == 3:
            fname = parts[2]
        else:
            continue  # metadata.json / attribution_index.json 不算 CN 內容
        for key, val in json.loads(data.decode("utf-8")).items():
            rk = (fname, key)
            if rk in recon:
                # 多重歸屬的複製份必須逐字一致（同源同值）
                if recon[rk] != val:
                    errors.append(f"複製份值不一致：{fname}|{key}")
            else:
                recon[rk] = val

    snapmap: dict[tuple[str, str], str] = {}
    for fname, fmap in snap.items():
        for key, val in fmap.items():
            snapmap[(fname, key)] = val

    missing = snapmap.keys() - recon.keys()
    extra = recon.keys() - snapmap.keys()
    if missing:
        errors.append(f"聯集缺少 {len(missing)} 個 (檔,鍵)，例：{sorted(missing)[:5]}")
    if extra:
        errors.append(f"聯集多出 {len(extra)} 個 (檔,鍵)，例：{sorted(extra)[:5]}")
    mismatched = [
        rk for rk in (snapmap.keys() & recon.keys()) if snapmap[rk] != recon[rk]
    ]
    if mismatched:
        errors.append(f"{len(mismatched)} 個 (檔,鍵) 值與快照不一致，例：{sorted(mismatched)[:5]}")
    return errors


# ============================================================
# 寫出（清空本腳本擁有的產出區，保證冪等；勿動 lua/ 與 snapshot.json）
# 例外：metadata.json 標 origin:"own" 的原創翻譯 mod 目錄為人工真相，
#       不屬 As1 衍生產出，重跑 split 必須保留（無 origin 欄位＝As1 衍生）
# ============================================================
def _own_mod_wids() -> set[str]:
    """列出 sources/mods 下 origin=='own' 的目錄名（原創翻譯 mod）。"""
    wids: set[str] = set()
    if not MODS_DIR.is_dir():
        return wids
    for child in MODS_DIR.iterdir():
        meta = child / "metadata.json"
        if child.is_dir() and meta.is_file():
            try:
                if json.loads(meta.read_text(encoding="utf-8-sig")).get("origin") == "own":
                    wids.add(child.name)
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"無法解析 {meta}：{exc}") from exc
    return wids


def write_outputs(out: dict[str, bytes]) -> None:
    own_wids = _own_mod_wids()
    as1_owners = {rel.split("/")[1] for rel in out if rel.startswith("mods/")}
    collision = own_wids & as1_owners
    if collision:
        raise SystemExit(
            f"原創 mod 與 As1 歸屬結果撞 workshop id：{sorted(collision)}——"
            "As1 已收錄該 mod，請依退役規則處理原創目錄後重跑"
        )
    if MODS_DIR.exists():
        for child in sorted(MODS_DIR.iterdir()):
            if child.name in own_wids:
                continue
            # 只刪「可證明為 split 產出」的目錄（metadata 含 attributed_via 且非 own）；
            # 無法歸類（metadata 缺失/壞損/schema 不符）一律 fail-loud——
            # 靜默刪除會無聲毀掉人工資料且後續 build/verify 全綠（codex review 隔離重現）
            is_split_generated = False
            meta_path = child / "metadata.json"
            if child.is_dir() and meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
                    is_split_generated = (
                        "attributed_via" in meta and meta.get("origin") != "own"
                    )
                except (OSError, json.JSONDecodeError):
                    is_split_generated = False
            if not (child.is_dir() and is_split_generated):
                raise SystemExit(
                    f"sources/mods/{child.name} 無法判別來源"
                    "（metadata 缺失/壞損，既非 split 產出亦非 origin:'own'）——"
                    "拒絕刪除以免誤毀人工資料，請人工確認後重跑"
                )
            shutil.rmtree(child)
    if UNSORTED_CN.exists():
        shutil.rmtree(UNSORTED_CN)
    if ATTR_INDEX_JSON.exists():
        ATTR_INDEX_JSON.unlink()
    for rel, data in sorted(out.items()):
        p = SOURCES / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def outputs_hash(out: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in sorted(out):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(out[rel])
    return h.hexdigest()


# ============================================================
# CH sync worklist：CN 樹層級差異 → 翻譯待辦
# （斷絕 OpenCC 後 CH 不再機轉跟進，上游變更必須逐鍵人工/AI 直譯落 sources/ch；
#   本節在覆寫 CN 樹前 diff 舊有效值，把新增/變更/移除鍵登記到 worklist，
#   build/verify 於 worklist 未清空時拒絕出貨。）
# ============================================================
def load_existing_cn() -> dict[tuple[str, str], str]:
    """讀現行 CN 樹（As1 衍生目錄＋_unsorted，排除 own）的 {(檔名, 鍵): 值}。

    多重歸屬複製份值一致（前次 split 完整性自檢保證），first-wins 即可。
    """
    result: dict[tuple[str, str], str] = {}
    own = _own_mod_wids()
    dirs: list[Path] = []
    if MODS_DIR.is_dir():
        for child in sorted(MODS_DIR.iterdir()):
            if child.is_dir() and child.name not in own:
                cn = child / "CN"
                if cn.is_dir():
                    dirs.append(cn)
    if UNSORTED_CN.is_dir():
        dirs.append(UNSORTED_CN)
    for d in dirs:
        for jf in sorted(d.glob("*.json")):
            for key, val in load_json(jf).items():
                result.setdefault((jf.name, key), val)
    return result


def cn_from_outputs(out: dict[str, bytes]) -> dict[tuple[str, str], str]:
    """從 serialize 產出還原 {(檔名, 鍵): 值}（只取 mods/*/CN 與 _unsorted/CN）。"""
    result: dict[tuple[str, str], str] = {}
    for rel, data in out.items():
        parts = rel.split("/")
        if rel.startswith("mods/") and len(parts) == 4 and parts[2] == "CN":
            fname = parts[3]
        elif rel.startswith("_unsorted/CN/") and len(parts) == 3:
            fname = parts[2]
        else:
            continue
        for key, val in json.loads(data.decode("utf-8")).items():
            result.setdefault((fname, key), val)
    return result


def _registry_keys() -> set[str]:
    """cn_overrides / placeholder_exceptions 的登記鍵集（worklist 標註 overridden 用）。

    登記鍵的 As1 原值在 build 期會被 registry 取代，不會出貨——worklist 條目標上
    overridden 供譯者辨識，避免對著不出貨的原值翻譯。
    """
    keys: set[str] = set()
    for name in ("cn_overrides.json", "placeholder_exceptions.json"):
        p = SOURCES / name
        if p.exists():
            keys |= {k for k in load_json(p) if "|" in k}
    return keys


def _corpus_keysets() -> dict[str, set[str]]:
    """讀 sources/ch/*.json 的逐檔鍵集；人工真相缺／空／壞形一律 fail-closed。"""
    out: dict[str, set[str]] = {}
    ch_dir = SOURCES / "ch"
    if not ch_dir.is_dir():
        raise SystemExit(f"❌ CH corpus 目錄不存在：{ch_dir}")
    files = sorted(ch_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"❌ CH corpus 目錄沒有任何 JSON：{ch_dir}")
    for jf in files:
        data = load_json(jf)
        if not isinstance(data, dict):
            raise SystemExit(f"❌ CH corpus {jf} 頂層須為物件")
        out[jf.name] = set(data)
    return out


def _parse_worklist_entry(entry_key: str, spec) -> tuple[str, str, str]:
    """驗證並回 `(kind, fname, key)`；壞真相不得進入自動清除路徑。"""
    fname, sep, key = entry_key.partition("|")
    if (
        not sep or len(fname) <= len(".json") or not fname.endswith(".json")
        or "/" in fname or "\\" in fname or not key
    ):
        raise SystemExit(f"❌ ch_sync_worklist.json entry key 形狀壞損：{entry_key!r}")
    if not isinstance(spec, dict):
        raise SystemExit(f"❌ ch_sync_worklist.json 的 {entry_key!r} 規格須為物件")
    kind = spec.get("kind")
    required = {
        "added": ("new_cn",),
        "removed": ("old_cn",),
        "changed": ("old_cn", "new_cn"),
    }
    if kind not in required:
        raise SystemExit(
            f"❌ ch_sync_worklist.json 的 {entry_key!r} kind 非法：{kind!r}"
        )
    missing = [field for field in required[kind] if not isinstance(spec.get(field), str)]
    if missing:
        raise SystemExit(
            f"❌ ch_sync_worklist.json 的 {entry_key!r} 缺字串欄位：{missing}"
        )
    return kind, fname, key


def _entry_satisfied(entry_key: str, spec, corpus_keys: dict[str, set[str]]) -> bool:
    """added 已落同名 corpus 檔／removed 已自同名 corpus 檔移除才算滿足。

    缺整個 corpus 檔不是「removed 完成」；那是人工真相遺失，必須保留待辦並由 gate 擋下。
    changed 一律未滿足（值層變更無法自動判定已複核，須人工移除條目）。
    """
    kind, fname, key = _parse_worklist_entry(entry_key, spec)
    if fname not in corpus_keys:
        return False
    present = key in corpus_keys[fname]
    return (kind == "added" and present) or (kind == "removed" and not present)


def update_sync_worklist(
    old: dict[tuple[str, str], str], new: dict[tuple[str, str], str]
) -> int:
    """CN 差異（added/changed/removed）合併進 worklist；回傳本次新增/更新條目數。

    既有未滿足條目保留（同鍵以新差異覆蓋）、已滿足條目自動清除（對帳，
    見 _entry_satisfied）；不含 | 的說明欄（_comment 等）原樣保留。
    old 為空時跳過差異登記——注意這**只在真正首次拆分時安全**：若既有樹被
    清除後重跑，changed 差異將無法偵測（main() 以 --allow-empty-baseline 把關）。
    """
    if not old:
        print(
            "  ⚠️ --allow-empty-baseline：無既有 CN 樹，跳過 worklist 差異登記"
            "（本次 changed 類差異無法偵測）。"
        )
        return 0
    delta: dict[str, dict] = {}
    for fk in sorted(new.keys() - old.keys()):
        delta[f"{fk[0]}|{fk[1]}"] = {"kind": "added", "new_cn": new[fk]}
    for fk in sorted(old.keys() - new.keys()):
        delta[f"{fk[0]}|{fk[1]}"] = {"kind": "removed", "old_cn": old[fk]}
    for fk in sorted(old.keys() & new.keys()):
        if old[fk] != new[fk]:
            delta[f"{fk[0]}|{fk[1]}"] = {
                "kind": "changed", "old_cn": old[fk], "new_cn": new[fk],
            }
    corpus_keys = _corpus_keysets()
    doc: dict = {}
    if WORKLIST_JSON.exists():
        existing = load_json(WORKLIST_JSON)
        if not isinstance(existing, dict):
            raise SystemExit("❌ ch_sync_worklist.json 頂層須為物件")
        for k, v in existing.items():
            if "|" not in k:
                doc[k] = v  # _comment / 人工加註的說明欄保留
            elif not _entry_satisfied(k, v, corpus_keys):
                doc[k] = v
    doc["_comment"] = WORKLIST_COMMENT  # 說明文字以最新常數為準
    doc.update(delta)
    # overridden 旗標對「全部」條目統一重算（含既有存活條目）：
    # 鍵進出 registry 時旗標跟著更新，不殘留過時標記
    registered = _registry_keys()
    for wkey, spec in doc.items():
        if "|" not in wkey or not isinstance(spec, dict):
            continue
        if wkey in registered:
            spec["overridden"] = True  # As1 原值被 registry 取代，出貨值以登記為準
        else:
            spec.pop("overridden", None)
    WORKLIST_JSON.write_text(dumps_canonical(doc), encoding="utf-8", newline="\n")
    return len(delta)


# ============================================================
# 主流程
# ============================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="As1 CN 快照 → per-mod 拆分（sources/en 第一手證據歸屬）"
    )
    parser.add_argument(
        "--allow-empty-baseline",
        action="store_true",
        help="明示允許在無既有 CN 樹時執行（僅限真正首次拆分；changed 差異將無法偵測）",
    )
    parser.add_argument(
        "--allow-low-evidence",
        action="store_true",
        help="明示放行證據**規模**不足（EN 鏡像檔數低於下限／零 owner）；"
             "不放行壞 JSON 或 schema 不符",
    )
    args = parser.parse_args()

    print("=" * 64)
    print("split_sources：As1 CN 快照 → per-mod 佈局 + _unsorted + attribution_index")
    print("=" * 64)

    snap, cn_dir = load_as1_snapshot()
    print(f"As1 CN 來源：{cn_dir}")
    print(f"  讀入 {len(snap)} 檔")

    en_key_owners, en_dn_owners, en_pair_owners, n_en_files = load_en_evidence()
    vanilla_pairs = load_vanilla_scoped()
    try:
        registry = mod_registry.load_mod_registry()
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    active_wids = {w for w, e in registry.items() if e.get("status") == "active"}
    print(
        f"  歸屬證據：sources/en {n_en_files} 檔、translate 鍵 {len(en_key_owners)}、"
        f"item_dn fullType {len(en_dn_owners)}、檔域限定 "
        f"{'/'.join(sorted(SCOPED_GENERIC_KEYS))} 對 {len(en_pair_owners)}；"
        f"vanilla 檔域對 {len(vanilla_pairs)}"
    )
    print(
        f"  mod_registry：active {len(active_wids)} / 全 {len(registry)}"
        "（僅 metadata facts，不參與歸屬）"
    )

    # 歸屬 + 序列化（跑兩次做冪等自檢：兩次 byte-dict 必須相等）
    result = attribute(snap, en_key_owners, en_dn_owners, en_pair_owners, vanilla_pairs)
    out = serialize(result, registry)
    result2 = attribute(snap, en_key_owners, en_dn_owners, en_pair_owners, vanilla_pairs)
    out2 = serialize(result2, registry)
    idempotent = out == out2

    # 完整性自檢
    errors = check_completeness(out, snap)

    if errors or not idempotent:
        print("\n❌ 自檢失敗，未寫出任何檔案：")
        if not idempotent:
            print("  - 冪等自檢失敗：兩次產出 byte 不一致（存在非確定性迭代）")
        for e in errors:
            print(f"  - {e}")
        return 1

    # destructive 歸屬縮水閘門：仍在 As1 的 pair 若失去既有 owner edge，必須明示接受。
    lost_edges = owner_edge_losses(
        result.index, snap, allow_missing=args.allow_empty_baseline
    )
    scale_errors = check_evidence_scale(
        n_en_files, len(result.owners), lost_edges, args.allow_low_evidence
    )
    if scale_errors:
        print("\n❌ 證據規模不足，未寫出任何檔案：", file=sys.stderr)
        for e in scale_errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "   確認證據面現況正確（例：上游全數退場）時，以 --allow-low-evidence 明示放行。",
            file=sys.stderr,
        )
        return 1
    if args.allow_low_evidence:
        print("  ⚠️ --allow-low-evidence：證據規模／owner-edge 縮水已明示接受。")
        if lost_edges:
            print(f"      本次接受移除 {len(lost_edges)} 條既有 owner edge。")

    old_cn = load_existing_cn()
    if not old_cn and not args.allow_empty_baseline:
        print(
            "❌ 既有 CN 樹為空。若樹曾被清除，本次 changed 差異將無法偵測\n"
            "   （鍵集 gate 只攔 added/removed，值變更會靜默漏接）。\n"
            "   請先 `git restore sources/mods sources/_unsorted` 還原舊樹再重跑；\n"
            "   確為首次拆分時，以 --allow-empty-baseline 明示跳過。",
            file=sys.stderr,
        )
        return 1
    # worklist 先於樹覆寫落地：中斷時最壞是「worklist 已登記、樹未更新」，
    # gate 會擋、重跑冪等；反向順序會在中斷後永久遺失差異（舊樹已被覆寫）。
    n_delta = update_sync_worklist(old_cn, cn_from_outputs(out))
    write_outputs(out)
    manifest_path = write_as1_manifest(cn_dir)

    # ---- 拆分報告 ----
    st = result.stats
    total = st["total"]
    attributed = st["attributed"]
    unattributed = st["unattributed"]
    vanilla_excluded = st["vanilla_excluded"]
    unsorted_total = unattributed + vanilla_excluded
    coverage = attributed / total * 100 if total else 0.0
    print("\n" + "-" * 64)
    print("拆分報告")
    print("-" * 64)
    print(f"  總 (檔,鍵) 數        : {total}")
    print(f"  已歸屬 (檔,鍵)       : {attributed}（覆蓋率 {coverage:.1f}%）")
    print(f"  複製總份數           : {st['copies']}（多重歸屬複製到全部 owner）")
    print(f"  未歸屬 → _unsorted   : {unsorted_total}")
    print(f"      ├ vanilla 排除   : {vanilla_excluded}")
    print(f"      └ 無 EN 證據     : {unattributed}")
    print(f"  owner 目錄數         : {len(result.owners)}")
    print("  各來源貢獻（filekey 層級，translate_en 勝過 script_item_dn）：")
    print(f"      en_translate     : {st['fk_en_translate']}")
    print(f"      en_item_dn       : {st['fk_en_item_dn']}")
    print(f"  EN 證據面            : {n_en_files} 檔 / translate {len(en_key_owners)} 鍵"
          f" / item_dn {len(en_dn_owners)} fullType"
          f" / 檔域限定 {len(en_pair_owners)} 對")
    zero_attr = sorted(active_wids - set(result.owners), key=int)
    if zero_attr:
        print(
            f"  registry active 但零歸屬 : {len(zero_attr)} 個 wid"
            "（新收錄尚未進 As1、或上游無我方可歸屬的鍵）"
        )
        print(f"      {', '.join(zero_attr[:20])}{' …' if len(zero_attr) > 20 else ''}")
    print(f"  產出檔案數           : {len(out)}（含 metadata.json ×{len(result.owners)} + attribution_index.json）")
    print(f"  產出 sha256          : {outputs_hash(out)}")
    print(f"  As1 逐檔 sha256 manifest : {manifest_path.relative_to(PROJECT_ROOT)}（{len(snap)} 檔）")
    if n_delta:
        print(
            f"  ⚠️ sync worklist 新增/更新 {n_delta} 條 → sources/ch_sync_worklist.json"
            "（對照 EN＋術語表翻譯落 sources/ch 後移除條目，build 才會放行）"
        )
    print("\n✅ 自檢通過（完整性 + 冪等），已寫出 sources/mods、sources/_unsorted/CN、attribution_index.json、as1_manifest.json。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
