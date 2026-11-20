#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""回歸測試：`untranslatable_keys.json` 讓內部／佔位／淘汰物品不虛胖缺口（#231）。

執行：uv run scripts/test_untranslatable_keys.py
不依賴測試框架，任一項失敗即非零退出。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coverage_survey  # noqa: E402
import tracker  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FAIL = 0
CHECKS = 0


def check(cond: bool, msg: str) -> None:
    global FAIL, CHECKS
    CHECKS += 1
    if not cond:
        print(f"❌ {msg}", file=sys.stderr)
        FAIL += 1


p = ROOT / "sources/untranslatable_keys.json"
pairs, items = tracker.load_untranslatable(p)
data = json.loads(p.read_text(encoding="utf-8"))
entries = data["entries"]

# 登記是漸進成長的，不寫死條數；只驗正規化不讓檔域身分互相塌縮。
check(len(pairs) == len(entries), "檔域身分不得因正規化互相塌縮")
check(("ItemName", "MirageWardrobeRender.JacketBulky01") in pairs,
      "幻裝衣櫥渲染載體有登記")
check("MirageWardrobeRender.JacketBulky01" in items, "ItemName fullType 正確抽取")
check(("IG_UI", "HEADER_IG_UI_EN_90fordF350ambulance") in pairs,
      "workshop id 標頭鍵有登記（非玩家文本）")
check(all(isinstance(v, str) and v.strip() for v in entries.values()), "每條理由非空")

# 缺檔＝空集合（漸進登記）。
with tempfile.TemporaryDirectory() as td:
    missing = Path(td) / "missing.json"
    check(tracker.load_untranslatable(missing) == (set(), set()), "缺檔合法退化為空集合")

# canonical identity：UI/Tooltip 等 prefix key 去檔名前綴；ItemName 口徑**同樣 canonical**
# ——B41 前綴形 `ItemName_Base.Foo` 一律落成 runtime 的裸 `Base.Foo`（bare 形不動）。
with tempfile.TemporaryDirectory() as td:
    q = Path(td) / "canonical.json"
    q.write_text(json.dumps({"entries": {
        "UI.json|UI_Foo": "理由",
        "Tooltip.json|Tooltip_Bar": "理由",
        "ItemName.json|Base.X": "理由",
        "ItemName.json|ItemName_Base.Foo": "理由",
    }}), encoding="utf-8", newline="\n")
    cpairs, citems = tracker.load_untranslatable(q)
check(cpairs == {("UI", "Foo"), ("Tooltip", "Bar"),
                 ("ItemName", "Base.X"), ("ItemName", "Base.Foo")},
      f"檔域身分使用與 coverage 相同的 _key_stem/_canon_key：{cpairs}")
check(citems == {"Base.X", "Base.Foo"},
      "ItemName 口徑須是 canonical runtime fullType——留 raw 前綴形時 prep 靠 untr_pairs "
      f"扣得掉、coverage 靠這個集合扣不掉，同一筆裁決兩支工具結論相反：{citems}")

# 壞形狀必須 fail-closed：若退化成空集合，coverage/prep 會無聲重現 398 個雜訊。
for payload, why in [
    ([], "頂層 list"),
    ({}, "缺 entries"),
    ({"entries": []}, "entries 非 dict"),
    ({"entries": {"no-separator": "理由"}}, "key 缺 |"),
    ({"entries": {"ItemName|Base.X": "理由"}}, "檔名漏 .json"),
    ({"entries": {"|Base.X": "理由"}}, "檔名空值"),
    ({"entries": {"ItemName.json|": "理由"}}, "key 空值"),
    ({"entries": {"ItemName.json|Base.X": ""}}, "理由空值"),
    ({"entries": {1: "理由"}}, "非字串 key（JSON 落地成「1」）"),
]:
    with tempfile.TemporaryDirectory() as td:
        q = Path(td) / "u.json"
        q.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
        try:
            tracker.load_untranslatable(q)
            raised = False
        except ValueError:
            raised = True
        check(raised, f"{why} 應 ValueError，不得靜默退化")

# `prefixes`：使用者裁定「整個前綴不翻」的類別。判定只走 `untranslatable_matcher`，
# 同檔域、canonical 口徑；前綴邊界不能吞到相鄰的正式鍵。
with tempfile.TemporaryDirectory() as td:
    q = Path(td) / "prefix.json"
    q.write_text(json.dumps({"entries": {"UI.json|UI_Foo": "理由"},
                             "prefixes": {"IG_UI.json|IGUI_Bench_": "測試台",
                                          "UI.json|UI_Pre_": "理由"}}, ensure_ascii=False),
                 encoding="utf-8", newline="\n")
    hit = tracker.untranslatable_matcher(q)
    check(hit("IG_UI", "IGUI_Bench_New"), "前綴命中上游新加的鍵")
    check(not hit("IG_UI", "IGUI_BenchX"), "前綴邊界：IGUI_BenchX 不得被 IGUI_Bench_ 吞掉")
    check(not hit("Tooltip", "IGUI_Bench_New"), "前綴只比同檔域")
    check(hit("UI", "Pre_X"), "前綴同樣走 canonical（UI.json|UI_Pre_ 吃 UI_Pre_X）")
    check(hit("UI", "Foo"), "逐鍵登記照舊命中")
    check(tracker.load_untranslatable(q) == ({("UI", "Foo")}, set()),
          "load_untranslatable 只回逐鍵視圖，不把前綴混進身分集")
for payload, why in [
    ({"entries": {}, "prefixes": []}, "prefixes 非 dict"),
    ({"entries": {}, "prefixes": {"IGUI_X_": "理由"}}, "前綴缺 |"),
    ({"entries": {}, "prefixes": {"IG_UI|IGUI_X_": "理由"}}, "前綴檔名漏 .json"),
    ({"entries": {}, "prefixes": {"IG_UI.json|": "理由"}}, "前綴空值"),
    ({"entries": {}, "prefixes": {"IG_UI.json|IGUI_X_": " "}}, "前綴理由空值"),
    ({"entries": {}, "prefixes": {"UI.json|UI_": "理由"}}, "去檔名前綴後為空（會吞掉整個檔）"),
]:
    with tempfile.TemporaryDirectory() as td:
        q = Path(td) / "u.json"
        q.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
        for fn in (tracker.load_untranslatable, tracker.untranslatable_matcher):
            try:
                fn(q)
                raised = False
            except ValueError:
                raised = True
            check(raised, f"{why}：{fn.__name__} 應 ValueError，不得靜默退化")

# 真 repo：Knox 測試台走前綴規則；逐鍵登記不得回流到前綴已涵蓋的鍵（同一裁決只留一個家）。
real_hit = tracker.untranslatable_matcher(p)
check(real_hit("IG_UI", "IGUI_KnoxTB_zz_new"), "Knox 測試台上游新鍵由前綴規則扣掉")
check(not real_hit("IG_UI", "IGUI_Knox_Module_generator"), "Knox 正式介面鍵不被測試台前綴吞掉")
rules = tracker._load_untranslatable_rules(p)[2]
dup = [k for k in entries
       if any(tracker._key_stem(k.split("|")[0]) == s
              and tracker._canon_key(*k.split("|", 1)).startswith(pre) for s, pre in rules)]
check(not dup, f"entries 有 {len(dup)} 條已被 prefixes 涵蓋（如 {dup[:2]}），刪掉逐鍵登記")


def run_coverage(mirrors: dict[str, dict], *, registry: dict | None = None,
                 prefixes: dict | None = None):
    """在臨時 repo 跑 `tracker.cmd_coverage()`，回 `(rc, artifact, stdout)`。

    state 由鏡像實值推導：record 值就是鏡像值的 hash（`records_to_map` 口徑），否則
    coherence gate 會把案例整批擋掉而測不到原本要測的行為。

    stdout 一併回傳：行動分類（「重抽即消除」vs「重抽無效」）只存在於人讀輸出裡，
    只看 artifact 的 `kinds` 測不到「某個 kind 一項指示都不落」這種失效。
    """
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        src, en_dir, state_dir = _mk_repo(t, mirrors, registry, prefixes)
        old = (tracker.SOURCES, tracker.EN_TEXT_DIR, tracker.EN_CORPUS_HASHES_DIR)
        buf = io.StringIO()
        try:
            tracker.SOURCES, tracker.EN_TEXT_DIR = src, en_dir
            tracker.EN_CORPUS_HASHES_DIR = state_dir / "en_corpus_hashes"
            out = t / "coverage.json"
            with contextlib.redirect_stdout(buf):
                rc = tracker.cmd_coverage(SimpleNamespace(limit=1, out=str(out)))
            return rc, json.loads(out.read_text(encoding="utf-8")), buf.getvalue()
        finally:
            tracker.SOURCES, tracker.EN_TEXT_DIR, tracker.EN_CORPUS_HASHES_DIR = old


def _mk_repo(t: Path, mirrors: dict[str, dict], registry: dict | None, prefixes: dict | None):
    """臨時 repo：state（由鏡像實值推 hash）、`sources/en` 鏡像、空 vanilla 基準與 registry。"""
    src = t / "sources"
    en_dir = src / "en"
    state_dir = t / "tracker-state"
    en_dir.mkdir(parents=True)
    state_dir.mkdir()
    mods = {wid: {"extractor_schema": tracker.ITEM_MODULE_SCHEMA,
                  "records": {r: tracker.value_hash(v) for r, v in m.items()}}
            for wid, m in mirrors.items()}
    tracker.write_corpus_hashes({"mods": mods}, state_dir / "en_corpus_hashes")
    for wid, m in mirrors.items():
        (en_dir / f"{wid}.json").write_text(json.dumps(m), encoding="utf-8", newline="\n")
    (src / "vanilla_keys.json").write_text(
        json.dumps({"keys": [], "scoped_keys": {"ItemName.json": []}}),
        encoding="utf-8", newline="\n")
    if registry is not None or prefixes is not None:
        (src / "untranslatable_keys.json").write_text(
            json.dumps({"entries": registry or {}, "prefixes": prefixes or {}}, ensure_ascii=False),
            encoding="utf-8", newline="\n")
    return src, en_dir, state_dir


def run_survey(mirrors: dict[str, dict], *, registry: dict | None = None,
               prefixes: dict | None = None) -> str:
    """在臨時 repo 跑 `coverage_survey.main()`，回 stdout（「N 個鍵已裁決不補譯」只在人讀輸出）。"""
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        src, _, _ = _mk_repo(t, mirrors, registry, prefixes)
        (src / "unshipped_keys.json").write_text('{"entries": {}}', encoding="utf-8", newline="\n")
        dist = t / "dist_CH"
        dist.mkdir()
        (dist / "UI.json").write_text("{}", encoding="utf-8", newline="\n")
        old = (coverage_survey.ROOT, coverage_survey.DIST_CH, sys.argv)
        buf = io.StringIO()
        try:
            coverage_survey.ROOT, coverage_survey.DIST_CH, sys.argv = t, dist, ["coverage_survey"]
            with contextlib.redirect_stdout(buf):
                coverage_survey.main()
            return buf.getvalue()
        finally:
            coverage_survey.ROOT, coverage_survey.DIST_CH, sys.argv = old


# 兩個 consumer 不能只「共用 loader」卻沒真的使用結果：直接跑 coverage 的最小臨時 state，
# 同時守 `script_item_dn`（canonical runtime fullType）與 `translate_en`（canonical prefix）
# 兩口徑。
SCRIPTS = "mods/M/common/media/scripts/items.txt"
rid_dn = f"script_item_dn|{SCRIPTS}|Base.Hidden"
rid_pre = f"script_item_dn|{SCRIPTS}|Base.Prefixed"
rid_en = "translate_en|mods/M/common/media/lua/shared/Translate/EN/UI.json|UI_Internal"
mirror = {rid_dn: "Hidden Item", rid_pre: "Prefixed Item", rid_en: "Internal"}
rc, artifact, _ = run_coverage(
    {"1": mirror},
    registry={"ItemName.json|Base.Hidden": "內部",
              # **以 B41 前綴形登記的同一個物品**：coverage 的 gap 鍵恆是引擎查表用的裸
              # `Base.Prefixed`，這條登記若留 raw `ItemName_Base.Prefixed` 就扣不掉，
              # 而 prep 走 `untr_pairs`（早已 canonical）照樣扣得掉＝同一筆人工裁決在
              # 兩支工具給出相反結論。prep 側的對應案例是 test_prep_item_dn 4c4。
              "ItemName.json|ItemName_Base.Prefixed": "內部",
              "UI.json|UI_Internal": "內部"})
check(rc == 0, f"coverage 最小 state 應 rc=0，實得 {rc}")
check(artifact["totals"]["dn_gap"] == 0,
      "coverage 有使用 untr_items 扣 script_item_dn（含以 B41 前綴形登記的那筆）："
      f"dn_gap={artifact['totals']['dn_gap']} mods={artifact['mods']}")
check(artifact["totals"]["en_gap"] == 0,
      "coverage 有使用 canonical untr_pairs 扣 UI.json|UI_Internal")

# 前綴規則同樣要被 coverage 真的使用（translate_en 與 script_item_dn 兩口徑）。
prefix_mirror = {"1": {
    "translate_en|mods/M/common/media/lua/shared/Translate/EN/IG_UI.json|IGUI_Bench_New": "Bench",
    f"script_item_dn|{SCRIPTS}|Base.HidThing": "Hid Thing"}}
_, ctrl, _ = run_coverage(prefix_mirror)
check(ctrl["totals"]["en_gap"] == 1 and ctrl["totals"]["dn_gap"] == 1,
      f"控制組（無前綴）兩口徑應各 1 個缺口：totals={ctrl['totals']}")
rc, artifact, _ = run_coverage(
    prefix_mirror, prefixes={"IG_UI.json|IGUI_Bench_": "測試台", "ItemName.json|Base.Hid": "內部物品"})
check(rc == 0, f"coverage 前綴 state 應 rc=0，實得 {rc}")
check(artifact["totals"]["en_gap"] == 0 and artifact["totals"]["dn_gap"] == 0,
      f"coverage 沒吃 prefixes：totals={artifact['totals']}")

# coverage_survey 是第三個 consumer：同一份登記（canonical 逐鍵＋前綴）要在它的人讀輸出裡
# 算成「已裁決不補譯」；它曾用 raw 鍵比對、以 `UI.json|UI_*` 登記的鍵全沒扣到（2026-11-20 修）。
# 另放一個沒登記的正式鍵，分母才不會是 0。
EN_DIR = "translate_en|mods/M/common/media/lua/shared/Translate/EN"
survey_mirror = {"1": {f"{EN_DIR}/UI.json|UI_Internal": "Internal",
                       f"{EN_DIR}/IG_UI.json|IGUI_Bench_New": "Bench",
                       f"{EN_DIR}/UI.json|UI_Real": "Real"}}
ctrl_out = run_survey(survey_mirror)
check("0 個鍵已裁決不補譯" in ctrl_out, f"coverage_survey 控制組（無登記）不該扣：{ctrl_out[:300]!r}")
got_out = run_survey(survey_mirror, registry={"UI.json|UI_Internal": "內部"},
                     prefixes={"IG_UI.json|IGUI_Bench_": "測試台"})
check("2 個鍵已裁決不補譯" in got_out and "有效鍵合計 1" in got_out,
      f"coverage_survey 沒用 canonical 逐鍵登記或前綴規則扣除：{got_out[:300]!r}")

# `stale_schema`（號稱現行 schema 卻仍是裸 key）必須與 schema／mirror／stale_state 同屬
# 「重抽即消除」桶。漏掉它時 `kinds == {"stale_schema"}` 的 mod 一項行動分類都不落：
# 它只出現在總數與明細列表裡，讀者看得到數字卻拿不到任何指示，`_pri` 還會把它排在
# 「要修 parser／回報上游」那批之前，把真正要動手的擠出預覽。artifact 的 `kinds` 兩種
# 實作下都一樣，故**必須驗人讀輸出**。
bare_mirror = {f"script_item_dn|{SCRIPTS}|ClassicTire1": "Classic Tire"}
rc, artifact, out = run_coverage({"1": bare_mirror})
check(rc == 0, f"coverage 裸 key state 應 rc=0，實得 {rc}")
check(artifact["undecidable"]["1"]["kinds"] == ["stale_schema"],
      f"現行 schema 的裸 key 未列 stale_schema：{artifact['undecidable']}")
check("重抽即消除" in out,
      f"stale_schema 未歸進「重抽即消除」桶＝該 mod 一項行動指示都沒有：{out!r}")
check("裸 key 殘留" in out,
      f"「重抽即消除」的文案未涵蓋 stale_schema（分類名不符實）：{out!r}")

# 真正玩家可見物品不得被 pattern 誤扣：registry 是逐鍵人工清單，不是 regex。
check("Base.AxleModernTire2" not in items, "正常車零件未被扣除")
check("Base.9mmG17RMagazine" not in items, "正常彈匣未被扣除")

if FAIL:
    print(f"\n❌ test_untranslatable_keys：{FAIL}/{CHECKS} 項失敗", file=sys.stderr)
    sys.exit(1)
print(f"✅ test_untranslatable_keys：{CHECKS} 項全過"
      f"（{len(entries)} 條、雙口徑、壞形狀 fail-closed）")
