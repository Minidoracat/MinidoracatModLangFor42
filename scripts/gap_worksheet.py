# /// script
# requires-python = ">=3.10"
# ///
"""補譯工作單產生器：把某個 mod 的「Lua 確證可見缺口」抽成可直接翻譯的清單。

用途：`tracker.py coverage` 只給數字，這支給**逐鍵的 EN 原文**與落地前的三道查核，
是 own_translations 補譯流程的固定第一步。

    uv run scripts/gap_worksheet.py <workshop_id> [--out 檔案]

輸出（JSON）：
    todo      需自行翻譯的鍵（含上游 EN）
    official  本體官方已有對照者（沿用官方譯名，不自行發明）
    skipped   上游 EN 為空／命中 vanilla 鍵集者（附原因）

「Lua 確證可見」＝該 mod 的 Lua 真的 getText 取這個鍵，優先序高於「在上游 EN 檔
裡但未必用到」的鍵。vanilla 碰撞對 `sources/vanilla_keys.json` 與本機官方
Translate/EN 雙重檢查——收錄鐵律：vanilla 鍵 override 一律不收。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker  # noqa: E402 — 共用 B42 有效分支解析，避免兩支各自實作而分岔

ROOT = Path(__file__).resolve().parent.parent
BASE_GAME = Path("D:/SteamLibrary/steamapps/common/ProjectZomboid/media/lua/shared/Translate")
KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _stem(basename: str) -> str:
    s = basename.rsplit(".", 1)[0]
    for suf in ("_EN", "_CN", "_CH"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def _jload(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def shipped_keys() -> set[str]:
    """我方已出貨的鍵，同時收原形與去前綴形（Lua 寫完整鍵、EN 檔可能寫任一種）。"""
    out: set[str] = set()

    def take(basename: str, keys) -> None:
        st = _stem(basename)
        for k in keys:
            out.add(k)
            out.add(k[len(st) + 1:] if st and k.startswith(st + "_") else k)
            if st:
                out.add(f"{st}_{k}")

    mods = ROOT / "sources/mods"
    for wid in os.listdir(mods):
        cn = mods / wid / "CN"
        if cn.is_dir():
            for jf in cn.glob("*.json"):
                take(jf.name, _jload(jf))
    uns = ROOT / "sources/_unsorted/CN"
    if uns.is_dir():
        for jf in uns.glob("*.json"):
            take(jf.name, _jload(jf))
    for fname, entries in _jload(ROOT / "sources/own_translations.json")["entries"].items():
        take(fname, entries)
    return out


def vanilla_keys() -> set[str]:
    raw = set(_jload(ROOT / "sources/vanilla_keys.json")["keys"])
    van = raw | {k.split("_", 1)[1] for k in raw if "_" in k}
    # 第二道：本機官方安裝實檔（vanilla_keys.json 可能落後遊戲更新）
    if BASE_GAME.is_dir():
        for jf in (BASE_GAME / "EN").glob("*.json"):
            try:
                van |= set(_jload(jf))
            except Exception:  # noqa: BLE001 — 官方檔壞掉不該擋住工作單
                pass
    return van


def official_map() -> dict[str, tuple[str, str]]:
    """本體官方 EN 值 → (官方鍵, 官方繁中)。技能/職業/特質名須以官方譯名為準。"""
    out: dict[str, tuple[str, str]] = {}
    if not BASE_GAME.is_dir():
        return out
    for name in ("UI.json", "IG_UI.json", "ItemName.json", "ContextMenu.json", "Tooltip.json"):
        en_p, ch_p = BASE_GAME / "EN" / name, BASE_GAME / "CH" / name
        if not (en_p.is_file() and ch_p.is_file()):
            continue
        try:
            en, ch = _jload(en_p), _jload(ch_p)
        except Exception:  # noqa: BLE001
            continue
        for k, v in en.items():
            if isinstance(v, str) and k in ch and isinstance(ch[k], str) and v.strip():
                out.setdefault(v.strip().lower(), (k, ch[k]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="產生某 mod 的補譯工作單")
    ap.add_argument("workshop_id")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    wid = args.workshop_id

    state = _jload(ROOT / "tracker-state/en_corpus_hashes.json")["mods"]
    if wid not in state:
        print(f"❌ tracker 無 {wid} 的基準，先跑 backfill-en", file=sys.stderr)
        return 1
    recs = state[wid]["records"]
    # 只取引擎真的會載入的分支（common ＋ 唯一最佳版本夾），且 EN 必須來自 .json。
    # 抽取器收全部分支，但拿舊版本夾／mod 根 media/ 的鍵去補譯＝死資料，
    # 更糟的是舊分支可能用已改名或語意不同的鍵，會直接譯錯。規則出處見 tracker.py。
    eff = tracker.resolve_effective_branches(recs)

    en_text: dict[str, str] = {}
    en_file: dict[str, str] = {}
    lua: set[str] = set()
    for rid, _h in recs.items():
        if not tracker.is_effective(rid, eff):
            continue
        kind, _, rest = rid.partition("|")
        rel, _, key = rest.partition("|")
        if kind == "lua_gettext" and KEY_RE.match(key) and not key.endswith("_"):
            lua.add(key)
        elif kind == "translate_en":
            en_file[key] = os.path.basename(rel)
    # EN 原文取自鏡像（狀態檔只有 hash）
    mirror = ROOT / "sources/en" / f"{wid}.json"
    if mirror.is_file():
        for rid, v in _jload(mirror).items():
            if not tracker.is_effective(rid, eff):
                continue
            kind, _, rest = rid.partition("|")
            _, _, key = rest.partition("|")
            if kind == "translate_en" and isinstance(v, str):
                en_text[key] = v

    ship, van, off = shipped_keys(), vanilla_keys(), official_map()
    todo, official, skipped = [], [], []
    for k in sorted(lua - ship):
        if k in van:
            skipped.append({"key": k, "reason": "vanilla 鍵（收錄鐵律不得 override）"})
            continue
        if k not in en_text:
            skipped.append({"key": k, "reason": "上游未定義此鍵（上游 bug，遊戲顯示鍵名）"})
            continue
        ev = en_text[k]
        if not ev.strip():
            skipped.append({"key": k, "reason": "上游 EN 為空，無從翻譯"})
            continue
        row = {"key": k, "en": ev, "file": en_file.get(k, "?")}
        hit = off.get(ev.strip().lower())
        if hit:
            official.append({**row, "official_key": hit[0], "official_ch": hit[1]})
        else:
            todo.append(row)
    out = {"workshop_id": wid, "todo": todo, "official": official, "skipped": skipped}
    p = Path(args.out) if args.out else ROOT / f".omc/tmp/gap_{wid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    by = collections.Counter(s["reason"] for s in skipped)
    print(f"{wid}：待譯 {len(todo)}／官方有對照 {len(official)}／跳過 {len(skipped)} {dict(by)}")
    print(f"→ {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
