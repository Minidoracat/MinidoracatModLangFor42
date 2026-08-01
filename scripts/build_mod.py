# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
MinidoracatModLangFor42 build 管線（PZ B42 如一模組翻譯繁中版）

用途：把 sources/ 的 canonical import（CN）+ 人工真相層（sources/ch corpus）
      合併成 MOD/.../Translate/{CH,CN} 成品；並由 metadata 彙整 README 支援清單。

使用方式：uv run scripts/build_mod.py [命令]

命令：
  build     - 合併去重 + corpus/worklist/placeholder gate → 寫出成品（預設）
  manifest  - 由 metadata.json + mod_names_zh.json 生成 SUPPORTED_MODS.md，並更新 README 統計摘要

真相模型：CN 為衍生佈局的 canonical import；CH 為 sources/ch/ 人工真相 corpus
（已斷絕 OpenCC 機轉；新增/變更鍵由 AI/人工對照 EN＋術語表直譯後落 corpus）。
build 僅做合併與把關，不做任何文字轉換。全程確定性輸出。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

# ============================================================
# 路徑配置
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent

SOURCES = PROJECT_ROOT / "sources"
MODS_DIR = SOURCES / "mods"
UNSORTED_CN = SOURCES / "_unsorted" / "CN"
LUA_SRC = SOURCES / "lua"
CH_CORPUS_DIR = SOURCES / "ch"
WORKLIST_JSON = SOURCES / "ch_sync_worklist.json"
REVIEW_STATE_JSON = SOURCES / "ch_review_state.json"
CN_OVERRIDES_JSON = SOURCES / "cn_overrides.json"
PLACEHOLDER_EXCEPTIONS_JSON = SOURCES / "placeholder_exceptions.json"
OWN_TRANSLATIONS_JSON = SOURCES / "own_translations.json"

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
# 角括號內容含 CJK 者是文本（如 <吱吱声>、耐力<25%, 疲劳>80%），屬翻譯文字一部分，
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
# 人工真相層載入
# ============================================================
def _require_truth_file(path: Path, label: str) -> None:
    """人工真相檔缺失即 fail（受版控真相檔，build 不自動建骨架）。"""
    if not path.exists():
        try:
            rel = path.relative_to(PROJECT_ROOT)
        except ValueError:  # 路徑不在 repo 下（如測試 monkeypatch）——錯誤路徑不得再擲錯
            rel = path
        print(
            f"❌ 人工真相檔缺失：{rel}（{label}）。此為受版控真相檔，"
            f"build 不會自動建立；請自版控還原該檔後重試。",
            file=sys.stderr,
        )
        sys.exit(1)


def load_ch_corpus() -> dict[str, dict]:
    """載入 sources/ch/ 人工繁中 corpus（缺失即 fail，不建骨架）。

    corpus 為人工真相層：CH 不再由 CN 機轉再生，逐鍵值以本目錄為準。
    """
    if not CH_CORPUS_DIR.is_dir():
        print(
            "❌ 人工真相層缺失：sources/ch/（人工繁中 corpus）。此為受版控真相目錄，"
            "build 不會自動建立；請自版控還原後重試。",
            file=sys.stderr,
        )
        sys.exit(1)
    corpus: dict[str, dict] = {}
    for jf in sorted(CH_CORPUS_DIR.glob("*.json")):
        try:
            data = load_json(jf)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as exc:
            print(f"❌ sources/ch/{jf.name} 讀取失敗：{exc}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(data, dict):
            print(f"❌ sources/ch/{jf.name} 頂層非物件。", file=sys.stderr)
            sys.exit(1)
        corpus[jf.name] = data
    return corpus


def load_sync_worklist() -> dict[str, dict]:
    """讀 ch_sync_worklist.json 的待辦條目（不含 | 的鍵為 _comment 等說明欄）。

    本檔為受版控狀態檔、As1 同步「值變更」的單點防線：**缺失即 fail**——
    「待辦清空」以「僅剩說明欄的物件」表示，絕不以「檔案不存在」表示
    （否則一次誤刪即可靜默繞過整道防線）。split_sources.py 於偵測到 CN
    差異時寫入；逐條翻譯落 corpus 後移除，build 於仍有未滿足條目時拒絕出貨。
    """
    _require_truth_file(WORKLIST_JSON, "As1 同步 worklist")
    try:
        data = load_json(WORKLIST_JSON)
    except json.JSONDecodeError as exc:
        print(f"❌ ch_sync_worklist.json 格式錯誤：{exc}", file=sys.stderr)
        sys.exit(1)
    return {k: v for k, v in data.items() if "|" in k}


def load_review_state() -> dict[str, str]:
    """載入 ch_review_state.json（已審台帳：<檔>|<鍵> → 有效 CN 值 sha256[:16]）。"""
    _require_truth_file(REVIEW_STATE_JSON, "CH 逐項審查台帳")
    try:
        data = load_json(REVIEW_STATE_JSON)
    except json.JSONDecodeError as exc:
        print(f"❌ ch_review_state.json 格式錯誤：{exc}", file=sys.stderr)
        sys.exit(1)
    out: dict[str, str] = {}
    for k, v in data.items():
        if "|" not in k:
            continue  # _comment 等說明欄
        if not isinstance(v, str):
            print(f"❌ ch_review_state.json 條目 {k!r} 值非字串。", file=sys.stderr)
            sys.exit(1)
        out[k] = v
    return out


def check_registry_ack(
    merged_cn: dict[str, dict], used_keys: set[str], review_state: dict[str, str]
) -> list[str]:
    """registry（cn_overrides / placeholder_exceptions）改的是 build 期 CN 值，
    split 的 worklist diff 看不到——以已審台帳強制背書：每個命中鍵的現行有效
    CN 值 hash 必須與 ch_review_state 登記一致，否則拒絕出貨。
    這確保每次 registry 改值都必經「檢視 sources/ch 對應鍵是否同步」的明示動作。
    """
    errors: list[str] = []
    for reg_key in sorted(used_keys):
        fname, _, key = reg_key.partition("|")
        expect = hashlib.sha256(merged_cn[fname][key].encode("utf-8")).hexdigest()[:16]
        got = review_state.get(reg_key)
        if got != expect:
            hint = "未登記" if got is None else f"hash 不符（登記 {got}）"
            errors.append(
                f"  {reg_key}：{hint}——請確認 sources/ch 對應鍵已同步後，"
                f"於 ch_review_state.json 登記 {expect}"
            )
    return errors


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


def load_cn_overrides() -> dict[str, dict]:
    """載入 cn_overrides.json（CN 人工修正層；缺失即 fail，不建骨架）。

    schema：{"<檔名>|<鍵>": {"value": "<修正後 CN 值>", "reason": "..."}}。
    用途：修 As1 上游的錯字／疊字等錯誤。CN 不再要求與 As1 快照逐字一致——
    登記於此的鍵，verify_dist 的 CN parity 改對登記值核對（oracle 效力保留）。
    """
    _require_truth_file(CN_OVERRIDES_JSON, "CN 人工修正層")
    try:
        data = load_json(CN_OVERRIDES_JSON)
    except json.JSONDecodeError as exc:
        print(f"❌ cn_overrides.json 格式錯誤：{exc}", file=sys.stderr)
        sys.exit(1)
    for ov_key, spec in data.items():
        if ov_key.startswith("_"):
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get("value"), str):
            print(
                f"❌ cn_overrides.json 條目 {ov_key!r} 缺 value 欄位（須為字串）。",
                file=sys.stderr,
            )
            sys.exit(1)
    return data


def load_own_translations() -> dict[str, dict[str, dict]]:
    """載入 own_translations.json（原創翻譯層；缺失即 fail，不建骨架）。

    schema：{"entries": {"<檔名>": {"<鍵>": {"en": 上游原文, "ch": 繁中, "cn": 簡中}}}}。
    ch 為直寫繁中（不經 OpenCC）；en 供上游過時比對。
    """
    _require_truth_file(OWN_TRANSLATIONS_JSON, "原創翻譯層")
    try:
        data = load_json(OWN_TRANSLATIONS_JSON)
    except json.JSONDecodeError as exc:
        print(f"❌ own_translations.json 格式錯誤：{exc}", file=sys.stderr)
        sys.exit(1)
    entries = data.get("entries", {})
    for fname, keys in entries.items():
        for key, spec in keys.items():
            if not isinstance(spec, dict) or not spec.get("ch") or not spec.get("cn"):
                print(
                    f"❌ own_translations.json 條目 {fname}|{key} 缺 ch/cn 欄位。",
                    file=sys.stderr,
                )
                sys.exit(1)
    return entries


def apply_own(
    merged_cn: dict[str, dict], merged_ch: dict[str, dict], own: dict[str, dict[str, dict]]
) -> tuple[int, list[str]]:
    """原創翻譯層合併：只補 As1 未收錄的鍵（As1 優先；同鍵列 shadowed 提示退役）。

    於 corpus 載入之後套用——ch 為直寫繁中人工真相；placeholder gate 隨後照常涵蓋。
    回傳 (新增鍵數, shadowed 清單)。
    """
    added = 0
    shadowed: list[str] = []
    for fname, keys in own.items():
        cn_map = merged_cn.setdefault(fname, {})
        ch_map = merged_ch.setdefault(fname, {})
        for key, spec in keys.items():
            if key in cn_map:
                shadowed.append(f"{fname}|{key}")
                continue
            cn_map[key] = spec["cn"]
            ch_map[key] = spec["ch"]
            added += 1
    return added, shadowed


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


def apply_cn_registry(
    merged_cn: dict[str, dict], entries: dict[str, dict], field: str
) -> set[str]:
    """對登記的 (檔|鍵) 以 entries[key][field] 全域取代 merged CN 值。

    不分 owner（merge 已收斂為每鍵一值）。供兩個登記檔共用：
      - placeholder_exceptions.json（field="cn_safe_value"）：換成安全值後 placeholder
        gate 自然不再觸發崩潰簽名。
      - cn_overrides.json（field="value"）：修 As1 上游錯誤（錯字／疊字等）。
    CH 為獨立人工真相 corpus，CN 修正不再自動帶到 CH——語意變更時須同步修
    sources/ch 對應鍵（並更新 ch_review_state.json）。
    回傳實際套用的登記鍵集合。
    """
    used: set[str] = set()
    for reg_key, spec in entries.items():
        if reg_key.startswith("_"):
            continue  # _comment 等說明欄位
        fname, _, key = reg_key.partition("|")
        fmap = merged_cn.get(fname)
        if fmap is not None and key in fmap:
            fmap[key] = spec[field]
            used.add(reg_key)
    return used


# 簡體專用字集（斷絕機轉後 CH 為手寫真相，防 CN 值誤貼直接出貨）：
# 僅收「繁中不合法」的簡化字——已排除 后/干/面/里/云/谷/系/准 等繁中亦有效字。
# 2026-08-02 實測：凍結 corpus＋own ch 零命中（零基線噪音）、CN 語料 174/176 字觸發。
_SIMPLIFIED_ONLY = frozenset(
    "们这边变币笔毕车陈迟达带单当导灯敌电东动断对队尔发费风刚钢国过华画欢环还会"
    "击鸡际间将节结进举觉开课块来乐离丽历联连两辆灵龙楼录虑论罗妈马买卖满门梦亩"
    "难鸟农盘钱枪桥亲轻请让认荣伞烧绍师时实识视试书数双谁说丝苏虽岁孙态谈汤铁听"
    "头图团万为伟卫温稳问乡响项写兴学寻压亚严盐养样阳药页业叶义亿忆艺阴银应营优"
    "邮语员远运杂载脏则泽张账阵证织职执纸钟种众专转装状驻总组"
)


def ch_value_gate(merged_cn: dict[str, dict], merged_ch: dict[str, dict]) -> list[str]:
    """CH 值層 gate：簡體專用字殘留、CN 有文而 CH 空值、非字串值 → 阻斷。

    corpus 為手寫真相後唯一的簡繁不變式防線；OpenCC 時代此類錯誤在物理上不可能。
    """
    errors: list[str] = []
    for fname in sorted(merged_ch):
        cn_map = merged_cn.get(fname, {})
        for key in sorted(merged_ch[fname]):
            val = merged_ch[fname][key]
            if not isinstance(val, str):
                errors.append(f"  {fname} | {key}: CH 值非字串（{type(val).__name__}）")
                continue
            bad = sorted(set(val) & _SIMPLIFIED_ONLY)
            if bad:
                errors.append(
                    f"  {fname} | {key}: 含簡體專用字「{''.join(bad)}」｜{val[:40]!r}"
                )
            elif not val and cn_map.get(key):
                errors.append(f"  {fname} | {key}: CH 空值但 CN 有內容")
    return errors


CORPUS_GATE_DETAIL_CAP = 30  # corpus gate 逐鍵明細上限（每檔）


def corpus_gate(merged_cn: dict[str, dict], corpus: dict[str, dict]) -> list[str]:
    """corpus 鍵集必須與 merged CN 完全一致（檔案集合＋逐檔鍵集）。

    缺鍵附 CN 值＝待翻譯 worklist；孤兒鍵＝上游已移除，須自 corpus 刪除。
    值不在此比對——corpus 即 CH 真相，值層品質由 placeholder gate 與 lint 把關。
    """
    errors: list[str] = []
    for fname in sorted(set(merged_cn) | set(corpus)):
        if fname not in corpus:
            errors.append(
                f"  corpus 缺檔：sources/ch/{fname}（{len(merged_cn[fname])} 鍵待翻譯）"
            )
            continue
        if fname not in merged_cn:
            errors.append(f"  corpus 孤兒檔：sources/ch/{fname}（CN 無此檔，請刪除）")
            continue
        cn_keys = set(merged_cn[fname])
        ch_keys = set(corpus[fname])
        missing = sorted(cn_keys - ch_keys)
        orphans = sorted(ch_keys - cn_keys)
        for key in missing[:CORPUS_GATE_DETAIL_CAP]:
            errors.append(f"  {fname} | {key} 待翻譯，CN={merged_cn[fname][key]!r}")
        if len(missing) > CORPUS_GATE_DETAIL_CAP:
            errors.append(f"  {fname}：…另有 {len(missing) - CORPUS_GATE_DETAIL_CAP} 鍵待翻譯")
        for key in orphans[:CORPUS_GATE_DETAIL_CAP]:
            errors.append(f"  {fname} | {key} 為 corpus 孤兒鍵（CN 已無此鍵，請刪除）")
        if len(orphans) > CORPUS_GATE_DETAIL_CAP:
            errors.append(f"  {fname}：…另有 {len(orphans) - CORPUS_GATE_DETAIL_CAP} 個孤兒鍵")
    return errors


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
    print("build：corpus 合併去重 + worklist/鍵集/placeholder gate")
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
    corpus = load_ch_corpus()
    exceptions = load_placeholder_exceptions()
    cn_overrides = load_cn_overrides()

    # CN 人工修正層：修 As1 上游錯誤（錯字／疊字）；CH 為獨立人工真相，不隨 CN 機轉
    used_cn_ov = apply_cn_registry(merged_cn, cn_overrides, "value")
    if used_cn_ov:
        print(f"  CN 人工修正層：套用 {len(used_cn_ov)} 鍵")

    # 登記制崩潰例外：以 cn_safe_value 全域取代（安全性最後把關，覆蓋前一層）
    used_exc = apply_cn_registry(merged_cn, exceptions, "cn_safe_value")

    # registry 背書 gate：registry 改值不經 split（worklist 看不到），
    # 強制每個命中鍵的有效 CN hash 與已審台帳一致（改值必經 CH 同步檢視）
    review_state = load_review_state()
    registry_errors = check_registry_ack(merged_cn, used_cn_ov | used_exc, review_state)

    # 斷絕機轉 gate：sync worklist 未滿足 or corpus 鍵集不鏡像 CN → 拒絕出貨。
    # worklist 自動對帳：added 已落 corpus / removed 已自 corpus 刪除 → 已滿足
    # 不阻斷（殘留條目由下次 split 重寫時清除）；changed 一律需人工確認後移除。
    worklist = load_sync_worklist()
    worklist_errors: list[str] = []
    for wkey, spec in sorted(worklist.items()):
        kind = spec.get("kind") if isinstance(spec, dict) else None
        wf, _, wk = wkey.partition("|")
        in_corpus = wk in corpus.get(wf, {})
        if (kind == "added" and in_corpus) or (kind == "removed" and not in_corpus):
            continue
        worklist_errors.append(f"  {wkey}（{kind or '?'}）")
    corpus_errors = corpus_gate(merged_cn, corpus)
    if worklist_errors or corpus_errors or registry_errors:
        if registry_errors:
            print(
                f"\n❌ registry 背書 gate {len(registry_errors)} 處"
                "（cn_overrides/placeholder_exceptions 改值須經 CH 同步檢視並登記）："
            )
            for e in registry_errors[:50]:
                print(e)
        if worklist_errors:
            print(
                f"\n❌ sync worklist 有 {len(worklist_errors)} 條未滿足"
                "（翻譯落 sources/ch 後自 ch_sync_worklist.json 移除條目）："
            )
            for e in worklist_errors[:50]:
                print(e)
            if len(worklist_errors) > 50:
                print(f"  ...（還有 {len(worklist_errors) - 50} 條）")
        if corpus_errors:
            print(f"\n❌ corpus 鍵集 gate {len(corpus_errors)} 處（sources/ch 須逐鍵鏡像 CN）：")
            for e in corpus_errors[:50]:
                print(e)
            if len(corpus_errors) > 50:
                print(f"  ...（還有 {len(corpus_errors) - 50} 處，完整清單見 ch_sync_worklist.json）")
        print("\n❌ build 失敗，未寫出成品。")
        return 1

    print(f"  CH corpus：{len(corpus)} 檔（人工真相層，無機轉）")
    merged_ch = {fname: dict(corpus[fname]) for fname in merged_cn}

    # 原創翻譯層（As1 未收錄的鍵；ch 直寫、cn 對應）——gate 之前合入使其受 placeholder 檢查
    own = load_own_translations()
    own_added, own_shadowed = apply_own(merged_cn, merged_ch, own)
    if own_added:
        print(f"  原創翻譯層：新增 {own_added} 鍵")
    if own_shadowed:
        print(f"  ⚠️ 原創翻譯層 {len(own_shadowed)} 鍵已被 As1 收錄（As1 優先，建議自 own_translations.json 退役）：")
        for s in own_shadowed[:10]:
            print(f"    {s}")

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

    print(f"\n✅ 已寫出 CN/CH 各 {len(merged_cn)} 檔、language.txt ×2、Lua {lua_count} 檔")

    # 未消費人工真相報告（非阻斷，供檢視）
    report_unused(exceptions, used_exc, cn_overrides, used_cn_ov)

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
    exceptions: dict[str, dict],
    used_exc: set[str],
    cn_overrides: dict[str, dict],
    used_cn_ov: set[str],
) -> None:
    """報告未被消費的人工真相（非阻斷）：cn_overrides / placeholder_exceptions
    未命中鍵。這些多半是鍵名過時或改寫後遺留，值得人工回頭確認。"""
    unused_exc = sorted(set(exceptions) - used_exc)
    unused_cn_ov = sorted(
        {k for k in cn_overrides if not k.startswith("_")} - used_cn_ov
    )
    if not (unused_exc or unused_cn_ov):
        return
    print("\n⚠️ 未消費人工真相（非阻斷，請檢視是否過時或鍵名有誤）：")
    for k in unused_cn_ov:
        print(f"  cn_overrides 未命中：{k}")
    for k in unused_exc:
        print(f"  placeholder_exceptions 未命中：{k}")


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
        if meta.get("origin") == "own":
            name = f"{name}〔原創翻譯〕"
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

    # 已下架標記來自 tracker state（tracker.py 每日維護；缺檔＝視為全部在架）
    ts_path = PROJECT_ROOT / "tracker-state" / "timestamps.json"
    ts_items = load_json(ts_path).get("items", {}) if ts_path.exists() else {}
    removed_at = {
        w: (v.get("removed_at") or "")[:10] for w, v in ts_items.items() if v.get("removed")
    }
    active_rows = [r for r in rows if r[0] not in removed_at]
    removed_rows = [r for r in rows if r[0] in removed_at]

    def row_line(ws_id, name, mod_ids, key_count, extra: str = "") -> str:
        link = f"[{cell(name)}]({WORKSHOP_URL.format(ws_id)})"
        ids = ", ".join(f"`{m}`" for m in mod_ids) if mod_ids else "—"
        zh = names_zh.get(ws_id, {})
        cells = [link, cell(zh.get("name_zh", "")), cell(zh.get("summary", "")), ids, str(key_count)]
        if extra:
            cells.append(extra)
        return "| " + " | ".join(cells) + " |"

    all_mod_ids = {m for r in active_rows for m in r[2]}
    lines = ["| MOD | 中文名稱 | 摘要 | Mod IDs | 鍵數 |", "| --- | --- | --- | --- | --- |"]
    lines.extend(row_line(*r) for r in active_rows)
    table = "\n".join(lines)
    print(
        f"  彙整 {len(rows)} 個 MOD（在架 {len(active_rows)}、已下架 {len(removed_rows)}、"
        f"中文名稱覆蓋 {sum(1 for w, *_ in rows if w in names_zh)} 個）"
    )

    removed_section = ""
    if removed_rows:
        rlines = [
            "| MOD | 中文名稱 | 摘要 | Mod IDs | 鍵數 | 下架偵測 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        rlines.extend(row_line(*r, extra=removed_at.get(r[0]) or "—") for r in removed_rows)
        removed_section = (
            f"\n## 已下架模組（{len(removed_rows)} 個，翻譯保留）\n\n"
            "以下模組已無法於 Workshop 存取（作者隱藏／移除或遭下架）。翻譯內容保留，"
            "既有訂閱者與側載玩家仍可使用；若重新上架會自動恢復追蹤並移回上表。\n\n"
            + "\n".join(rlines) + "\n"
        )

    page = (
        "# 支援 MOD 清單\n\n"
        "> 本檔由 `uv run scripts/build_mod.py manifest` 自動生成，請勿手動編輯。\n"
        "> 中文名稱與摘要維護於 `sources/mod_names_zh.json`，修改後重跑 manifest。\n\n"
        f"共支援 **{len(active_rows)} 個 Workshop 模組**（{len(all_mod_ids)} 個 mod ID）"
        f"{f'；另 **{len(removed_rows)} 個已下架**（翻譯保留，見文末）' if removed_rows else ''}。\n\n"
        f"{table}\n"
        f"{removed_section}"
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
        f"共支援 **{len(active_rows)} 個 Workshop 模組**（{len(all_mod_ids)} 個 mod ID）"
        f"{f'，另 {len(removed_rows)} 個已下架（翻譯保留）' if removed_rows else ''}，"
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
  uv run scripts/build_mod.py build      # 合併 + corpus/worklist/placeholder gate + 寫出（預設）
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
