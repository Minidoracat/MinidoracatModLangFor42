# /// script
# requires-python = ">=3.10"
# ///
"""硬原則回歸測試：**出貨物不得覆蓋本體現有的任何一個 CH／CN 翻譯鍵**。

執行：uv run scripts/test_vanilla_no_override.py

與 `test_vanilla_suppress.py` 的分工：那支拿 fixture 驗「抑制機制本身」的行為，
本支拿**本機 PZ 安裝的現況**驗「我方 dist 的實際結果」——是對真實資料的端到端斷言，
故必須列入每次收尾的驗證鏈。

守三件事：

1. **零覆蓋**：dist 的 `Translate/{CH,CN}/<檔>` 不得出現本體同 (檔,鍵)。
   判準是**本體現在真的有的鍵**（EN ∪ CH ∪ CN 三語聯集），不是 `vanilla_keys.json` 快照。
   PZ 的 `Translator.tryFillMapFromFile()` 把每個 mod 的 Translate 檔 `map.put()` 進同一張
   全域字串表、後載入者覆寫（`Translator.java:353`），出貨任何本體同 (檔,鍵) 就是全域改寫
   本體譯文，**連沒裝任何模組的玩家都會看到**。
   **本測試不認 `vanilla_keys.json` 的 `keep` 豁免**——使用者裁決（2026-08-12）：一個都不行。
2. **基準不得過時**：本體現有鍵若不在 `vanilla_keys.json` 的 `scoped_keys` 內即失敗，
   要求重跑 `extract_vanilla_keys.py`。遊戲更新會新增鍵，基準是快照、不會自己跟上；
   少了誰，抑制就對誰整批靜默失效。
3. **條件譯文的本體英文錨點不得過時**：`sources/owner_variants.json` 的 `kind=vanilla` 條目，
   `vanilla_en` 必須等於本體現況 EN。本體改英文時，哪些 MOD 與本體同英文（`skip_owners`）、
   哪些不同（要出 MOD 版譯文）的分組可能已不成立，必須重新裁決。
4. **不撞本體翻譯包的鍵**：原版會查、原版翻譯檔卻沒定義的名稱（物品、車輛、製作站…）不在
   [1] 的三語聯集裡，只有本體翻譯包（CatLangFor42）翻。本包預設排在它之後，同鍵會改到所有
   玩家看到的原版名稱。dist 與本機 LangFor42 出貨鍵的交集必須都登記在
   `sources/langfor42_shared_keys.json`（原版不會顯示、可共存）；原版會顯示的要經使用者裁決
   登記 `unshipped_keys.json` 第三類不出貨。

本體安裝或本機 LangFor42 不在時**一律判失敗**，沒有豁免旗標——一個「因為讀不到本體所以通過」的綠燈，
正是這道防線最該擋住的東西。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSLATE = Path("D:/SteamLibrary/steamapps/common/ProjectZomboid/media/lua/shared/Translate")
DEFAULT_BASE_PACK = ROOT.parent / ("MinidoracatLangFor42/MOD/MinidoracatLangFor42/Contents/mods/"
                                   "MinidoracatLangFor42/42/media/lua/shared/Translate")
DIST = ROOT / "MOD/MinidoracatModLangFor42/Contents/mods/MinidoracatModLangFor42/42/media/lua/shared/Translate"
SHARED_KEYS_JSON = ROOT / "sources/langfor42_shared_keys.json"
LANGS = ("EN", "CH", "CN")
MIN_KEYS = 10000        # 本體量級守門：遠低於此＝讀到殘缺安裝，不可當成「本體沒幾個鍵」
MIN_DIST_FILES = 50     # dist 量級守門：現況 85 檔／10 萬鍵，殘缺 dist 掃出來的零交集沒有意義
MIN_DIST_KEYS = 20000
MIN_BASE_PACK_KEYS = 20000  # 本體翻譯包量級守門：現況 CH∪CN 約 5 萬個 (檔,鍵)


def load_dir(d: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(d.glob("*.json")):
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict):
            out[p.name] = data
    return out


def load_shared_allow(path: Path) -> dict[str, str]:
    """`langfor42_shared_keys.json` → {"檔名.json|鍵": 理由}。缺檔或壞形 raise（fail-closed）。"""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        raise ValueError("缺 entries 物件")
    bad = [k for k, v in entries.items()
           if not k.partition("|")[0].endswith(".json") or not k.partition("|")[2]
           or not isinstance(v, str) or not v.strip()]
    if bad:
        raise ValueError(f"條目須為「檔名.json|鍵」: 非空理由，壞的：{bad[:5]}")
    return entries


def shared_with_base_pack(dist_pairs: set[str], base_pairs: set[str],
                          allow: dict[str, str]) -> tuple[list[str], list[str]]:
    """回 (未登記的撞鍵, 登記了卻已不再撞鍵的條目)；pairs 都是「檔名.json|鍵」、CH∪CN。"""
    shared = dist_pairs & base_pairs
    return sorted(shared - allow.keys()), sorted(allow.keys() - shared)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--translate-dir", default=str(DEFAULT_TRANSLATE), help="本機 PZ 的 Translate 目錄")
    ap.add_argument("--base-pack-dir", default=str(DEFAULT_BASE_PACK), help="本機本體翻譯包的 Translate 目錄")
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

    # [1] 零覆蓋。**先確認 dist 真的在**——空集合對空集合永遠零交集，
    # 「因為讀不到 dist 所以通過」正是這道防線最該擋住的東西（2026-08-12 codex
    # review 實測：把 DIST 指向不存在的路徑，舊版照樣印 ✅ 並回傳 0）。
    dist_maps: dict[str, dict[str, dict]] = {}
    for lang in ("CN", "CH"):
        d = DIST / lang
        if not d.is_dir():
            print(f"❌ 找不到 dist 目錄 {d}——請先跑 build_mod.py build。無 dist 可掃≠零覆蓋。")
            return 1
        dist_maps[lang] = load_dir(d)
        n_keys = sum(len(v) for v in dist_maps[lang].values())
        if len(dist_maps[lang]) < MIN_DIST_FILES or n_keys < MIN_DIST_KEYS:
            print(f"❌ dist/{lang} 只有 {len(dist_maps[lang])} 檔、{n_keys} 鍵，量級不對"
                  f"（門檻 {MIN_DIST_FILES} 檔／{MIN_DIST_KEYS} 鍵）——掃了殘缺的 dist 等於沒掃。")
            return 1
    if set(dist_maps["CN"]) != set(dist_maps["CH"]):
        print("❌ dist CN/CH 檔案集合不一致，先修 build 再驗零覆蓋。")
        return 1

    hits: list[str] = []
    for lang in ("CN", "CH"):
        for fname, data in dist_maps[lang].items():
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

    # [3] 條件譯文的本體英文錨點：`kind=vanilla` 條目的 `vanilla_en`＝本機遊戲現況 EN。
    # 本體改了英文，「哪些 owner 與本體同英文（skip_owners）」的分組就可能不再成立，要重新裁決。
    vpath = Path(os.environ.get("MODLANG_OWNER_VARIANTS") or ROOT / "sources/owner_variants.json")
    ventries = json.loads(vpath.read_text(encoding="utf-8-sig"))["entries"]
    en = load_dir(tdir / "EN")
    drift: list[str] = []
    n_var = 0
    for fk, e in ventries.items():
        if fk.startswith("_") or not isinstance(e, dict) or e.get("kind") != "vanilla":
            continue
        n_var += 1
        fname, _, key = fk.partition("|")
        cur = en.get(f"{fname}.json", {}).get(key)
        if cur != e.get("vanilla_en"):
            drift.append(f"{fk}：錨點 {e.get('vanilla_en')!r} ≠ 本體現況 {cur!r}")
    if drift:
        print(f"❌ 條件譯文 {len(drift)} 個本體鍵的 vanilla_en 錨點與本體現況 EN 不符（本體改英文，要重新裁決）：")
        for d in drift[:20]:
            print(f"     {d}")
        return 1

    # [4] 不撞本體翻譯包出貨的鍵（交集都要登記可共存，原版會顯示的走 unshipped_keys 第三類）
    bdir = Path(args.base_pack_dir)
    if not all((bdir / lang).is_dir() for lang in ("CH", "CN")):
        print(f"❌ 找不到本體翻譯包的 Translate/CH、CN（{bdir}）——[4] 無法降級為通過。")
        return 1
    base_pairs = {f"{f}|{k}" for lang in ("CH", "CN") for f, d in load_dir(bdir / lang).items() for k in d}
    if len(base_pairs) < MIN_BASE_PACK_KEYS:
        print(f"❌ 本體翻譯包只讀到 {len(base_pairs)} 個 (檔,鍵)，量級不對（門檻 {MIN_BASE_PACK_KEYS}）。")
        return 1
    try:
        allow = load_shared_allow(SHARED_KEYS_JSON)
    except (OSError, ValueError) as exc:
        print(f"❌ {SHARED_KEYS_JSON.name} 讀不到或形狀壞損：{exc}")
        return 1
    dist_pairs = {f"{f}|{k}" for lang in ("CN", "CH") for f, d in dist_maps[lang].items() for k in d}
    clash, gone = shared_with_base_pack(dist_pairs, base_pairs, allow)
    if clash:
        print(f"❌ dist 與本體翻譯包同時出貨 {len(clash)} 個 (檔,鍵)——本包排在它之後時會改到原版名稱：")
        for c in clash[:40]:
            print(f"     {c}")
        print("   修法（要使用者裁決）：原版會顯示的鍵登記 sources/unshipped_keys.json 第三類不出貨；"
              "原版不會顯示的鍵登記 sources/langfor42_shared_keys.json 並寫明理由。")
        return 1
    for g in gone:
        print(f"⚠️ langfor42_shared_keys.json 的 {g} 已不再撞鍵，請移除。")

    print(f"✅ 零覆蓋：dist CN/CH 對本體現有 {total} 個 (檔,鍵) 無任何交集；vanilla_keys.json 基準與本體同步；"
          f"條件譯文 {n_var} 個本體鍵的 vanilla_en 錨點與本體現況相符；"
          f"與本體翻譯包共用的 {len(allow) - len(gone)} 個 (檔,鍵) 都已登記可共存。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
