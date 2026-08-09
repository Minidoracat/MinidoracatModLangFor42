#!/usr/bin/env python3
"""自本機 PZ 安裝重新擷取 `sources/vanilla_keys.json` 的鍵名基準。

**遊戲大版本更新後必跑**——vanilla 增刪鍵後，舊基準會讓 verify [12] 的 dist
碰撞閘門同時漏報（新增的 vanilla 鍵沒進基準）與誤報（已移除的鍵仍在基準）。

產出三個由本腳本共同維護的欄位，彼此保證一致（單一 writer，無漂移）：

* ``scoped_keys``  ``{檔名: [鍵, ...]}``——**檔域**基準。PZ 的字串表逐檔載入，
  同名鍵只在同檔才互撞（vanilla 自身多張地圖檔各帶 ``title``/``description``
  而不互撞即為此故），出貨抑制與 dist 碰撞閘門一律以此判定。
* ``keys``        扁平裸鍵集（= scoped_keys 的值聯集）。own 層碰撞閘門與
  coverage/gap/tracker 等既有 consumer 沿用此欄，語意較寬（跨檔即算撞），
  對「原創鍵不得撞本體」而言是刻意保守的網。
* ``vanilla_scoped_pairs`` 地圖檔泛用鍵（title/description）的精確對，
  供 As1 lane report-only 比對沿用。

人工維護欄位（``allowlist`` / ``as1_overlap_known`` / ``keep``）原樣保留。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "sources" / "vanilla_keys.json"
DEFAULT_EN = Path("D:/SteamLibrary/steamapps/common/ProjectZomboid/media/lua/shared/Translate/EN")

# 本腳本重生 keys / scoped_keys / vanilla_scoped_pairs / _source；
# 其餘欄位（allowlist / keep / as1_overlap_known 等人工登記）原樣保留
GENERIC_MAP_KEYS = {"title", "description"}


def read_en_dir(en_dir: Path) -> dict[str, list[str]]:
    """{檔名: 排序鍵清單}。PZ 的 Translate JSON 允許 BOM，故用 utf-8-sig。"""
    out: dict[str, list[str]] = {}
    for path in sorted(en_dir.glob("*.json")):
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} 不是物件（PZ Translate JSON 應為扁平字串表）")
        out[path.name] = sorted(data)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--en-dir", default=str(DEFAULT_EN), help="本機 PZ 的 Translate/EN 目錄")
    ap.add_argument("--pz-build", required=True, help="擷取當下的遊戲版本（寫進 _source 供追溯）")
    ap.add_argument("--date", required=True, help="擷取日期 YYYY-MM-DD（寫進 _source）")
    ap.add_argument("--dry-run", action="store_true", help="只印差異，不寫檔")
    ap.add_argument(
        "--allow-shrink",
        action="store_true",
        help="允許既有檔案的鍵大幅減少或整個消失（遊戲真的移除該檔時才用）",
    )
    args = ap.parse_args(argv)

    en_dir = Path(args.en_dir)
    if not en_dir.is_dir():
        print(f"❌ 找不到 Translate/EN 目錄：{en_dir}")
        return 1

    scoped = read_en_dir(en_dir)
    flat = sorted({k for ks in scoped.values() for k in ks})
    if len(flat) < 10000:  # 量級 4.7 萬；遠低於此＝讀到殘缺安裝
        print(f"❌ 只讀到 {len(flat)} 個鍵，量級不對——確認 --en-dir 指向完整安裝。")
        return 1
    pairs = sorted(
        f"{fname}|{key}"
        for fname, keys in scoped.items()
        for key in keys
        if key in GENERIC_MAP_KEYS
    )

    with open(TARGET, encoding="utf-8-sig") as f:
        data = json.load(f)
    old_flat, old_scoped = set(data.get("keys", [])), data.get("scoped_keys") or {}
    added, removed = sorted(set(flat) - old_flat), sorted(old_flat - set(flat))
    print(f"檔 {len(scoped)} 個、檔域鍵 {sum(len(v) for v in scoped.values())} 個、裸鍵 {len(flat)} 個")
    print(f"  對現行基準：新增 {len(added)}、移除 {len(removed)}、地圖泛用鍵對 {len(pairs)}")
    for label, sample in (("新增", added), ("移除", removed)):
        if sample:
            print(f"  {label}樣本：{sample[:8]}")
    if not old_scoped:
        print("  （現行基準尚無 scoped_keys，本次為首次建立）")

    # 縮水守門：整個 bucket 消失或大量減少幾乎都是「讀到殘缺安裝」而非遊戲真的砍檔，
    # 而基準一旦少掉某檔，該檔的出貨抑制就整批靜默失效（總鍵數卻幾乎不變，看不出來）。
    shrunk = [
        f"{f}: {len(old)} → {len(scoped.get(f, []))}"
        for f, old in sorted(old_scoped.items())
        if isinstance(old, list) and old and len(scoped.get(f, [])) < len(old) * 0.8
    ]
    if shrunk and not args.allow_shrink:
        print(f"❌ {len(shrunk)} 個既有檔案的鍵大幅減少或消失：")
        for line in shrunk[:20]:
            print(f"     {line}")
        print("   多半是讀到殘缺安裝。確認遊戲真的移除了這些檔再加 --allow-shrink 重跑。")
        return 1

    if args.dry_run:
        print("dry-run：未寫檔。")
        return 0

    data["keys"] = flat
    data["scoped_keys"] = scoped
    data["vanilla_scoped_pairs"] = pairs
    data["_source"] = (
        f"{en_dir.as_posix()}（PZ B{args.pz_build} 本機安裝，{args.date} 擷取；"
        "遊戲大版本更新後以 scripts/extract_vanilla_keys.py 重新產生）"
    )
    tmp = TARGET.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, TARGET)
    print(f"✅ 已更新 {TARGET.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
