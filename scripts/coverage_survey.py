# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""有效覆蓋率普查：玩家**實際看得到**的翻譯比例，逐 mod 排序。

與 `tracker.py coverage` 的差別——後者問「這個鍵名我方收了嗎」，本支問
「這個鍵在遊戲裡會不會顯示成中文」。三道 coverage 沒有的濾網：

  1. **有效分支**：只算 `common/` ＋ 唯一最佳版本夾（`tracker.resolve_effective_branches`）。
  2. **只認 `.json`**：`Translator.tryFillMapFromFile():353` 路徑寫死 `.json`，
     legacy `_EN.txt` 的 EN 定義在執行期並不存在。
  3. **檔名要對**：`getTextInternal():419` 按鍵前綴硬路由到特定 map，
     鍵放在別的檔案裡等於沒翻。coverage 用裸鍵名比對，會把這種情況誤判為已覆蓋。

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

    state = _jload(ROOT / "tracker-state/en_corpus_hashes.json")["mods"]
    rows, tot_up, tot_cov = [], 0, 0
    for wid in sorted(state):
        recs = state[wid].get("records") or {}
        eff = tracker.resolve_effective_branches(recs)
        need: set[str] = set()          # "<落點檔>|<鍵>"
        unroutable = 0
        for rid in recs:
            if not tracker.is_effective(rid, eff):
                continue                # 有效分支濾網（含 .json-only）
            kind, _, rest = rid.partition("|")
            rel, _, key = rest.partition("|")
            if kind != "translate_en" or key in vanilla:
                continue
            stem = os.path.basename(rel)[:-5]
            tgt = target_file(stem, key)
            if tgt is None:
                unroutable += 1
                continue
            need.add(f"{tgt}|{key}")
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
