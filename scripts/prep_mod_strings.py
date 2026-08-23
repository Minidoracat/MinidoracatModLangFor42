# /// script
# requires-python = ">=3.11"
# ///
"""把一或多個 mod 的有效缺口抽成「相異字串清單」，供補譯流程使用。

    uv run scripts/prep_mod_strings.py <wid> [<wid> ...] --out <檔案>

本支提**所有落點檔對得上的 JSON／script 物品名有效缺口**；物品名走專用 getter，
不依賴 MOD Lua consumer。

兩類來源：上游 `Translate/EN` 的鍵（`translate_en`），以及 script 定義的物品顯示名
（`script_item_dn`，落點固定 `ItemName`、鍵為完整 fullType `Module.Item`）。後者需
per-mod `extractor_schema >= 9` 才有 module 可精確比對；不可判定者逐類計數列出，
**不靜默跳過**（#221 的病因就是靜默：報表報 0、玩家看到一整批英文物品名）。

`shipped` 取 **dist**（已套 vanilla／unshipped 出貨抑制），`tracker.py coverage` 取
**真相層**；兩者對缺口的結論相同——差集實測 146 鍵全是 vanilla 鍵，而 vanilla 在兩邊
都另外扣掉。問的問題不同（「dist 出貨了嗎」vs「真相層收了嗎」），別把差集當成矛盾。

輸出每項：
    en / keys（連動出貨鍵數）/ files（落點檔）/ key_samples / wid
並附 `_gap`：`"<落點檔>|<鍵>" -> en`，落地時用它把譯文展開回所有鍵。

`_owner_conflicts`／`_owner_conflicts_other`／`_owner_conflicts_resolved` 的每個 owner
條目帶 `{en, has_json_en, en_source}`（見 `annotate`）：`has_json_en` 決定「抑制後這個
owner 的玩家看到自己 mod 的英文，還是字面鍵名」，是 translate／unship 裁決的承重事實。

有效性判準見 tracker.resolve_effective_branches：`common` ＋唯一最佳版本夾。
此處**只濾分支不濾副檔名**——`_EN.txt` 的鍵在執行期沒有 EN 定義，但我方譯文
照樣生效（Translator 按鍵查譯文），把它們算進缺口才對。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tracker  # noqa: E402
from coverage_survey import DIST_CH, WHITELIST, target_file  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def branch_ok(rid: str, eff: dict[str, set[str]]) -> bool:
    _, _, rest = rid.partition("|")
    relpath, _, _ = rest.partition("|")
    parts = relpath.split("/")
    if len(parts) < 3 or parts[0] != "mods":
        return True
    return parts[2] in eff.get(parts[1], set())


# owner 粒度（mod root）的定義以 tracker 為準（`coverage` 同一把尺），勿在此再實作一份。
owner_of = tracker.owner_of


_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


def norm_en(s: str) -> str:
    """衝突比對用的**保守**正規化：彎引號折成直引號 ＋ 同行空白收斂。

    逐字元相等會讓同一個 workshop 項目底下的**變體 mod**（`Firearms` vs `FirearmsBETA`、
    `vlmainquest1` vs `..._legacy_42_12`、`GaelGunStore` vs `..._Legacy`）因排版級漂移全部
    升格成 blocking：實測 wid `3620552991` 的 `IGUI_VLQ_2_Task_q1s038` 兩側只差
    `Dr. Venter's` 的 `’`(U+2019) vs `'`。那種「衝突」對譯文沒有語意差別，卻讓 prep 對整個
    mod 恆非零退出且無自動出路。正規化後全等即不算衝突；**原值照樣寫進 artifact** 供人核。

    **刻意不用 NFKC**：它會把全形字母與相容字元（`Ⅳ`、`㎜`、上標）折成普通字元，而那些
    在型號／單位文案裡是有語意的差異，折掉就是把真 owner 衝突靜默合併——與 census 的
    fail-closed 取向相反。空白只收斂「行內」的連續空白，不把多行合成一行；行的切法用
    `str.splitlines()`，故 `\v`／`\f`／`U+2028/2029` 等也算換行並統一改寫成 `\n`、行首尾
    空白（含 NBSP）被剝除——`"a\u2028b"` 與 `"a\nb"` 正規化後同值。實務影響≈0（值含
    換行者早被 `malformed` 擋在 census 外），列出是讓邊界可查。
    """
    return "\n".join(" ".join(line.split())
                     for line in s.translate(_QUOTES).splitlines())


def census_signature(owners: dict[str, str]) -> str:
    """該鍵完整 census 的簽名：`sorted((owner, raw_en))` 的 canonical JSON sha256[:16]。

    **必須錨定完整的 owner→原值對映**，不能只記「這個鍵已裁決過」：只標一次的話，日後
    新增 owner 或上游改值都會被永久放行，而那正是需要重新裁決的時機。用**原值**而非
    `norm_en` 正規化值——裁決是對著實際上游文本做的。

    **序列化必須是 canonical JSON，不可用 `f"{o}={v}"` 串接**：EN 值本身可含 `=` 與換行
    （`malformed` 那類上游值就是），`{"a": "b\\nc=d"}` 與 `{"a": "b", "c": "d"}` 會壓成同一
    字串，造成裁決錯誤命中而放行一個從未裁決過的衝突。
    """
    return hashlib.sha256(
        json.dumps(sorted(owners.items()), ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


# `has_json_en` 用的來源標記：script DisplayName 不是 Translate 檔，走的是
# `getItemNameFromFullType()` → `Item.getDisplayName()` 的 fallback 路徑。
EN_SOURCE_SCRIPT = "script"


def loadable_json(basename: str) -> bool:
    """這個上游來源檔在 B42 會被 `Translator` 載入嗎？

    **兩個條件都要滿足**，缺一即取不到 EN：
      * 副檔名是 `.json`——`Translator.tryFillMapFromFile()` 的路徑寫死 `.json`
        （`Translator.java:354`），legacy `_EN.txt` 在 B42 永不被讀取。
      * 檔名 stem 在 `Translator.BY_NAME` 的 31 個白名單內——故 `UI_EN.json`
        這種「是 json 但檔名不對」的死檔同樣不算（As1 上游就有這樣出貨的）。
    """
    stem, _, ext = basename.rpartition(".")
    return ext == "json" and stem in WHITELIST


def annotate(owners: dict[str, str], srcs: dict[str, str]) -> dict[str, dict]:
    """把 `{owner: en}` 加註成 `{owner: {en, has_json_en, en_source}}`，供裁決用。

    裁決 `translate` 還是 `unship` 的關鍵是「抑制後這個 owner 的玩家看到什麼」：
      * `has_json_en: true` → 看到該 mod 自己的英文（Translator map 有 EN 底層）。
      * `has_json_en: false` 且 `en_source` 是死檔（`*_EN.txt`／非白名單檔名）
        → 看到 `getTextInternal()` 回傳的**字面鍵名**（`Translator.java:495`）。
        unship 對這個 owner 是有可見代價的，要在 reason 裡記為已接受殘留。
      * `has_json_en: false` 且 `en_source == EN_SOURCE_SCRIPT` → 仍看到英文，但走
        `getItemNameFromFullType()` → `Item.getDisplayName()` 的 fallback，不經
        Translator。**不可與死檔混為一談**，故 `en_source` 必須一起輸出。

    `srcs` 缺該 owner 時 `en_source` 為 `None`、`has_json_en` 為 `False`——那是
    en_src 與 census 不同步（不該發生），保守當成沒有 EN 底層而非靜默放行。
    """
    return {o: {"en": en,
                "has_json_en": bool(srcs.get(o)) and loadable_json(srcs[o]),
                "en_source": srcs.get(o)}
            for o, en in owners.items()}


def converge_owner(recs: dict, mirror: dict, eff: dict, *, vanilla: set[str],
                   dn_gap: dict[str, set[str]],
                   src: dict[tuple[str, str], str] | None = None
                   ) -> dict[tuple[str, str], str]:
    """把一個 wid 的 record 收斂成 `{(owner, "檔|鍵"): en}`，**不扣 shipped**。

    兩層優先序都在同一個 owner 內套（跨 owner 是衝突，不是覆寫）：
      * 分支層：`common` 先、有效版本夾後覆寫（引擎讓版本夾疊在 common 之上）。
      * 來源層：`translate_en` 勝過 `script_item_dn`（引擎先查 ItemName map，查不到才
        退回 `Item.getDisplayName()`）。上游留白的 `translate_en` 同樣參與——它會把
        同鍵的 script DisplayName 頂掉，只 `continue` 會留下無據的英文。
    `dn_gap` 是 `_item_dn_stats` 判出的可補物品名，形狀 `{owner: {fullType}}`。
    `src` 是選配 out-param：填入每個 `(owner, "檔|鍵")` **勝出來源**的檔名
    （`"UI.json"`／`"UI_EN.txt"`）或 `EN_SOURCE_SCRIPT`。做成 out-param 而非改回傳
    型別，是為了讓既有呼叫端零改動——而勝出優先序只能在這裡決定，另寫一份判定就會
    與本函式分岔（`AGENTS.md`「不要另寫第二套」）。
    """
    out: dict[tuple[str, str], str] = {}
    # **dn 值一律走 `tracker.winning_dn_text`**：勝出 rid 由 state 決定（同 owner 內
    # common 先、版本夾後覆寫），勝出 rid 缺值即整鍵不入——直接迭代 mirror rows 會在
    # 「版本夾那筆缺值」時回退用 common 的舊英文（backfill 中斷殘跡可達），拿低優先序
    # 的過期值當翻譯來源，census 也用它比 owner 衝突＝與引擎執行期相反。
    dn_val = tracker.winning_dn_text(recs, mirror, eff, is_eff=lambda r, e: branch_ok(r, e))
    for owner, keys in dn_gap.items():
        for k in keys:
            if (owner, k) in dn_val:
                out[(owner, f"ItemName|{k}")] = dn_val[(owner, k)]
                if src is not None:
                    src[(owner, f"ItemName|{k}")] = EN_SOURCE_SCRIPT
    en_rids = [r for r in recs if r.startswith("translate_en|") and branch_ok(r, eff)]
    # **空值的語意由 `tryFillMapFromFile():362` 的 put 條件決定**：
    # `if (!map.containsKey(k) || !isNullOrEmpty(v))`，且 `isNullOrEmpty` 是
    # `s == null || s.isEmpty()`（`StringUtils.java:11`）——**只認長度零，純空白 `"  "` 是
    # 非空值、照常 put／覆寫**。三種形狀，不可混為一談：
    #   * 首次就是 `""` → put（該鍵存在、值為空）。`getItemNameFromFullType():601` 只對
    #     `null` 才 fallback 到 script DisplayName，空字串不是 null，故 **script 被抑制、
    #     顯示空白** → 該鍵不是缺口，且要把同鍵的 script 值移除。
    #   * 已有非空值後才遇到 `""`（common 非空、版本夾留空）→ 引擎**不覆寫**，執行期仍是
    #     那個非空值 → 保留，否則真缺口會從 census／`_gap` 消失。
    #   * 值是**純空白**（`"  "`）→ 不是 isEmpty，引擎**一律 put／覆寫**——不論先後，
    #     執行期都顯示空白 → 不是缺口，移除同鍵值。誤用 `.strip()` 判空會把這支走成
    #     「不覆寫」，census 留著 common 的非空值＝與引擎相反的結論。
    seen_en: set[tuple[str, str]] = set()
    for rid in sorted(en_rids, key=lambda r: tracker._branch_tag(r) != "common"):
        relpath, _, key = rid.partition("|")[2].partition("|")
        if key in vanilla:
            continue
        base = os.path.basename(relpath)
        tgt = target_file(base.rsplit(".", 1)[0], key)
        if not tgt:
            continue
        val = mirror.get(rid)
        ok = (owner_of(rid), f"{tgt}|{key}")
        if rid not in mirror:
            # **鏡像缺該筆值 ≠ 上游把它定義成空**（引擎的 put 語意只適用後者），但也
            # **不能保留先前寫入的低優先值**：迭代順序 common 先、版本夾後，走到這裡的
            # 缺值 rid 若是版本夾那筆，它才是 runtime 勝出者——執行期值未知，回退用
            # common 的舊英文＝拿過期值當翻譯來源。整鍵撤銷，交給呼叫端的 `en_missing`
            # 通報（mirror 盲區）。不標 seen：後續若另有同鍵 rid（不同檔）仍可重建。
            out.pop(ok, None)
            if src is not None:
                src.pop(ok, None)
            continue
        if not isinstance(val, str) or val == "":
            if ok not in seen_en:
                out.pop(ok, None)
                if src is not None:
                    src.pop(ok, None)
                seen_en.add(ok)
            continue
        if not val.strip():
            out.pop(ok, None)   # 純空白：引擎一律覆寫，執行期顯示空白＝不是缺口
            if src is not None:
                src.pop(ok, None)
            seen_en.add(ok)
            continue
        out[ok] = val
        if src is not None:
            src[ok] = base
        seen_en.add(ok)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wids", nargs="*")
    ap.add_argument("--out", required=True)
    ap.add_argument("--check-decisions", action="store_true",
                    help="只驗全庫 owner conflict decision／unship registry，不產生翻譯待辦")
    args = ap.parse_args()
    if not args.wids and not args.check_decisions:
        ap.error("至少給一個 wid；若只驗裁決台帳，使用 --check-decisions")

    shipped_ch = {f"{p[:-5]}|{k}": v
                  for p in os.listdir(DIST_CH) if p.endswith(".json")
                  for k, v in _jload(DIST_CH / p).items()}
    shipped = set(shipped_ch)
    # **CN 側也要錨定**：本包是雙語出貨，人工裁決的產物包含兩邊；只驗 CH 的話 CN 被改成
    # 偏向某個 owner 時，decision 仍會靜默放行。**目錄缺席即炸**（同本函式其他基準檔的
    # fail-closed 慣例）：靜默退化成空 dict 會讓 `shipped_cn.get(fk)` 恆為 None，與台帳
    # 缺 `cn` 欄的 None 相等——正確登記的條目反被判漂移，錯的反而放行。
    dist_cn = DIST_CH.parent / "CN"
    shipped_cn = {f"{p[:-5]}|{k}": v
                  for p in os.listdir(dist_cn) if p.endswith(".json")
                  for k, v in _jload(dist_cn / p).items()}
    # 物品名的出貨集**不做正規化**：引擎以裸 `Module.Item` 查 ItemName map，B41 前綴形
    # 是死鍵（見 tracker._is_runtime_item_key）。缺檔即炸——fail-closed。
    shipped_items = {k for k in _jload(DIST_CH / "ItemName.json")
                     if tracker._is_runtime_item_key(k)}
    vjson = _jload(ROOT / "sources/vanilla_keys.json")
    vraw = set(vjson["keys"])
    vanilla = vraw | {k.split("_", 1)[1] for k in vraw if "_" in k}
    # 物品名只查 ItemName map，用檔域基準；扁平聯集會把其他檔的同名鍵也當本體鍵。
    # 下標存取＝欄位缺失即炸，同 repo 對這份基準的 fail-closed 慣例（verify_dist
    # `_load_vanilla_basis`／lint_ch／build_mod 皆然）：靜默退化成空集合會讓本體鍵
    # 被當成缺口送進補譯管線，違反「不得覆寫本體」鐵律的第一道防線。
    vanilla_items = set(vjson["scoped_keys"]["ItemName.json"])
    state = _jload(ROOT / "tracker-state/en_corpus_hashes.json")["mods"]

    unchecked: list[str] = []                 # 整個 wid 沒被檢查（≠ 零缺口）
    undecidable: dict[str, dict] = {}         # wid → 部分鍵不可判定的成因
    idonly_total = 0
    # 「檔|鍵」→ {owner → en}。**census 掃全庫、不扣 shipped**：只比本批 wid 會讓
    # 「先 apply A、日後才處理 B」的衝突永久消失（B 的鍵已 shipped 而被過濾掉）；而
    # 「已出貨」只證明當時有譯文，不證明對**後來才進 tracker 的 owner** 裁決過。
    census: dict[str, dict[str, str]] = collections.defaultdict(dict)
    # 平行於 census 的「勝出來源檔名」索引，形狀 `{檔|鍵: {owner: 檔名｜"script"}}`。
    # **刻意不併進 census**：`census_signature()` 對 census 的值做 hash，混進來源就會讓
    # 全部既有裁決的 signature 一次失效、382 條台帳全部要重簽。
    en_src: dict[str, dict[str, str]] = collections.defaultdict(dict)
    batch_owners: set[str] = set()            # 本批 wid 底下的 owner（決定 blocking 範圍）
    gap: dict[str, tuple[str, str]] = {}      # "<file>|<key>" -> (en, wid)

    # prep 仍需讀 schema 9 歷史 state，故用 current＋legacy 聯集；現行 schema 10 的
    # `backfill_done` 另用 CURRENT_EXTRACTOR_KINDS，刻意不共用。
    KNOWN_KINDS = tracker.EXTRACTOR_KINDS

    def rid_ids(rids) -> set[str] | None:
        """rid 集 → 可能的出貨落點身分集（「檔|鍵」）；**壞損 rid 回 `None`**。

        身分無法還原時不能推論「無交集」：缺 key 段的 `script_item_dn|.../items.txt`
        會被寬鬆 partition 解析成 `ItemName|`（空鍵），與任何本批鍵都不相交＝靜默放行。
        回 `None` 讓呼叫端直接 fail-closed（`_unchecked`），不做交集。
        """
        out: set[str] = set()
        for rid in rids:
            kind, s1, rest = rid.partition("|")
            relpath, s2, key = rest.partition("|")
            if kind not in KNOWN_KINDS or not s1 or not s2 or not relpath:
                return None
            # 空 key 的豁免只給 `lua_gettext`（唯一已證實的合法空 key，且不參與身分推導）
            if not key:
                if kind != "lua_gettext":
                    return None
                continue
            if kind == "script_item_dn":
                out.add(f"ItemName|{key}")
            elif kind == "translate_en":
                tgt = target_file(os.path.basename(relpath).rsplit(".", 1)[0], key)
                if tgt:
                    out.add(f"{tgt}|{key}")
        return out

    def load_wid(wid: str):
        """回 (recs, mirror, eff)；不可用時回 None（呼叫端決定是否記 `_unchecked`）。"""
        # **state 條目本身也要先驗**：`state[wid]` 若是 list／字串／None，`.get()` 直接拋
        # AttributeError 逃出 `main()`＝artifact 不被重寫、舊的成功檔留在原地被誤用。
        if not isinstance(state[wid], dict):
            return None, f"tracker state 條目形狀壞損（{type(state[wid]).__name__}）"
        recs = state[wid].get("records")
        if not isinstance(recs, dict):
            return None, f"tracker state 的 records 形狀壞損（{type(recs).__name__}）"
        # **rid 三段形狀也要驗**：容器是 dict 不代表 rid 合法。壞損 rid（未知 kind、缺
        # 分隔符、空 relpath/key）會被下游一路寬鬆的 `partition()` 吃掉——解析成空鍵或
        # 錯的落點檔，既不進 census 也無從與本批交集＝靜默放行。**驗法用兩次 partition、
        # 不限總段數**：key 本身可含 `|`（producer 直接拼接，consumer 一貫只切前兩刀）。
        for rid in recs:
            kind, s1, rest = rid.partition("|")
            relpath, s2, key = rest.partition("|")
            if kind not in KNOWN_KINDS or not s1 or not s2 or not relpath:
                return None, f"records 含壞損 rid（{rid[:60]!r}）"
            # **空 key 的豁免只給 `lua_gettext`**：它是唯一已證實合法的空 key——上游真的
            # 寫了 `getText("")`，抽取器忠實記錄（實測 3 筆／2 個 mod）。其餘 kind 的
            # producer 都不產生空 key，而它們**並非惰性**：空 `script_item` 會進
            # `owners_item`（schema 盲區計數）、空 `lua_literal` 進 coverage 計數、空
            # `script_craftRecipe` 進 verify_dist [16] 的上游實據。放行就是讓壞損 state
            # 污染那些判定。
            if not key and kind != "lua_gettext":
                return None, f"records 含壞損 rid（{rid[:60]!r}）"
        eff = tracker.resolve_effective_branches(recs)
        mp = ROOT / "sources/en" / f"{wid}.json"
        has_text = any(r.partition("|")[0] in tracker.TEXT_BEARING_KINDS for r in recs)
        if not mp.is_file():
            # 「無鏡像」是**合法狀態**：無 text-bearing record 時 backfill 會刪掉鏡像檔。
            # 一律早退會把「schema 3、只有 `script_item`」的 mod（實測 3633899582，6 筆）
            # 從 `_item_dn_stats` 的 schema 盲區裡整個抹掉——它本該被列出來。
            if has_text:
                return None, "state 有文本 record 卻無 sources/en 鏡像"
            return (recs, {}, eff), None
        # **parse 失敗必須轉成 `(None, why)`，不能讓例外逃出去**：`main()` 拋例外時
        # artifact 根本不會被重寫，於是**舊的成功檔留在原地**——下游 `apply_wf_result`
        # 讀到 `{"strings":[],"_gap":{},"_unchecked":[],"_owner_conflicts":{}}` 會判「機械
        # 檢查全過」rc=0，整個 fail-closed contract 被繞過（本檔的設計前提正是「失敗也要
        # 寫出 artifact」）。
        try:
            mirror = _jload(mp)
        except (ValueError, OSError) as exc:
            return None, f"sources/en 鏡像無法解析（{type(exc).__name__}）"
        if not isinstance(mirror, dict):
            return None, f"sources/en 鏡像頂層形狀壞損（{type(mirror).__name__}）"
        bad = tracker.mirror_incoherent_rids(recs, mirror)
        if bad:
            # 鏡像領先 → 宇宙（取自 state）少鍵＝缺口低報；值 hash 不符 → 拿過期英文當
            # 翻譯來源。兩者都是 #221 的失效模式，不可套用。
            return None, f"{len(bad)} 筆 record 的鏡像與 state 不一致（backfill 中斷殘跡）"
        return (recs, mirror, eff), None

    # **本批 wid 缺 tracker 基準要先檢出**：下面的主迴圈跑的是**全庫** state（census 需要
    # 完整 owner universe），不在 state 裡的 wid 根本不會進迴圈，於是靜默變成「零缺口」。
    for wid in args.wids:
        if wid not in state:
            unchecked.append(f"{wid}：無 tracker 基準（先跑 backfill-en）")
    # load 失敗的 wid：**不能只是 continue**。census 少了它的 owner，若它剛好也定義了本批
    # 的某個鍵，blocking conflict 就變成假陰性。值取不到，但**身分（檔|鍵）從 rid 就算得
    # 出來**，故先收下來，等本批缺口算完再取交集。
    skipped: list[tuple[str, str, set[str]]] = []   # (wid, 原因, 該 wid 的落點身分集)
    for wid in sorted(state):
        loaded, why = load_wid(wid)
        if loaded is None:
            if wid in args.wids:
                unchecked.append(f"{wid}：{why}（重抽該 mod）")
                continue
            r = state[wid].get("records") if isinstance(state[wid], dict) else None
            if not isinstance(r, dict):
                # 連身分都取不出來＝無法判斷它有沒有參與本批的鍵，一律 fail-closed。
                unchecked.append(f"{wid}：{why}——連落點身分都取不出，無法排除它與本批衝突")
                continue
            # **身分集必須含鏡像側的 rid**：「鏡像領先 state」正是 load 失敗的一種成因，
            # 領先的那批 rid 只存在於鏡像——若其中就有與本批共鍵的新 owner，只掃 state
            # 會漏掉它，交集為空＝靜默放行（假陰性）。鏡像檔還在，讀它的 key 不需要值
            # 可信。頂層不是 dict 就只能靠 state。
            ids = rid_ids(r)
            mp = ROOT / "sources/en" / f"{wid}.json"
            if ids is not None and mp.is_file():
                try:
                    mdata = _jload(mp)
                except (ValueError, OSError):
                    # 捕捉集要與 `load_wid` 一致：`is_file()` 後檔案被鎖／權限變更會拋
                    # OSError，只捉 ValueError 就讓例外逃出 `main()`、抵銷這道防線。
                    mdata = None
                # 鏡像檔**存在但壞損**（parse 失敗／頂層非 dict）＝鏡像側身分不可還原，
                # 不能當成「沒有額外 identity」——mirror-only 的共鍵可能就藏在裡面。
                m_ids = rid_ids(mdata) if isinstance(mdata, dict) else None
                ids = None if m_ids is None else ids | m_ids
            if ids is None:
                # 壞損 rid＝身分不可還原，不能推論「無交集」，直接 fail-closed。
                unchecked.append(f"{wid}：{why}——rid 壞損、身分不可還原，"
                                 "無法排除它與本批衝突（重抽該 mod）")
                continue
            skipped.append((wid, why, ids))
            continue
        recs, mirror, eff = loaded
        # 物品名走 getItemNameFromFullType()：落點固定 ItemName、鍵為完整 fullType。
        # 判定一律委給 tracker._item_dn_stats——把 schema<9／`?.`／鏡像缺值／id-only 的
        # 判定在這裡重寫一次，兩支腳本遲早分岔。**宇宙取自 state records，值才取自鏡像**：
        # `dn_keys` 若也從鏡像建，鏡像少一個 rid 時該鍵會同時從宇宙消失，`missing` 永遠是
        # 空集合＝盲區偵測整條失效（#221 的病：報表報 0，玩家看到英文）。
        #
        # **必須逐 owner 各算一次**：跨 owner 把 fullType 合併只算一次，A 的值等於 item id
        # 而 B 有真英文時（或 A 缺鏡像、B 有值），收斂順序會讓 B 的真缺口被整體扣掉，或
        # 把 A 的「沒有英文」誤列成 conflict。owner 才是引擎的載入單位。
        owners_dn: dict[str, set[str]] = collections.defaultdict(set)
        owners_item: dict[str, set[str]] = collections.defaultdict(set)
        owners_txt: dict[str, dict[str, str]] = collections.defaultdict(dict)
        for rid in recs:
            if not branch_ok(rid, eff):
                continue
            if rid.startswith("script_item_dn|"):
                owners_dn[owner_of(rid)].add(rid.rpartition("|")[2])
            elif rid.startswith("script_item|"):
                owners_item[owner_of(rid)].add(rid.rpartition("|")[2])
        # **值一律走 `tracker.winning_dn_text`**（勝出 rid 由 state 決定、缺值不回退
        # common 舊值——理由見 `converge_owner`），不直接迭代 mirror rows。
        for (o, k), v in tracker.winning_dn_text(
                recs, mirror, eff, is_eff=lambda r, e: branch_ok(r, e)).items():
            owners_txt[o][k] = v
        schema = state[wid].get("extractor_schema")
        stats = {o: tracker._item_dn_stats(schema, owners_dn.get(o, set()),
                                           owners_txt.get(o, {}), shipped_items,
                                           vanilla_items, len(owners_item.get(o, set())))
                 for o in set(owners_dn) | set(owners_item)}
        # **census 需要自己的一套 stats**：它不扣 shipped（見上），但 id-only／malformed／
        # 鏡像缺值一樣要扣——那些 owner「沒有真英文」或值是壞的，塞進 census 就會製造
        # 假 conflict。故同一份輸入跑兩次，只差 `shipped_items`；vanilla 兩邊都扣（那是
        # 「不得覆寫本體」鐵律，不是裁決）。
        census_stats = {o: tracker._item_dn_stats(schema, owners_dn.get(o, set()),
                                                  owners_txt.get(o, {}), set(),
                                                  vanilla_items,
                                                  len(owners_item.get(o, set())))
                        for o in stats}
        census_dn = {o: st_c["gap"] for o, st_c in census_stats.items()}
        cen_src: dict[tuple[str, str], str] = {}
        cen = converge_owner(recs, mirror, eff, vanilla=vanilla, dn_gap=census_dn,
                             src=cen_src)
        for (owner, fk), en in cen.items():
            census[fk][f"{wid}/{owner}"] = en
            en_src[fk][f"{wid}/{owner}"] = cen_src[(owner, fk)]
        if wid not in args.wids:
            # **非本批 wid 的 census 盲區也要 fail-closed**：`load_wid` 成功不代表這個 wid
            # 的每個 owner 都進了 census——落入 `mirror` 缺值／`malformed` 桶的鍵不進
            # census，而 `mirror_incoherent_rids` 依設計不驗「state 有而鏡像沒有」，那些
            # 缺值不會在別處被攔下。若它與本批同鍵，衝突判定就是假陰性。
            # **盲區明細必須取 `_item_dn_stats` 的 `blind_keys` 桶，不可用「不在 census 的
            # 都算」反推**：id-only 與上游留白也不在 census，那是合法扣除——誤列會讓完全
            # 正常的批次被卡死（實測 `Base.M249`：本批 translate_en "FN M249"、非本批
            # script id-only "M249"，後者不是衝突 owner，「重抽」也是 no-op）。
            blind_ids = {f"ItemName|{k}"
                         for st_c in census_stats.values() for k in st_c["blind_keys"]} | {
                f"{tgt}|{key}"
                for rid in recs if rid.startswith("translate_en|") and branch_ok(rid, eff)
                and rid not in mirror   # 鏡像缺值＝取不到 EN；留白（在鏡像但空值）是合法扣除
                for relpath, key in [rid.partition("|")[2].partition("|")[::2]]
                for tgt in [target_file(os.path.basename(relpath).rsplit(".", 1)[0], key)]
                if tgt and key not in vanilla}
            if blind_ids:
                skipped.append((wid, "部分 owner 的鍵未進 census"
                                     "（鏡像缺值／上游格式壞損）", blind_ids))
            continue
        batch_owners |= {f"{wid}/{o}" for o in stats} | {
            f"{wid}/{owner_of(r)}" for r in recs
            if r.startswith("translate_en|") and branch_ok(r, eff)}
        for o, st in stats.items():
            idonly_total += st["idonly"]
            if st["why"]:
                prev = undecidable.get(wid, {})
                undecidable[wid] = {
                    "why": "；".join(filter(None, [prev.get("why"), f"[{o}] {st['why']}"])),
                    "kinds": sorted(set(prev.get("kinds", [])) | st["kinds"]),
                }
        # 本批缺口＝逐 owner 的有效 gap 收斂後扣 shipped（已出貨的鍵不用再翻）
        local = converge_owner(recs, mirror, eff, vanilla=vanilla,
                               dn_gap={o: st["gap"] for o, st in stats.items()})
        # 與 `_undecidable` 其餘計數同口徑：先扣無落點檔與 vanilla（兩者只需 rid 本身即可
        # 判定，缺鏡像值不妨礙過濾），否則數字系統性偏大、kinds 可能只因 vanilla 鍵就掛上
        # `mirror`——這份報表存在的理由就是別失真（#221 的病）。
        en_missing = sum(
            1 for r in recs
            if r.startswith("translate_en|") and branch_ok(r, eff) and r not in mirror
            for relpath, key in [r.partition("|")[2].partition("|")[::2]]
            if key not in vanilla
            and target_file(os.path.basename(relpath).rsplit(".", 1)[0], key))
        # 與 `_undecidable` 其餘計數同口徑：先扣無落點檔與 vanilla，否則數字系統性偏大。
        # **`""` 與純空白要分開計**：兩者的引擎語意相反（前者「已有值則不覆寫」、後者一律
        # put／覆寫）。實測 `sources/en/3403870858.json` 同時有 16 個 `""` 與 4 個純空白。
        # **這裡計的是 raw rows、不是勝出者**：純空白若被後載入的非空值蓋掉（`common="  "`
        # ＋版本夾 `"Real Name"`），最終值非空、該鍵仍是缺口。文案必須說「若它是勝出者」，
        # 不能寫成「一定不是缺口」。
        def _blank_kind(v) -> str | None:
            if not isinstance(v, str):
                return "bad"
            return "empty" if v == "" else ("ws" if not v.strip() else None)

        blanks = collections.Counter(
            _blank_kind(v) for r, v in mirror.items()
            if r.startswith("translate_en|") and branch_ok(r, eff)
            and _blank_kind(v) is not None
            for relpath, key in [r.partition("|")[2].partition("|")[::2]]
            if key not in vanilla
            and target_file(os.path.basename(relpath).rsplit(".", 1)[0], key))
        en_blank = sum(blanks.values())
        if en_missing or en_blank:
            reasons = ([f"{en_missing} 筆 translate_en 鏡像缺值"] if en_missing else []) + \
                      ([f"{blanks['empty']} 筆 translate_en 空字串（首次即空＝抑制 script；"
                        f"同鍵已有非空值則引擎不覆寫、不影響缺口）"] if blanks["empty"] else []) + \
                      ([f"{blanks['ws']} 筆 translate_en 純空白（引擎一律 put／覆寫；**若它是該鍵的"
                        f"勝出者**執行期就顯示空白＝不是缺口，被後載入的非空值蓋掉則不影響）"]
                       if blanks["ws"] else []) + \
                      ([f"{blanks['bad']} 筆 translate_en 鏡像值非字串"] if blanks["bad"] else [])
            prev = undecidable.get(wid, {})
            undecidable[wid] = {
                "why": "；".join(filter(None, [prev.get("why"), *reasons])),
                "kinds": sorted(set(prev.get("kinds", []))
                                | ({"mirror"} if en_missing else set())
                                | ({"upstream_blank"} if en_blank else set())),
            }
        # `local` 已扣過 shipped（它走本批 stats），故 `batch_keys` 不從這裡累加——見下方
        # 由 census 反推的版本。
        for (owner, fk), en in local.items():
            if fk in shipped:
                continue
            gap.setdefault(fk, (en, wid))

    # `ItemName` 等落點都是**全域字串表**、後載入者覆寫，同一鍵被多個 owner 定義成不同
    # 英文時，譯文必須對每個 owner 都成立（AGENTS.md 多 owner 共用鍵原則）。
    # **blocking 的判準是「衝突是否涉及本批 owner」，不是「有沒有出貨過」**：已出貨 A、
    # 這次處理新 B 時，正是 B 的玩家會拿到照 A 的英文翻的譯文。
    # 人工裁決台帳：signature 相符**且該鍵已出貨**才放行。缺檔＝空台帳（漸進登記）；
    # 但形狀壞損一律炸——靜默退化成空會讓所有裁決失效，人會以為 gate 壞了而繞過它。
    # 台帳是**人工逐條手編**的真相檔，壞損機率遠高於原子寫出的鏡像。故壞損時**不 raise**
    # ——那會讓 artifact 不被重寫、上一輪的成功檔留在原地，接著被 `apply_wf_result` 判「機械
    # 檢查全過」rc=0（本檔的設計前提是「失敗也要寫出 artifact」）。改列 `_unchecked`：同樣
    # 達成「不靜默退化成空台帳」，又保住 artifact 必寫的不變量。
    dec_p = ROOT / "sources/owner_conflict_decisions.json"
    decided: dict = {}
    if dec_p.is_file():
        reported = False
        try:
            raw_dec = _jload(dec_p)
        except (ValueError, OSError) as exc:
            raw_dec, reported = None, True
            unchecked.append(f"{dec_p.name} 無法解析（{type(exc).__name__}）"
                             "——裁決台帳不可用，所有 owner 衝突維持 blocking")
        cand = raw_dec.get("entries") if isinstance(raw_dec, dict) else None
        # **任何一種壞損都要 append**：頂層非 dict、缺 `entries`、`entries` 非 dict，三種
        # 都會退成空台帳；漏報就等於靜默把所有裁決作廢卻讓無衝突批次 rc=0。
        if isinstance(cand, dict):
            decided = cand
        elif not reported:
            unchecked.append(f"{dec_p.name} 的 entries 形狀壞損或缺失"
                             "——裁決台帳不可用，所有 owner 衝突維持 blocking")
    # `action: "unship"` 的裁決需與 `unshipped_keys.json` **雙向背書**：台帳與 registry
    # 的 `owner_signature` 共同錨定 owner census；build 另以 `as1_value` 監看抑制前有效
    # CN 值漂移。缺任一邊都維持 blocking。
    unship_p = ROOT / "sources/unshipped_keys.json"
    unship_entries: dict = {}
    if unship_p.is_file():
        try:
            raw_unship = _jload(unship_p)
        except (ValueError, OSError):
            raw_unship = None
        cand_unship = raw_unship.get("entries") if isinstance(raw_unship, dict) else None
        if isinstance(cand_unship, dict):
            unship_entries = cand_unship
        else:
            unchecked.append(f"{unship_p.name} 無法解析或 entries 形狀壞損"
                             "——不出貨裁決不可用，相關 owner 衝突維持 blocking")
    conflicts: dict[str, dict[str, str]] = {}
    conflicts_other: dict[str, dict[str, str]] = {}
    resolved: dict[str, dict[str, str]] = {}
    stale_dec: list[str] = []

    # **unship 裁決即使「衝突已消失」也必須重審**：build 本身不讀 owner census，會繼續
    # 抑制；故 check mode 全庫 blocking。一般 prep 只在該 owner 涉及本批時 blocking，
    # 非本批則降為 stale report——否則任一無關 mod 更新都會凍結全庫所有補譯工作。
    skipped_ids = {fk for _, _, ids in skipped for fk in ids}

    def unship_issue(message: str, owners: dict | None) -> None:
        if args.check_decisions or (owners and set(owners) & batch_owners):
            unchecked.append(message)
        else:
            stale_dec.append(message)

    for fk, d in decided.items():
        if not isinstance(d, dict) or d.get("action") != "unship":
            continue
        owners = census.get(fk)
        if not owners:
            if fk in skipped_ids:
                unship_issue(f"{fk}：相關 owner 載入失敗，census 不可判定；"
                             "先修基準／鏡像，不得據此退役 unship", owners)
            else:
                unship_issue(f"{fk}：unship 裁決鍵已不在 census，應退役／重查", owners)
            continue
        if len({norm_en(v) for v in owners.values()}) < 2:
            unship_issue(f"{fk}：owner 衝突已消失，unship 裁決應退役並恢復出貨", owners)
        signature = census_signature(owners)
        fname, _, key = fk.partition("|")
        bare = unship_entries.get(f"{fname}.json|{key}")
        if not isinstance(bare, dict) or bare.get("owner_signature") != signature:
            unship_issue(f"{fk}：unship 裸鍵 owner_signature 已過時或缺失", owners)
        if fname == "ItemName" and not key.startswith("ItemName_"):
            twin_fk = f"ItemName|ItemName_{key}"
            twin = unship_entries.get(f"ItemName.json|ItemName_{key}")
            if isinstance(twin, dict):
                twin_owners = census.get(twin_fk)
                # 前綴孿生鍵可能只存在 As1 真相層、不在 upstream census；仍需抑制，
                # 不可因 census 缺席要求退役。只有能算出 census 時才驗 owner_signature。
                if twin_owners and twin.get("owner_signature") != census_signature(twin_owners):
                    unship_issue(f"{twin_fk}：unship 前綴孿生鍵 owner_signature 已過時", owners)
    resolved_unship_keys: set[str] = set()
    for fk, owners in census.items():
        # 比對用 `norm_en`（排版級漂移不算衝突，見該函式），**列出的仍是原值**供人核對。
        if len({norm_en(v) for v in owners.values()}) < 2:
            continue
        # **裁決要有可機讀的完成狀態**，否則 census 不扣 shipped 會讓同一組 owner/value 永遠
        # 報衝突、相關 wid 連無關的新缺口都無法 apply（工具實質不可用）。條件缺一即過時：
        #   * signature 相符（owner 增減或上游改值都會讓它不符＝該重新裁決）；
        #   * `reason` 是非空**字串**（`str()` 硬轉會讓 `123`／`["x"]` 混過去）；
        #   * `ch`／`cn` 都是**字串**且等於現行出貨值——**缺欄不是「不驗」**：台帳缺 `cn`
        #     而該鍵又不在 CN dist 時，`None == None` 會把從未裁決過的東西放行；
        #   * 該鍵已出貨——裁決的產物是譯文，沒出貨等於沒裁完，而 `gap.setdefault` 的
        #     first-wins 會把某一個 owner 的語意直接落地。
        # 後兩條是 `action: "translate"` 的出貨錨點；`action: "unship"`（不同實體撞同一鍵、
        # 無中性譯名）改錨 `unshipped_keys.json` 雙向背書＋dist 已抑制，見下方分支。
        # 「沒登記」與「登記成 null」由下方的 `elif fk in decided` 分開（**承重的是那一行**，
        # 不是這裡的取值方式）：null 是壞損條目，要具名報出來而非靜默當成沒登記。
        d = decided[fk] if fk in decided else None
        if isinstance(d, dict):
            why = None
            signature = census_signature(owners)
            action = d.get("action", "translate")
            if d.get("signature") != signature:
                why = "裁決簽名已過時（owner 增減或上游改值）"
            elif not isinstance(d.get("reason"), str) or not d["reason"].strip():
                why = "裁決缺 reason（無從得知當初怎麼裁的）"
            elif action == "unship":
                # ledger key 不含 `.json`；unshipped registry 沿用 `<檔名.json>|<鍵>` schema。
                fname, _, key = fk.partition("|")
                pair = f"{fname}.json|{key}"
                spec = unship_entries.get(pair)
                twin_fk = (f"ItemName|ItemName_{key}"
                           if fname == "ItemName" and not key.startswith("ItemName_") else None)
                # 只有真相層／census 真的存在 B41 前綴孿生鍵才強制雙抑制；不存在時不要逼
                # registry 塞幽靈條目，否則 build 每輪都報「未命中、可退役」假警報。
                twin_exists = bool(twin_fk and twin_fk in census)
                twin_pair = (f"ItemName.json|ItemName_{key}" if twin_exists else None)
                twin_spec = unship_entries.get(twin_pair) if twin_pair else None
                twin_signature = census_signature(census[twin_fk]) if twin_exists else None
                if not isinstance(spec, dict):
                    why = f"裁決為 unship，但 {pair} 未登記於 unshipped_keys.json"
                elif not isinstance(spec.get("as1_value"), str):
                    why = "unshipped_keys 裸鍵缺 as1_value（抑制前有效 CN 錨點）"
                elif spec.get("owner_signature") != signature:
                    why = "unshipped_keys 的 owner_signature 已過時"
                elif twin_exists and not isinstance(twin_spec, dict):
                    why = f"ItemName 不出貨須同步登記舊式前綴鍵 ItemName_{key}"
                elif twin_exists and not isinstance(twin_spec.get("as1_value"), str):
                    why = "ItemName 前綴孿生鍵缺 as1_value（抑制前有效 CN 錨點）"
                elif twin_exists and twin_spec.get("owner_signature") != twin_signature:
                    # 孿生條目錨**自己的** census，不是裸鍵 census。否則孿生 owner／EN 漂移
                    # 偵測不到，且孿生自己成為衝突時無法以自身 signature 完成裁決。
                    why = "ItemName 前綴孿生鍵的 owner_signature 已過時或缺失"
                elif fk in shipped_ch or fk in shipped_cn:
                    why = "裁決為 unship，但裸鍵仍在 CH/CN dist（先跑 build_mod.py build）"
                elif twin_fk and (twin_fk in shipped_ch or twin_fk in shipped_cn):
                    # 前綴舊鍵若留在 dist，裸鍵被抑制後 verify [15] 會判為無裸鍵死鍵。
                    why = "裁決為 unship，但 ItemName 前綴孿生鍵仍在 CH/CN dist"
            elif action == "translate":
                if not isinstance(d.get("ch"), str) or not isinstance(d.get("cn"), str):
                    why = "裁決缺 ch／cn 出貨錨點（兩側都是裁決產物，缺一即不完整）"
                elif fk not in shipped:
                    why = "已登記中性譯名裁決但譯文尚未出貨"
                elif d["ch"] != shipped_ch.get(fk) or d["cn"] != shipped_cn.get(fk):
                    why = (f"出貨譯文已漂移（登記 ch={d['ch']!r} cn={d['cn']!r}，"
                           f"現況 ch={shipped_ch.get(fk)!r} cn={shipped_cn.get(fk)!r}）")
            else:
                why = f"未知 action={action!r}（只接受 translate／unship）"
            if why is None:
                resolved[fk] = owners
                if action == "unship":
                    resolved_unship_keys.add(fk)
                    if twin_fk:
                        resolved_unship_keys.add(twin_fk)
                continue
            stale_dec.append(f"{fk}：{why}")
        elif fk in decided:
            # 條目存在但形狀壞損（含明確的 `null`）：**必須具名**，否則操作者只看到
            # 「owner 衝突」，不知道自己登記的那條被整條忽略，會以為 gate 壞了而繞過它。
            stale_dec.append(f"{fk}：裁決條目形狀壞損（{type(d).__name__}），已忽略")
        # **裁決驗證是全庫規則，必須在 batch 分流之前跑**：否則 `_owner_conflicts_other`
        # 先 `continue`，台帳永遠不生效，已裁的 66 鍵會永久留在 708 待辦裡。
        # 合格者已在上方 `continue`；未裁決／裁決過時者才依是否涉及本批 owner 分流。
        (conflicts if set(owners) & batch_owners else conflicts_other)[fk] = owners
    # **`batch_keys` 由 census 反推**：census 不扣 shipped，才涵蓋「本批 owner 的鍵已出貨、
    # 而被跳過的 wid 是新 owner」這個形狀——用扣過 shipped 的 `local`／`gap` 取交集會漏掉。
    batch_keys = {fk for fk, owners in census.items() if set(owners) & batch_owners}
    if args.check_decisions:
        # check mode 沒有 batch_owners；把**所有 decision key**當成必驗 identity，讓下方
        # skipped 交集把相關 owner 的鏡像／state 盲區轉成 non-zero，避免台帳假綠。
        batch_keys |= set(decided)
    # 被跳過的 wid 若與本批身分集有交集，它可能就是另一個 owner——census 少了它，衝突
    # 判定即為假陰性。故列 `_unchecked` 讓退出碼與消費端都攔住。
    for wid, why, ids in skipped:
        hit = ids & batch_keys
        if hit:
            unchecked.append(f"{wid}（非本批）：{why}——它與本批共用 {len(hit)} 個鍵"
                             f"（如 {sorted(hit)[0]}），無法判定是否 owner 衝突；重抽該 mod")

    # 衝突鍵**必須在建 by_en 之前**自 `_gap` 移除：留著就是 first-wins 的譯文，忽略
    # 退出碼時照樣落地；反之若只從 `_gap` 移除卻已進 `strings`，下游會拿到沒有落點的
    # 孤兒字串。
    for fk in set(conflicts) | resolved_unship_keys:
        # blocking 衝突與已裁決 unship 都不能送進 `_gap`／`strings`。後者若殘留，下一步
        # `apply_wf_result` 會把「無誠實中性譯名」的 first-wins 英文重新寫回真相層。
        gap.pop(fk, None)
    by_en: dict[str, list[str]] = collections.defaultdict(list)
    wid_of: dict[str, set[str]] = collections.defaultdict(set)
    for fk, (en, wid) in gap.items():
        by_en[en].append(fk)
        wid_of[en].add(wid)
    rows = [{"en": en,
             "keys": len(fks),
             "files": sorted({f.split("|")[0] for f in fks}),
             "key_samples": sorted(f.split("|", 1)[1] for f in fks)[:4],
             "wid": sorted(wid_of[en])}
            for en, fks in by_en.items()]
    rows.sort(key=lambda r: (r["wid"][0], r["key_samples"][0]))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"strings": rows, "_gap": {k: v[0] for k, v in gap.items()},
                   "_unchecked": unchecked, "_undecidable": undecidable,
                   # 三個衝突欄位都帶 `has_json_en`／`en_source` 加註（見 `annotate`）：
                   # 裁決 translate vs unship 全靠它，先前得逐一人工翻 `sources/en/<wid>.json`
                   # 的 rid 路徑，是最容易判錯的環節（#245 項目 1）。
                   "_owner_conflicts": {fk: annotate(o, en_src.get(fk, {}))
                                        for fk, o in conflicts.items()},
                   # 不涉及本批 owner 的歷史衝突：report-only，但**必須寫進 artifact**，
                   # 否則它們只存在於某次 stdout，下一個人無從知道有這批待辦。
                   "_owner_conflicts_other": {fk: annotate(o, en_src.get(fk, {}))
                                              for fk, o in conflicts_other.items()},
                   # 已由 `sources/owner_conflict_decisions.json` 背書者：report-only，
                   # 但寫進 artifact 讓「放行了哪些」可稽核。
                   "_owner_conflicts_resolved": {fk: annotate(o, en_src.get(fk, {}))
                                                 for fk, o in resolved.items()}},
                  f, ensure_ascii=False, indent=1)
    print(f"{len(gap)} 鍵 → {len(rows)} 條相異字串"
          f"（重複率 {(1 - len(rows) / max(len(gap), 1)) * 100:.1f}%）→ {out}")
    print("  落點:", dict(collections.Counter(k.split("|")[0] for k in gap).most_common(8)))
    if idonly_total:
        print(f"  · 另扣除 {idonly_total} 筆物品名 DisplayName 等於 item id 或為空白（上游沒給真英文名）")
    if undecidable:
        print(f"  ⚠️ {len(undecidable)} 個 mod 有部分缺口不可判定"
              "（未列入缺口，也不算已覆蓋）:")
        for wid, info in list(undecidable.items())[:8]:
            print(f"    {wid}：{info['why']}")
        if len(undecidable) > 8:
            print(f"    ...（還有 {len(undecidable) - 8} 個）")
    if conflicts:
        print(f"  ⚠️ {len(conflicts)} 個鍵被多個 mod 定義成不同英文（`ItemName` 是全域表，"
              "譯文須對每個 owner 都成立）:")
        for fk, owners in list(conflicts.items())[:8]:
            srcs = en_src.get(fk, {})
            print(f"    {fk}: " + " | ".join(
                f"{w}={e[:40]!r}"
                f"[{'json' if srcs.get(w) and loadable_json(srcs[w]) else srcs.get(w) or '?'}]"
                for w, e in owners.items()))
        if len(conflicts) > 8:
            print(f"    ...（還有 {len(conflicts) - 8} 個）")
    if resolved:
        print(f"  ✓ {len(resolved)} 個衝突已由 sources/owner_conflict_decisions.json 背書放行")
    for s in stale_dec:
        print(f"  ⚠️ {s}", file=sys.stderr)
    if conflicts_other:
        print(f"  ℹ️ 另有 {len(conflicts_other)} 個鍵在**本批之外**的 owner 間就已衝突"
              "（report-only，不阻斷本批；已出貨者需人工重新核對 `_note`）")
    if unchecked or conflicts or (args.check_decisions and stale_dec):
        # **非零退出**：wid 級跳過會讓 artifact 長得跟「這個 mod 沒缺口」一模一樣，
        # 下游 apply_wf_result 只讀 strings/_gap，於是整個 mod 的物品名再次隱形（#221）。
        # 多 owner 衝突同理——first-wins 會把另一方的語意靜默丟掉，必須人工裁決。
        for u in unchecked:
            print(f"❌ 未檢查：{u}", file=sys.stderr)
        for fk, owners in conflicts.items():
            # stderr 一樣帶加註：這是人裁決時唯一會看的輸出，缺了它就得再開 artifact。
            print(f"❌ owner 衝突：{fk} → "
                  f"{annotate(owners, en_src.get(fk, {}))}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
