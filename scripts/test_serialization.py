# /// script
# requires-python = ">=3.10"
# ///
"""受版控 JSON 的行尾／編碼正規形式 gate。

存在理由：真相層與成品的 JSON 沒有任何一道 gate 在看**序列化形式**——build／verify／
lint 全部先 `json.load` 再比對語意，行尾對它們一律透明。於是任何漏掉 `newline="\\n"`
的寫檔（Windows 預設把 `\\n` 轉成 `\\r\\n`）都能把整棵樹重寫成 CRLF 而三道全綠。

實際發生過：2026-08-19 清償 34 張「可能過時」issue 時，一次性落地腳本寫
`sources/ch/*.json`／`own_translations.json`／`cn_overrides.json` 時漏了 `newline`，
把 11 個檔寫成 CRLF、其中 6 個 indent 從 2 變 1。內容完全正確、build／verify 15/15／
lint 棘輪全零，但 `git diff` 從應有的約 7,300 行膨脹成 **234,769 insertions／227,622
deletions**——review 在那個規模下等於無法進行。是人眼看 diff 大小才發現的。

同批也發現 `sources/snapshot.json` 自 dd31b14 起就是 CRLF 且無尾端換行（repo 自己的
`split_sources.py` 寫它時帶 `newline="\\n"`），已一併正規化，故本 gate 為零基線棘輪。

**不變量是「寫受版控 JSON 不得讓行尾被平台改寫」**，不是禁用某個 API。兩條正確路徑：
文字模式必須顯式帶 `newline="\\n"`（`Path.write_text(text, encoding="utf-8", newline="\\n")`
與 `open(p, "w", encoding="utf-8", newline="\\n")` 皆可）；二進位模式寫入已含 LF 的 bytes
（`path.write_bytes(...)`）本就不做行尾轉換，天生安全。repo 既有實例：
`build_mod.write_json`／`tracker.write_json`／`apply_translations.py` 屬前者，
`split_sources` 的 bulk 輸出屬後者（`dumps_canonical` 只負責序列化、不寫檔，
其文字模式呼叫端才帶 `newline`）。**文字模式漏掉 `newline` 才是缺陷。**

**為什麼不能靠 `.gitattributes` 解決**：本 repo 的 `.gitattributes` 是 `* -text`，
刻意**停用** git 的行尾轉換——因為 dist 與 sources 受 `verify_dist.py` 位元組級核對，
讓 git 在 checkout/commit 時改寫行尾會直接破壞那些比對。也就是說 git 不會幫你把 CRLF
正規化回 LF，寫進去什麼就 commit 什麼（本機 `core.autocrlf=true` 也被 `-text` 蓋掉）。
在維持該政策的前提下，這道「看產出、不看誰寫」的下游 gate 是能攔住的位置。

檢查對象刻意涵蓋三棵樹：`sources/`（人工真相＋split 衍生）、`tracker-state/*.json`
（CI 寫入）、`MOD/**/Translate/`（build 產出，受版控故新 clone 未跑 build 也存在）。
`tracker-state/_dl` 是 steamcmd 下載的上游內容、已 gitignore，明確排除。

本 gate **不管 indent**（已知 accepted residual risk）：`sources/` 現況 indent 1 與 2 混用，
另有一批 own lane 手編檔與 metadata 不符任何機械正規形式——把 indent 寫死會逼人重排大量
既有檔案。代價是「LF 但改錯 indent」的同類 churn 仍會放行；行尾會讓**每一行**都變 diff，
那才是傷害最大的部分，故先守這一層。存量數字一律不寫死（下限語意見 `TREES` 第三欄）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (標籤, glob, 檔數下限) —— 第三欄是**棘輪下限**：擋 glob 退化與目錄搬遷造成的覆蓋崩塌。
# 只驗 n > 0 擋不住 `sources/**/*.json` 被寫成 `sources/*.json`（仍命中十餘個頂層檔
# 而全綠，卻漏掉 sources/ch/*.json——正是 2026-08-19 出事的那批）。
# sources 與 dist 的下限留有餘裕（約數十個 mod／九組檔名家族）；`tracker-state` 的 3
# **刻意零餘裕**——那三個是永久狀態檔（timestamps／en_corpus_hashes／watchlist），
# 少一個就該紅。只有 intentional 的大量刪除才調低下限，否則要修的是 glob 或佈局。
TREES: tuple[tuple[str, str, int], ...] = (
    ("sources", "sources/**/*.json", 3000),
    ("tracker-state", "tracker-state/*.json", 3),
    ("dist", "MOD/**/Translate/**/*.json", 150),
)
BOM = b"\xef\xbb\xbf"
FIXME = (
    "受版控 JSON 不得讓行尾被平台改寫。文字模式須顯式帶 newline='\\n'（"
    "Path.write_text(text, encoding='utf-8', newline='\\n') 或 "
    "open(p, 'w', encoding='utf-8', newline='\\n')）；二進位模式寫已含 LF 的 bytes "
    "（path.write_bytes(...)）天生安全。文字模式漏掉 newline 在 Windows 會產生 CRLF。"
    "優先呼叫既有 writer：build_mod.write_json／tracker.write_json。"
)


def violations(path: Path) -> list[str]:
    """回傳該檔違反的正規形式條目；空 list ＝ 合規。"""
    raw = path.read_bytes()
    bad = []
    if raw.startswith(BOM):
        bad.append("有 UTF-8 BOM")
    if b"\r" in raw:
        bad.append("含 CR（CRLF 或孤立 CR）")
    # 尾端必須恰為一個 \n：不可只排除 b"\n\n"——`}\n \n` 與 `}\n\t\n` 都以單一 \n 結尾
    # 且 json.loads 容忍尾端空白，會整批假通過。以「剝掉尾端空白後補一個 \n」比對。
    # rstrip 集合刻意**不含 \r**：含了會讓 CRLF 檔同時被判「尾端非恰一個換行」，而那句
    # 對它是假描述（它只有一個換行，只是帶 CR）。排除 \r 後 CRLF 只報 CR，其餘案例
    # （缺換行／多餘空行／尾端空白／尾端 tab／孤立 CR 結尾／空檔）偵測結果完全不變。
    if raw.rstrip(b" \t\n") + b"\n" != raw:
        bad.append("尾端非恰一個換行（缺換行／多餘空行／尾端空白）")
    try:
        json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        bad.append("非合法 UTF-8")
    except json.JSONDecodeError as e:
        bad.append(f"JSON 解析失敗：{e}")
    return bad


def scan(tree_root: Path, pattern: str) -> tuple[int, list[str]]:
    """掃一棵樹，回傳 (檔數, 違規描述)。排除 gitignore 的 `_dl` 下載暫存。"""
    found, bad = 0, []
    for p in sorted(tree_root.glob(pattern)):
        if "_dl" in p.parts:
            continue
        found += 1
        if v := violations(p):
            bad.append(f"{p.relative_to(tree_root)}：{'、'.join(v)}")
    return found, bad


# 1. 現況零違反，且每棵樹的檔數不得低於下限（覆蓋崩塌棘輪）
total, all_bad = 0, []
per_tree = {}
for _label, _pattern, _floor in TREES:
    # 下限被調成 0 就等於繳銷整道覆蓋棘輪（只剩「零違反」而不管掃到幾個檔）。
    # 測試無法防自身被刻意削弱，但把 0 擋掉能攔住「為了讓 CI 變綠而歸零」這種順手之舉。
    assert _floor > 0, f"TREES 的 {_label} 下限為 {_floor}——下限必須為正，否則覆蓋棘輪失效"
for label, pattern, floor in TREES:
    n, bad = scan(ROOT, pattern)
    assert n >= floor, (
        f"{label}（{pattern}）只掃到 {n} 個檔，低於下限 {floor}——"
        "glob 退化或目錄被搬移，gate 覆蓋率已崩塌。要修的通常是 glob 或佈局；"
        "只有 intentional 的大量刪除才調低 TREES 該列的第三欄下限。"
    )
    per_tree[label] = n
    total += n
    all_bad += bad
assert not all_bad, (
    f"❌ {len(all_bad)} 個受版控 JSON 不符行尾／編碼正規形式：\n  "
    + "\n  ".join(all_bad[:30])
    + f"\n\n{FIXME}"
)

# 2. 每一種違規都要真的抓得到——否則第 1 條是永遠為真的假綠燈。
#    在 temp 目錄造樣本，真檔全程不動。
CASES: tuple[tuple[str, bytes, str], ...] = (
    ("CRLF", b'{\r\n "a": 1\r\n}\r\n', "含 CR"),
    ("孤立 CR", b'{\r "a": 1\r}\n', "含 CR"),
    ("BOM", BOM + b'{\n "a": 1\n}\n', "BOM"),
    ("缺尾端換行", b'{\n "a": 1\n}', "尾端非恰一個換行"),
    ("尾端多餘空行", b'{\n "a": 1\n}\n\n', "尾端非恰一個換行"),
    ("尾端空白＋換行", b'{\n "a": 1\n}\n \n', "尾端非恰一個換行"),
    # `}\n\t\n` 才是註解點名的漏洞形（以單一 \n 結尾、json.loads 容忍）；
    # `}\n\t`（無最終 LF）只驗到一般的缺換行，鎖不住它。兩者都收。
    ("尾端 tab＋換行", b'{\n "a": 1\n}\n\t\n', "尾端非恰一個換行"),
    ("尾端純 tab", b'{\n "a": 1\n}\n\t', "尾端非恰一個換行"),
    ("壞 JSON", b'{\n "a": \n}\n', "JSON 解析失敗"),
    ("非 UTF-8", b'{\n "a": "\xff\xfe"\n}\n', "UTF-8"),
)
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    for name, payload, expect in CASES:
        f = tmp / f"{name}.json"
        f.write_bytes(payload)
        got = violations(f)
        assert any(expect in g for g in got), f"{name} 未被抓到（實得 {got}）"
    clean = tmp / "clean.json"
    clean.write_bytes(b'{\n "a": 1\n}\n')
    assert violations(clean) == [], f"乾淨檔被誤報：{violations(clean)}"

# 3. scan() → 違規清單這條**串接**也要驗：只驗 violations() 這個述詞的話，
#    收集端（`if v := violations(p)`）被改壞時 CASES 與第 1 條會同時保持全綠。
#    同時驗 `_dl` 排除確實生效——用遞迴 pattern 才測得到（正式 TREES 的
#    tracker-state 是單層 glob，本來就進不去 _dl，直接斷言等於恆真）。
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    (tmp / "good").mkdir()
    (tmp / "good" / "ok.json").write_bytes(b'{\n "a": 1\n}\n')
    (tmp / "good" / "bad.json").write_bytes(b'{\r\n "a": 1\r\n}\r\n')
    (tmp / "_dl").mkdir()
    (tmp / "_dl" / "upstream.json").write_bytes(b'{\r\n "a": 1\r\n}\r\n')
    n, bad = scan(tmp, "**/*.json")
    assert n == 2, f"_dl 未被排除或掃錯檔數（實得 {n}）"
    assert len(bad) == 1 and "bad.json" in bad[0], f"scan 未把真檔違規浮上來（實得 {bad}）"
    assert all("upstream.json" not in b for b in bad), f"_dl 內容被納入回報：{bad}"

# 4. 官方寫檔器的**行為**回歸：第 1 條只看樹的結果，要等 CRLF 真的落地才會紅。
#    三支 writer 的輸出一律須為 LF。CRLF 前置只對 `reanchor_registries.write_json`
#    **承重**——它原本 `path.read_bytes()` 嗅探目標檔行尾並沿用（2026-08-19 移除），
#    沒有這條的話那個嗅探能被重新加回而 CI 全綠。`build_mod`／`tracker` 從不讀目標檔
#    （後者寫同目錄 .tmp 再 os.replace），對它們這是一般的「輸出必為 LF」contract。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402
import reanchor_registries  # noqa: E402
import tracker  # noqa: E402

WRITERS = (
    ("build_mod.write_json", lambda p, d: build_mod.write_json(p, d)),
    ("tracker.write_json", lambda p, d: tracker.write_json(p, d)),
    ("reanchor_registries.write_json", lambda p, d: reanchor_registries.write_json(p, d)),
)
with tempfile.TemporaryDirectory() as td:
    for label, writer in WRITERS:
        target = Path(td) / f"{label.replace('.', '_')}.json"
        # 統一預置 CRLF 檔。這個前提只對 reanchor 承重（它原本會讀目標檔嗅探行尾）；
        # build_mod／tracker 不讀目標檔，對它們純粹是驗「輸出必為 LF」。
        target.write_bytes(b'{\r\n "old": 1\r\n}\r\n')
        writer(target, {"k": "值"})
        out = target.read_bytes()
        assert b"\r" not in out, (
            f"{label} 寫出 CR：{out[:40]!r}\n"
            "  → 文字模式漏了 newline='\\n'，或（僅 reanchor）行尾嗅探被重新加回。"
        )
        assert violations(target) == [], f"{label} 產出不符正規形式：{violations(target)}"
        assert json.loads(out.decode("utf-8")) == {"k": "值"}, f"{label} 寫出的內容不對：{out[:60]!r}"

print(
    f"✅ test_serialization：{total} 個受版控 JSON 全合規"
    f"（{'／'.join(f'{k} {v}' for k, v in per_tree.items())}）"
    f"、{len(CASES)} 種違規皆可偵測、scan 串接與 _dl 排除已驗"
)
