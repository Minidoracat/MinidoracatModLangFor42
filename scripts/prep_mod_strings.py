# /// script
# requires-python = ">=3.11"
# ///
"""把一或多個 mod 的有效缺口抽成「相異字串清單」，供補譯流程使用。

    uv run scripts/prep_mod_strings.py <wid> [<wid> ...] --out <檔案>

與 `gap_worksheet.py` 的差別：後者只提「Lua 確證可見」的鍵（getText 現場），
本支提**所有落點檔對得上的有效鍵**——物品名走專用 getter、不經 getText，
`coverage_survey.py` 揭露那才是缺口主體（62% 在 ItemName）。

輸出每項：
    en / keys（連動出貨鍵數）/ files（落點檔）/ key_samples / wid
並附 `_gap`：`"<落點檔>|<鍵>" -> en`，落地時用它把譯文展開回所有鍵。

有效性判準見 tracker.resolve_effective_branches：`common` ＋唯一最佳版本夾。
此處**只濾分支不濾副檔名**——`_EN.txt` 的鍵在執行期沒有 EN 定義，但我方譯文
照樣生效（Translator 按鍵查譯文），把它們算進缺口才對。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker  # noqa: E402
from coverage_survey import DIST_CH, target_file  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def branch_ok(rid: str, eff: dict[str, set[str]]) -> bool:
    _, _, rest = rid.partition("|")
    relpath, _, _ = rest.partition("|")
    parts = relpath.split("/")
    if len(parts) < 3 or parts[0] != "mods":
        return True
    return parts[2] in eff.get(parts[1], set())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wids", nargs="+")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    shipped = {f"{p[:-5]}|{k}"
               for p in os.listdir(DIST_CH) if p.endswith(".json")
               for k in _jload(DIST_CH / p)}
    vraw = set(_jload(ROOT / "sources/vanilla_keys.json")["keys"])
    vanilla = vraw | {k.split("_", 1)[1] for k in vraw if "_" in k}
    state = _jload(ROOT / "tracker-state/en_corpus_hashes.json")["mods"]

    gap: dict[str, tuple[str, str]] = {}   # "<file>|<key>" -> (en, wid)
    for wid in args.wids:
        if wid not in state:
            print(f"⚠ {wid} 無 tracker 基準，跳過", file=sys.stderr)
            continue
        eff = tracker.resolve_effective_branches(state[wid]["records"])
        mirror_p = ROOT / "sources/en" / f"{wid}.json"
        if not mirror_p.is_file():
            print(f"⚠ {wid} 無 sources/en 鏡像，跳過", file=sys.stderr)
            continue
        for rid, val in _jload(mirror_p).items():
            kind, _, rest = rid.partition("|")
            relpath, _, key = rest.partition("|")
            if kind != "translate_en" or key in vanilla:
                continue
            if not isinstance(val, str) or not val.strip() or not branch_ok(rid, eff):
                continue
            tgt = target_file(os.path.basename(relpath).rsplit(".", 1)[0], key)
            if tgt and f"{tgt}|{key}" not in shipped:
                gap.setdefault(f"{tgt}|{key}", (val, wid))

    by_en: dict[str, list[str]] = collections.defaultdict(list)
    wid_of: dict[str, set[str]] = collections.defaultdict(set)
    for fk, (en, wid) in gap.items():
        by_en[en].append(fk)
        wid_of[en].add(wid)
    rows = [{"en": en,
             "keys": len(fks),
             "files": sorted({f.split("|")[0] for f in fks}),
             "key_samples": sorted(f.split("|", 1)[1] for f in fks)[:4],
             "wid": sorted(wid_of[en])}
            for en, fks in by_en.items()]
    rows.sort(key=lambda r: (r["wid"][0], r["key_samples"][0]))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"strings": rows, "_gap": {k: v[0] for k, v in gap.items()}},
                  f, ensure_ascii=False, indent=1)
    print(f"{len(gap)} 鍵 → {len(rows)} 條相異字串"
          f"（重複率 {(1 - len(rows) / max(len(gap), 1)) * 100:.1f}%）→ {out}")
    print("  落點:", dict(collections.Counter(k.split("|")[0] for k in gap).most_common(8)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
