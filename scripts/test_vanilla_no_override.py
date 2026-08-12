# /// script
# requires-python = ">=3.10"
# ///
"""硬原則回歸測試：**出貨物不得覆蓋本體現有的任何一個 CH／CN 翻譯鍵**。

執行：uv run scripts/test_vanilla_no_override.py

與 `test_vanilla_suppress.py` 的分工：那支拿 fixture 驗「抑制機制本身」的行為，
本支拿**本機 PZ 安裝的現況**驗「我方 dist 的實際結果」——是對真實資料的端到端斷言，
故必須列入每次收尾的驗證鏈。

守兩件事：

1. **零覆蓋**：dist 的 `Translate/{CH,CN}/<檔>` 不得出現本體同 (檔,鍵)。
   判準是**本體現在真的有的鍵**（EN ∪ CH ∪ CN 三語聯集），不是 `vanilla_keys.json` 快照。
   PZ 的 `Translator.tryFillMapFromFile()` 把每個 mod 的 Translate 檔 `map.put()` 進同一張
   全域字串表、後載入者覆寫（`Translator.java:353`），出貨任何本體同 (檔,鍵) 就是全域改寫
   本體譯文，**連沒裝任何模組的玩家都會看到**。
   **本測試不認 `vanilla_keys.json` 的 `keep` 豁免**——使用者裁決（2026-08-12）：一個都不行。
2. **基準不得過時**：本體現有鍵若不在 `vanilla_keys.json` 的 `scoped_keys` 內即失敗，
   要求重跑 `extract_vanilla_keys.py`。遊戲更新會新增鍵，基準是快照、不會自己跟上；
   少了誰，抑制就對誰整批靜默失效。

本體安裝不在本機時**一律判失敗**，沒有豁免旗標——一個「因為讀不到本體所以通過」的綠燈，
正是這道防線最該擋住的東西。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSLATE = Path("D:/SteamLibrary/steamapps/common/ProjectZomboid/media/lua/shared/Translate")
DIST = ROOT / "MOD/MinidoracatModLangFor42/Contents/mods/MinidoracatModLangFor42/42/media/lua/shared/Translate"
LANGS = ("EN", "CH", "CN")
MIN_KEYS = 10000  # 量級守門：遠低於此＝讀到殘缺安裝，不可當成「本體沒幾個鍵」


def load_dir(d: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(d.glob("*.json")):
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict):
            out[p.name] = data
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--translate-dir", default=str(DEFAULT_TRANSLATE), help="本機 PZ 的 Translate 目錄")
    args = ap.parse_args(argv)

    tdir = Path(args.translate_dir)
    missing = [lang for lang in LANGS if not (tdir / lang).is_dir()]
    if missing:
        print(f"❌ 找不到本體語言目錄 {missing}（{tdir}）——本測試以真實安裝為判準，無法降級為通過。")
        return 1

    # 本體現有鍵（檔域）
    base: dict[str, set[str]] = {}
    for lang in LANGS:
        for fname, data in load_dir(tdir / lang).items():
            base.setdefault(fname, set()).update(data)
    total = sum(len(v) for v in base.values())
    if total < MIN_KEYS:
        print(f"❌ 只讀到 {total} 個本體鍵，量級不對——確認 --translate-dir 指向完整安裝。")
        return 1

    # [1] 零覆蓋
    hits: list[str] = []
    for lang in ("CN", "CH"):
        for fname, data in load_dir(DIST / lang).items():
            for key in data:
                if key in base.get(fname, ()):  # 檔域比對：同名鍵只在同檔互撞
                    hits.append(f"{lang}/{fname}|{key}")
    if hits:
        print(f"❌ dist 覆蓋了本體現有的 {len(hits)} 個 (檔,鍵)——這會全域改寫本體譯文：")
        for h in hits[:40]:
            print(f"     {h}")
        if len(hits) > 40:
            print(f"     …另有 {len(hits) - 40} 筆")
        print("   修法：確認 sources/vanilla_keys.json 已重生（extract_vanilla_keys.py）後重跑 build。")
        return 1

    # [2] 基準不得過時
    snap = json.loads((ROOT / "sources/vanilla_keys.json").read_text(encoding="utf-8-sig"))["scoped_keys"]
    stale = [f"{f}|{k}" for f, ks in base.items() for k in ks if k not in set(snap.get(f, ()))]
    if stale:
        print(f"❌ 本體現有 {len(stale)} 個鍵不在 vanilla_keys.json 基準內（基準已過時）：")
        for s in stale[:20]:
            print(f"     {s}")
        print("   修法：uv run scripts/extract_vanilla_keys.py --pz-build <ver> --date <YYYY-MM-DD>")
        return 1

    print(f"✅ 零覆蓋：dist CN/CH 對本體現有 {total} 個 (檔,鍵) 無任何交集；vanilla_keys.json 基準與本體同步。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
