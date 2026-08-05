# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
lint_ch.py — CH 真相層品質稽核與棘輪 gate

掃描範圍為**兩個 CH 真相層**：`sources/ch/` corpus 與 `sources/own_translations.json`
的 `ch` 欄（原創翻譯層）。兩者 (檔名|鍵) 命名空間互斥（own 鍵依設計不進 corpus，
apply_own 在 corpus_gate 之後才合入），故合併掃描後 lint_exemptions 與
ch_review_state 的 (檔名|鍵) 查找對兩層一致適用；報告以 [own] 標記來源真相層。

斷絕 OpenCC 後 CH corpus 為人工真相層，本工具是批次償還審查債的雷達＋防退步 gate：
  [A] opencc_fixes 十族 regex：凍結基線殘留＋人工新條目回歸（**棘輪 gate**，超基線退出 1）
  [B] terminology charfix 異體字：一對一安全字級映射（**棘輪 gate**，超基線退出 1）
  [C] terminology select 術語：須人工裁決的台灣用語（已裁決鍵經 ch_review_state 過濾，
      餘下為新增待裁決——**棘輪 gate**，超基線退出 1）
  [D] terminology vendor 同步：本體 repo 在本機時比對 vendor 副本是否漂移（report-only）
  [E] terminology replace 術語：無條件替換的已核准規則（**棘輪 gate**，超基線退出 1）。
      CH 凍結後本 repo 不跑 terminology 引擎（CH 直取真相層、無任何機轉），這些規則
      因此完全無人執行——[E] 是它們唯一的落地檢查。誤中走 lint_exemptions（帶
      ch_value 錨點），不走 ch_review_state：replace 語意是「一律替換」，開放台帳
      keep 會變成繞過 gate 的後門。

豁免與過濾皆 fail-closed：lint_exemptions 條目須帶 ch_value 錨點且與現行 CH 值相符
才生效；規則損壞／豁免 schema 不符＝非零退出。缺檔／格式錯誤亦 fail-loud。

使用方式：uv run scripts/lint_ch.py [--limit N] [--base-terminology PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CH_DIR = PROJECT_ROOT / "sources" / "ch"
OWN_JSON = PROJECT_ROOT / "sources" / "own_translations.json"
FIXES_JSON = PROJECT_ROOT / "sources" / "opencc_fixes.json"
TERM_JSON = PROJECT_ROOT / "sources" / "terminology.json"
REVIEW_STATE_JSON = PROJECT_ROOT / "sources" / "ch_review_state.json"
DIST_CN_DIR = (
    PROJECT_ROOT / "MOD" / "MinidoracatModLangFor42" / "Contents" / "mods"
    / "MinidoracatModLangFor42" / "42" / "media" / "lua" / "shared" / "Translate" / "CN"
)
BASE_TERM_JSON = Path("D:/github/MinidoracatLangFor42/scripts/terminology.json")
RATCHET = {"A": 0, "B": 0, "C": 0, "E": 0, "F": 0}  # 命中數棘輪基線（2026-08-02 首批償還後歸零）

# [F] 42.20.1 Translator.formatted() 安全文法：安全 token（%%/%1-%9/%s/%d/%.Nf/%+.Nf）
# 之外的裸 % 必炸（UnknownFormatConversionException → 主選單黑畫面）。
# 與 build_mod.sanitize_format_tokens 同語意（lint 為獨立稽核工具，不 import builder）。
# precision 用 ASCII [0-9] 並限 2 位：\d 是 Unicode-aware（%.١f 會被誤放行，JDK 崩潰），
# 無上限則 %.2147483648f 拋 IllegalFormatPrecisionException。
_FMT_SAFE_RE = re.compile(r"%\+?\.[0-9]{1,2}f|%[1-9]|%[sd]")
# Java 完整位置參數 %N$<conversion> → PZ 簡寫 %N（formatFixer 自行補 $s）；
# conversion 須完整消費（date/time 為 [tT] 後再接一字母）。
# flags 有界重複：與 width `[0-9]*` 在 `0` 上重疊，無界時長 0 串失敗匹配 O(N²)
_FMT_POSITIONAL_RE = re.compile(
    r"%([1-9])\$[-#+ 0,(]{0,8}[0-9]*(?:\.[0-9]+)?(?:[tT][a-zA-Z]|[a-zA-Z])"
)


def fmt_sanitize(value: str) -> str:
    """與 build_mod.sanitize_format_tokens 同語意（獨立實作，測試驗等價）。

    left-to-right 掃描、`%%` 最優先——全域 sub 會穿透字面 `%%`（`%%1$s` → `%%1`）。
    """
    if "%" not in value:
        return value
    out: list[str] = []
    i, n = 0, len(value)
    while i < n:
        if value[i] != "%":
            out.append(value[i])
            i += 1
        elif value.startswith("%%", i):
            out.append("%%")
            i += 2
        elif (p := _FMT_POSITIONAL_RE.match(value, i)) and not value.startswith("$", p.end()):
            out.append(f"%{p.group(1)}")
            i = p.end()
        elif m := _FMT_SAFE_RE.match(value, i):
            out.append(m.group())
            i = m.end()
        else:
            out.append("%%")
            i += 1
    return "".join(out)


def h16(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


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


def show(hits: list[tuple[str, str, str]], limit: int, own: set[tuple[str, str]]) -> None:
    """印命中例句；own 層鍵標 [own]，指明該去哪個真相層修。"""
    for fname, key, val in hits[:limit]:
        preview = val if len(val) <= 60 else val[:60] + "…"
        tag = " [own]" if (fname, key) in own else ""
        print(f"    {fname} | {key}{tag}：{preview!r}")
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

    for path, label in (
        (CH_DIR, "corpus 目錄"), (OWN_JSON, "原創翻譯層"),
        (FIXES_JSON, "lint 規則"), (TERM_JSON, "術語表"),
    ):
        if not path.exists():
            print(f"❌ {label}不存在：{path}", file=sys.stderr)
            return 1

    corpus = {p.name: load_json(p) for p in sorted(CH_DIR.glob("*.json"))}
    n_keys = sum(len(m) for m in corpus.values())

    # own_translations 的 ch 欄同為 CH 真相層，併入同一輪掃描。命名空間互斥
    # （own 鍵不進 corpus，見 build 的 apply_own 時序），撞名即真相層重疊＝fail-loud。
    own_entries = load_json(OWN_JSON).get("entries", {})
    own_keys: set[tuple[str, str]] = set()
    n_own = 0
    for fname, emap in own_entries.items():
        fmap = corpus.setdefault(fname, {})
        for key, spec in emap.items():
            if key in fmap:
                print(f"❌ 真相層重疊：{fname}|{key} 同時存在於 sources/ch 與 own_translations",
                      file=sys.stderr)
                return 1
            fmap[key] = spec.get("ch") if isinstance(spec, dict) else spec
            own_keys.add((fname, key))
            n_own += 1

    non_str = [
        (f, k) for f, m in corpus.items() for k, v in m.items() if not isinstance(v, str)
    ]
    print(f"corpus：{len(corpus)} 檔、{n_keys} 鍵（＋own_translations {len(own_entries)} 檔、{n_own} 鍵）")
    if non_str:
        print(f"⚠️ corpus 非字串值 {len(non_str)} 鍵（異常，掃描已跳過）：{non_str[:5]}")

    schema_errors = 0
    fix_hits = 0
    fixes = load_json(FIXES_JSON)
    term = load_json(TERM_JSON)
    # approved 且 mode=replace 的規則＝[E] 的掃描域；pattern 一併納入 known_patterns，
    # 否則 [E] 誤中無法登記豁免（會被判 schema error）。
    replace_rules = [
        r for r in term.get("rules", [])
        if r.get("status") == "approved" and r.get("mode") == "replace"
        and isinstance(r.get("match", {}).get("value"), str)
    ]
    # 裁決豁免登記：(檔|鍵) → {patterns: [...], reason, ch_value}——經人工裁決為
    # 合法語境的 regex 誤中（如「彩色光＋標記」誤中光標）。fail-closed：
    #   * pattern 必須存在於 post_fixes 規則集，否則 schema error（豁免空轉零訊號）
    #   * ch_value（裁決當時 CH 值 sha256[:16]）必須與現行 CH 相符，否則豁免失效
    #     （命中重新計入棘輪）並列警告——值變了就必須重新裁決
    exemptions = fixes.get("lint_exemptions", {})
    known_patterns = {
        r.get("pattern") for g in fixes.get("post_fixes", []) for r in g.get("rules", [])
    } | {r["match"]["value"] for r in replace_rules}
    active_exempt: dict[str, set[str]] = {}
    for rk, spec in sorted(exemptions.items()):
        pats = spec.get("patterns") if isinstance(spec, dict) else None
        if not isinstance(pats, list) or not all(p in known_patterns for p in pats):
            print(f"❌ lint_exemptions schema/pattern 不符：{rk}（{pats!r}）", file=sys.stderr)
            schema_errors += 1
            continue
        rf, _, rkey = rk.partition("|")
        val = corpus.get(rf, {}).get(rkey)
        if not isinstance(val, str):
            print(f"⚠️ lint_exemptions 過時：{rk} 已不在 corpus，請移除條目")
            continue
        anchor = spec.get("ch_value")
        if anchor != h16(val):
            print(f"⚠️ lint_exemptions 錨點不符：{rk} 的 CH 值已變，豁免失效，請重新裁決")
            continue
        active_exempt[rk] = set(pats)
    for group in fixes.get("post_fixes", []):
        for rule in group.get("rules", []):
            try:
                pat = re.compile(rule["pattern"])
            except (re.error, KeyError, TypeError) as exc:
                print(f"❌ [A] 規則損壞（{group.get('category', '?')}）：{rule!r}（{exc}）", file=sys.stderr)
                schema_errors += 1
                continue
            hits = [
                h for h in scan(corpus, pat.search)
                if rule["pattern"] not in active_exempt.get(f"{h[0]}|{h[1]}", set())
            ]
            if hits:
                fix_hits += len(hits)
                print(f"\n[A] {group.get('category', '?')} pattern={rule['pattern']!r}：{len(hits)} 鍵")
                show(hits, args.limit, own_keys)

    charfix_hits = 0
    for bad, good in sorted(term.get("charfix", {}).items()):
        hits = scan(corpus, lambda v, b=bad: b in v)
        if hits:
            charfix_hits += len(hits)
            print(f"\n[B] 異體字 {bad}→{good}：{len(hits)} 鍵")
            show(hits, args.limit, own_keys)

    # [C] 已裁決過濾：ch_review_state 中 hash 與現行有效 CN 相符的鍵＝已經人工/AI
    # 逐鍵裁決（keep 或 fix 皆登記），不再重報；餘下命中＝新增待裁決 → 棘輪
    review_state: dict[str, str] = {}
    if REVIEW_STATE_JSON.exists():
        review_state = {
            k: v for k, v in load_json(REVIEW_STATE_JSON).items()
            if "|" in k and isinstance(v, str)
        }
    dist_cn: dict[str, dict] = {}
    if DIST_CN_DIR.is_dir():
        dist_cn = {p.name: load_json(p) for p in sorted(DIST_CN_DIR.glob("*.json"))}

    def adjudicated(fname: str, key: str) -> bool:
        h = review_state.get(f"{fname}|{key}")
        val = dist_cn.get(fname, {}).get(key)
        return bool(h and isinstance(val, str) and h16(val) == h)

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
        hits = [
            h for h in scan(corpus, lambda v, n=needle: n in v)
            if not adjudicated(h[0], h[1])
        ]
        if hits:
            select_hits += len(hits)
            print(f"\n[C] 待裁決 {rule.get('pair', needle)}：{len(hits)} 鍵（{rule.get('note', '')}）")
            show(hits, min(args.limit, 3), own_keys)

    if non_literal:
        print(f"\nNOTE: {non_literal} 條非 literal 的 select 規則未掃描（本工具僅支援 literal）")

    # [E] approved replace 規則：CH 凍結後本 repo 無 terminology 引擎執行它們，此處是
    # 唯一落地檢查。誤中走 lint_exemptions（pattern 已納入 known_patterns），不吃
    # ch_review_state——replace 語意為一律替換，台帳 keep 會變成繞過 gate 的後門。
    replace_hits = 0
    for rule in replace_rules:
        m = rule["match"]
        if m.get("type") == "regex":
            try:
                pat = re.compile(m["value"])
            except re.error as exc:
                print(f"❌ [E] 規則損壞：{rule.get('pair', m['value'])!r}（{exc}）", file=sys.stderr)
                schema_errors += 1
                continue
            test = (lambda v, p=pat: bool(p.search(v)))
        else:
            test = (lambda v, n=m["value"]: n in v)
        hits = [
            h for h in scan(corpus, test)
            if m["value"] not in active_exempt.get(f"{h[0]}|{h[1]}", set())
        ]
        if hits:
            replace_hits += len(hits)
            print(f"\n[E] 應替換 {rule.get('pair', m['value'])}（→{rule.get('replace')!r}）：{len(hits)} 鍵")
            show(hits, args.limit, own_keys)

    # [F] 42.20.1 formatted() 危險 % 序列：CH 真相層（corpus＋own ch）值必須已是
    # 安全形式（裸 % 逸出 %%、%N$s 正規化為 %N）。build 的 format 安全 gate 同語意
    # 阻斷出貨，此處提早在翻譯工作流雷達可見。
    # 掃描域僅 CH（本工具定位為 CH 品質稽核，[A]-[E] 皆繁中規則）——own 的 cn 側
    # 與 own-mod CN 由 build 的 format_gate_errors 涵蓋，非防線缺口。
    fmt_hits = scan(corpus, lambda v: "%" in v and fmt_sanitize(v) != v)
    if fmt_hits:
        print(f"\n[F] 42.20.1 formatted() 危險 % 序列：{len(fmt_hits)} 鍵（裸 % 須逸出為 %%）")
        show(fmt_hits, args.limit, own_keys)

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
        f"[C] 待裁決 {select_hits} 鍵、[E] 應替換 {replace_hits} 鍵、"
        f"[F] 危險 % {len(fmt_hits)} 鍵"
    )
    # 棘輪：基線已於 2026-08-02 首批償還歸零——超過基線即非零退出（防品質單調
    # 劣化）。[C] 命中時：逐鍵裁決（fix 修 corpus／keep 不動）→ 登記 ch_review_state
    # 即消化；[A]/[B] 命中：修正，regex 誤中則登記 lint_exemptions（附 ch_value 錨點）。
    exceeded = {
        k: (n, RATCHET[k])
        for k, n in (
            ("A", fix_hits), ("B", charfix_hits), ("C", select_hits),
            ("E", replace_hits), ("F", len(fmt_hits)),
        )
        if n > RATCHET[k]
    }
    if exceeded:
        for cat, (n, base) in exceeded.items():
            print(f"❌ 棘輪超標：[{cat}] {n} 鍵 > 基線 {base}", file=sys.stderr)
        return 1
    if schema_errors:
        print(f"❌ schema/規則錯誤 {schema_errors} 處（見上）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
