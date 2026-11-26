# /// script
# requires-python = ">=3.10"
# ///
"""登記簿錨點重算：值只動了標點/空白時，重算 hash 而非重新裁決。

    uv run scripts/reanchor_registries.py [--base HEAD] [--write]

兩本登記簿各自把「當時的值」壓成 hash 當錨點，值一變就失效、命中重新計入棘輪：

  * `sources/ch_review_state.json`      → 錨點是 **dist CN** 值
  * `sources/opencc_fixes.json` 的 `lint_exemptions` → 錨點是 **sources/ch** corpus 值

這是刻意設計：值變了就該重審。但**標點正規化**（全形→半形、補句號後空格）會
一口氣打掉幾十個錨點，而裁決的語意前提一個字都沒動——逐筆手工重算既無聊又易錯
（實測三輪稽核各踩一次）。本工具只處理這種情形。

**fail-closed**：以 `--base` 的版本為對照，把兩邊的空白與標點全部剝除後比對；
不相同者＝語意有變，**一律不重錨**並列出來要求人工重新裁決。
不帶 `--write` 只報告。

`--glyph-fold`：出貨字元代換表（`sources/glyph_fold.json`）新增來源字後，含該字的已審
有效 CN 值（dist）跟著變；只對「`--base` 版背書有效、且新值就是 base 值代換後」的條目重錨，
其餘不動。base 一律對 base 版的 dist 與台帳算，commit 前改了表要重跑：先
`git restore sources/ch_review_state.json` 再跑。改既有來源字的代換字（不是新增）不支援。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from build_mod import fold_glyphs, sanitize_format_tokens

ROOT = Path(__file__).resolve().parent.parent
DIST_CN_REL = "MOD/MinidoracatModLangFor42/Contents/mods/MinidoracatModLangFor42/42/media/lua/shared/Translate/CN"
DIST_CN = ROOT / DIST_CN_REL
# 剝除域：空白 ＋ 兩岸半形/全形標點。刻意**不含**頓號與省略號——那兩個是實詞層級的
# 選擇（rules.md 明列為例外），動了就該重審。
STRIP = re.compile(r"[\s,.;:!?，。？！：；]")


def h16(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def norm(value: str) -> str:
    return STRIP.sub("", value)


def git_show(ref: str, path: str) -> dict:
    out = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"讀不到 {ref}:{path} — {out.stderr.strip()}")
    return json.loads(out.stdout)


def git_load_dir(ref: str, path: str) -> dict[str, dict]:
    """`ref:path` 底下全部 *.json（一次 `git cat-file --batch`；檔名含 `[` 不能走 pathspec）。"""
    ls = subprocess.run(["git", "ls-tree", "-z", "--name-only", f"{ref}:{path}"], cwd=ROOT,
                        capture_output=True)
    if ls.returncode != 0:
        raise SystemExit(f"讀不到 {ref}:{path} — {ls.stderr.decode('utf-8', 'replace').strip()}")
    names = [n for n in ls.stdout.decode("utf-8").split("\0") if n.endswith(".json")]
    req = "".join(f"{ref}:{path}/{n}\n" for n in names).encode("utf-8")
    raw = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, input=req,
                         capture_output=True, check=True).stdout
    out: dict[str, dict] = {}
    pos = 0
    for name in names:
        nl = raw.index(b"\n", pos)
        header = raw[pos:nl].split()
        if len(header) != 3 or header[1] != b"blob":
            raise SystemExit(f"讀不到 {ref}:{path}/{name}")
        size = int(header[2])
        out[name] = json.loads(raw[nl + 1 : nl + 1 + size].decode("utf-8-sig"))
        pos = nl + 1 + size + 1
    return out


def glyph_fold_anchors(st: dict, base_st: dict, base_cn: dict[str, dict]) -> tuple[int, list[str]]:
    """就地重錨 st（工作樹台帳）；回 (重錨數, 拒絕說明)。

    只動 base 版背書有效（`base_st` 錨點＝h16(base dist CN 值)）、且代換後值不同的條目；
    工作樹錨點已是新 hash 視為完成，既不是舊 hash 也不是新 hash 就拒絕（有人另改過）。
    """
    fixed, refused = 0, []
    for rkey, old in sorted(base_st.items()):
        if "|" not in rkey:
            continue                       # 非錨點條目（如 _keep_rationale）
        f, _, k = rkey.partition("|")
        was = base_cn.get(f, {}).get(k)
        if not isinstance(was, str) or old != h16(was):
            continue                       # base 版就沒有有效背書，不代為背書
        new = h16(fold_glyphs(was))
        if new == old or st.get(rkey) == new:
            continue
        if st.get(rkey) == old:
            st[rkey] = new
            fixed += 1
        else:
            refused.append(f"  ⚠ ch_review_state {rkey}：工作樹錨點已另外改過，未重錨")
    return fixed, refused


def write_json(path: Path, data: dict, sort_keys: bool = False) -> None:
    """就地改寫，**一律 LF**。

    `.gitattributes` 是 `* -text`（禁止 git 行尾轉換），所以行尾是檔案內容的一部分，
    漏指定 `newline` 在 Windows 上會寫出 CRLF。本函式因此顯式寫死 LF。

    歷史：這裡原本會嗅探該檔原有行尾並沿用，理由是「`ch_review_state.json` 一向是
    CRLF，寫死 LF 會產生 16,112 行整檔 diff」。該前提已不成立——兩個目標檔現皆為 LF
    （`scripts/test_serialization.py` 把「受版控 JSON 一律 LF」升成零基線棘輪）。
    沿用嗅探反而會在 CRLF 因任何路徑回流時**原樣固化**，讓 gate 紅燈而成因難查。
    """
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=sort_keys)  # 兩個目標檔都是 indent 2
        f.write("\n")


def load_dir(path: Path) -> dict[str, dict]:
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(path.glob("*.json"))}


def reanchor(name: str, entries: dict, get_anchor, set_anchor, cur: dict, base: dict) -> tuple[int, list[str]]:
    """回傳 (重錨數, 拒絕重錨的說明)。cur/base 皆為 {檔名: {鍵: 值}}。"""
    fixed, refused = 0, []
    for rkey in sorted(entries):
        if "|" not in rkey:
            continue                       # 非錨點條目（如 _keep_rationale）
        fname, _, key = rkey.partition("|")
        now = cur.get(fname, {}).get(key)
        if not isinstance(now, str) or get_anchor(entries[rkey]) == h16(now):
            continue                       # 不在範圍 / 錨點仍有效
        was = base.get(fname, {}).get(key)
        if isinstance(was, str) and norm(was) == norm(now):
            set_anchor(entries[rkey], h16(now))
            fixed += 1
        else:
            refused.append(f"  ⚠ {name} {rkey}：非純標點變動，須重新裁決")
    return fixed, refused


def main() -> int:
    ap = argparse.ArgumentParser(description="標點正規化後的登記簿錨點重算")
    ap.add_argument("--base", default="HEAD", help="對照版本（預設 HEAD）")
    ap.add_argument("--write", action="store_true", help="實際寫檔（預設只報告）")
    ap.add_argument("--glyph-fold", action="store_true",
                    help="出貨字元代換表新增來源字後重錨 ch_review_state（見檔頭）")
    args = ap.parse_args()

    if args.glyph_fold:
        st_p = ROOT / "sources/ch_review_state.json"
        st = json.loads(st_p.read_text(encoding="utf-8"))
        base_cn = git_load_dir(args.base, DIST_CN_REL)
        # registry 背書對「出貨抑制前」的合併值算（build check_registry_ack），被本體／unshipped
        # 抑制、不在 dist 的 registry 鍵改用 base 版登記值補上（2026-11-26 實測 1 鍵：Tooltip_PillsBetablocker）
        for rel, field in (("sources/cn_overrides.json", "value"),
                           ("sources/placeholder_exceptions.json", "cn_safe_value")):
            for rkey, spec in git_show(args.base, rel).items():
                f, _, k = rkey.partition("|")
                if k and isinstance(spec, dict) and isinstance(spec.get(field), str):
                    base_cn.setdefault(f, {}).setdefault(k, sanitize_format_tokens(spec[field]))
        n, refused = glyph_fold_anchors(st, git_show(args.base, "sources/ch_review_state.json"), base_cn)
        print(f"ch_review_state 字元代換重錨 {n}　拒絕 {len(refused)}")
        for line in refused:
            print(line)
        if args.write and n:
            write_json(st_p, st)  # 保留原鍵序（台帳不是排序檔），diff 只有改到的錨點
            print("✅ 已寫入")
        elif not args.write:
            print("（唯讀模式，加 --write 才寫檔）")
        return 1 if refused else 0

    refused: list[str] = []
    total = 0

    # [1] ch_review_state — 錨點是 dist CN 值。dist 是生成物、base 版取不到，
    #     故拿現行 dist CN 對 base 版 own_translations 的 cn 欄比對；corpus 鍵的 CN
    #     源自 As1 快照，標點正規化不會動它，本工具自然不會碰到。
    st_p = ROOT / "sources/ch_review_state.json"
    st = json.loads(st_p.read_text(encoding="utf-8"))
    cur_cn = load_dir(DIST_CN)
    base_src = git_show(args.base, "sources/own_translations.json").get("entries", {})
    base_cn = {f: {k: s.get("cn", "") for k, s in d.items()} for f, d in base_src.items()}
    n1 = 0
    for rkey, anchor in list(st.items()):
        if "|" not in rkey:
            continue                       # 非錨點條目（如 _keep_rationale）
        f, _, k = rkey.partition("|")
        now = cur_cn.get(f, {}).get(k)
        if not isinstance(now, str) or anchor == h16(now):
            continue                       # 不在 dist / 錨點仍有效
        was = base_cn.get(f, {}).get(k)
        # dist 值已過出貨字元代換，own 真相的 cn 欄沒有，比對前先同樣代換
        if isinstance(was, str) and norm(fold_glyphs(was)) == norm(now):
            st[rkey] = h16(now)
            n1 += 1
        else:
            refused.append(f"  ⚠ ch_review_state {rkey}：非純標點變動，須重新裁決")
    total += n1

    # [2] lint_exemptions — 錨點是 sources/ch corpus 值
    fx_p = ROOT / "sources/opencc_fixes.json"
    fx = json.loads(fx_p.read_text(encoding="utf-8"))
    ex = fx.get("lint_exemptions", {})
    # lint_ch 掃描的 corpus ＝ sources/ch **合併 own 的 ch 欄**，故錨點可能指向 own 層的鍵。
    # 只查 sources/ch 會靜默漏掉那些（實測一次：兩筆 own 層豁免被漏、[A] 誤報復活）。
    cur_ch = load_dir(ROOT / "sources/ch")
    cur_own = json.loads((ROOT / "sources/own_translations.json").read_text(encoding="utf-8"))
    for fname, bucket in cur_own.get("entries", {}).items():
        cur_ch.setdefault(fname, {}).update(
            {k: v["ch"] for k, v in bucket.items() if isinstance(v.get("ch"), str)})
    base_ch: dict[str, dict] = {}
    for fname in cur_ch:
        try:
            base_ch[fname] = git_show(args.base, f"sources/ch/{fname}")
        except SystemExit:
            base_ch[fname] = {}
    for fname, bucket in base_src.items():
        base_ch.setdefault(fname, {}).update(
            {k: v.get("ch", "") for k, v in bucket.items()})
    n2, r2 = reanchor("lint_exemptions", ex,
                      lambda spec: spec.get("ch_value"),
                      lambda spec, h: spec.__setitem__("ch_value", h),
                      cur_ch, base_ch)
    total += n2
    refused += r2

    print(f"ch_review_state 重錨 {n1}　lint_exemptions 重錨 {n2}　合計 {total}")
    for line in refused:
        print(line)
    if not args.write:
        print("（唯讀模式，加 --write 才寫檔）")
        return 1 if refused else 0
    if n1:
        write_json(st_p, st)  # 保留原鍵序：台帳不是排序檔，sort_keys 會整檔重排
    if n2:
        write_json(fx_p, fx)
    print("✅ 已寫入")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
