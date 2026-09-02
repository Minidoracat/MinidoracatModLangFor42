# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""有效覆蓋率普查：玩家**實際看得到**的翻譯比例，逐 mod 排序。

與 `tracker.py coverage` 的差別——後者問「這個鍵名我方收了嗎」，本支問
「這個鍵在遊戲裡會不會顯示成中文」。三道 coverage 沒有的濾網：

  1. **有效分支**：只算 `common/` ＋ 唯一最佳版本夾（`tracker.resolve_effective_branches`）。
  2. **檔名要對**：`getTextInternal():419` 按鍵前綴硬路由到特定 map，
     鍵放在別的檔案裡等於沒翻。coverage 用裸鍵名比對，會把這種情況誤判為已覆蓋。

**刻意不套 `.json` 濾網**（2026-08-07 修正）：`tracker.is_effective` 會排除
legacy `_EN.txt` 的 `translate_en`，那是為了「EN 錨點該從哪取」而設。但一個鍵的
上游 EN 定義存不存在，**不影響我方譯文能否顯示**——`Translator` 是按鍵查我方
CH/CN 的。把這類鍵從分母剔除會低估宇宙、也讓 1,485 個真正可補的鍵從雷達上消失。

用途：抓出「掛名支援但玩家全看英文」的 mod——這類缺口 `coverage` 的
「Lua 確證可見」口徑看不見（上游若不用 getText 取鍵就不計入）。

    uv run scripts/coverage_survey.py [--limit N] [--min-keys N] [--out x.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker  # noqa: E402 — 共用有效分支解析

ROOT = Path(__file__).resolve().parent.parent
DIST_CH = (ROOT / "MOD/MinidoracatModLangFor42/Contents/mods/MinidoracatModLangFor42/42"
           "/media/lua/shared/Translate/CH")

# Translator.BY_NAME（31 檔）——上游若已用這些檔名，該檔名就是落點
WHITELIST = frozenset({
    "Tooltip", "IG_UI", "Recipes", "RecipeGroups", "Farming", "ContextMenu", "SurvivalGuide",
    "UI", "Items", "ItemName", "Moodles", "Sandbox", "Challenge", "Stash", "Moveables",
    "MakeUp", "GameSound", "DynamicRadio", "EvolvedRecipeName", "Recorded_Media",
    "SurvivorNames", "Attributes", "Fluids", "Print_Media", "Print_Text", "Entity",
    "RadioData", "BodyParts", "MapLabel", "Credits", "Mod",
})
# getTextInternal 的前綴路由（長前綴在前，避免被短前綴截走）
PREFIX_ROUTE = (
    ("SurvivorSurname_", "SurvivorNames"), ("SurvivorName_", "SurvivorNames"),
    ("SurvivalGuide_", "SurvivalGuide"), ("Print_Media_", "Print_Media"),
    ("Print_Text_", "Print_Text"), ("ContextMenu_", "ContextMenu"),
    ("Attributes_", "Attributes"), ("BODYPART_", "BodyParts"), ("GameSound_", "GameSound"),
    ("Challenge_", "Challenge"), ("MapLabel_", "MapLabel"), ("Moodles_", "Moodles"),
    ("Farming_", "Farming"), ("Sandbox_", "Sandbox"), ("Tooltip_", "Tooltip"),
    ("credits_", "Credits"), ("AEBS_", "DynamicRadio"), ("Stash_", "Stash"),
    ("Fluid_", "Fluids"), ("IGUI_", "IG_UI"), ("MakeUp", "MakeUp"), ("EC_", "Entity"),
    ("RD_", "RadioData"), ("RM_", "Recorded_Media"), ("UI_", "UI"),
)


def _jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _branch_ok(rid: str, eff: dict[str, set[str]]) -> bool:
    """該 record 是否落在遊戲會載入的分支。與 tracker.is_effective 的差別是
    **不看副檔名**——見模組 docstring 對 `.json` 濾網的說明。"""
    _, _, rest = rid.partition("|")
    relpath, _, _ = rest.partition("|")
    parts = relpath.split("/")
    if len(parts) < 3 or parts[0] != "mods":
        return True
    return parts[2] in eff.get(parts[1], set())


def target_file(src_stem: str, key: str) -> str | None:
    """這個鍵要生效，必須落在哪個檔？None＝前綴無路由，放哪都取不到。"""
    if src_stem in WHITELIST:
        return src_stem
    for prefix, tgt in PREFIX_ROUTE:
        if key.startswith(prefix):
            return tgt
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="有效覆蓋率普查")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--min-keys", type=int, default=20, help="上游有效鍵少於此值的 mod 不列入排行")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    shipped = {f"{p[:-5]}|{k}"
               for p in os.listdir(DIST_CH) if p.endswith(".json")
               for k in _jload(DIST_CH / p)}
    vraw = set(_jload(ROOT / "sources/vanilla_keys.json")["keys"])
    vanilla = vraw | {k.split("_", 1)[1] for k in vraw if "_" in k}
    # 已裁決不出貨（owner 衝突無誠實中性譯名等，見 unshipped_keys.json）與 vanilla 抑制
    # 同性質：是刻意決定、不是積壓。不扣會讓 100% 在數學上永遠達不到——2026-09-02 實測
    # 280 鍵卡住上限 99.75%，其中 233 鍵是 Motorious Zone 兩個可獨立啟用的 mod 用同鍵
    # 指向不同車名，那是本包不出貨的裁決結果，報成缺口只會讓數字永遠不誠實。
    unshipped = {f"{f[:-5] if f.endswith('.json') else f}|{k}"
                 for fk in _jload(ROOT / "sources/unshipped_keys.json")["entries"]
                 if not fk.startswith("_")
                 for f, _, k in (fk.partition("|"),)}
    n_unshipped = 0

    state = _jload(ROOT / "tracker-state/en_corpus_hashes.json")["mods"]
    rows, tot_up, tot_cov = [], 0, 0
    n_blank = 0
    for wid in sorted(state):
        recs = state[wid].get("records") or {}
        eff = tracker.resolve_effective_branches(recs)
        # 上游把鍵定義成空字串者不計入分母——遊戲顯示空白，沒有可翻的內容，
        # 填中文等於憑空造內容。狀態檔只有 hash，故查 sources/en/ 鏡像取值；
        # 無鏡像的 mod 無從判斷，一律照計（寧可高估分母）。
        mirror_p = ROOT / "sources/en" / f"{wid}.json"
        blank: set[str] = set()
        if mirror_p.is_file():
            for rid, val in _jload(mirror_p).items():
                if rid.startswith("translate_en|") and not (isinstance(val, str) and val.strip()):
                    blank.add(rid.partition("|")[2].partition("|")[2])
        n_blank += len(blank)
        need: set[str] = set()          # "<落點檔>|<鍵>"
        unroutable = 0
        for rid in recs:
            if not _branch_ok(rid, eff):
                continue                # 只濾分支，不濾副檔名（見模組 docstring）
            kind, _, rest = rid.partition("|")
            rel, _, key = rest.partition("|")
            if kind != "translate_en" or key in vanilla:
                continue
            if key in blank:            # 上游值為空字串，無可翻內容
                continue
            stem = os.path.basename(rel)[:-5]
            tgt = target_file(stem, key)
            if tgt is None:
                unroutable += 1
                continue
            pair = f"{tgt}|{key}"
            if pair in unshipped:       # 已裁決不出貨，非積壓
                n_unshipped += 1
                continue
            need.add(pair)
        if not need:
            continue
        covered = len(need & shipped)
        tot_up += len(need)
        tot_cov += covered
        rows.append({"wid": wid, "upstream": len(need), "covered": covered,
                     "pct": round(covered / len(need) * 100, 1),
                     "unroutable": unroutable,
                     "sample": sorted(k.split("|", 1)[1] for k in (need - shipped))[:3]})

    print(f"有效鍵合計 {tot_up}　已覆蓋 {tot_cov}（{tot_cov / tot_up * 100:.1f}%）　"
          f"缺口 {tot_up - tot_cov}　涵蓋 {len(rows)} 個 mod")
    print(f"（另有 {n_blank} 個鍵上游值為空字串無可翻內容、{n_unshipped} 個鍵已裁決不出貨，"
          "皆不計入分母）")
    zero = [r for r in rows if r["covered"] == 0 and r["upstream"] >= args.min_keys]
    print(f"\n★ 零覆蓋 mod（有效鍵 ≥{args.min_keys}）：{len(zero)} 個、"
          f"合計 {sum(r['upstream'] for r in zero)} 鍵——玩家全看英文")
    for r in sorted(zero, key=lambda r: -r["upstream"])[:args.limit]:
        print(f"  {r['wid']:>12} {r['upstream']:>5} 鍵  {r['sample']}")

    partial = [r for r in rows if 0 < r["pct"] < 50 and r["upstream"] >= args.min_keys]
    print(f"\n覆蓋率 <50% 的 mod：{len(partial)} 個、"
          f"缺口合計 {sum(r['upstream'] - r['covered'] for r in partial)} 鍵")
    for r in sorted(partial, key=lambda r: -(r["upstream"] - r["covered"]))[:args.limit]:
        print(f"  {r['wid']:>12} {r['covered']:>5}/{r['upstream']:<5} ({r['pct']:>5.1f}%)  {r['sample']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"totals": {"upstream": tot_up, "covered": tot_cov}, "mods": rows},
                      f, ensure_ascii=False, indent=1)
        print(f"\n明細 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
