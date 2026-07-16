# /// script
# requires-python = ">=3.10"
# ///
"""
MinidoracatModLangFor42 拆分管線（PZ B42 如一模組翻譯繁中版）

用途：把 As1 CN 快照（釘定於 sources/snapshot.json）依 helper 歸屬候選鏈，
      拆成「每 MOD 一目錄」的受版控衍生佈局：
        sources/mods/<workshop_id>/CN/<原檔名>.json + metadata.json
        sources/_unsorted/CN/<原檔名>.json（用盡候選仍未歸屬）
        sources/attribution_index.json（(檔|鍵) → owner ids 或 "_unsorted"）

真相模型：
  - As1 CN 快照 = canonical import（唯一事實）。
  - helper 的 key_source_* 5 檔「只提供候選 owner，非歸屬事實」。
  - 歸屬 identity = (相對檔名, 鍵, CN值)；多重歸屬 = 複製到全部候選 owner 目錄，
    去重延後至 build（消除定序敏感性）。
  - 最終 gate 是逐檔 parity（verify_dist.py）；本腳本內建完整性自檢確保
    owner + _unsorted 聯集去重後 == As1 快照，一個不多一個不少、值逐字一致。

演算法確定性且冪等：所有迭代排序後進行、owner 清單排序、序列化以 sort_keys 正規化，
重跑 byte-identical。

使用方式：uv run scripts/split_sources.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

# ============================================================
# 路徑配置
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES = PROJECT_ROOT / "sources"
SNAPSHOT_JSON = SOURCES / "snapshot.json"
MODS_DIR = SOURCES / "mods"
UNSORTED_CN = SOURCES / "_unsorted" / "CN"
ATTR_INDEX_JSON = SOURCES / "attribution_index.json"

# helper 本地 checkout（snapshot.json 只釘 git SHA，不釘本地路徑）。可用 --helper-dir 覆寫。
DEFAULT_HELPER_DIR = Path("D:/github/pz-mod-translation-helper/translation_utils")

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
# 快照釘定：helper git SHA 比對 + As1 逐檔 sha256 manifest
# ============================================================
def helper_git_sha(helper_dir: Path) -> str | None:
    """回傳 helper checkout 的 HEAD commit SHA；取不到（非 git repo / 無 git）回傳 None。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(helper_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return proc.stdout.strip()


def check_helper_pin(helper_dir: Path, allow_drift: bool) -> int:
    """比對 helper HEAD 與 snapshot.json 釘定的 helper.git_sha。

    不符即 fail（回傳 1，未跑拆分）；--allow-drift 則跳過檢查並把 snapshot 的 git_sha/pulled_at
    更新為現況（回傳 0）。相符或已在 allow_drift 下更新 → 回傳 0。
    """
    snap = load_json(SNAPSHOT_JSON)
    pinned = snap.get("helper", {}).get("git_sha")
    actual = helper_git_sha(helper_dir)

    if allow_drift:
        if actual is None:
            print("  ⚠️ --allow-drift：無法取得 helper HEAD（非 git repo？），snapshot 未更新。")
        elif actual != pinned:
            snap.setdefault("helper", {})["git_sha"] = actual
            snap["helper"]["pulled_at"] = date.today().isoformat()
            # 保留原鍵序（勿 sort_keys），只就地換值。
            SNAPSHOT_JSON.write_text(
                json.dumps(snap, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            print(f"  ⚠️ --allow-drift：snapshot helper.git_sha {pinned} → {actual}")
        else:
            print(f"  helper 釘定相符（{pinned[:12]}…），--allow-drift 無需更新。")
        return 0

    if actual is None:
        print(
            f"❌ 無法取得 helper HEAD（git -C {helper_dir} rev-parse HEAD 失敗）。\n"
            f"   請確認 helper 為 git checkout；或以 --allow-drift 跳過釘定檢查。",
            file=sys.stderr,
        )
        return 1
    if actual != pinned:
        print(
            f"❌ helper 漂移：snapshot 釘定 {pinned} 但 HEAD 為 {actual}。\n"
            f"   請將 helper checkout 切回釘定 commit，或以 --allow-drift 更新 snapshot 後重跑。",
            file=sys.stderr,
        )
        return 1
    print(f"  helper 釘定相符（{pinned[:12]}…）")
    return 0


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
# 讀入 helper 歸屬候選鏈（只提供候選，非事實）
# ============================================================
def load_map_index(helper_dir: Path) -> dict[str, set[str]]:
    """key_source_map.json（{ws: {翻譯鍵: 類型}}）反轉為 {翻譯鍵: {ws...}}。主候選來源。"""
    data = load_json(helper_dir / "key_source_map.json")
    index: dict[str, set[str]] = defaultdict(set)
    for ws, key_types in data.items():
        for key in key_types:
            index[key].add(ws)
    return index


def load_mod_index(helper_dir: Path) -> dict[str, set[str]]:
    """key_source_mod.json（{json字串化[鍵,英文值]: [ws...]}）→ {鍵: union(ws...)}。候選補充。"""
    data = load_json(helper_dir / "key_source_mod.json")
    index: dict[str, set[str]] = defaultdict(set)
    for key_str, ids in data.items():
        bare = json.loads(key_str)[0]  # tuple 首元素 = 翻譯鍵；同鍵多 tuple → union ids
        index[bare].update(ids)
    return index


def load_vanilla_keys(helper_dir: Path) -> set[str]:
    """key_source_vanilla.json 的鍵集合。命中者屬遊戲本體 → 一律排除歸屬、直接落 _unsorted。"""
    return set(load_json(helper_dir / "key_source_vanilla.json").keys())


def load_manual(helper_dir: Path) -> dict[str, list[str]]:
    """人工補正（優先級最高）。

    註：helper 的 key_source_map_manual.json 與 key_source_regex_overrides.json
    實為「鍵→類型/檔名」路由層（KeyPrefix / FileNameReplace / source 改寫），
    與「鍵→workshop_id 歸屬」是不同維度，且本腳本已逐實體檔案迭代（已知檔名），
    故其類型路由對歸屬無作用。此處只收「值為 workshop_id 清單」形狀的條目作 ws 歸屬覆寫；
    helper 現況無此形狀 → 回傳空，manual 貢獻為 0（見拆分報告 NOTE）。
    """
    p = helper_dir / "key_source_map_manual.json"
    if not p.exists():
        return {}
    raw = load_json(p)
    manual: dict[str, list[str]] = {}
    for key, val in raw.items():
        if isinstance(val, list) and val and all(
            isinstance(x, str) and x.isdigit() for x in val
        ):
            manual[key] = sorted(set(val))
    return manual


def load_ws_to_modids(helper_dir: Path) -> dict[str, list[str]]:
    """workshop_id_to_mod_id_map.json（{ws: [mod_id...]}）。metadata.mod_ids 用。"""
    p = helper_dir / "workshop_id_to_mod_id_map.json"
    if not p.exists():
        return {}
    return {ws: list(ids) for ws, ids in load_json(p).items()}


def load_ws_to_name(helper_dir: Path) -> dict[str, str]:
    """mod_id_name_map.json（{ws: {name, ...}}）→ {ws: name}。metadata.name 用（build manifest 顯示）。"""
    p = helper_dir / "mod_id_name_map.json"
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for ws, meta in load_json(p).items():
        if isinstance(meta, dict) and meta.get("name"):
            out[ws] = meta["name"]
    return out


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
        # ws → Counter(manual/map/mod_tuple)
        self.via: dict[str, Counter] = defaultdict(Counter)
        self.stats: Counter = Counter()


def attribute(
    snap: dict[str, dict[str, str]],
    map_index: dict[str, set[str]],
    mod_index: dict[str, set[str]],
    vanilla: set[str],
    manual: dict[str, list[str]],
) -> Attribution:
    """對每個 (檔名, 鍵, 值) 決定 owner 集合。排序後迭代，確定性。"""
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

            # vanilla 命中 → 不歸屬（即使有候選也強制 _unsorted，避免誤歸屬）
            if key in vanilla:
                r.unsorted[fname][key] = val
                r.index[idx_key] = UNSORTED
                r.stats["vanilla_excluded"] += 1
                continue

            # 候選解析：manual（最高優先、獨佔）→ else map ∪ mod tuple
            mp: set[str] | None = None
            if key in manual:
                cands: set[str] = set(manual[key])
                kind = "manual"
            else:
                mp = map_index.get(key)
                md = mod_index.get(key)
                cands = set()
                if mp:
                    cands |= mp
                if md:
                    cands |= md
                kind = None

            if not cands:
                r.unsorted[fname][key] = val
                r.index[idx_key] = UNSORTED
                r.stats["unattributed"] += 1
                continue

            owner_list = sorted(cands)
            for ws in owner_list:
                r.owners[ws][fname][key] = val
                # 逐 ws 分類 attributed_via（該 mod 是經哪個來源成為 owner）
                if kind == "manual":
                    r.via[ws]["manual"] += 1
                elif mp and ws in mp:
                    r.via[ws]["map"] += 1
                else:
                    r.via[ws]["mod_tuple"] += 1
            r.index[idx_key] = owner_list
            r.stats["attributed"] += 1
            r.stats["copies"] += len(owner_list)

            # filekey 層級來源歸類（報告用；優先序 manual > map > mod_tuple）
            if kind == "manual":
                r.stats["fk_manual"] += 1
            elif mp:
                r.stats["fk_map"] += 1
            else:
                r.stats["fk_mod_tuple"] += 1
    return r


# ============================================================
# 序列化為 {sources 下相對路徑: bytes}（純函式，冪等自檢用）
# ============================================================
def serialize(
    r: Attribution,
    ws_to_modids: dict[str, list[str]],
    ws_to_name: dict[str, str],
) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for ws in sorted(r.owners):
        files = r.owners[ws]
        for fname in sorted(files):
            rel = f"mods/{ws}/CN/{fname}"
            out[rel] = dumps_canonical(files[fname]).encode("utf-8")
        key_count = sum(len(m) for m in files.values())
        meta = {
            "workshop_id": ws,
            "mod_ids": ws_to_modids.get(ws, []),
            "key_count": key_count,
            "files": sorted(files),
            "attributed_via": {
                "manual": r.via[ws]["manual"],
                "map": r.via[ws]["map"],
                "mod_tuple": r.via[ws]["mod_tuple"],
            },
        }
        name = ws_to_name.get(ws)
        if name:
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
# ============================================================
def write_outputs(out: dict[str, bytes]) -> None:
    if MODS_DIR.exists():
        shutil.rmtree(MODS_DIR)
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
# 主流程
# ============================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="As1 CN 快照 → per-mod 拆分")
    parser.add_argument(
        "--helper-dir",
        type=Path,
        default=DEFAULT_HELPER_DIR,
        help="helper translation_utils 目錄（預設本機 checkout）",
    )
    parser.add_argument(
        "--allow-drift",
        action="store_true",
        help="跳過 helper git SHA 釘定檢查，並把 snapshot.json 的 git_sha/pulled_at 更新為現況",
    )
    args = parser.parse_args()
    helper_dir: Path = args.helper_dir

    print("=" * 64)
    print("split_sources：As1 CN 快照 → per-mod 佈局 + _unsorted + attribution_index")
    print("=" * 64)

    if not helper_dir.is_dir():
        print(f"❌ helper 目錄不存在：{helper_dir}", file=sys.stderr)
        return 1

    # 快照釘定：helper HEAD 須與 snapshot.json 的 helper.git_sha 相符（--allow-drift 跳過並更新）
    if check_helper_pin(helper_dir, args.allow_drift) != 0:
        return 1

    snap, cn_dir = load_as1_snapshot()
    print(f"As1 CN 來源：{cn_dir}")
    print(f"  讀入 {len(snap)} 檔")

    map_index = load_map_index(helper_dir)
    mod_index = load_mod_index(helper_dir)
    vanilla = load_vanilla_keys(helper_dir)
    manual = load_manual(helper_dir)
    ws_to_modids = load_ws_to_modids(helper_dir)
    ws_to_name = load_ws_to_name(helper_dir)
    print(
        f"  歸屬候選：map 反查 {len(map_index)} 鍵、mod tuple 反查 {len(mod_index)} 鍵、"
        f"vanilla {len(vanilla)} 鍵、manual {len(manual)} 鍵"
    )
    if not manual:
        print(
            "  NOTE: helper 的 key_source_map_manual.json / key_source_regex_overrides.json "
            "為「鍵→類型/檔名」路由層，非 workshop_id 歸屬，對本拆分無作用（manual 貢獻 0）。"
        )

    # 歸屬 + 序列化（跑兩次做冪等自檢：兩次 byte-dict 必須相等）
    result = attribute(snap, map_index, mod_index, vanilla, manual)
    out = serialize(result, ws_to_modids, ws_to_name)
    result2 = attribute(snap, map_index, mod_index, vanilla, manual)
    out2 = serialize(result2, ws_to_modids, ws_to_name)
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
    print(f"  複製總份數           : {st['copies']}（多重歸屬複製到全部候選 owner）")
    print(f"  未歸屬 → _unsorted   : {unsorted_total}")
    print(f"      ├ vanilla 排除   : {vanilla_excluded}")
    print(f"      └ 用盡候選無歸屬 : {unattributed}")
    print(f"  owner 目錄數         : {len(result.owners)}")
    print("  各來源貢獻（filekey 層級，優先序 manual>map>mod_tuple）：")
    print(f"      manual           : {st['fk_manual']}")
    print(f"      key_source_map   : {st['fk_map']}")
    print(f"      key_source_mod   : {st['fk_mod_tuple']}")
    print(f"  產出檔案數           : {len(out)}（含 metadata.json ×{len(result.owners)} + attribution_index.json）")
    print(f"  產出 sha256          : {outputs_hash(out)}")
    print(f"  As1 逐檔 sha256 manifest : {manifest_path.relative_to(PROJECT_ROOT)}（{len(snap)} 檔）")
    print("\n✅ 自檢通過（完整性 + 冪等），已寫出 sources/mods、sources/_unsorted/CN、attribution_index.json、as1_manifest.json。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
