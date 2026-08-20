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

# 角括號在 PZ 有**兩種**用途，不可用同一條規則檢查：
#   * 真標記 `<br> <LINE> <TEXT> <CENTRE> <SPACE> <RGB:..> <IMAGE:..>`——引擎解析，
#     必須逐字存活，翻了就壞版面。
#   * 顯示用文字 `<Hidden>`／`<static>`——玩家看得到，**本來就該翻**
#     （本體先例：`<噗滋>`／`<對講機雜訊>`／`<爆炸>`）。
# 故只對真標記做逐字守恆，另外用「角括號對數」抓括號被吃掉的情況。
PZ_TAG = r"<(?:br|BR|LINE|TEXT|CENTRE|CENTER|SPACE|RGB:[^>]*|IMAGE:[^>]*)>"
MARKUP = (
    (r"\[img=music\]", "img標記"), (r"\*\*", "雙星號"), (r"----", "斷訊殘字"),
    (PZ_TAG, "PZ標記"), (r"<", "角括號數"), (r"%[1-9]", "位置token"),
    (r"\{[a-zA-Z_]+\}", "大括號佔位"),
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
    # **`--result` 與 `--strings` 兩側都要受控拒絕**：兩者都是外部（工作流輸出）artifact，
    # 形狀壞掉時只有一邊給得出可讀訊息、另一邊拋裸 traceback，是無意義的不對稱。
    tr = res.get("translations") if isinstance(res, dict) else None
    if not isinstance(tr, list) or any(not isinstance(t, dict) for t in tr):
        print(f"❌ --result 的 translations 應為物件陣列，實得 "
              f"{type(tr).__name__}（頂層 {type(res).__name__}）", file=sys.stderr)
        return 1
    src = _jload(args.strings)
    # **wid 級跳過與 owner 衝突都要在這裡再擋一次**：`prep_mod_strings` 遇到缺 tracker
    # 基準／缺 `sources/en` 鏡像／state 落後於鏡像／同鍵多 owner 不同英文時會非零退出，
    # 但仍寫出 artifact（不寫的話舊的成功檔會留在原地被誤用，更糟）。而 artifact 少了
    # 這兩個欄位之外的任何跡象——`strings` 與 `_gap` 長得跟「這個 mod 沒缺口」一模一樣。
    # 只靠人盯退出碼＝#221 的管線級重演。
    # **欄位必須存在且型別精確**，不可寫成 `src.get(x) or []`：那會讓「舊版 prep 產出的
    # artifact（根本沒這兩欄）」與「欄位型別壞掉」雙雙判成安全通過，等於 gate 只在
    # 「新版 prep 且真的有衝突」時才生效——最該擋的陳舊 artifact 正好從縫裡走掉。
    # **`src` 本身先驗是 dict**：`--strings` 若是合法 JSON 的 list／字串／數字，
    # `src.get()` 會拋 AttributeError／TypeError traceback，而不是受控的 schema 拒絕。
    if not isinstance(src, dict):
        print(f"❌ 來源 artifact 頂層應為物件，實得 {type(src).__name__}"
              "（請以現行 `prep_mod_strings.py` 重新產生）", file=sys.stderr)
        return 1
    schema: dict[str, type] = {"_unchecked": list, "_owner_conflicts": dict}
    bad = [f"{k}：{'缺欄位' if k not in src else f'型別為 {type(src[k]).__name__}，應為 {t.__name__}'}"
           for k, t in schema.items() if not isinstance(src.get(k), t)]
    if bad:
        print("❌ 來源 artifact 的 fail-closed 欄位不合格，拒絕套用（請以現行 "
              "`prep_mod_strings.py` 重新產生）：", file=sys.stderr)
        for x in bad:
            print(f"   {x}", file=sys.stderr)
        return 1
    # `_undecidable` **不阻斷**（那是逐鍵盲區，不是整批不可用），但必須印出來：
    # 整個 mod 的 `extractor_schema < 9` 時 `_gap` 只剩 `translate_en`、rc=0，artifact 與
    # 「這個 mod 沒有物品名缺口」在管線上完全不可區分——正是本檔上方註解說的「只靠人盯
    # 退出碼＝#221 的管線級重演」。
    und = src.get("_undecidable")
    if isinstance(und, dict) and und:
        print(f"⚠️ 來源 artifact 有 {len(und)} 個 mod 的部分缺口不可判定"
              "（未列入缺口，也不算已覆蓋）：", file=sys.stderr)
        for wid, info in list(und.items())[:8]:
            print(f"   {wid}：{(info or {}).get('why')}", file=sys.stderr)
        if len(und) > 8:
            print(f"   ...（還有 {len(und) - 8} 個）", file=sys.stderr)
    blockers = [(k, src[k]) for k in schema if src[k]]
    if blockers:
        for field, val in blockers:
            print(f"❌ 來源 artifact 的 {field} 非空（{len(val)} 項），拒絕套用：",
                  file=sys.stderr)
            for x in (val if isinstance(val, list) else [f"{k} → {v}" for k, v in val.items()]):
                print(f"   {x}", file=sys.stderr)
        print("   `_unchecked`：先跑 `tracker.py backfill-en` 補齊基準／鏡像後重跑 prep。\n"
              "   `_owner_conflicts`：同一 fullType 被多個 mod 定義成不同英文，`ItemName`\n"
              "   是全域表、後載入者覆寫，須人工裁出對每個 owner 都成立的中性譯文後\n"
              "   直接寫進 `own_translations.json`（附 `_note` 記裁決理由）。", file=sys.stderr)
        return 1
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
        # 只抓「中文句子裡的三點」＝該正規化為「…」；ASCII 圖案／摩斯訊號式的
        # `... --- ...` 不是省略號，原樣保留才對。
        if re.search(r"[一-鿿]\s*\.\.\.|\.\.\.\s*[一-鿿]", ch):
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
