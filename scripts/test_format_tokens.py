# /// script
# requires-python = ">=3.10"
# ///
"""42.20.1 Translator.formatted() 安全化（sanitize_format_tokens）回歸測試

覆蓋：sanitize 語意（裸 % 逸出、安全 token 保留、冪等）、三份獨立實作同語意
（builder／oracle／lint，防各自演化出分歧文法）、verify [4] 殘留必炸序列 FAIL
（CN/CH 雙側、例外鍵不豁免）、multiset 排除 %%、[1] 期望值 sanitize 包裝與
own 層原值 fail-loud 的不對稱、build format 安全 gate 的三個真相層掃描域。

執行：uv run scripts/test_format_tokens.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mod  # noqa: E402
import lint_ch  # noqa: E402
import verify_dist  # noqa: E402

S = build_mod.sanitize_format_tokens

# 1. sanitize 語意：裸 % 一律 %%，安全 token 原樣
CASES = {
    "50%的机率": "50%%的机率",                    # 裸 %CJK（LETHAL 主力）
    "力量 +5%": "力量 +5%%",                      # 行尾裸 %
    "%1 的 %2": "%1 的 %2",                       # 編號佔位保留
    "%s (%d)": "%s (%d)",                          # printf 保留（不轉編號！）
    "%.1f 公里": "%.1f 公里",                      # %.Nf 保留
    "%+.3f": "%+.3f",                              # 帶 + 旗標浮點保留
    "%i 個": "%%i 個",                             # %i Java 必炸 → 逸出
    "%1%.": "%1%%.",                               # Moodles 崩潰簽名
    "%.d": "%%.d",                                 # EHR 崩潰簽名
    "已是 %% 安全": "已是 %% 安全",                # 既有逸出不動
    "%10": "%10",                                  # %1 匹配後餘 0（遊戲同語意）
    "%0 開頭": "%%0 開頭",                         # %0 不在遊戲文法 → 逸出
    "已領取 %1$s/%2$s": "已領取 %1/%2",            # Java 完整位置參數 → PZ 簡寫
    "%1$d 級 %2$.1f": "%1 級 %2",                  # $d/$.Nf 後綴同樣剝除
    "%1$,d 個": "%1 個",                           # 帶 flag 的完整形式
    # --- precision 文法必須 ASCII-only 且有上限（JDK 對兩者皆拋未捕例外）---
    "%.١f": "%%.١f",                               # 阿拉伯數字：\d 會誤放行 → 須逸出
    "%.2147483648f": "%%.2147483648f",             # precision 超界 → 須逸出
    "%.12f": "%.12f",                              # 兩位 precision 仍合法
    # --- tokenizer 優先序：%% 最優先，不得被位置參數規則穿透 ---
    "%%1$s": "%%1$s",                              # 字面 %% + 文字，整體不得改動
    "%%%1$s": "%%%1",                              # %% 字面 + 真位置參數，只轉後者
    "%1$0005d": "%1",                              # zero-pad width（flags/width 重疊區）
    "%1$tY": "%1",                                 # date/time conversion 須完整消費
    "%1$s$A": "%1$s$A",                            # 歧義（緊接 $）→ 保守不轉，交 oracle
    "%10$s": "%10$s",                              # index 超出 %1-%9 → 不轉，交 oracle
    "100%F": "100%%F",                             # %F Java 無此轉換符 → 逸出
    "A<LINE>B": "A<LINE>B",                        # 標籤不動
    "無百分號": "無百分號",
}
for raw, want in CASES.items():
    got = S(raw)
    assert got == want, f"sanitize({raw!r}) = {got!r}，應為 {want!r}"
    assert S(got) == got, f"不冪等：{raw!r} → {got!r} → {S(got)!r}"

# 2. builder / oracle / lint 三份獨立實作同語意（防文法各自漂移）
samples = list(CASES) + list(CASES.values()) + [
    "%%%", "%", "%%", "%.2fh 尸体=%%.d", "%1%%. <br>超过50%最终", "%s%d%i%.1f%",
    "%00FF00 顏色碼", "%10 個", "%9%0",
    "%%1$s", "%1$tY", "%1$s$A", "%10$s", "%.١f", "%.2147483648f", "%%%1$s", "%1$Tb",
]
for v in samples:
    b, o, li = S(v), verify_dist.sanitize_expectation(v), lint_ch.fmt_sanitize(v)
    assert b == o, f"builder/oracle 分歧：{v!r} → build={b!r} oracle={o!r}"
    assert b == li, f"builder/lint 分歧：{v!r} → build={b!r} lint={li!r}"
assert verify_dist.sanitize_expectation(123) == 123, "oracle 非字串應原樣返還"

# 2b. %0 不得被任一文法當合法 token 吸收（遊戲 FORMAT_TOKEN 只認 %[1-9]）
assert verify_dist.extract_tokens("%0 開頭")[1], "oracle grammar 誤吞 %0（[4] 必炸檢查會漏）"
assert build_mod.scan_percents("%0 開頭")[1], "builder grammar 誤吞 %0"

# 3. verify [4]：dist 殘留必炸序列 → FAIL（例外鍵不豁免）；乾淨值不誤殺
def wjson(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

with tempfile.TemporaryDirectory() as td:
    cn_d, ch_d = Path(td) / "CN", Path(td) / "CH"
    wjson(cn_d / "UI.json", {
        "bad": "50%的机率", "ok": "50%% (%1)", "pf": "%s %.1f", "chbad": "50%%", "z": "%0 開頭",
    })
    wjson(ch_d / "UI.json", {
        "bad": "50%%的機率", "ok": "百分之五十（%1）", "pf": "%s %.1f", "chbad": "50%", "z": "%%0 開頭",
    })
    # chbad 登記為例外 → 新的必炸殘留 FAIL 不得因此豁免（CH 側尤然）
    ok, fail, _ = verify_dist.check_placeholder(
        str(cn_d), str(ch_d), {"UI.json|chbad": {"cn_safe_value": "50%%", "reason": "t"}}
    )
    text = "\n".join(fail)
    assert not ok and "必炸 % 序列" in text and "'bad'" in text, fail
    assert "'ok'" not in text, f"%% 不入 multiset：CN 有 %% CH 無不得誤殺：{fail}"
    assert "'pf'" not in text, f"printf token 誤殺：{fail}"
    assert "CH 值殘留必炸" in text, f"CH 側必炸殘留未檢／被例外豁免：{fail}"
    assert any("'z'" in f and "CN" in f for f in fail), f"%0 未被判必炸（grammar 誤吞）：{fail}"

# 3b. verify [4]：dist 殘留 Java 完整位置參數 %N$（$s 不含 %，% 掃描看不到）→ FAIL
with tempfile.TemporaryDirectory() as td:
    cn_d, ch_d = Path(td) / "CN", Path(td) / "CH"
    wjson(cn_d / "UI.json", {"p": "已领取 %1$s/%2$s"})
    wjson(ch_d / "UI.json", {"p": "已領取 %1$s/%2$s"})
    ok, fail, _ = verify_dist.check_placeholder(str(cn_d), str(ch_d), {})
    assert not ok and sum("位置參數" in f for f in fail) == 2, f"%N$ 兩側皆須 FAIL：{fail}"
    # sanitize 保守不轉的兩類（歧義 / index 超界）必須由 oracle 攔下，不得靜默出貨
    for bad in ("%1$s$A 尾", "第 %10$s 項"):
        wjson(cn_d / "UI.json", {"p": bad})
        wjson(ch_d / "UI.json", {"p": bad})
        ok, fail, _ = verify_dist.check_placeholder(str(cn_d), str(ch_d), {})
        assert not ok and any("位置參數" in f for f in fail), f"{bad!r} 未被 oracle 攔下：{fail}"
    # 反向：字面 %% 之後的 %N$ 是**文字**（formatFixer 原樣、顯示 %1$s），殘留檢查
    # 不得穿透逸出誤報——與 sanitize 同一套 %% 優先序，兩處必須一致
    for good in ("%%1$s", "%%0$s", "%%10$s", "%%%%1$s"):
        assert build_mod.sanitize_format_tokens(good) == good, f"{good!r} 應原樣保留"
        wjson(cn_d / "UI.json", {"p": good})
        wjson(ch_d / "UI.json", {"p": good})
        ok, fail, _ = verify_dist.check_placeholder(str(cn_d), str(ch_d), {})
        assert ok, f"{good!r} 是安全值，殘留檢查穿透 %% 誤報：{fail}"
    assert verify_dist.has_positional_residue("%%%1$s"), "%%% 後的第三個 % 是真殘留，不得漏"
    wjson(cn_d / "UI.json", {"p": "已领取 %1/%2"})
    wjson(ch_d / "UI.json", {"p": "已領取 %1/%2"})
    ok, fail, _ = verify_dist.check_placeholder(str(cn_d), str(ch_d), {})
    assert ok, f"PZ 簡寫 %N 不得誤報：{fail}"

# 4. builder token_multiset：獨立 %% 排除、緊鄰 token 的 %% 必須配對、真 token 保留
tm = build_mod.token_multiset
assert tm("50%% (%1)") == tm("百分之五十（%1）"), "獨立 %% 應排除於 multiset"
assert tm("%s %.1f <br>") != tm("%s <br>"), "%.1f 缺失須偵測"
assert tm("%+.3f") == tm("%+.3f") and sum(tm("%+.3f").values()) == 1, "%+.Nf 應為單一 token"
# 格式單位 %1%%：CH 漏掉百分號＝數值單位消失，須偵測（獨立 %% 的自由譯法不受影響）
assert tm("進度 %1%%") != tm("進度 %1"), "緊鄰 token 的 %% 漏失未偵測（數值單位消失）"
assert tm("%.1f%%") != tm("%.1f"), "%.1f%% 的格式單位漏失未偵測"
assert sum(tm("%1%%").values()) == 1, "%1%% 應整體吸收為單一 token"
for v in ("進度 %1%%", "%.1f%% 完成", "50%% 與 %1%%"):
    assert build_mod.token_multiset(v) == Counter(
        t for t in verify_dist.extract_tokens(v)[0] if t != "%%"
    ), f"builder/oracle multiset 分歧：{v!r}"

# 5. verify [1]：As1 原值裸 % → 期望 dist 為 sanitize 後值；registry 登記值同語意
with tempfile.TemporaryDirectory() as td:
    as1_d, dist_d = Path(td) / "as1", Path(td) / "dist"
    wjson(as1_d / "UI.json", {"k": "50%的机率", "e": "%1%.", "v": "旧值 5%"})
    wjson(dist_d / "UI.json", {"k": "50%%的机率", "e": "%1%%.", "v": "新值 5%%"})
    exc = {"UI.json|e": {"cn_safe_value": "%1%%.", "as1_value": "%1%."}}
    cov = {"UI.json|v": {"value": "新值 5%", "as1_value": "旧值 5%"}}
    ok, details, *_ = verify_dist.check_cn_parity(str(as1_d), str(dist_d), exc, {}, cov)
    assert ok, f"sanitize 後期望值應 parity 通過：{details}"
    # dist 未 sanitize（模擬 build 漏逸出）→ 必須 FAIL
    wjson(dist_d / "UI.json", {"k": "50%的机率", "e": "%1%%.", "v": "新值 5%%"})
    ok, details, *_ = verify_dist.check_cn_parity(str(as1_d), str(dist_d), exc, {}, cov)
    assert not ok and any("'k'" in d for d in details), f"未逸出 dist 應 FAIL：{details}"

# 6. verify [1] own 層**刻意不套 sanitize**：真相檔須直寫安全值，dist 與其不符即 FAIL
#    （與 As1/registry 路徑的 sanitize 包裝不對稱——這是 fail-loud 設計，勿「順手」對稱化）
with tempfile.TemporaryDirectory() as td:
    as1_d, dist_d = Path(td) / "as1", Path(td) / "dist"
    wjson(as1_d / "UI.json", {})
    wjson(dist_d / "UI.json", {"o": "5%%"})
    ok, details, *_ = verify_dist.check_cn_parity(
        str(as1_d), str(dist_d), {}, {"UI.json": {"o": {"en": "5%", "ch": "5%%", "cn": "5%"}}}
    )
    assert not ok and any("原創鍵 'o'" in d for d in details), (
        f"own 真相未修（cn='5%%'）卻放行＝fail-loud 失效：{details}"
    )
    ok, details, *_ = verify_dist.check_cn_parity(
        str(as1_d), str(dist_d), {}, {"UI.json": {"o": {"en": "5%", "ch": "5%%", "cn": "5%%"}}}
    )
    assert ok, f"own 真相已直寫安全值應 PASS：{details}"

# 7. build format 安全 gate：三個真相層（corpus / own_translations ch+cn / own-mod CN）
with tempfile.TemporaryDirectory() as td:
    own_cn_dir = Path(td) / "mods" / "999" / "CN"
    wjson(own_cn_dir / "UI.json", {"m": "9%", "safe": "9%%"})
    merged_ch = {"UI.json": {"c": "壞 5%", "cok": "好 5%%"}}
    own = {"UI.json": {"o": {"en": "e", "ch": "壞 %", "cn": "壞 %"}}}
    errs = build_mod.format_gate_errors(merged_ch, own, [own_cn_dir])
    joined = "\n".join(errs)
    assert len(errs) == 4, f"三真相層各自掃描域有缺（應 4 條：corpus 1、own ch/cn 2、own-mod 1）：{errs}"
    assert "sources/ch/UI.json | c" in joined and "'壞 5%%'" in joined, joined
    assert ".ch" in joined and ".cn" in joined, f"own 須掃 ch 與 cn 雙欄：{errs}"
    assert "mods/999/CN/UI.json | m" in joined, f"own-mod CN 未納入 gate 掃描域：{errs}"
    assert not build_mod.format_gate_errors(
        {"UI.json": {"c": "好 5%%"}}, {}, []
    ), "全安全值不得誤報"

# 8. restore_over_escape：錨點漂移比對只還原、不 sanitize
#    2026-08-10 實案：42.20 的 As1 把 `%s`/`%1` 全逸出成 `%%s`/`%%1`，verify [1] 的
#    `as1_value` 錨點比對直接拿 As1 原始值比，讓 6 條帶佔位符的登記全數假報「上游原值
#    已變，請複核是否退役」。build 端不受影響是因為它的錨點快照取在 normalize 之後。
#    照假警報退役 override＝把上游的過度逸出當成正確值收下，佔位符會變字面文字。
R = verify_dist.restore_over_escape
assert R("可以以 %%s 等级 %%d 操作!") == "可以以 %s 等级 %d 操作!", "安全 token 還原失敗"
assert R("所需肥皂:%%1") == "所需肥皂:%1", "%%1 還原失敗"
assert R("精度: %%1%% (+%%2)%%") == "精度: %1%% (+%2)%%", "混合逸出還原失敗"
assert R("暴露=%%.1f 时间=%%.2fh") == "暴露=%.1f 时间=%.2fh", "精度 token 還原失敗"
assert R("%%%%") == "%%", "全域 %→%% 使合法字面 %% 變 %%%% 的還原失敗"
# **只還原不 sanitize**：as1_value 記的是 As1 原值不是應出貨值，多套 sanitize 會讓
# 裸 % 被逸出而再次假報漂移
assert R("50%的机率") == "50%的机率", "restore 不得順手 sanitize 裸 %"
assert R("沒有百分號") == "沒有百分號" and R("") == "", "無 %% 者原樣返還"
assert R(R("可以以 %%s 操作")) == R("可以以 %%s 操作"), "還原須冪等"
# as1_expectation 仍是「還原後再 sanitize」——抽出 restore 不得改變其語意
assert verify_dist.as1_expectation("50%的机率") == "50%%的机率", "as1_expectation 語意被改壞"
assert verify_dist.as1_expectation("所需肥皂:%%1") == "所需肥皂:%1", "as1_expectation 語意被改壞"
assert verify_dist.as1_expectation(None) is None, "非字串原樣返還"

print("PASS: format tokens 8/8 案例通過")
