# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
lint_ch.py — sources/ch corpus 品質稽核（report-only：命中不影響退出碼、不改檔；
缺檔／格式錯誤仍以非零退出 fail-loud）

斷絕 OpenCC 後 CH corpus 為人工真相層，本工具是批次償還審查債的雷達：
  [A] opencc_fixes 十族 regex：凍結基線殘留的機轉錯誤＋人工新條目回歸（命中＝建議修正）
  [B] terminology charfix 異體字：本體術語表的一對一安全字級映射（命中＝建議修正）
  [C] terminology select 術語：須人工裁決的台灣用語（命中＝裁決參考，非錯誤）
  [D] terminology vendor 同步：本體 repo 在本機時比對 vendor 副本是否漂移

使用方式：uv run scripts/lint_ch.py [--limit N] [--base-terminology PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CH_DIR = PROJECT_ROOT / "sources" / "ch"
FIXES_JSON = PROJECT_ROOT / "sources" / "opencc_fixes.json"
TERM_JSON = PROJECT_ROOT / "sources" / "terminology.json"
BASE_TERM_JSON = Path("D:/github/MinidoracatLangFor42/scripts/terminology.json")
RATCHET = {"A": 0, "B": 0}  # [A]/[B] 命中數棘輪基線（2026-08-02 首批償還後歸零）


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def scan(corpus: dict[str, dict], hit) -> list[tuple[str, str, str]]:
    """回傳 [(檔名, 鍵, 值)] 命中清單；hit 為 value → bool。"""
    return [
        (fname, key, val)
        for fname, fmap in corpus.items()
        for key, val in fmap.items()
        if isinstance(val, str) and hit(val)
    ]


def show(hits: list[tuple[str, str, str]], limit: int) -> None:
    for fname, key, val in hits[:limit]:
        preview = val if len(val) <= 60 else val[:60] + "…"
        print(f"    {fname} | {key}：{preview!r}")
    if len(hits) > limit:
        print(f"    ...（還有 {len(hits) - limit} 鍵）")


def main() -> int:
    parser = argparse.ArgumentParser(description="sources/ch corpus 品質稽核（report-only）")
    parser.add_argument("--limit", type=int, default=10, help="每規則例句上限（預設 10）")
    parser.add_argument(
        "--base-terminology", type=Path, default=BASE_TERM_JSON,
        help="本體 terminology.json 路徑（[D] 同步檢查用；預設本機 checkout）",
    )
    args = parser.parse_args()

    for path, label in ((CH_DIR, "corpus 目錄"), (FIXES_JSON, "lint 規則"), (TERM_JSON, "術語表")):
        if not path.exists():
            print(f"❌ {label}不存在：{path}", file=sys.stderr)
            return 1

    corpus = {p.name: load_json(p) for p in sorted(CH_DIR.glob("*.json"))}
    n_keys = sum(len(m) for m in corpus.values())
    non_str = [
        (f, k) for f, m in corpus.items() for k, v in m.items() if not isinstance(v, str)
    ]
    print(f"corpus：{len(corpus)} 檔、{n_keys} 鍵")
    if non_str:
        print(f"⚠️ corpus 非字串值 {len(non_str)} 鍵（異常，掃描已跳過）：{non_str[:5]}")

    fix_hits = 0
    fixes = load_json(FIXES_JSON)
    # 裁決豁免登記：(檔|鍵) → {patterns: [...], reason}——經人工裁決為合法語境的
    # regex 誤中（如「彩色光＋標記」誤中光標），逐筆登記後不再計入 [A]／棘輪。
    exemptions = fixes.get("lint_exemptions", {})
    for group in fixes.get("post_fixes", []):
        for rule in group.get("rules", []):
            try:
                pat = re.compile(rule["pattern"])
            except (re.error, KeyError, TypeError) as exc:
                print(f"⚠️ [A] 規則損壞（{group.get('category', '?')}）：{rule!r}（{exc}）")
                continue
            hits = [
                h for h in scan(corpus, pat.search)
                if rule["pattern"] not in exemptions.get(f"{h[0]}|{h[1]}", {}).get("patterns", [])
            ]
            if hits:
                fix_hits += len(hits)
                print(f"\n[A] {group.get('category', '?')} pattern={rule['pattern']!r}：{len(hits)} 鍵")
                show(hits, args.limit)

    term = load_json(TERM_JSON)
    charfix_hits = 0
    for bad, good in sorted(term.get("charfix", {}).items()):
        hits = scan(corpus, lambda v, b=bad: b in v)
        if hits:
            charfix_hits += len(hits)
            print(f"\n[B] 異體字 {bad}→{good}：{len(hits)} 鍵")
            show(hits, args.limit)

    select_hits = 0
    non_literal = 0
    for rule in term.get("rules", []):
        if rule.get("status") != "approved" or rule.get("mode") != "select":
            continue
        match = rule.get("match", {})
        if match.get("type") != "literal":
            non_literal += 1  # 非 literal（regex 型）select 規則本工具不掃，計數提示
            continue
        needle = match["value"]
        hits = scan(corpus, lambda v, n=needle: n in v)
        if hits:
            select_hits += len(hits)
            print(f"\n[C] 裁決參考 {rule.get('pair', needle)}：{len(hits)} 鍵（{rule.get('note', '')}）")
            show(hits, min(args.limit, 3))

    if non_literal:
        print(f"\nNOTE: {non_literal} 條非 literal 的 select 規則未掃描（本工具僅支援 literal）")

    base_term = args.base_terminology
    if base_term.exists():
        base = load_json(base_term)
        ours = {k: v for k, v in term.items() if k != "_vendor"}
        if base != ours:
            print("\n[D] ⚠️ terminology vendor 與本體不同步——本體已更新，請重新 vendor 並檢視差異")
        else:
            print("\n[D] terminology vendor 與本體同步 ✓")
    else:
        print("\n[D] NOTE: 本體 repo 不在本機，跳過 terminology 同步檢查")

    print(
        f"\n總計：[A] 修正建議 {fix_hits} 鍵、[B] 異體字 {charfix_hits} 鍵、"
        f"[C] 裁決參考 {select_hits} 鍵（[C] 為語境參考，不計棘輪）"
    )
    # 棘輪：[A]/[B] 屬「應修正」類，基線已於 2026-08-02 首批償還歸零——
    # 超過基線即非零退出（防品質單調劣化）；償還例外時同步調整基線並附理由。
    exceeded = {k: (n, RATCHET[k]) for k, n in (("A", fix_hits), ("B", charfix_hits)) if n > RATCHET[k]}
    if exceeded:
        for cat, (n, base) in exceeded.items():
            print(f"❌ 棘輪超標：[{cat}] {n} 鍵 > 基線 {base}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
