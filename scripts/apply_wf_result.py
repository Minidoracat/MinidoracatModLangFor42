# /// script
# requires-python = ">=3.11"
# ///
"""把補譯 workflow 的產出（譯文＋合併複核）落地成可 apply 的批次檔。

    uv run scripts/apply_wf_result.py --result <workflow輸出.json> \\
        --strings <prep_mod_strings 產出.json> --out-prefix .omc/tmp/xxx [--batches N]

流程：譯文 → 套用複核修正 → 機械檢查 → 依 `_gap` 展開回所有出貨鍵 → 切批。

**這支存在的理由是兩個手工套用時踩過的坑**：
  * 複核用 `null` 表示「這一欄不改」，直接指派會把欄位寫成 None（實測一次寫壞 19 欄）。
  * 複核對長句只給開頭＋「…」當示意，直接當完整值套用會**把句子截斷**（實測一次）。
機械檢查在寫檔前擋下這兩類，不是事後補救。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

MARKUP = (
    (r"\[img=music\]", "img標記"), (r"\*\*", "雙星號"), (r"----", "斷訊殘字"),
    (r"<[A-Za-z][^>]*>", "角括號標記"), (r"%[1-9]", "位置token"), (r"\{[a-zA-Z_]+\}", "大括號佔位"),
)
# CH 側的陸用語預篩。**只收沒有台灣正當語境的詞**——像「質量」在物理義
# （質量守恆／質量數）是台灣標準用語，放進來只會製造誤報，交給 lint_ch 的
# terminology 規則去逐鍵裁決即可。「電視頻道」含子字串「視頻」，故用負向前後文。
MAINLAND = ("信息", "默認", "軟件", "屏幕", "網絡", "鼠標", "內存", "硬盤", "服務器")
MAINLAND_RE = re.compile("|".join(MAINLAND) + r"|(?<!電)視頻(?!道)")


def _jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--strings", required=True)
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--batches", type=int, default=3)
    args = ap.parse_args()

    raw = _jload(args.result)
    res = raw.get("result", raw) if isinstance(raw, dict) else raw
    tr = res["translations"]
    src = _jload(args.strings)
    want = {r["en"] for r in src["strings"]}
    gap = src["_gap"]

    # 去重（保留第一筆）
    seen, rows = set(), []
    for t in tr:
        if t["en"] in seen:
            continue
        seen.add(t["en"])
        rows.append(t)
    idx = {t["en"]: t for t in rows}
    print(f"譯文 {len(tr)} 筆 → 去重 {len(rows)}；應譯 {len(want)}")
    if want - set(idx):
        print(f"❌ 漏譯 {len(want - set(idx))} 條：{sorted(want - set(idx))[:5]}", file=sys.stderr)
        return 1

    # 套用複核修正：null／空字串＝該欄不改；長度暴跌＝疑似截斷，擋下
    review = res.get("review") or ""
    m = re.search(r"```json\s*(\[.*?\])\s*```", review, re.S)
    fixes = json.loads(m.group(1)) if m else []
    applied = skipped = 0
    trunc: list[str] = []
    for f in fixes:
        t = idx.get(f.get("en"))
        if not t:
            continue
        for col in ("ch", "cn"):
            v = f.get(col)
            if not (isinstance(v, str) and v.strip()):
                skipped += 1
                continue
            # 截斷防護：建議值比原譯短一半以上且原譯不含「…」＝疑似只給了片段
            if len(v) * 2 < len(t[col]) and "…" not in t[col]:
                trunc.append(f"{f['en'][:40]} | {t[col][:36]} → {v[:36]}")
                continue
            t[col] = v
            applied += 1
        if f.get("why"):
            t["note"] = (t.get("note", "") + " ｜複核: " + f["why"])[:400]
    print(f"複核 {len(fixes)} 條 → 套用 {applied} 欄、略過(null) {skipped}、擋下疑似截斷 {len(trunc)}")
    for x in trunc:
        print("   ⚠ 疑似截斷未套用：" + x)

    # 機械檢查
    bad: dict[str, list] = collections.defaultdict(list)
    for t in rows:
        en, ch, cn = t["en"], t.get("ch"), t.get("cn")
        if not (isinstance(ch, str) and ch.strip() and isinstance(cn, str) and cn.strip()):
            bad["空值"].append(en)
            continue
        for pat, nm in MARKUP:
            n = len(re.findall(pat, en))
            if n != len(re.findall(pat, ch)) or n != len(re.findall(pat, cn)):
                bad[nm].append((en[:44], ch[:44]))
        if any(c in ch for c in "，。？！：；"):
            bad["CH全形標點"].append((en[:32], ch[:38]))
        if "..." in ch:
            bad["未正規化省略號"].append((en[:32], ch[:38]))
        m = MAINLAND_RE.search(ch)
        if m:
            bad["CH陸用語"].append((en[:28], ch[:34], m.group(0)))
    for k, v in bad.items():
        print(f"  ❌ {k}: {len(v)}  {v[:3]}")
    if bad:
        print("機械檢查未過，未寫出批次檔。", file=sys.stderr)
        return 1
    print("  ✅ 機械檢查全過")

    patch: dict[str, dict] = collections.defaultdict(dict)
    for fk, en in gap.items():
        fname, _, key = fk.partition("|")
        t = idx[en]
        patch[f"{fname}.json"][key] = {"en": en, "ch": t["ch"], "cn": t["cn"]}
    items = [(f, k, v) for f, e in patch.items() for k, v in e.items()]
    n, B = len(items), max(1, args.batches)
    for i in range(B):
        chunk: dict[str, dict] = collections.defaultdict(dict)
        for f, k, v in items[i * n // B:(i + 1) * n // B]:
            chunk[f][k] = v
        p = Path(f"{args.out_prefix}_{i + 1}.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(chunk, fh, ensure_ascii=False, indent=1)
        print(f"  批 {i + 1}: {sum(len(v) for v in chunk.values())} 鍵 → {p}")
    print(f"展開 {n} 鍵、{len(patch)} 檔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
