# /// script
# requires-python = ">=3.10"
# ///
"""SUPPORTED_MODS.md／README 摘要不得與來源漂移的回歸測試。

背景：這兩處是 `build_mod.py manifest` 的生成物，但**改了來源卻沒重跑 manifest
時沒有任何 gate 攔得到**——build 不碰它們、verify_dist 只驗 dist、lint 只掃譯文。
實例：`cfcf3d8` 給 3628922658 補了 18 個裸 ItemName 鍵（總鍵數 628→646），
SUPPORTED_MODS.md 卻一直寫 628，隔天有人剛好重生才發現，等於玩家看了一天錯數字。

放這裡而不是 verify_dist：freshness 必須拿生成器的輸出來比對，而
`verify_dist.py` 開宗明義「這是獨立 oracle：絕不 import 或共用 build_mod.py
的任何函式」——把它塞進去會破壞那個立身原則。測試套件本來就會 import build 端。

執行：uv run scripts/test_manifest_fresh.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import contextlib
import json
import io
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402


def _check() -> int:
    """跑 check_only，吞掉輸出只取退出碼。"""
    with contextlib.redirect_stdout(io.StringIO()):
        return build_mod.cmd_manifest(check_only=True)


# 1. 現況必須同步——不同步就是有人改了 sources 沒重跑 manifest
assert _check() == 0, (
    "SUPPORTED_MODS.md / README 摘要與來源不同步。"
    "請重跑：uv run scripts/build_mod.py manifest"
)

# 2. check_only 不得寫檔——它會在收尾驗證裡跑，不能有副作用
real = build_mod.SUPPORTED_MODS_MD
before = real.read_text(encoding="utf-8")
_check()
assert real.read_text(encoding="utf-8") == before, "check_only 不該寫檔"

# 2b. support universe = metadata ∪ active registry；retired veto；registry-only 鍵數未知。
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    mods = root / "sources" / "mods"
    mods.mkdir(parents=True)
    registry_path = root / "sources" / "mod_registry.json"
    registry_path.write_text(json.dumps({"mods": {
        "111": {"status": "active", "source": "test", "verified": "2026-08-30",
                "name": "Registry Alpha", "mod_ids": ["RegA"]},
        "222": {"status": "active", "source": "test", "verified": "2026-08-30",
                "name": "Registry Only", "mod_ids": ["RegOnly"]},
        "333": {"status": "retired", "source": "test", "verified": "2026-08-30",
                "name": "Retired", "mod_ids": ["Retired"]},
    }}), encoding="utf-8")
    fixtures = {
        "111": ({"workshop_id": "111", "name": "Metadata Alpha", "mod_ids": ["MetaA"]},
                {"A": "甲", "B": "乙"}),
        "333": ({"workshop_id": "333", "name": "Should Disappear", "mod_ids": ["Old"]},
                {"K": "舊"}),
        "444": ({"workshop_id": "444", "name": "Own Mod", "mod_ids": ["Own"],
                 "origin": "own"}, {"K": "自有"}),
    }
    for wid, (meta, cn) in fixtures.items():
        d = mods / wid
        (d / "CN").mkdir(parents=True)
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "CN" / "UI.json").write_text(json.dumps(cn), encoding="utf-8")
    old_mods, old_registry = build_mod.MODS_DIR, build_mod.MOD_REGISTRY_JSON
    old_sources, old_vanilla = build_mod.SOURCES, build_mod.VANILLA_KEYS_JSON
    registry_original = registry_path.read_text(encoding="utf-8")
    try:
        build_mod.MODS_DIR, build_mod.MOD_REGISTRY_JSON = mods, registry_path
        rows = build_mod._collect_manifest_rows()
        by_id = {row[0]: row for row in rows}
        assert set(by_id) == {"111", "222", "444"}, (
            f"metadata∪active/retired veto 錯誤：{sorted(by_id)}"
        )
        assert by_id["111"][1:4] == ("Metadata Alpha", ["MetaA"], 2), by_id["111"]
        assert by_id["222"][1:4] == ("Registry Only", ["RegOnly"], None), by_id["222"]
        meta111 = mods / "111" / "metadata.json"
        bad_meta = json.loads(meta111.read_text(encoding="utf-8"))
        bad_meta["workshop_id"] = "999"
        meta111.write_text(json.dumps(bad_meta), encoding="utf-8")
        try:
            build_mod._collect_manifest_rows()
            raise AssertionError("manifest 未擋 metadata workshop_id/目錄名不一致")
        except ValueError:
            pass
        bad_meta["workshop_id"] = "111"
        meta111.write_text(json.dumps(bad_meta), encoding="utf-8")
        assert by_id["444"][1].endswith("〔原創翻譯〕") and by_id["444"][3] == 1
        orphan_cn = mods / "777" / "CN"
        orphan_cn.mkdir(parents=True)
        try:
            build_mod._collect_manifest_rows()
            raise AssertionError("manifest 未擋缺 metadata 的 partial source mod 目錄")
        except ValueError:
            pass
        orphan_cn.rmdir()
        orphan_cn.parent.rmdir()

        # registry-only 仍應用 sources/en 算「覆寫本體」，不能因沒有 metadata 一律顯示 ?。
        vanilla_path = root / "sources" / "vanilla_keys.json"
        vanilla_path.write_text(json.dumps({
            "scoped_keys": {"UI.json": ["UI_Vanilla"]}
        }), encoding="utf-8")
        en = root / "sources" / "en"
        en.mkdir()
        (en / "222.json").write_text(json.dumps({
            "translate_en|mods/R/42.20/media/lua/shared/Translate/EN/UI.json|UI_Vanilla": "V"
        }), encoding="utf-8")
        build_mod.SOURCES, build_mod.VANILLA_KEYS_JSON = root / "sources", vanilla_path
        counts = build_mod.vanilla_override_counts()
        assert counts["222"] == 1 and "333" not in counts, counts

        # metadata 完全為零仍須能由 active registry 建立支援宇宙。
        empty_mods = root / "empty-mods"
        empty_mods.mkdir()
        build_mod.MODS_DIR = empty_mods
        zero_rows = build_mod._collect_manifest_rows()
        assert {r[0] for r in zero_rows} == {"111", "222"} and all(
            r[3] is None for r in zero_rows
        ), zero_rows

        registry_path.write_text(json.dumps({"mods": {
            "333": {
                "status": "retired", "source": "test", "verified": "2026-08-30"
            }
        }}), encoding="utf-8")
        assert build_mod._collect_manifest_rows() == [], "全 retired/零 metadata 應為 zero rows"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert build_mod.cmd_manifest(check_only=True) == 1
            assert build_mod.cmd_manifest(check_only=False) == 1
        registry_path.write_text(registry_original, encoding="utf-8")
    finally:
        build_mod.MODS_DIR, build_mod.MOD_REGISTRY_JSON = old_mods, old_registry
        build_mod.SOURCES, build_mod.VANILLA_KEYS_JSON = old_sources, old_vanilla

# 3. 真的漂移時要抓得到——否則第 1 條是永遠為真的假綠燈。
#    把常數指向 temp 副本再擾動，**真檔全程不動**：測試中斷也不會留下髒生成物。
with tempfile.TemporaryDirectory() as td:
    fake = Path(td) / "SUPPORTED_MODS.md"
    fake.write_text(before + "\n<!-- drift -->\n", encoding="utf-8", newline="\n")
    try:
        build_mod.SUPPORTED_MODS_MD = fake
        assert _check() == 1, "生成物被改動後 check 仍回報同步——漂移偵測失效"
    finally:
        build_mod.SUPPORTED_MODS_MD = real
assert real.read_text(encoding="utf-8") == before, "測試不該動到真的生成物"

# 4. metadata 來源目錄缺席時，check/write 都必須 fail-closed 且不可改寫生成物。
#    目錄存在但 metadata 為零可由 active registry bootstrap（2b 已驗）；整個目錄消失
#    無法區分合法空集合與來源被刪除，不能把 no-op 當成功。
orig_mods = build_mod.MODS_DIR
try:
    build_mod.MODS_DIR = Path(__file__).resolve().parent / "__no_such_dir__"
    assert _check() == 1, "sources/mods 缺席時 check 仍回報通過——假的 fail-closed"
    with contextlib.redirect_stdout(io.StringIO()):
        assert build_mod.cmd_manifest(check_only=False) == 1, \
            "sources/mods 缺席時 write no-op 卻回成功"
finally:
    build_mod.MODS_DIR = orig_mods

# 5. README 缺席同樣要 fail-closed——只驗了 SUPPORTED_MODS.md 那半段就報綠是假綠燈。
orig_readme = build_mod.README
try:
    build_mod.README = Path(__file__).resolve().parent / "__no_such_readme__.md"
    assert _check() == 1, "README 缺席時 check 仍回報通過——摘要那半段根本沒驗到"
    with contextlib.redirect_stdout(io.StringIO()):
        assert build_mod.cmd_manifest(check_only=False) == 0, "寫入模式的既有寬鬆行為不該被改掉"
finally:
    build_mod.README = orig_readme

# 6. --check 只對 manifest 有意義：`build --check` 必須被擋下，
#    否則使用者以為在 dry-run，實際跑的是會覆蓋成品的 cmd_build()。
for argv in (["build", "--check"], ["--check"]):  # 後者靠 command 預設值落到 build
    sys.argv = ["build_mod.py", *argv]
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            build_mod.main()
    except SystemExit as exc:
        assert exc.code == 2, f"{argv} 應被 argparse 擋下（exit 2），實際 {exc.code}"
    else:  # pragma: no cover — main() 一定會 sys.exit
        raise AssertionError(f"{argv} 未被擋下")

# 7. 表格欄數合約：header／分隔列／資料列的欄數必須齊一。
#    前六條都是「生成器輸出 vs 生成物」比對，兩邊一起錯照樣全綠——加欄位時改了
#    header 卻漏改 row_line（或反之）正是這種同步性錯誤，產出的 Markdown 會渲染
#    錯位而 build／verify／lint 三道無感。欄數寫死＝合約變更必須顯式改這裡。
page = real.read_text(encoding="utf-8")
head, sep, tail = page.partition("\n## 已下架模組")
assert sep, "已下架模組區塊不見了——欄數合約只驗到一半"


def _cols(line: str) -> int:
    """Markdown 表格列的欄數。cell() 把值內的 | 跳脫成 \\|，切欄時不可命中它。"""
    return len(re.split(r"(?<!\\)\|", line.strip())) - 2


# 欄位合約：MOD／中文名稱／摘要／Mod IDs／鍵數／覆寫本體／涵蓋範圍（＋已下架區多一欄下架偵測）
for label, chunk, want in (("在架", head, 7), ("已下架", tail, 8)):
    widths = {_cols(ln) for ln in chunk.splitlines() if ln.startswith("|")}
    assert widths == {want}, f"{label}表欄數不齊：{sorted(widths)}，應全為 {want}"

# --- 8. STEAM_DESCRIPTION.md 模組數 ＋ workshop.txt description 的同步 --------- #
# 這兩個是「數字會靜默過期」的既有實證：README／SUPPORTED_MODS 由 manifest 自動改所以
# 一直對，STEAM_DESCRIPTION.md 是手寫的，42.20.2-1.18.0 同步 As1 v3.7.1（+75 個 MOD）
# 那次漏更新、同類漏更新發生過兩次（470+ 停在 458+13 的年代，實際已 564）。
# 全部用 temp 副本，真檔不動。
SD_LINE = "[*] 560+ 個 Workshop 模組（710+ 個模組 ID）的中文翻譯\n"
WS_HEAD = "version=1\r\nid=123\r\ntitle=T\r\n"
WS_TAIL = "tags=\r\nvisibility=public\r\n"


def _sync(sd_text: str | None, ws_text: str | None, *, mods=564, ids=715,
          check_only=True):
    """在 temp 目錄跑 _sync_steam_description，回傳 (drift, sd 內容, ws 內容)。"""
    with tempfile.TemporaryDirectory() as td:
        sd, ws = Path(td) / "STEAM_DESCRIPTION.md", Path(td) / "workshop.txt"
        if sd_text is not None:
            sd.write_text(sd_text, encoding="utf-8", newline="\n")
        if ws_text is not None:
            with open(ws, "w", encoding="utf-8", newline="") as fh:
                fh.write(ws_text)
        o_sd, o_ws = build_mod.STEAM_DESCRIPTION_MD, build_mod.WORKSHOP_TXT
        build_mod.STEAM_DESCRIPTION_MD, build_mod.WORKSHOP_TXT = sd, ws
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                drift = build_mod._sync_steam_description(mods, ids, check_only)
        finally:
            build_mod.STEAM_DESCRIPTION_MD, build_mod.WORKSHOP_TXT = o_sd, o_ws
        return (drift,
                sd.read_text(encoding="utf-8") if sd.exists() else None,
                open(ws, encoding="utf-8", newline="").read() if ws.exists() else None)


def _ws_from(sd_text: str) -> str:
    body = sd_text.split("\n")
    if body and body[-1] == "":
        body.pop()
    return WS_HEAD + "".join(f"description={l}\r\n" for l in body) + WS_TAIL


# 8a. 現況同步 → 零漂移
d, _, _ = _sync(SD_LINE, _ws_from(SD_LINE))
assert d == [], f"同步狀態不該報漂移：{d}"

# 8b. 模組數過期 → check 抓到（這條是本節的承重點：470+ 那個實際發生過的錯）
stale = SD_LINE.replace("560+ 個 Workshop 模組（710+", "470+ 個 Workshop 模組（600+")
d, _, _ = _sync(stale, _ws_from(stale))
assert "STEAM_DESCRIPTION.md" in d, "模組數過期必須被抓到"

# 8c. 約數規則＝向下取整到十位。寫成 `>=` 區間會讓「560+」在實際 640 時仍算成立，
#     數字就會一路失真下去——這條釘死那個判準。
d, _, _ = _sync(SD_LINE, _ws_from(SD_LINE), mods=640, ids=800)
assert "STEAM_DESCRIPTION.md" in d, "實際值遠高於宣稱時仍須報漂移（約數是取整、不是下限）"
for actual, want in ((564, 560), (560, 560), (569, 560), (570, 570)):
    d, sd_new, _ = _sync(SD_LINE, _ws_from(SD_LINE), mods=actual, ids=715,
                         check_only=False)
    assert f"{want}+ 個 Workshop 模組" in sd_new, f"{actual} 應取整為 {want}+，實得 {sd_new!r}"

# 8d. write 模式修好後，再 check 必須乾淨（round-trip）
d, sd_new, _ = _sync(stale, _ws_from(stale), check_only=False)
assert "560+ 個 Workshop 模組（710+ 個模組 ID）" in sd_new, "write 模式應修好模組數"
d2, _, ws_new = _sync(sd_new, _ws_from(sd_new))
assert d2 == [], f"修好後 check 應乾淨：{d2}"

# 8e. workshop.txt 的 description 與 STEAM_DESCRIPTION 不同步 → 抓到
d, _, _ = _sync(SD_LINE, WS_HEAD + "description=舊內容\r\n" + WS_TAIL)
assert "workshop.txt" in d, "workshop.txt description 漂移必須被抓到"

# 8f. write 模式重生 workshop.txt：head／tail 原樣保留、行尾維持 CRLF、逐行前綴
d, _, ws_new = _sync(SD_LINE, WS_HEAD + "description=舊\r\n" + WS_TAIL, check_only=False)
assert ws_new.startswith(WS_HEAD) and ws_new.endswith(WS_TAIL), \
    "head／tail 是遊戲回寫的正式格式，重生時必須原樣保留"
assert "\n" not in ws_new.replace("\r\n", ""), "workshop.txt 必須維持 CRLF"
assert f"description={SD_LINE.rstrip(chr(10))}\r\n" in ws_new, "description 應逐行前綴"

# 8g. 三種 fail-closed：檔案缺席、找不到數字那一行、workshop.txt 形狀壞損。
#     「沒驗到」不等於「驗過沒問題」。
assert "STEAM_DESCRIPTION.md" in _sync(None, _ws_from(SD_LINE))[0], \
    "STEAM_DESCRIPTION 缺席須 fail-closed"
assert "STEAM_DESCRIPTION.md" in _sync("[*] 沒有數字那一行\n", None)[0], \
    "找不到數字那一行須 fail-closed"
assert "workshop.txt" in _sync(SD_LINE, None)[0], "workshop.txt 缺席須 fail-closed"
for bad, why in ((f"id=1\r\nversion=1\r\ntitle=T\r\n{WS_TAIL}", "head 順序錯"),
                 (WS_HEAD + "description=x\r\n", "tail 缺失")):
    assert "workshop.txt" in _sync(SD_LINE, bad)[0], f"{why} 須 fail-closed"

# 9. STEAM_CHANGELOG.md（Workshop 更新註記）的版號新鮮度。
#    承重點：它是 release 必改檔，卻長期沒有 gate——最近 7 個 tag 裡漏更 3 次
#    （v42.20.2-1.18.0／-1.18.1 停在 1.17.0、v42.20.2-1.19.0 停在 1.18.1），
#    連 `b055581`「補上 42.20.2-1.17.0 漏更的 STEAM_CHANGELOG」之後的下一版都又漏了。
#    **刻意只驗版號、不自動生成內容**：那份 BBCode 是人工為 Workshop 讀者重寫的
#    （1.18.1 的第二點在該檔被改寫並補上逐 MOD 鍵數，與 CHANGELOG 原文不同），
#    自動生成等於用 CHANGELOG 原文蓋掉潤飾過的文案。
H1 = "[h1][B42]繁體簡體模組翻譯 By Minidoracat 如一漢化組 {}[/h1]\n[i]2026-08-26[/i]\n"


def _notes(sc_text: str | None, mod_info: str | None, changelog: str | None):
    """在 temp 目錄跑 check_release_notes，回傳 drift 清單。"""
    with tempfile.TemporaryDirectory() as td:
        paths, originals = {}, (
            build_mod.STEAM_CHANGELOG_MD, build_mod.MOD_INFO, build_mod.CHANGELOG_MD)
        for name, text in (("STEAM_CHANGELOG.md", sc_text), ("mod.info", mod_info),
                           ("CHANGELOG.md", changelog)):
            p = Path(td) / name
            if text is not None:
                p.write_text(text, encoding="utf-8", newline="\n")
            paths[name] = p
        (build_mod.STEAM_CHANGELOG_MD, build_mod.MOD_INFO,
         build_mod.CHANGELOG_MD) = (paths["STEAM_CHANGELOG.md"], paths["mod.info"],
                                    paths["CHANGELOG.md"])
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return build_mod.check_release_notes()
        finally:
            (build_mod.STEAM_CHANGELOG_MD, build_mod.MOD_INFO,
             build_mod.CHANGELOG_MD) = originals


V, OLD = "42.20.4-1.20.0", "42.20.2-1.18.1"
MI = f"name=x\nid=y\nmodversion={V}\nversionMin=42.20.4\n"
CL = f"# Changelog\n\n## [{V}] - 2026-08-26\n\n### Fixed\n\n- x\n\n## [{OLD}] - 2026-08-24\n"

# 9a. 三處一致 → 零漂移
assert _notes(H1.format(V), MI, CL) == [], "三處版號一致不該報漂移"

# 9b. **實際發生過的錯**：release bump 了 modversion，STEAM_CHANGELOG 停在舊版
assert _notes(H1.format(OLD), MI, CL) == ["STEAM_CHANGELOG.md"], \
    "STEAM_CHANGELOG 版號落後未被抓到——這正是漏更 4 次的那個缺口"

# 9c. CHANGELOG 最新版區塊落後（release commit 漏改 CHANGELOG）也要抓
stale_cl = f"# Changelog\n\n## [{OLD}] - 2026-08-24\n"
assert _notes(H1.format(V), MI, stale_cl) == ["STEAM_CHANGELOG.md"], \
    "CHANGELOG 版號不一致須報漂移"

# 9d. `[Unreleased]` 不得被當成版號（正則要求開頭是數字）
unrel = f"# Changelog\n\n## [Unreleased]\n\n## [{V}] - 2026-08-26\n"
assert _notes(H1.format(V), MI, unrel) == [], "[Unreleased] 應被跳過、取下一個版本區塊"

# 9e. 四種 fail-closed：三個檔各自缺席、首行形狀不符。「沒驗到」不等於「驗過沒問題」。
assert _notes(None, MI, CL) == ["STEAM_CHANGELOG.md"], "STEAM_CHANGELOG 缺席須 fail-closed"
assert _notes(H1.format(V), None, CL) == ["STEAM_CHANGELOG.md"], "mod.info 缺席須 fail-closed"
assert _notes(H1.format(V), MI, None) == ["STEAM_CHANGELOG.md"], "CHANGELOG 缺席須 fail-closed"
for bad, why in (("沒有 h1 的第一行\n", "首行非 [h1]"),
                 ("[h1][/h1]\n", "抓不到版號"),
                 ("", "空檔")):
    assert _notes(bad, MI, CL) == ["STEAM_CHANGELOG.md"], f"{why} 須 fail-closed"

# 9f. modversion／CHANGELOG 抓不到版號同樣 fail-closed（不可因「來源壞掉」就放行）
assert _notes(H1.format(V), "name=x\nid=y\n", CL) == ["STEAM_CHANGELOG.md"], \
    "mod.info 無 modversion 須 fail-closed"
assert _notes(H1.format(V), MI, "# Changelog\n\n沒有版本區塊\n") == ["STEAM_CHANGELOG.md"], \
    "CHANGELOG 無版本區塊須 fail-closed"

print("✅ test_manifest_fresh：9 組情境全過"
      "（含 STEAM_DESCRIPTION 模組數取整判準、workshop.txt CRLF 與 head/tail 保留、"
      "STEAM_CHANGELOG 版號新鮮度與 [Unreleased] 跳過，共十一種 fail-closed）")
