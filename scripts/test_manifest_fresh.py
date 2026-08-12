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

# 4. 來源缺席時 check 模式必須 fail-closed——「無法驗證」不等於「驗過沒問題」。
#    寫入模式維持原本的寬鬆行為（回 0），兩者不得混為一談。
orig_mods = build_mod.MODS_DIR
try:
    build_mod.MODS_DIR = Path(__file__).resolve().parent / "__no_such_dir__"
    assert _check() == 1, "sources/mods 缺席時 check 仍回報通過——假的 fail-closed"
    with contextlib.redirect_stdout(io.StringIO()):
        assert build_mod.cmd_manifest(check_only=False) == 0, "寫入模式的既有寬鬆行為不該被改掉"
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

print("✅ test_manifest_fresh：7 組情境全過")
