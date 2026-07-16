# /// script
# requires-python = ">=3.10"
# dependencies = ["opencc>=1.4.1"]
# ///
# pyright: reportMissingImports=false
"""
MinidoracatModLangFor42 build 管線（PZ B42 如一模組翻譯繁中版）

用途：把 sources/ 的 canonical import（CN）+ 人工真相層（opencc_fixes / ch_overrides）
      冪等再生成 MOD/.../Translate/{CH,CN} 成品；並由 metadata 彙整 README 支援清單。

使用方式：uv run scripts/build_mod.py [命令]

命令：
  build     - CH 再生(OpenCC s2twp) + 合併去重 + placeholder gate → 寫出成品（預設）
  manifest  - 由 metadata.json + mod_names_zh.json 生成 SUPPORTED_MODS.md，並更新 README 統計摘要

真相模型：CN 為衍生佈局的 canonical import；CH 由 CN 冪等再生
（OpenCC + opencc_fixes.json + ch_overrides.json），成品不手改。全程確定性輸出。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import opencc

# ============================================================
# 路徑配置
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent

SOURCES = PROJECT_ROOT / "sources"
MODS_DIR = SOURCES / "mods"
UNSORTED_CN = SOURCES / "_unsorted" / "CN"
LUA_SRC = SOURCES / "lua"
OPENCC_FIXES_JSON = SOURCES / "opencc_fixes.json"
CH_OVERRIDES_JSON = SOURCES / "ch_overrides.json"
PLACEHOLDER_EXCEPTIONS_JSON = SOURCES / "placeholder_exceptions.json"

MOD_MEDIA = (
    PROJECT_ROOT
    / "MOD"
    / "MinidoracatModLangFor42"
    / "Contents"
    / "mods"
    / "MinidoracatModLangFor42"
    / "42"
    / "media"
)
OUT_CH = MOD_MEDIA / "lua" / "shared" / "Translate" / "CH"
OUT_CN = MOD_MEDIA / "lua" / "shared" / "Translate" / "CN"
OUT_LUA = MOD_MEDIA / "lua" / "client"

README = PROJECT_ROOT / "README.md"
SUPPORTED_MODS_MD = PROJECT_ROOT / "SUPPORTED_MODS.md"
MOD_NAMES_ZH_JSON = SOURCES / "mod_names_zh.json"  # 人工真相：{wid: {name_zh, summary}}
MANIFEST_START = "<!-- SUPPORTED_MODS_START -->"
MANIFEST_END = "<!-- SUPPORTED_MODS_END -->"
WORKSHOP_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={}"

# language.txt：CH 結構照抄 LangFor42，CN 沿用同結構換 text 值
LANGUAGE_TXT = {
    "CH": "VERSION = 1,\ntext = Traditional Chinese,\ncharset = UTF-8,\n",
    "CN": "VERSION = 1,\ntext = Simplified Chinese,\ncharset = UTF-8,\n",
}

# ============================================================
# placeholder token 文法
# ============================================================
# multiset 比對用：% 格式 token + <...> 標籤，CN/CH 須逐一致
# conversion 只允許 %.Nf（f 限定）；%.N[其他字母] 太寬，會把崩潰簽名誤吞成合法 token，故收緊。
_FMT_TOKEN_RE = re.compile(r"%%|%\.\d+f|%\d+|%[sdi]|<[^<>]+>")
# 掃 grammar 之外的 % 用：只認 % 系列 token（不含標籤）
_PCT_TOKEN_RE = re.compile(r"%%|%\.\d+f|%\d+|%[sdi]")
# 「值是否含真正的 format token」用（不含 %% 與標籤）：%N/%s/%d/%i/%.Nf。
# 只有含 format token 的值，殘留的字面 %. 才會被 PZ 轉換 + JDK .formatted() 當成轉換符而崩潰。
_FMT_ONLY_RE = re.compile(r"%\.\d+f|%\d+|%[sdi]")
# 角括號內容含 CJK 者是文本（如 <吱吱声>、耐力<25%, 疲劳>80%），OpenCC 本就該轉換，
# 不得當標籤比對；真正的標籤（<br>、<LINE>、<RGB:...>）皆為 ASCII。
_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


def token_multiset(value: str) -> Counter:
    """抽取 allowlist 內的 format token 與標籤，回傳 multiset。"""
    tokens = [
        t for t in _FMT_TOKEN_RE.findall(value)
        if not (t.startswith("<") and _CJK_RE.search(t))
    ]
    return Counter(tokens)


def scan_percents(value: str) -> tuple[list[str], list[str]]:
    """掃 grammar 之外的 % 序列，分成 (崩潰阻斷, 警告) 兩桶，各回傳上下文片段。

    崩潰阻斷：值含 format token（%N/%s/%d/%i/%.Nf）且殘留字面 %.（% 緊接句點）——
      PZ 轉換後再經 JDK .formatted() 會拋 UnknownFormatConversionException
      （實例：Moodles 的 %1%.、EHR 遙測字串的 %.d）。
    警告：其餘 grammar 之外的 %（裸 %、無 format token 值裡的 %.）——非阻斷、僅提示。
    """
    has_fmt = bool(_FMT_ONLY_RE.search(value))
    blocking: list[str] = []
    warning: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        if value[i] == "%":
            m = _PCT_TOKEN_RE.match(value, i)
            if m:
                i = m.end()
                continue
            ctx = value[max(0, i - 8) : i + 9]
            if has_fmt and i + 1 < n and value[i + 1] == ".":
                blocking.append(ctx)
            else:
                warning.append(ctx)
            i += 1
        else:
            i += 1
    return blocking, warning


# ============================================================
# 通用 I/O
# ============================================================
def load_json(path: Path) -> dict:
    """讀 JSON（容忍 BOM）。"""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    """確定性寫出：UTF-8 無 BOM、indent 2、鍵排序、LF、尾端換行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


# ============================================================
# OpenCC 轉換（快取單一 converter 實例 + post_fixes）
# ============================================================
_CONVERTER: opencc.OpenCC | None = None


def get_converter() -> opencc.OpenCC:
    global _CONVERTER
    if _CONVERTER is None:
        _CONVERTER = opencc.OpenCC("s2twp")
    return _CONVERTER


def _require_truth_file(path: Path, label: str) -> None:
    """人工真相檔缺失即 fail（受版控真相檔，build 不自動建骨架）。"""
    if not path.exists():
        rel = path.relative_to(PROJECT_ROOT)
        print(
            f"❌ 人工真相檔缺失：{rel}（{label}）。此為受版控真相檔，"
            f"build 不會自動建立；請自版控還原該檔後重試。",
            file=sys.stderr,
        )
        sys.exit(1)


def load_post_fixes() -> list[tuple[re.Pattern, str]]:
    """載入 opencc_fixes.json 的 post_fixes（缺失即 fail，不建骨架）。"""
    _require_truth_file(OPENCC_FIXES_JSON, "OpenCC 修正字典")
    try:
        data = load_json(OPENCC_FIXES_JSON)
    except json.JSONDecodeError as exc:
        print(f"❌ opencc_fixes.json 格式錯誤：{exc}", file=sys.stderr)
        sys.exit(1)
    fixes: list[tuple[re.Pattern, str]] = []
    for group in data.get("post_fixes", []):
        for rule in group.get("rules", []):
            fixes.append((re.compile(rule["pattern"]), rule["replacement"]))
    return fixes


def load_overrides() -> dict[str, str]:
    """載入 ch_overrides.json（{"<檔名>|<鍵>": 值}；缺失即 fail，不建骨架）。"""
    _require_truth_file(CH_OVERRIDES_JSON, "人工繁中覆寫層")
    try:
        return load_json(CH_OVERRIDES_JSON)
    except json.JSONDecodeError as exc:
        print(f"❌ ch_overrides.json 格式錯誤：{exc}", file=sys.stderr)
        sys.exit(1)


def load_placeholder_exceptions() -> dict[str, dict]:
    """載入 placeholder_exceptions.json（登記制崩潰例外；缺失即 fail，不建骨架）。

    schema：{"<檔名>|<鍵>": {"cn_safe_value": "<安全 CN 值>", "reason": "..."}}。
    """
    _require_truth_file(PLACEHOLDER_EXCEPTIONS_JSON, "placeholder 登記制例外")
    try:
        data = load_json(PLACEHOLDER_EXCEPTIONS_JSON)
    except json.JSONDecodeError as exc:
        print(f"❌ placeholder_exceptions.json 格式錯誤：{exc}", file=sys.stderr)
        sys.exit(1)
    for exc_key, spec in data.items():
        if not isinstance(spec, dict) or "cn_safe_value" not in spec:
            print(
                f"❌ placeholder_exceptions.json 條目 {exc_key!r} 缺 cn_safe_value 欄位。",
                file=sys.stderr,
            )
            sys.exit(1)
    return data


def convert_value(
    text: str,
    post_fixes: list[tuple[re.Pattern, str]],
    fix_hits: Counter | None = None,
) -> str:
    """簡體 → 繁體（台灣用語）+ post_fixes。

    fix_hits 若提供，累計各 post_fix（以清單索引為鍵）的命中次數，供「零命中 pattern」報告。
    """
    result = get_converter().convert(text)
    for idx, (pattern, replacement) in enumerate(post_fixes):
        result, n = pattern.subn(replacement, result)
        if n and fix_hits is not None:
            fix_hits[idx] += n
    return result


# ============================================================
# 來源收集與合併（值感知去重）
# ============================================================
def collect_source_cn_dirs() -> list[Path]:
    """回傳所有 CN 來源目錄：sources/mods/<id>/CN + sources/_unsorted/CN（排序、unsorted 最後）。"""
    dirs: list[Path] = []
    if MODS_DIR.is_dir():
        for mod_dir in sorted(MODS_DIR.iterdir()):
            cn = mod_dir / "CN"
            if cn.is_dir():
                dirs.append(cn)
    if UNSORTED_CN.is_dir():
        dirs.append(UNSORTED_CN)
    return dirs


def merge_cn(dirs: list[Path]) -> tuple[dict[str, dict], list[str]]:
    """把各來源同名 <type>.json 合併。值感知去重：同 (檔,鍵) 同值靜默；異值列錯誤。"""
    merged: dict[str, dict] = {}
    origin: dict[tuple[str, str], Path] = {}
    conflicts: list[str] = []
    for cn_dir in dirs:
        for jf in sorted(cn_dir.glob("*.json")):
            fname = jf.name
            data = load_json(jf)
            fmap = merged.setdefault(fname, {})
            for key in sorted(data):
                val = data[key]
                if key in fmap:
                    if fmap[key] != val:
                        src_a = origin[(fname, key)].relative_to(PROJECT_ROOT)
                        src_b = jf.relative_to(PROJECT_ROOT)
                        conflicts.append(
                            f"  {fname} | {key}\n"
                            f"      {src_a} = {fmap[key]!r}\n"
                            f"      {src_b} = {val!r}"
                        )
                else:
                    fmap[key] = val
                    origin[(fname, key)] = jf
    return merged, conflicts


def apply_exceptions(
    merged_cn: dict[str, dict], exceptions: dict[str, dict]
) -> set[str]:
    """對登記的 (檔|鍵) 以 cn_safe_value 全域取代 merged CN 值（不分 owner；merge 已收斂為每鍵一值）。

    登記鍵因值被換成安全值，後續 placeholder gate 自然不再觸發崩潰簽名。回傳實際套用的登記鍵集合。
    """
    used: set[str] = set()
    for exc_key, spec in exceptions.items():
        fname, _, key = exc_key.partition("|")
        fmap = merged_cn.get(fname)
        if fmap is not None and key in fmap:
            fmap[key] = spec["cn_safe_value"]
            used.add(exc_key)
    return used


def regen_ch(
    merged_cn: dict[str, dict],
    post_fixes: list[tuple[re.Pattern, str]],
    overrides: dict[str, str],
    fix_hits: Counter | None = None,
) -> tuple[dict[str, dict], set[str]]:
    """CH 由 CN 冪等再生：OpenCC → post_fixes → ch_overrides（最後套）。

    回傳 (merged_ch, 實際套用的 ch_overrides 鍵集合)。fix_hits 透傳給 convert_value 累計命中。
    """
    merged_ch: dict[str, dict] = {}
    used_ov: set[str] = set()
    for fname, fmap in merged_cn.items():
        out: dict[str, str] = {}
        for key, cn_val in fmap.items():
            ov_key = f"{fname}|{key}"
            if ov_key in overrides:
                out[key] = overrides[ov_key]
                used_ov.add(ov_key)
            else:
                out[key] = convert_value(cn_val, post_fixes, fix_hits)
        merged_ch[fname] = out
    return merged_ch, used_ov


def placeholder_gate(
    merged_cn: dict[str, dict], merged_ch: dict[str, dict]
) -> tuple[list[str], list[str]]:
    """CN/CH token multiset 比對 + 崩潰簽名 gate + 可疑 % warning。回傳 (errors, warnings)。

    崩潰簽名 = 含 format token 的殘留字面 %.（JDK .formatted() 會拋例外）→ blocking error；
    CN 與 CH 都掃（登記例外已於 merge 換成安全值，故不會觸發）。裸 % 與無 format token 的 %.
    僅列 warning（沿用原行為只報 CN 側）。
    """
    errors: list[str] = []
    warnings: list[str] = []
    for fname in sorted(merged_cn):
        cn_map = merged_cn[fname]
        ch_map = merged_ch[fname]
        for key in sorted(cn_map):
            cn_val = cn_map[key]
            ch_val = ch_map[key]
            cn_tok = token_multiset(cn_val)
            ch_tok = token_multiset(ch_val)
            if cn_tok != ch_tok:
                diff_cn = cn_tok - ch_tok
                diff_ch = ch_tok - cn_tok
                errors.append(
                    f"  {fname} | {key}: token 不一致 "
                    f"CN多={dict(diff_cn)} CH多={dict(diff_ch)}\n"
                    f"      CN={cn_val!r}\n      CH={ch_val!r}"
                )
            cn_blk, cn_wrn = scan_percents(cn_val)
            ch_blk, _ = scan_percents(ch_val)
            for ctx in cn_blk:
                errors.append(
                    f"  {fname} | {key} [CN]: %. 崩潰簽名（含 format token，"
                    f"JDK .formatted() 會拋 UnknownFormatConversionException）...{ctx}...\n"
                    f"      → 修正上游或於 sources/placeholder_exceptions.json 登記安全值"
                )
            for ctx in ch_blk:
                errors.append(
                    f"  {fname} | {key} [CH]: %. 崩潰簽名（含 format token）...{ctx}..."
                )
            for ctx in cn_wrn:
                warnings.append(f"  {fname} | {key}: 可疑 % 序列 ...{ctx}...")
    return errors, warnings


# ============================================================
# build 命令
# ============================================================
def cmd_build() -> int:
    print("=" * 60)
    print("build：CH 再生 + 合併去重 + placeholder gate")
    print("=" * 60)

    dirs = collect_source_cn_dirs()
    if not dirs:
        print("❌ 找不到任何 CN 來源目錄（sources/mods/<id>/CN 或 sources/_unsorted/CN）。")
        print("   拆分（split_sources.py）尚未產出資料？請先執行拆分。")
        return 1

    merged_cn, conflicts = merge_cn(dirs)
    total_files = len(merged_cn)
    total_keys = sum(len(m) for m in merged_cn.values())
    if total_keys == 0:
        print("❌ 來源目錄存在但無任何 (檔,鍵)。無可 build 內容。")
        return 1
    print(f"  來源目錄 {len(dirs)} 個 → 合併 {total_files} 檔、{total_keys} 個 (檔,鍵)")

    # 人工真相層（缺失即 fail，不自動建骨架）
    post_fixes = load_post_fixes()
    overrides = load_overrides()
    exceptions = load_placeholder_exceptions()

    # 登記制崩潰例外：以 cn_safe_value 全域取代 As1 原值（CH 隨後由 safe CN 冪等再生）
    used_exc = apply_exceptions(merged_cn, exceptions)

    fix_hits: Counter = Counter()
    merged_ch, used_ov = regen_ch(merged_cn, post_fixes, overrides, fix_hits)

    errors, warnings = placeholder_gate(merged_cn, merged_ch)

    # Lua 複製計畫先算：basename 衝突屬硬錯，須在清空/寫出前先攔
    lua_plan, lua_conflicts = plan_lua()

    # gate：合併衝突 + placeholder 崩潰簽名/token 不一致 + Lua 衝突 → 不寫出、非零退出
    if conflicts or errors or lua_conflicts:
        if conflicts:
            print(f"\n❌ 合併衝突（同 (檔,鍵) 異值）{len(conflicts)} 處：")
            for c in conflicts:
                print(c)
        if errors:
            print(f"\n❌ placeholder gate {len(errors)} 處（崩潰簽名 / token 不一致）：")
            for e in errors:
                print(e)
        if lua_conflicts:
            print(f"\n❌ Lua basename 衝突 {len(lua_conflicts)} 處（拒絕覆寫）：")
            for c in lua_conflicts:
                print(f"  {c}")
        if warnings:
            print(f"\n⚠️ 另有 {len(warnings)} 處可疑 % 序列（非阻斷）：")
            for w in warnings[:50]:
                print(w)
        print("\n❌ build 失敗，未寫出成品。")
        return 1

    # 全部 gate 通過 → 精確鏡像：先清空本 build 擁有的輸出區再寫出
    # （只清 CN/CH 與 client/；勿碰 media/textures/ 靜態資產）
    clear_output_dir(OUT_CN)
    clear_output_dir(OUT_CH)
    clear_output_dir(OUT_LUA)

    for fname, fmap in merged_cn.items():
        write_json(OUT_CN / fname, fmap)
    for fname, fmap in merged_ch.items():
        write_json(OUT_CH / fname, fmap)
    write_text(OUT_CH / "language.txt", LANGUAGE_TXT["CH"])
    write_text(OUT_CN / "language.txt", LANGUAGE_TXT["CN"])
    lua_count = write_lua(lua_plan)

    print(f"\n✅ 已寫出 CN/CH 各 {total_files} 檔、language.txt ×2、Lua {lua_count} 檔")

    # 未消費人工真相報告（非阻斷，供檢視）
    report_unused(overrides, used_ov, exceptions, used_exc, post_fixes, fix_hits)

    if warnings:
        print(f"\n⚠️ {len(warnings)} 處可疑 % 序列（非阻斷，僅提示）：")
        for w in warnings[:50]:
            print(w)
        if len(warnings) > 50:
            print(f"  ... 還有 {len(warnings) - 50} 處")
    print("\n完成：build 綠。")
    return 0


def clear_output_dir(d: Path) -> None:
    """清空本 build 擁有的輸出目錄（精確鏡像，去除舊殘留）。勿用於 media/textures/ 靜態資產。"""
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)


def plan_lua() -> tuple[dict[str, Path], list[str]]:
    """規劃 sources/lua/<id>/*.lua → media/lua/client/ 的複製。

    回傳 ({目標 basename: 來源路徑}, [衝突訊息])。不同 <id> 下同 basename 視為衝突（拒絕覆寫）。
    """
    plan: dict[str, Path] = {}
    conflicts: list[str] = []
    if not LUA_SRC.is_dir():
        return plan, conflicts
    for sub in sorted(LUA_SRC.iterdir()):
        if not sub.is_dir():
            continue
        for lua in sorted(sub.glob("*.lua")):
            if lua.name in plan:
                conflicts.append(
                    f"{lua.name}：{plan[lua.name].relative_to(PROJECT_ROOT)} 與 "
                    f"{lua.relative_to(PROJECT_ROOT)} 同名"
                )
            else:
                plan[lua.name] = lua
    return plan, conflicts


def write_lua(plan: dict[str, Path]) -> int:
    """依 plan_lua 的計畫複製 Lua（OUT_LUA 已由 clear_output_dir 清空）。"""
    count = 0
    for name, src in sorted(plan.items()):
        OUT_LUA.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, OUT_LUA / name)
        count += 1
    return count


def report_unused(
    overrides: dict[str, str],
    used_ov: set[str],
    exceptions: dict[str, dict],
    used_exc: set[str],
    post_fixes: list[tuple[re.Pattern, str]],
    fix_hits: Counter,
) -> None:
    """報告未被消費的人工真相（非阻斷）：ch_overrides 未命中鍵、placeholder_exceptions 未命中鍵、
    opencc_fixes 零命中 pattern。這些多半是鍵名過時或改寫後遺留，值得人工回頭確認。"""
    unused_ov = sorted(set(overrides) - used_ov)
    unused_exc = sorted(set(exceptions) - used_exc)
    zero_fixes = [
        post_fixes[i][0].pattern
        for i in range(len(post_fixes))
        if fix_hits.get(i, 0) == 0
    ]
    if not (unused_ov or unused_exc or zero_fixes):
        return
    print("\n⚠️ 未消費人工真相（非阻斷，請檢視是否過時或鍵名有誤）：")
    for k in unused_ov:
        print(f"  ch_overrides 未命中：{k}")
    for k in unused_exc:
        print(f"  placeholder_exceptions 未命中：{k}")
    for p in zero_fixes:
        print(f"  opencc_fixes 零命中 pattern：{p!r}")


# ============================================================
# manifest 命令
# ============================================================
def cmd_manifest() -> int:
    print("=" * 60)
    print("manifest：由 metadata.json 彙整 README 支援清單")
    print("=" * 60)

    if not MODS_DIR.is_dir():
        print("⚠️ 找不到 sources/mods/，README 未更新。")
        return 0

    rows: list[tuple[str, str, list[str], int]] = []
    for mod_dir in sorted(MODS_DIR.iterdir()):
        if not mod_dir.is_dir():
            continue
        ws_id = mod_dir.name
        meta_path = mod_dir / "metadata.json"
        meta = load_json(meta_path) if meta_path.exists() else {}
        mod_ids = meta.get("mod_ids")
        if not mod_ids:
            mod_ids = [meta["mod_id"]] if meta.get("mod_id") else []
        name = meta.get("name") or meta.get("title") or ws_id
        cn = mod_dir / "CN"
        key_count = 0
        if cn.is_dir():
            for jf in cn.glob("*.json"):
                key_count += len(load_json(jf))
        rows.append((ws_id, name, mod_ids, key_count))

    if not rows:
        print("⚠️ sources/mods/ 無任何 MOD 目錄，未更新。")
        return 0

    names_zh: dict = load_json(MOD_NAMES_ZH_JSON) if MOD_NAMES_ZH_JSON.exists() else {}

    def cell(text: str) -> str:
        # Markdown 表格安全：去換行、跳脫直線
        return str(text).replace("\n", " ").replace("|", "\\|").strip() or "—"

    all_mod_ids = {m for _, _, mod_ids, _ in rows for m in mod_ids}
    lines = ["| MOD | 中文名稱 | 摘要 | Mod IDs | 鍵數 |", "| --- | --- | --- | --- | --- |"]
    for ws_id, name, mod_ids, key_count in rows:
        link = f"[{cell(name)}]({WORKSHOP_URL.format(ws_id)})"
        ids = ", ".join(f"`{m}`" for m in mod_ids) if mod_ids else "—"
        zh = names_zh.get(ws_id, {})
        lines.append(
            f"| {link} | {cell(zh.get('name_zh', ''))} | {cell(zh.get('summary', ''))} | {ids} | {key_count} |"
        )
    table = "\n".join(lines)
    print(f"  彙整 {len(rows)} 個 MOD（中文名稱覆蓋 {sum(1 for w, *_ in rows if w in names_zh)} 個）")

    page = (
        "# 支援 MOD 清單\n\n"
        "> 本檔由 `uv run scripts/build_mod.py manifest` 自動生成，請勿手動編輯。\n"
        "> 中文名稱與摘要維護於 `sources/mod_names_zh.json`，修改後重跑 manifest。\n\n"
        f"共支援 **{len(rows)} 個 Workshop 模組**（{len(all_mod_ids)} 個 mod ID）。\n\n"
        f"{table}\n"
    )
    old_page = SUPPORTED_MODS_MD.read_text(encoding="utf-8") if SUPPORTED_MODS_MD.exists() else None
    if page != old_page:
        SUPPORTED_MODS_MD.write_text(page, encoding="utf-8", newline="\n")
        print(f"✅ 已更新 {SUPPORTED_MODS_MD.name}（{len(rows)} 個 MOD）")
    else:
        print(f"ℹ️ {SUPPORTED_MODS_MD.name} 內容未變動")

    if not README.exists():
        print(f"⚠️ README 不存在（{README.name}），跳過更新。")
        return 0
    content = README.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(MANIFEST_START) + r".*?" + re.escape(MANIFEST_END), re.DOTALL
    )
    if not pattern.search(content):
        print(
            f"❌ README 內找不到 {MANIFEST_START} ... {MANIFEST_END} 標記，無法更新支援清單。",
            file=sys.stderr,
        )
        return 1
    summary_line = (
        f"共支援 **{len(rows)} 個 Workshop 模組**（{len(all_mod_ids)} 個 mod ID），"
        f"完整清單（含中文名稱與摘要）見 [SUPPORTED_MODS.md](./SUPPORTED_MODS.md)。"
    )
    replacement = f"{MANIFEST_START}\n{summary_line}\n{MANIFEST_END}"
    updated = pattern.sub(lambda _m: replacement, content)
    if updated != content:
        README.write_text(updated, encoding="utf-8", newline="\n")
        print(f"✅ 已更新 {README.name} 支援清單摘要")
    else:
        print("ℹ️ README 支援清單摘要未變動")
    return 0


# ============================================================
# 入口
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="MinidoracatModLangFor42 build 管線",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例：
  uv run scripts/build_mod.py build      # CH 再生 + 合併 + placeholder gate + 寫出（預設）
  uv run scripts/build_mod.py manifest   # 生成 SUPPORTED_MODS.md + 更新 README 摘要
        """,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="build",
        choices=["build", "manifest"],
        help="執行的命令（預設：build）",
    )
    args = parser.parse_args()

    if args.command == "build":
        sys.exit(cmd_build())
    elif args.command == "manifest":
        sys.exit(cmd_manifest())


if __name__ == "__main__":
    main()
