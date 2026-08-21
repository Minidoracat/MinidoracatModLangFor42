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
              （--check：只驗不寫，生成物與來源不同步即退出 1）

真相模型：CN 為衍生佈局的 canonical import；CH 為 sources/ch/ 人工真相 corpus
（已斷絕 OpenCC 機轉；新增/變更鍵由 AI/人工對照 EN＋術語表直譯後落 corpus）。
build 僅做合併與把關，不做任何文字轉換——唯一例外：CN 值全量過
sanitize_format_tokens（42.20.1 Translator.formatted() 安全逸出，機械冪等；
As1 快照不可手改故於 build 期處理；CH/own 為人工真相須直寫安全值、gate 把關）。
全程確定性輸出。
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
VANILLA_KEYS_JSON = SOURCES / "vanilla_keys.json"
UNSHIPPED_KEYS_JSON = SOURCES / "unshipped_keys.json"

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
# 人工真相：{wid: {name_zh, summary, note?}}。note＝涵蓋範圍例外說明（渲染成獨立的
# 「涵蓋範圍」欄，慣例以 ⚠️ 起頭）：上游把文字放在 PZ 翻譯表取不到的位置，任何翻譯包都補不了。
MOD_NAMES_ZH_JSON = SOURCES / "mod_names_zh.json"
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
# 42.20.1 起 zombie.core.Translator 於載入期對每值跑 formatFixer（只認 %% 與 %1-%9，
# %N → %N$s），getText 再對結果跑 String.formatted(args)、僅捕 MissingFormatArgumentException。
# 因此 %s/%d/%.Nf（無參數時 MissingFormatArgument 被捕、原文返還）是安全 token；
# 裸 % 與 %i/%F 等非法轉換符會拋 UnknownFormatConversionException（主選單黑畫面）。
# multiset 比對用：% 格式 token + <...> 標籤，CN/CH 須逐一致
# conversion 只允許 %.Nf（f 限定，可帶 + 旗標）；%.N[其他字母] 太寬，會把崩潰簽名誤吞成合法 token，故收緊。
# %i 已自 allowlist 移除——Java 無 %i 轉換符，出現即必炸，一律視為裸 % 逸出。
# 編號佔位一律 %[1-9] 單位數——與遊戲 FORMAT_TOKEN（%%|%([1-9])）逐字對齊。
# %0 不在遊戲文法內（formatFixer 不改寫、formatted() 拋 UnknownFormatConversionException），
# 故不得當合法 token 吸收，否則必炸序列會被靜默漏掉；%10 同遊戲解為 %1 後接字面 0。
# **一律用 [0-9] 而非 \d**：Python 的 \d 是 Unicode-aware，會把 %.١f（阿拉伯數字）
# 判為合法 precision，而 JDK 對它拋 UnknownFormatConversionException（未被捕＝崩潰）。
# precision 位數同樣設上限：%.2147483648f 超出 int 會拋 IllegalFormatPrecisionException。
# 上限 2 位涵蓋一切實用場景（現有語料 708 個 precision token 最大值為 5）；
# 三位數以上一律逸出成字面——寧可顯示 %.123f 也不崩潰。
_PRECISION = r"%\+?\.[0-9]{1,2}f"
# 「佔位符緊接 %%」（如 %1%%、%.1f%%）是**格式單位**——百分比符號屬該數值的一部分，
# CN/CH 必須逐一配對（漏掉即數值單位消失）。故整體吸收為單一 token 進 multiset，
# 與獨立字面 %%（允許譯成「百分之…」）區隔開。順序在前，優先於單獨的 %%。
_ADJ_PCT = rf"(?:%[1-9]|%[sd]|{_PRECISION})%%"
_FMT_TOKEN_RE = re.compile(rf"{_ADJ_PCT}|%%|{_PRECISION}|%[1-9]|%[sd]|<[^<>]+>")
# 掃 grammar 之外的 % 用：只認 % 系列 token（不含標籤）
_PCT_TOKEN_RE = re.compile(rf"{_ADJ_PCT}|%%|{_PRECISION}|%[1-9]|%[sd]")
# 「值是否含真正的 format token」用（不含 %% 與標籤）：%N/%s/%d/%.Nf。
# 只有含 format token 的值，殘留的字面 %. 才會被 PZ 轉換 + JDK .formatted() 當成轉換符而崩潰。
_FMT_ONLY_RE = re.compile(rf"{_PRECISION}|%[1-9]|%[sd]")
# sanitize 安全 token（不含 %%，%% 由 tokenizer 優先另行消費）
_SAFE_RE = re.compile(rf"{_PRECISION}|%[1-9]|%[sd]")
# Java 完整位置參數 `%N$<conversion>`（%1$s、%2$.1f、%1$,d、%1$tY…）→ 正規化為 PZ 簡寫 %N。
# formatFixer 對 %N 一律補 $s，故值裡已寫完整形式時會疊成 %1$s$s，
# formatted() 輸出「值$s」＝顯示損壞（不崩潰，但字串壞掉）。實例：Burd's Journals 上游 EN。
# conversion 必須**完整**消費：date/time 是 [tT] 後再接一個字母，只吃 t 會留下孤兒字母。
# flags 用**有界**重複：`[-#+ 0,(]*` 與其後的 width `[0-9]*` 在 `0` 上重疊，
# 對「%1$ + 長串 0 + 非 conversion」的失敗匹配會 O(N²) 回溯（N=4000 約 0.16s，
# 外部 As1／own 值可觸發的 build-time availability 風險）。Java flags 至多 6 種，
# 上限 8 足夠且把回溯壓成線性。
_POSITIONAL_RE = re.compile(
    r"%([1-9])\$[-#+ 0,(]{0,8}[0-9]*(?:\.[0-9]+)?(?:[tT][a-zA-Z]|[a-zA-Z])"
)


# 反向正規化：上游把「已經安全」的 token 又逸出一次的形態。
# 2026-08-10 As1 42.20 同步實證：上游對 64,541 鍵做了 % 逸出，其中 1,397 鍵逸出過頭
# （`%1`→`%%1`、`%s`→`%%s`、`%.2f`→`%%.2f`），另有 89 鍵是全域 `%`→`%%` 導致合法的
# 字面 `%%` 變成 `%%%%`。照單全收會讓佔位符變成字面文字——玩家看到「攻擊速度: %1」。
# 安全性實證（同步當下）：我方 145,595 個正確值中，`%%` 緊接安全 token 起始者 0 筆、
# 含 `%%%%` 者 0 筆，故這兩條反向規則在本語料上不會誤傷合法的字面百分號。
_OVER_ESCAPED = re.compile(r"%%(?=(?:[1-9]|s|d|\.\d+f|\+\.\d+f))")


def normalize_over_escape(value: str) -> str:
    """把上游過度逸出的 token 還原成安全形式（機械、冪等）。

    只作用於 As1 canonical import，於合併後、registry 套用前執行——registry 值是
    人工直寫真相，不套本轉換。與 sanitize_format_tokens 的關係：**先還原再逸出**
    （`normalize` 處理「逸出過頭」，`sanitize` 處理「該逸出而沒逸出」）。
    """
    if not isinstance(value, str) or "%%" not in value:
        return value
    for _ in range(8):  # 收斂到定點；巢狀逸出（%%%%%%%%）需多輪
        nxt = _OVER_ESCAPED.sub("%", value).replace("%%%%", "%%")
        if nxt == value:
            break
        value = nxt
    return value


def sanitize_format_tokens(value: str) -> str:
    """42.20.1 Translator.formatted() 安全化（冪等）。

    **left-to-right 單次掃描**，依 PZ／JDK 優先序逐 token 消費——不可用全域 sub
    前置改寫：那會在 tokenizer 之前動手，把 `%%1$s` 的字面 `%%` 穿透成 `%%1`。
    優先序：`%%`（字面逸出，最優先）> `%N$<conv>` → `%N` > 安全 token 原樣 > 其餘 % 逸出 `%%`。

    `%N$<conv>` 後**緊接另一個 `$`** 者（如 `%1$s$A`）語意有歧義，保守不轉、原樣留下
    ——正規化會逐次剝離（不冪等）而靜默丟失字面文字；改由 verify [4] 的 `%N$` 檢查
    fail-loud 交人工裁決。同理 `%10$s` 這類超出 PZ %1-%9 的 index 也不轉、由 oracle 攔。

    **刻意不做 printf→編號轉換**（與本體 repo 修法不同）：第三方 mod 的消費模式是
    Lua 端 string.format(getText(...))——無參數 getText 觸發 MissingFormatArgumentException
    被 Translator 捕捉後原文返還，%s/%d/%.Nf 照常由 mod 消費；若轉成 %1-%9，
    formatFixer 會把 %N 改寫成 %N$s，反而炸掉 mod 的 string.format。
    本函式只消滅必炸序列（裸 %、%i、%F 等 Java 非法轉換符）與 %N$ 顯示損壞。
    """
    if "%" not in value:
        return value
    out: list[str] = []
    i, n = 0, len(value)
    while i < n:
        if value[i] != "%":
            out.append(value[i])
            i += 1
            continue
        if value.startswith("%%", i):  # 字面逸出最優先，勿被後續規則穿透
            out.append("%%")
            i += 2
            continue
        m = _POSITIONAL_RE.match(value, i)
        if m and not value.startswith("$", m.end()):
            out.append(f"%{m.group(1)}")
            i = m.end()
            continue
        m = _SAFE_RE.match(value, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        out.append("%%")
        i += 1
    return "".join(out)
# 角括號內容含 CJK 者是文本（如 <吱吱声>、耐力<25%, 疲劳>80%），屬翻譯文字一部分，
# 不得當標籤比對；真正的標籤（<br>、<LINE>、<RGB:...>）皆為 ASCII。
_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


def token_multiset(value: str) -> Counter:
    """抽取 allowlist 內的 format token 與標籤，回傳 multiset。

    %% 為字面逸出、非佔位，不入 multiset——sanitize 之後字面 % 的繁簡寫法
    允許不同（如 CN「50%%」對 CH「百分之五十」），強制配對會誤殺合法翻譯。
    """
    tokens = [
        t for t in _FMT_TOKEN_RE.findall(value)
        if t != "%%" and not (t.startswith("<") and _CJK_RE.search(t))
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
    CN 值 hash（＝sanitize 後的出貨值，呼叫端須在 sanitize 之後才呼叫本檢查）
    必須與 ch_review_state 登記一致，否則拒絕出貨。
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
        if exc_key.startswith("_"):
            continue
        if not isinstance(spec, dict) or "cn_safe_value" not in spec:
            print(
                f"❌ placeholder_exceptions.json 條目 {exc_key!r} 缺 cn_safe_value 欄位。",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(spec.get("as1_value"), str):
            print(
                f"❌ placeholder_exceptions.json 條目 {exc_key!r} 缺 as1_value 錨點"
                "（登記當時的 As1 原值，過時偵測必要欄位）。",
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
        if not isinstance(spec.get("as1_value"), str):
            print(
                f"❌ cn_overrides.json 條目 {ov_key!r} 缺 as1_value 錨點"
                "（登記當時的 As1 原值，過時偵測必要欄位）。",
                file=sys.stderr,
            )
            sys.exit(1)
    return data


# vanilla 一定會有的核心字串檔。整個 bucket 消失是最危險的殘缺——**總鍵數幾乎不變**
# （拿掉 ItemName.json 仍有 42,364 鍵），純量級門檻攔不到，抑制卻會對該檔全面失效。
VANILLA_CORE_FILES = frozenset({
    "ItemName.json", "UI.json", "IG_UI.json", "ContextMenu.json", "Tooltip.json",
    "Recipes.json", "Sandbox.json", "Fluids.json", "Moveables.json", "Moodles.json",
})


def _vanilla_basis_problem(data: dict) -> str | None:
    """基準不可信的理由，可信則 None。**fail-closed 的重點在結構不變式而非量級**。

    2026-08-10 review 實證：舊版只驗「總數 ≥ 10000」，於是
    (a) 整個 `ItemName.json` bucket 消失仍過關（剩 42,364 鍵）——`Base.Shotgun` 直接放行；
    (b) 同一個鍵重複 10,001 次也過關，實際 unique pair 只有 1。
    兩者都是「看起來 fail-closed、實際 fail-open」。
    """
    scoped = data.get("scoped_keys")
    if not isinstance(scoped, dict) or not scoped:
        return "scoped_keys 缺失或非物件"
    seen: set[str] = set()
    for fname, ks in scoped.items():
        if not isinstance(fname, str) or not fname:
            return f"檔名非法：{fname!r}"
        if not isinstance(ks, list) or not all(isinstance(k, str) and k for k in ks):
            return f"{fname} 的鍵清單非法（須為非空字串清單）"
        if len(set(ks)) != len(ks):
            return f"{fname} 內有重複鍵（灌水會讓量級檢查失真）"
        seen.update(ks)
    if missing := VANILLA_CORE_FILES - set(scoped):
        return f"缺少核心字串檔 {sorted(missing)}（該檔的出貨抑制會整批失效）"
    if len(scoped) < 30:
        return f"只有 {len(scoped)} 個檔（vanilla 量級 43，遠低於此＝擷取殘缺）"
    if sum(len(v) for v in scoped.values()) < 10000:
        return "檔域鍵量級不足（vanilla 量級 4.7 萬）"
    if set(data.get("keys") or []) != seen:
        # 兩欄由 extract_vanilla_keys.py 單一 writer 共同重生，不一致＝有人手改或只重生一半
        return "keys 與 scoped_keys 的聯集不一致（基準只重生了一半？）"
    return None


def suppress_unshipped(
    merged_cn: dict[str, dict], merged_ch: dict[str, dict]
) -> tuple[int, list[str], list[str]]:
    """出貨前剔除 `unshipped_keys.json` 登記的 (檔,鍵)；CN/CH 對稱以維持 [2] 鍵集鏡像。

    語意同 vanilla 出貨抑制：**真相層照樣保留**（`_unsorted/CN` 是 As1 lane 鏡像，
    刪掉會讓 layer-B 永遠報差異；`sources/ch` 也須逐鍵鏡像 CN 才過 corpus 鍵集 gate），
    只有出貨那一步濾掉。登記分兩類（判準與複查規則見該檔 `_rule`／`_recheck`）：
    (1) 鍵落在 PZ 不載入的檔名、且找不到正確落點；(2) #230 起的 owner 衝突——同一
    (檔,鍵) 被多個 owner 定義成不同實體、無誠實中性譯名，與
    `owner_conflict_decisions.json` 的 `action:"unship"` 以 `owner_signature` 雙向背書。
    **第二類的檔名通常是可載入的**（`ItemName.json|Base.Glock23`、
    `Recipes.json|MakeTortilla`），不可因「檔名可載入」就當成可退役的垃圾條目。

    `as1_value` 錨點對**抑制前的合併 CN 值**比對：上游動過該鍵就是重新查 mod 的訊號
    （見該檔 `_recheck`）。回傳 (剔除數, 錨點漂移訊息, 登記但未命中的條目)。
    """
    if not UNSHIPPED_KEYS_JSON.is_file():
        return 0, [], []
    entries = load_json(UNSHIPPED_KEYS_JSON).get("entries", {})
    dropped = 0
    drift: list[str] = []
    unused: list[str] = []
    for pair, spec in sorted(entries.items()):
        fname, _, key = pair.partition("|")
        cn_map = merged_cn.get(fname)
        if cn_map is None or key not in cn_map:
            unused.append(pair)
            continue
        anchor = spec.get("as1_value")
        if isinstance(anchor, str) and cn_map[key] != anchor:
            drift.append(
                f"  {pair}：上游值已變（登記時 {anchor!r} → 現行 {cn_map[key]!r}），"
                "請重查該 mod 是否已可指認（見 unshipped_keys.json 的 _recheck）"
            )
        cn_map.pop(key, None)
        if merged_ch.get(fname) is not None:
            merged_ch[fname].pop(key, None)
        dropped += 1
    # 清空的檔**照樣出貨成空 JSON**——[1]/[9] 是逐「檔」比對檔案集合，少一個檔就 FAIL。
    # vanilla 抑制早就把 6 個檔（Brandenburg, KY／CisternsName／PZKMZ_* 等）清成空檔
    # 並照常寫出，本函式沿用同一慣例。（我一度加了「空檔就不寫」，直接炸掉那 6 個檔。）
    return dropped, drift, unused


def load_vanilla_scoped() -> tuple[dict[str, set[str]], dict[str, dict]]:
    """vanilla 檔域鍵基準 `{檔名: {鍵}}` 與 keep 豁免登記（缺失即 fail）。

    PZ 的 `Translator.tryFillMapFromFile()` 把每個 mod 的 Translate 檔 `map.put()`
    進同一張全域字串表，後載入者覆寫前者——**同 (檔,鍵) 出貨即全域改寫本體譯文，
    連沒裝任何模組的玩家都會看到**。本包是模組翻譯包，故 vanilla 同名鍵一律不出貨。
    """
    _require_truth_file(VANILLA_KEYS_JSON, "vanilla 鍵名基準")
    data = load_json(VANILLA_KEYS_JSON)
    problem = _vanilla_basis_problem(data)
    if problem:
        print(
            f"❌ vanilla_keys.json 基準不可信：{problem}。"
            "遊戲更新後請跑 scripts/extract_vanilla_keys.py 重生。",
            file=sys.stderr,
        )
        sys.exit(1)
    keep = data.get("keep", {})
    # 2026-08-12 使用者裁決：**MOD 翻譯不得覆蓋本體任何一個現有 EN/CH/CN 鍵，一個都不行。**
    # keep 欄位保留（避免舊資料讀不動）但不再是放行通道——非空即拒絕出貨。
    if keep:
        print(
            f"❌ vanilla_keys.json 的 keep 有 {len(keep)} 條登記：{sorted(keep)[:5]}。"
            "本包不得覆蓋本體任何一個現有翻譯鍵（使用者裁決，無例外），keep 必須維持全空；"
            "要處理個別鍵請改用 sources/unshipped_keys.json 或直接移除該鍵的譯文。",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(keep, dict) or not all(
        isinstance(s, dict)
        and isinstance(s.get("anchor"), str)
        and s["anchor"]
        and isinstance(s.get("reason"), str)
        and s["reason"].strip()
        for s in keep.values()
    ):
        print(
            "❌ vanilla_keys.json keep 形狀壞損（每筆須為含非空 anchor 與非空 reason 的物件）。"
            "保留一個覆寫＝改寫全體玩家看到的本體文字，必須寫明理由。",
            file=sys.stderr,
        )
        sys.exit(1)
    return {f: set(ks) for f, ks in data["scoped_keys"].items()}, keep


def suppress_vanilla(
    merged_cn: dict[str, dict], merged_ch: dict[str, dict]
) -> tuple[int, list[str], list[str]]:
    """出貨前剔除 vanilla 同名 (檔,鍵)；CN/CH 對稱處理以維持 [2] 鍵集鏡像。

    回傳 (剔除鍵數, keep 豁免鍵, 錨點失效訊息)。keep 錨點對出貨 CH 值比對——
    豁免是「已確認這個覆寫無害」的背書，值一變背書即失效。
    """
    scoped, keep = load_vanilla_scoped()
    dropped = 0
    kept: list[str] = []
    anchor_errors: list[str] = []
    for fname, van_keys in scoped.items():
        cn_map, ch_map = merged_cn.get(fname), merged_ch.get(fname)
        if cn_map is None:
            continue
        for key in sorted(van_keys & set(cn_map)):
            pair = f"{fname}|{key}"
            if pair in keep:
                kept.append(pair)
                ch_val = (ch_map or {}).get(key, "")
                got = hashlib.sha256(str(ch_val).encode("utf-8")).hexdigest()[:16]
                if got != keep[pair]["anchor"]:
                    anchor_errors.append(
                        f"  {pair} keep 錨點失效（出貨 CH 值已變動 {got}≠{keep[pair]['anchor']}，"
                        "須重新確認無害後更新錨點）"
                    )
                continue
            cn_map.pop(key, None)
            if ch_map is not None:
                ch_map.pop(key, None)
            dropped += 1
    return dropped, kept, anchor_errors


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
            if not isinstance(spec, dict) or any(
                not isinstance(spec.get(f), str) or not spec.get(f) for f in ("en", "ch", "cn")
            ):
                print(
                    f"❌ own_translations.json 條目 {fname}|{key} 缺 en/ch/cn 欄位（須為非空字串）。",
                    file=sys.stderr,
                )
                sys.exit(1)
    return entries


def report_own_anchor_gaps(own: dict[str, dict[str, dict]]) -> None:
    """report-only：own_translations 鍵於 tracker-state/en_corpus_hashes.json 查無上游錨點者。

    此類鍵不在 layer-A 全語料 hash 內，上游此後的變動永遠不會觸發「可能過時」issue——
    顯性化偵測盲區供人工留意。缺 state 檔或壞損時靜默跳過（本檢查非 gate）。

    已知限制：錨點集合為全 mod 裸鍵名扁平聯集（不分 mod/檔），同名鍵存在於不相干 mod
    時會誤判「有錨點」而漏報——本報告偏鬆，報出的是盲區下限而非全集。
    """
    try:
        state_path = PROJECT_ROOT / "tracker-state" / "en_corpus_hashes.json"
        if not state_path.is_file():
            return
        try:
            mods = json.loads(state_path.read_text(encoding="utf-8")).get("mods", {})
        except (OSError, json.JSONDecodeError):
            return
        # 錨點＝值感知記錄限定：translate_*（值=英文原文）與 script_item_dn（值=DisplayName）。
        # script_item/recipe/vehicle 名稱記錄的 value=區塊 id，DisplayName 漂移無感，不算錨點
        # （改名仍以 added/removed 呈現，但 own 過時比對要的是「顯示文字」層級）。
        anchors: set[str] = set()
        for mod in mods.values():
            records = mod.get("records", {}) if isinstance(mod, dict) else {}
            for rid in records:
                parts = rid.split("|", 2)
                if len(parts) < 3:
                    continue
                kind, _rel, key = parts
                if kind.startswith("translate_"):
                    anchors.add(key)
                    if key.startswith("ItemName_"):
                        anchors.add(key[len("ItemName_"):])  # 上游前綴鍵 ↔ own 裸鍵互通
                elif kind == "script_item_dn":
                    # schema>=9 的 key 已是完整 fullType（`Module.Item`）——它就是
                    # ItemName 出貨鍵本身，故連前綴形一起收。
                    # schema<=8 的遺留基準只有裸 item 名（module 未記錄）：**不補猜
                    # `Base.<name>`**——那違反「module 名不可猜」硬規則，猜錯會讓真正
                    # 沒有錨點的 own 鍵被誤判成有錨點，把該出的 warning 壓掉。裸名照原樣
                    # 收，錨點對不上就讓它出現在報告裡（本函式偏鬆、報的是盲區下限）。
                    anchors.add(key)
                    if "." in key:
                        anchors.add(f"ItemName_{key}")
        gaps = [
            f"{fname}|{key}"
            for fname, keys in sorted(own.items())
            for key in sorted(keys)
            if key not in anchors
        ]
        if gaps:
            print(f"  ℹ️ 原創翻譯層 {len(gaps)} 鍵於 tracker 基準查無值感知上游錨點（layer-A 對其顯示文字變動無感）：")
            for g in gaps[:20]:
                print(f"    {g}")
            if len(gaps) > 20:
                print(f"    ...（還有 {len(gaps) - 20} 條）")
    except Exception as exc:  # noqa: BLE001 — report-only：state 形狀壞損不得阻斷 build
        print(f"  ⚠️ 錨點缺口報告略過（state 形狀異常：{exc}）")


def report_stale_as1_keys() -> None:
    """report-only：As1 譯了、但該 mod 上游已不再定義的鍵（＝上游改名後的遺留）。

    與 `report_own_anchor_gaps` 互補——那支管 own 層，這支管 As1 衍生層。
    實例（2026-08-08 查證）：B42 PZLinux 把整批鍵名由 `UI_PZLinux_*` 改成
    `IGUI_PZLinux_*`，該 mod 的 Lua 現在只呼叫新鍵名（61 個 .lua 掃描，舊鍵名 0 命中），
    但 As1 語料仍留著 280 個舊鍵，於是我方照樣出貨——玩家永遠看不到，純屬死重量，
    且與新譯是同一批文本的第二份分歧譯文。

    **不是 gate、也不自動移除**：`split_sources` 有硬性不變式「owner ＋ _unsorted
    聯集 == As1 快照，一個不多一個不少」，刪了下次 split 會再生。要清除須先重釘 As1
    快照、確認上游 As1 自己也已改名，屬 As1 同步流程的一環。

    只涵蓋 `sources/mods/<wid>/` 有歸屬的鍵；`_unsorted` 無 mod 歸屬，判不了（PZLinux
    那 280 鍵正落在此，見上）。缺鏡像的 mod 一律跳過（無從判斷≠已作廢）。
    """
    try:
        mods_dir = SOURCES / "mods"
        en_dir = SOURCES / "en"
        if not mods_dir.is_dir() or not en_dir.is_dir():
            return
        rows: list[tuple[str, int, int]] = []
        for mod_dir in sorted(p for p in mods_dir.iterdir() if p.is_dir()):
            mirror = en_dir / f"{mod_dir.name}.json"
            if not mirror.is_file():
                continue                      # 未收錄的 mod：無從判斷
            try:
                upstream = {rid.rpartition("|")[2]
                            for rid in json.loads(mirror.read_text(encoding="utf-8"))}
            except (OSError, json.JSONDecodeError):
                continue
            if not upstream:
                continue
            have: set[str] = set()
            for f in mod_dir.glob("C*/*.json"):
                try:
                    have |= set(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
            stale = have - upstream
            if stale:
                rows.append((mod_dir.name, len(stale), len(have)))
        if rows:
            rows.sort(key=lambda r: -r[1])
            total = sum(n for _, n, _ in rows)
            print(f"  ℹ️ As1 衍生層 {total} 鍵於上游已查無同名鍵（改名遺留，出貨但玩家看不到），"
                  f"分佈 {len(rows)} 個 mod：")
            for wid, n_stale, n_have in rows[:10]:
                print(f"    {wid}  {n_stale}/{n_have}")
            if len(rows) > 10:
                print(f"    ...（還有 {len(rows) - 10} 個 mod）")
    except Exception as exc:  # noqa: BLE001 — report-only 不得阻斷 build
        print(f"  ⚠️ As1 作廢鍵報告略過（{exc}）")


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


def collect_own_mod_cn_dirs() -> list[Path]:
    """origin=='own' 的原創 mod CN 目錄——**人工直寫真相**，非 As1 衍生。

    這些值與 sources/ch corpus 同屬「build 不機轉、須直寫安全值」的真相層，
    但它們同時也在 collect_source_cn_dirs 的收集範圍內（合併後吃 build 期
    sanitize）。若無本 gate，往 own-mod CN 寫裸 % 會被靜默逸出出貨，
    真相檔與 dist 分歧且 build 全綠——verify [1] 的 own 原值比對雖能 fail-loud，
    但那是 oracle 端事後把關，不該是唯一防線。
    """
    dirs: list[Path] = []
    if not MODS_DIR.is_dir():
        return dirs
    for mod_dir in sorted(MODS_DIR.iterdir()):
        meta, cn = mod_dir / "metadata.json", mod_dir / "CN"
        if not (meta.is_file() and cn.is_dir()):
            continue
        try:
            is_own = load_json(meta).get("origin") == "own"
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as exc:
            print(f"❌ {meta.relative_to(PROJECT_ROOT)} 讀取失敗：{exc}", file=sys.stderr)
            sys.exit(1)
        if is_own:
            dirs.append(cn)
    return dirs


def format_gate_errors(
    merged_ch: dict[str, dict],
    own: dict[str, dict[str, dict]],
    own_mod_dirs: list[Path],
) -> list[str]:
    """format 安全 gate：**人工真相層**的值必須已是 formatted() 安全形式。

    涵蓋三處不受 build 期 sanitize 保護（或不該受其保護）的真相層：
      1. sources/ch corpus（CH 全部，build 不對 CH 機轉）
      2. own_translations.json 的 ch + cn（原創層直寫）
      3. origin=='own' 的 mod CN 目錄（人工直寫真相，雖混在 CN 合併流內）
    錯誤訊息附 sanitize 後的建議值，讓修真相檔是照抄而非重推。
    """
    errors = [
        f"  sources/ch/{fname} | {key}: 含 formatted() 必炸 % 序列，"
        f"請改為 {sanitize_format_tokens(val)!r}"
        for fname in sorted(merged_ch)
        for key, val in sorted(merged_ch[fname].items())
        if isinstance(val, str) and sanitize_format_tokens(val) != val
    ]
    errors += [
        f"  own_translations {fname}|{key}.{field}: 含 formatted() 必炸 % 序列，"
        f"請改為 {sanitize_format_tokens(spec[field])!r}"
        for fname, keys in sorted(own.items())
        for key, spec in sorted(keys.items())
        for field in ("ch", "cn")
        if sanitize_format_tokens(spec[field]) != spec[field]
    ]
    for cn_dir in own_mod_dirs:
        try:  # 路徑不在 repo 下（測試 tempdir 等）——錯誤路徑不得再擲錯
            rel = cn_dir.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            rel = cn_dir.as_posix()
        for jf in sorted(cn_dir.glob("*.json")):
            for key, val in sorted(load_json(jf).items()):
                if isinstance(val, str) and sanitize_format_tokens(val) != val:
                    errors.append(
                        f"  {rel}/{jf.name} | {key}: 含 formatted() 必炸 % 序列，"
                        f"請改為 {sanitize_format_tokens(val)!r}"
                    )
    return errors


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
    merged_cn: dict[str, dict],
    entries: dict[str, dict],
    field: str,
    raw_values: dict[str, str] | None = None,
) -> tuple[set[str], list[str]]:
    """對登記的 (檔|鍵) 以 entries[key][field] 全域取代 merged CN 值。

    不分 owner（merge 已收斂為每鍵一值）。供兩個登記檔共用：
      - placeholder_exceptions.json（field="cn_safe_value"）：換成安全值後 placeholder
        gate 自然不再觸發崩潰簽名。
      - cn_overrides.json（field="value"）：修 As1 上游錯誤（錯字／疊字等）。
    CH 為獨立人工真相 corpus，CN 修正不再自動帶到 CH——語意變更時須同步修
    sources/ch 對應鍵（並更新 ch_review_state.json）。

    過時偵測：條目帶 `as1_value`（登記當時的 As1 原值）時，與現行 As1 原值比對，
    不符即列 warning——多半是上游已自行修正，override 再蓋上去會靜默壓過上游更新，
    須人工複核該條目是否退役。raw_values（{登記鍵: 套用前原值}）供錨點比對用：
    兩個 registry 依序套用時，後套者的 merged_cn 已被前者改過，必須對套用前
    快照比對，否則同鍵雙登記時會產生假漂移警告。
    回傳 (實際套用的登記鍵集合, 過時警告清單)。
    """
    used: set[str] = set()
    stale: list[str] = []
    for reg_key, spec in entries.items():
        if reg_key.startswith("_"):
            continue  # _comment 等說明欄位
        fname, _, key = reg_key.partition("|")
        fmap = merged_cn.get(fname)
        if fmap is not None and key in fmap:
            anchor = spec.get("as1_value")
            raw = (raw_values or {}).get(reg_key, fmap[key])
            if isinstance(anchor, str) and anchor != raw:
                stale.append(
                    f"  {reg_key}：As1 原值已變（登記時 {anchor!r} → 現行 {raw!r}），"
                    "請複核 override 是否退役或更新 as1_value"
                )
            fmap[key] = spec[field]
            used.add(reg_key)
    return used, stale


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
    # 上游過度逸出還原：緊接合併之後、registry 與 anchor 快照之前——registry 值是人工
    # 直寫真相不套本轉換，而 as1_value 錨點對還原後的值比對（還原對 42.19 期值為 no-op，
    # 既有錨點不受影響），避免上游只是改了逸出就讓整批 override 誤報過時。
    n_unescaped = 0
    for fmap in merged_cn.values():
        for key, val in fmap.items():
            if isinstance(val, str) and (fixed := normalize_over_escape(val)) != val:
                fmap[key] = fixed
                n_unescaped += 1
    if n_unescaped:
        print(f"  上游過度逸出還原：{n_unescaped} 鍵（`%%1`→`%1` 等，避免佔位符變字面文字）")
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

    # registry 套用前先快照原值（as1_value 錨點一律對 As1 原值比對，不受套用順序影響）
    raw_anchor: dict[str, str] = {}
    for reg in (cn_overrides, exceptions):
        for rk in reg:
            if rk.startswith("_"):
                continue
            rf, _, rkey = rk.partition("|")
            if rf in merged_cn and rkey in merged_cn[rf]:
                raw_anchor[rk] = merged_cn[rf][rkey]

    # CN 人工修正層：修 As1 上游錯誤（錯字／疊字）；CH 為獨立人工真相，不隨 CN 機轉
    used_cn_ov, stale_cn_ov = apply_cn_registry(merged_cn, cn_overrides, "value", raw_anchor)
    if used_cn_ov:
        print(f"  CN 人工修正層：套用 {len(used_cn_ov)} 鍵")
    if stale_cn_ov:
        print(f"\n⚠️ cn_overrides 過時警告 {len(stale_cn_ov)} 條（上游已改，override 可能該退役）：")
        for w in stale_cn_ov:
            print(w)

    # 登記制崩潰例外：以 cn_safe_value 全域取代（安全性最後把關，覆蓋前一層）
    used_exc, stale_exc = apply_cn_registry(merged_cn, exceptions, "cn_safe_value", raw_anchor)
    if stale_exc:
        print(f"\n⚠️ placeholder_exceptions 過時警告 {len(stale_exc)} 條：")
        for w in stale_exc:
            print(w)

    # 42.20.1 formatted() 安全逸出：CN 真相為 As1 快照不可手改，於 build 期全量
    # 機械 sanitize（冪等；registry 值一體適用）。verify_dist 以同語意對 sanitize
    # 後的期望值核對 CN parity；「有效 CN 值」（背書 hash、已審台帳）自此指出貨值。
    n_sanitized = 0
    for fmap in merged_cn.values():
        for key, val in fmap.items():
            if isinstance(val, str) and (fixed := sanitize_format_tokens(val)) != val:
                fmap[key] = fixed
                n_sanitized += 1
    if n_sanitized:
        print(f"  CN sanitize：{n_sanitized} 鍵含裸 % 等必炸序列，已逸出為 formatted() 安全形式")

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

    # format 安全 gate：人工真相層（corpus / own_translations / own-mod CN）須直寫
    # formatted() 安全形式（build 不對它們機轉，不安全即擋、附建議值）
    fmt_errors = format_gate_errors(merged_ch, own, collect_own_mod_cn_dirs())

    own_added, own_shadowed = apply_own(merged_cn, merged_ch, own)
    if own_added:
        print(f"  原創翻譯層：新增 {own_added} 鍵")
    if own_shadowed:
        print(f"  ⚠️ 原創翻譯層 {len(own_shadowed)} 鍵已被 As1 收錄（As1 優先，建議自 own_translations.json 退役）：")
        for s in own_shadowed[:10]:
            print(f"    {s}")
    report_own_anchor_gaps(own)
    report_stale_as1_keys()

    # CH 值層 gate 須在 apply_own 之後：own_translations 的 ch 也走這道簡繁不變式檢查
    ch_value_errors = ch_value_gate(merged_cn, merged_ch)
    errors, warnings = placeholder_gate(merged_cn, merged_ch)

    # Lua 複製計畫先算：basename 衝突屬硬錯，須在清空/寫出前先攔
    lua_plan, lua_conflicts = plan_lua()

    # vanilla 出貨抑制：置於所有鍵集/值層 gate 之後——corpus 鍵集鏡像、placeholder、
    # CH 值層都對「完整合併結果」把關（真相層照樣要正確），只有出貨那一步濾掉本體同名鍵。
    n_suppressed, kept_vanilla, keep_anchor_errors = suppress_vanilla(merged_cn, merged_ch)
    if n_suppressed:
        print(f"  vanilla 出貨抑制：剔除 {n_suppressed} 個本體同名 (檔,鍵)（避免全域改寫本體譯文）")
    if kept_vanilla:
        print(f"  ⚠️ keep 登記豁免 {len(kept_vanilla)} 鍵仍出貨（刻意覆寫本體）：")
        for k in kept_vanilla[:20]:
            print(f"    {k}")

    # 已裁決不出貨（鍵落在 PZ 不載入的檔名、且找不到正確落點）
    n_unshipped, unshipped_drift, unshipped_unused = suppress_unshipped(merged_cn, merged_ch)
    if n_unshipped:
        print(f"  已裁決不出貨：剔除 {n_unshipped} 個 (檔,鍵)（見 sources/unshipped_keys.json）")
    if unshipped_drift:
        print(f"  ⚠️ unshipped_keys 錨點漂移 {len(unshipped_drift)} 條——上游動過，該重查 mod：")
        for line in unshipped_drift:
            print(line)
    if unshipped_unused:
        print(f"  ⚠️ unshipped_keys 未命中 {len(unshipped_unused)} 條（鍵已不在合併結果，"
              f"登記可退役）：{', '.join(unshipped_unused[:10])}")

    # gate：合併衝突 + CH 值層 + format 安全 + placeholder 崩潰簽名/token 不一致 + Lua 衝突
    # → 不寫出、非零退出
    if keep_anchor_errors:
        print(f"\n❌ vanilla keep 錨點失效 {len(keep_anchor_errors)} 處：")
        for e in keep_anchor_errors:
            print(e)
    if conflicts or ch_value_errors or fmt_errors or errors or lua_conflicts or keep_anchor_errors:
        if conflicts:
            print(f"\n❌ 合併衝突（同 (檔,鍵) 異值）{len(conflicts)} 處：")
            for c in conflicts:
                print(c)
        if fmt_errors:
            print(
                f"\n❌ format 安全 gate {len(fmt_errors)} 處"
                "（42.20.1 formatted() 必炸 % 序列，真相層須直寫安全值）："
            )
            for e in fmt_errors[:50]:
                print(e)
            if len(fmt_errors) > 50:
                print(f"  ...（還有 {len(fmt_errors) - 50} 處）")
        if ch_value_errors:
            print(
                f"\n❌ CH 值層 gate {len(ch_value_errors)} 處"
                "（簡體專用字殘留 / CN 有文而 CH 空值 / 非字串）："
            )
            for e in ch_value_errors[:50]:
                print(e)
            if len(ch_value_errors) > 50:
                print(f"  ...（還有 {len(ch_value_errors) - 50} 處）")
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
def vanilla_override_counts() -> dict[str, int | None]:
    """`{wid: 該 MOD 覆寫了幾個本體 (檔,鍵)}`——**下限**；完全無資料可判定者為 `None`。

    **覆寫本體是 MOD 自己的行為**：它在自帶的 `Translate/` 檔裡放了與本體同名的
    (檔,鍵)，而 PZ 把所有 mod 的翻譯檔 `map.put()` 進同一張全域字串表、後載入者勝
    （`Translator.java:353`），於是那句官方文字被改掉。本包對這些鍵**一律不出貨**
    （見「vanilla 出貨抑制」），遊戲內顯示的是本體原譯；但玩家仍該知道「裝了這個 MOD
    會有官方文字被改動」——尤其像 `UI_B42MP`（多人測試歡迎頁被換成模組作者募款文案）
    這種與該 MOD 功能無關的改動。故列成 SUPPORTED_MODS.md 的獨立一欄。

    **兩個來源取聯集**，缺一都會漏報，而漏報的代價是玩家被告知「這個 MOD 不動官方
    文字」而其實會動：

    1. `sources/en/<wid>.json`——上游自帶 EN 翻譯檔（只算 `translate_en`，且只算引擎
       真的會載入的分支；非有效分支是死資料，計進去只會虛報）。
    2. `sources/mods/<wid>/CN/`——As1 收錄的該 mod 譯文。**這一路不可省**：mod 可以
       只在自己的 CN／CH 檔覆寫本體鍵而 EN 檔沒有，只看 EN 就是重蹈
       `extract_vanilla_keys` 舊版的覆轍（2026-08-12 codex review 抓到：`3633421539`
       的 `Tooltip_item_Weight` 只在 CN 側；改聯集後另有 25 個 mod 由「—」變成有碰撞）。

    **回傳值是下限**：上游自帶的 CN/CH 檔我方沒有鏡像，覆寫只存在於那裡的鍵仍數不到。
    故渲染成 `≥N`，且 `—` 只代表「在這兩個口徑下未發現」，不是「保證沒有」。
    """
    import tracker  # 有效分支規則的單一實作來源，勿在此重寫

    vk = load_json(VANILLA_KEYS_JSON)
    scoped = {f: set(ks) for f, ks in (vk.get("scoped_keys") or {}).items()}
    out: dict[str, int | None] = {}
    for mod_dir in sorted(MODS_DIR.iterdir()):
        if not mod_dir.is_dir():
            continue
        hits: set[tuple[str, str]] = set()
        seen_any = False

        mirror = SOURCES / "en" / f"{mod_dir.name}.json"
        if mirror.is_file():
            seen_any = True
            recs = load_json(mirror)
            eff = tracker.resolve_effective_branches(recs)
            for rid in recs:
                if not rid.startswith("translate_en|") or not tracker.is_effective(rid, eff):
                    continue
                _, relpath, key = rid.split("|", 2)   # record id ＝ kind|relpath|key
                fname = relpath.rsplit("/", 1)[-1]
                if key in scoped.get(fname, ()):
                    hits.add((fname, key))

        cn_dir = mod_dir / "CN"
        if cn_dir.is_dir():
            seen_any = True
            for jf in sorted(cn_dir.glob("*.json")):
                for key in load_json(jf):
                    if key in scoped.get(jf.name, ()):
                        hits.add((jf.name, key))

        out[mod_dir.name] = len(hits) if seen_any else None
    return out


def cmd_manifest(check_only: bool = False) -> int:
    """check_only=True：不寫檔，產物與來源不同步即回傳 1。

    存在理由：SUPPORTED_MODS.md／README 摘要是生成物，但**沒有任何 gate 攔得到漂移**——
    改了 sources 卻沒重跑 manifest，文件就靜默停留在舊數字。實例：`cfcf3d8` 給
    3628922658 補了 18 個裸 ItemName 鍵（總數 628→646），文件卻一直寫 628，
    直到隔天有人剛好重生才發現。回歸測試 `scripts/test_manifest_fresh.py`。
    """
    print("=" * 60)
    print("manifest：由 metadata.json 彙整 README 支援清單")
    print("=" * 60)

    if not MODS_DIR.is_dir():
        # check 模式 fail-closed：來源缺席＝「無法驗證」，不是「驗過沒問題」。
        print("⚠️ 找不到 sources/mods/，README 未更新。")
        return 1 if check_only else 0

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
        return 1 if check_only else 0

    names_zh: dict = load_json(MOD_NAMES_ZH_JSON) if MOD_NAMES_ZH_JSON.exists() else {}

    def cell(text: str) -> str:
        # Markdown 表格安全：去換行、跳脫直線。**CR 也要去**——JSON 字串合法帶 \r，
        # 殘留的 CR 被 Markdown parser 當換行，整列會被拆斷。
        out = str(text).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
        return out.strip() or "—"

    # 已下架標記來自 tracker state（tracker.py 每日維護；缺檔＝視為全部在架）
    ts_path = PROJECT_ROOT / "tracker-state" / "timestamps.json"
    ts_items = load_json(ts_path).get("items", {}) if ts_path.exists() else {}
    removed_at = {
        w: (v.get("removed_at") or "")[:10] for w, v in ts_items.items() if v.get("removed")
    }
    active_rows = [r for r in rows if r[0] not in removed_at]
    removed_rows = [r for r in rows if r[0] in removed_at]

    overrides = vanilla_override_counts()

    def override_cell(ws_id: str) -> str:
        n = overrides.get(ws_id)
        if n is None:
            return "?"          # 兩個來源都沒有（多為已下架、無法重新下載）＝無法判定
        return f"⚠️ ≥{n}" if n else "—"

    def row_line(ws_id, name, mod_ids, key_count, extra: str = "") -> str:
        link = f"[{cell(name)}]({WORKSHOP_URL.format(ws_id)})"
        ids = ", ".join(f"`{m}`" for m in mod_ids) if mod_ids else "—"
        zh = names_zh.get(ws_id, {})
        # note（選配）＝涵蓋範圍例外說明：上游把文字放在 PZ 翻譯表取不到的地方
        # （Lua 寫死字面、自有文字系統、鍵前綴不在 getTextInternal 路由表），
        # 任何翻譯包都補不了。獨立一欄＝「已查證有此類文字的 MOD」可掃清單；
        # 空欄意為「未發現或未查證」，**不主動全庫普查**，遇到（多為玩家回報）才查證登記。
        cells = [
            link,
            cell(zh.get("name_zh", "")),
            cell(zh.get("summary", "")),
            ids,
            str(key_count),
            override_cell(ws_id),
            cell(zh.get("note", "")),
        ]
        if extra:
            cells.append(extra)
        return "| " + " | ".join(cells) + " |"

    all_mod_ids = {m for r in active_rows for m in r[2]}
    lines = [
        "| MOD | 中文名稱 | 摘要 | Mod IDs | 鍵數 | 覆寫本體 | 涵蓋範圍 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(row_line(*r) for r in active_rows)
    table = "\n".join(lines)
    print(
        f"  彙整 {len(rows)} 個 MOD（在架 {len(active_rows)}、已下架 {len(removed_rows)}、"
        f"中文名稱覆蓋 {sum(1 for w, *_ in rows if w in names_zh)} 個）"
    )

    removed_section = ""
    if removed_rows:
        rlines = [
            "| MOD | 中文名稱 | 摘要 | Mod IDs | 鍵數 | 覆寫本體 | 涵蓋範圍 | 下架偵測 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
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
        "> 中文名稱與摘要維護於 `sources/mod_names_zh.json`，修改後重跑 manifest。\n"
        "> 「覆寫本體」欄＝**該 MOD 自己改寫了幾個遊戲本體的官方翻譯鍵**。PZ 把所有 MOD 的翻譯檔"
        "併進同一張全域字串表、後載入者勝，所以裝了這類 MOD 之後，被它改寫的官方文字就會跟著變"
        "（例如原版彈匣被改成某槍械 MOD 的專屬名稱，或多人測試歡迎頁被換成模組作者的募款文案）。\n"
        "> **本包對這些鍵一律不出貨中文**，遊戲內顯示的是遊戲本體自己的譯文，"
        "所以本包不會幫任何 MOD 把官方文字改掉；此欄純粹是讓你知道**那個 MOD 本身**會動到哪些官方內容。\n"
        "> 數字取自「該 MOD 自帶的英文翻譯檔（只算引擎會載入的分支）」與「本包收錄的該 MOD 中文譯文」兩個來源的聯集，"
        "**是下限故標成 `≥`**——MOD 自帶的中文檔本包沒有鏡像，只存在於那裡的覆寫數不到。"
        "`—` 代表在這兩個來源裡沒發現，不等於保證沒有；`?` 代表該 MOD（多為已下架）兩個來源都取不到、無法判定。\n"
        "> 「涵蓋範圍」欄若有 ⚠️，代表該 MOD 有部分文字沒有走遊戲的翻譯機制"
        "（Lua 寫死、自有文字系統等），本包（以及任何翻譯包）都無法覆蓋，該部分會維持英文。\n"
        "> 此欄為**遇到才查證**的登記，並非全庫普查；空白只代表未發現或未查證，不保證完全涵蓋。\n\n"
        f"共支援 **{len(active_rows)} 個 Workshop 模組**（{len(all_mod_ids)} 個 mod ID）"
        f"{f'；另 **{len(removed_rows)} 個已下架**（翻譯保留，見文末）' if removed_rows else ''}。\n\n"
        f"{table}\n"
        f"{removed_section}"
    )
    drift: list[str] = []
    old_page = SUPPORTED_MODS_MD.read_text(encoding="utf-8") if SUPPORTED_MODS_MD.exists() else None
    if page != old_page:
        if check_only:
            drift.append(SUPPORTED_MODS_MD.name)
            print(f"❌ {SUPPORTED_MODS_MD.name} 與來源不同步（需重跑 manifest）")
        else:
            SUPPORTED_MODS_MD.write_text(page, encoding="utf-8", newline="\n")
            print(f"✅ 已更新 {SUPPORTED_MODS_MD.name}（{len(rows)} 個 MOD）")
    else:
        print(f"ℹ️ {SUPPORTED_MODS_MD.name} 內容未變動")

    if not README.exists():
        # 同上的 fail-closed：README 缺席代表摘要那半段沒驗到，不可因另一半同步就報綠。
        print(f"⚠️ README 不存在（{README.name}），跳過更新。")
        return 1 if (check_only or drift) else 0
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
        if check_only:
            drift.append(README.name)
            print(f"❌ {README.name} 支援清單摘要與來源不同步（需重跑 manifest）")
        else:
            README.write_text(updated, encoding="utf-8", newline="\n")
            print(f"✅ 已更新 {README.name} 支援清單摘要")
    else:
        print("ℹ️ README 支援清單摘要未變動")
    return 1 if drift else 0


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
  uv run scripts/build_mod.py manifest --check   # 只驗生成物是否與來源同步（不寫檔，有漂移退出 1）
        """,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="build",
        choices=["build", "manifest"],
        help="執行的命令（預設：build）",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="僅 manifest：不寫檔，生成物與來源不同步即退出 1",
    )
    args = parser.parse_args()
    # --check 只對 manifest 有意義。不擋的話 `build --check` 會被默默接受並跑真正的
    # 寫入式 build——使用者以為在 dry-run，實際成品已經被覆蓋。
    if args.check and args.command != "manifest":
        parser.error("--check 僅適用於 manifest 命令")

    if args.command == "build":
        sys.exit(cmd_build())
    elif args.command == "manifest":
        sys.exit(cmd_manifest(check_only=args.check))


if __name__ == "__main__":
    main()
