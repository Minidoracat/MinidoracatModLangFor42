# /// script
# requires-python = ">=3.10"
# ///
"""把補譯結果寫入 sources/own_translations.json。

    uv run scripts/apply_translations.py <翻譯檔.json>

翻譯檔格式：`{"<檔名>": {"<鍵>": {"en": ..., "ch": ..., "cn": ...}}}`

落地前的硬檢查（任一不過即中止、不寫檔）：
  * en/ch/cn 三欄皆非空——schema 要求，缺一 build 會 fail
  * ch/cn 不得含裸 `%`——own_translations 是人工真相層，字面百分號須直寫 `%%`，
    否則 42.20.1 的 formatted() 會拋 UnknownFormatConversionException 黑畫面
  * ch/cn 的 format token 與 en 一致——防止翻譯時漏掉或多出 %d/%1/%s
  * 鍵不得撞 vanilla（對 vanilla_keys.json 與本機官方 Translate/EN 雙查，
    allowlist 登記者除外）——收錄鐵律：vanilla override 影響未裝該 mod 的玩家
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_GAME = Path("D:/SteamLibrary/steamapps/common/ProjectZomboid/media/lua/shared/Translate/EN")
TOKEN = re.compile(r"%%|%[1-9]|%[sdi]|%\+?\.[0-9]{1,2}f")


def _jload(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def escape_bare(s: str) -> str:
    """把裸 `%` 逸出為 `%%`，合法 token 原樣保留（同 build 的 sanitize 語意）。

    必須 left-to-right 且先消費 `%%`——全域 re.sub 會把 `%%1` 改壞（AGENTS.md 實證）。
    """
    out, i, n = [], 0, len(s)
    while i < n:
        m = TOKEN.match(s, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        out.append("%%" if s[i] == "%" else s[i])
        i += 1
    return "".join(out)


def bare_percent(s: str) -> bool:
    """去掉合法 token 後仍有 `%` ＝ 裸百分號。left-to-right 消費，不可用全域 sub。"""
    i, n = 0, len(s)
    while i < n:
        m = TOKEN.match(s, i)
        if m:
            i = m.end()
            continue
        if s[i] == "%":
            return True
        i += 1
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    args = ap.parse_args()
    incoming = _jload(Path(args.infile))

    v = _jload(ROOT / "sources/vanilla_keys.json")
    van = set(v["keys"])
    van |= {k.split("_", 1)[1] for k in van if "_" in k}
    if BASE_GAME.is_dir():
        for jf in BASE_GAME.glob("*.json"):
            try:
                van |= set(_jload(jf))
            except Exception:  # noqa: BLE001
                pass
    allow = set(v.get("allowlist", {}))

    errs: list[str] = []
    total = 0
    for fname, entries in incoming.items():
        for k, spec in entries.items():
            total += 1
            for col in ("en", "ch", "cn"):
                if not isinstance(spec.get(col), str) or not spec[col].strip():
                    errs.append(f"{fname}|{k}: {col} 缺失或空白")
            if errs and errs[-1].startswith(f"{fname}|{k}"):
                continue
            for col in ("ch", "cn"):
                if bare_percent(spec[col]):
                    errs.append(f"{fname}|{k}: {col} 含裸 % → {spec[col]!r}")
            # token 比對須拿 **EN 逸出後**的形式當基準：上游 EN 常帶裸 `%`
            # （例 `75% chance`），而我方人工真相層必須直寫 `%%`，否則 42.20.1 的
            # formatted() 會拋 UnknownFormatConversionException。直接比原始 EN 會誤判。
            en_safe = sorted(TOKEN.findall(escape_bare(spec["en"])))
            for col in ("ch", "cn"):
                b = sorted(TOKEN.findall(spec[col]))
                if en_safe != b:
                    errs.append(f"{fname}|{k}: {col} format token 與 sanitize(en) 不符 {en_safe} vs {b}")
            if k in van and k not in allow:
                errs.append(f"{fname}|{k}: 撞 vanilla 鍵（鐵律不得 override）")
    if errs:
        print(f"❌ {len(errs)} 項檢查未過，未寫入：", file=sys.stderr)
        for e in errs[:25]:
            print("   " + e, file=sys.stderr)
        return 1

    own_p = ROOT / "sources/own_translations.json"
    own = _jload(own_p)
    added = updated = 0
    for fname, entries in incoming.items():
        bucket = own["entries"].setdefault(fname, {})
        for k, spec in entries.items():
            if k in bucket:
                updated += 1
            else:
                added += 1
            # 保留 `_note` 等底線開頭欄位：那是人工裁決記錄（多 owner 中性譯法的理由、
            # 型號依據等），覆寫成三欄會把它靜默清掉，下一個人就看不到裁決依據了。
            keep = {c: v for c, v in bucket.get(k, {}).items() if c.startswith("_")}
            bucket[k] = {"en": spec["en"], "ch": spec["ch"], "cn": spec["cn"], **keep}
    with open(own_p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(own, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"✅ {total} 鍵通過檢查；新增 {added}、更新 {updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
