# /// script
# requires-python = ">=3.10"
# ///
"""wid 級 MOD 名冊：`sources/mod_registry.json`（我方名冊）的 loader／writer，以及 As1
網站名單（`sources/as1_modlist.json`）的解析。

**我方名冊是支援與監看的唯一名冊**（2026-10-01 使用者裁決）：As1 支援的 MOD 一律獨立
登記在這裡，登記後由我方自行偵測更新、補鍵；As1 只作為「該支援哪些 MOD」與簡中用語的
參考。監看面＝名冊 active ∪ split 歸屬結果（`tracker.expected_watchlist_items`），As1 名單
不直接進監看面——As1 改標狀態、移除或網站停擺都不會讓我方追蹤面跟著縮水。
  * As1 名單只存在於 As1「如一汉化」網站（`AS1_MODLIST_URL`，免登入公開 API）：Workshop 包
    把所有 MOD 的譯文按類型合併、不帶 wid，包內與 Workshop 頁面都沒有清單。
    `tracker.py as1-list` 擷取快照後，把標「正常」與 split 已歸屬、但名冊還沒有的 wid
    補登為 active（source `as1-modlist`／`as1-split`）。**只增不減**：As1 改標其他狀態或
    從名單移除時只列出供人工裁決，不自動退役。
  * 名冊也登記 As1 以外的 MOD（原創翻譯、翻譯申請、`own_translations` 錨點、owner 衝突的
    共同 owner、作者換 ID 重新上傳的新版），並提供 metadata facts（顯示名、mod_ids）。它同時
    解開新 MOD 的 bootstrap 死結——沒進 watchlist 就不會抽 `sources/en` 語料，沒有語料就
    永遠不會被歸屬。

**名冊與 As1 名單都不是鍵歸屬證據**：`split_sources.py` 的 owner 一律只認 `sources/en` 的
第一手鍵證據（上游自帶 EN 檔／script DisplayName）。名冊只決定「追蹤哪些 wid」與
顯示用的 facts，絕不能拿來把鍵掛到某個 wid 上——否則「我覺得這個 mod 有這個鍵」
會變成事實。

`mod_registry.json` schema（頂層 `{"_comment": str, "mods": {wid: entry}}`）：
  * wid          — 純數字字串（Workshop id）
  * status       — 必填，僅 `active` / `retired`（retired 否決殘留 metadata，as1-list 也不會重新登記）
  * source       — 必填非空字串：這筆 wid 是怎麼進來的（人工來源說明或 `as1-modlist`／`as1-split`）
  * verified     — 必填非空字串：最後一次核實的依據／日期
  * name         — 選配字串（顯示名）
  * note         — 選配字串
  * mod_ids      — 選配 `list[str]`，每項非空
未知欄位一律放行（日後小幅擴充不該讓舊版 reader 全炸）。

`retired` 條目照樣回傳，由 consumer 自行篩 `status == "active"`——loader 不替
consumer 決定政策（tracker 只追 active、split 只吃 active 的 metadata，但兩者都
需要看得到 retired 才能報告「這個 wid 是刻意退役、不是漏了」）。
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_JSON = PROJECT_ROOT / "sources" / "mod_registry.json"

VALID_STATUS = ("active", "retired")
_REQUIRED_STR = ("status", "source", "verified")
_OPTIONAL_STR = ("name", "note")

AS1_MODLIST_URL = "https://www.asone.fun/api/Home/GetAllModinfo"
# 網站前端（www.asone.fun 首頁 bundle）的列舉表：ModType＝收錄狀態、ModStatesType＝
# 翻譯進度。表外的值代表網站改版，一律拒收，不猜語意。
AS1_MOD_TYPES = {0: "未知", 1: "未审核", 2: "已审核", 3: "正常", 4: "不收录",
                 5: "无json", 6: "版本过旧", 7: "已下架"}
AS1_MOD_STATES = {0: "未知", 1: "无状态", 2: "审核中", 3: "翻译中", 4: "校对中", 5: "已完成"}
# 「正常」＝As1 收錄且仍維護。翻譯進度不限：翻譯中的 MOD 已有部分譯文進包。
AS1_TYPE_SUPPORTED = 3
# 擷取下限：「正常」低於此值疑似 API 截斷或改版，拒寫快照（2026-10-01 實測 1,114）。
AS1_SUPPORTED_MIN = 500


def _is_enum(value, table: dict) -> bool:
    return type(value) is int and value in table  # bool 是 int 子類，刻意排除


def parse_as1_api(doc) -> dict[str, dict]:
    """`GetAllModinfo` 回應 → `{wid: {"name", "type", "state"}}`。

    任何形狀問題都 raise ValueError、不回部分結果：少一段名單＝那些 MOD 從監看面
    靜默消失，而快照照樣寫得出來。
    """
    if not isinstance(doc, dict) or doc.get("code") != 200 or not isinstance(doc.get("data"), list):
        raise ValueError("As1 API 回應形狀不符（須為 {code: 200, data: [...]}）")
    mods: dict[str, dict] = {}
    for item in doc["data"]:
        wid = item.get("ModId") if isinstance(item, dict) else None
        if type(wid) is not int or wid <= 0:
            raise ValueError(f"As1 API 條目 ModId 須為正整數：{str(item)[:200]}")
        name, mtype, state = item.get("ModName"), item.get("ModType"), item.get("ModStatesType")
        if not (isinstance(name, str) and _is_enum(mtype, AS1_MOD_TYPES)
                and _is_enum(state, AS1_MOD_STATES)):
            raise ValueError(f"As1 API 條目 {wid} 的 ModName／ModType／ModStatesType 形狀不符")
        if str(wid) in mods:
            raise ValueError(f"As1 API 條目 ModId 重複：{wid}")
        mods[str(wid)] = {"name": name.strip(), "type": mtype, "state": state}
    supported = len(as1_supported(mods))
    if supported < AS1_SUPPORTED_MIN:
        raise ValueError(
            f"As1 名單「正常」僅 {supported} 項（下限 {AS1_SUPPORTED_MIN}），疑似 API 異常"
        )
    return mods


def as1_supported(mods: dict[str, dict]) -> set[str]:
    """As1 名單中標「正常」的 wid。"""
    return {wid for wid, entry in mods.items() if entry["type"] == AS1_TYPE_SUPPORTED}


def load_mod_registry(path: Path = REGISTRY_JSON) -> dict[str, dict]:
    """讀名冊並驗 schema，回 `{wid: 原始 entry dict}`。

    **缺檔即 `raise ValueError`（無豁免）**：名冊已是人工真相，同時是 registry-only
    監看的唯一保底——新 MOD 尚未進 As1 歸屬結果時，只有名冊記得要追它。缺檔回空集
    會讓「名冊被誤刪／路徑寫錯」與「名冊真的一個 mod 都沒有」在產出上完全不可區分：
    watchlist 靜默縮回純衍生集、新 MOD 從此不再抽語料，而所有 gate 都是綠的。
    壞形／schema 不符同樣 `raise ValueError`，訊息帶具體 wid 與欄位名——
    靜默丟棄壞條目會讓「名冊裡有這個 mod」與「追蹤器真的在追」無聲脫鉤。
    """
    if not Path(path).is_file():
        raise ValueError(
            f"{path} 缺檔——mod_registry.json 為人工真相且是 registry-only 監看的"
            "唯一保底，缺檔一律 fail-closed（不得以空名冊繼續）；請自版控還原該檔"
        )
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} 無法解析：{exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path} 頂層須為物件，實得 {type(doc).__name__}")
    mods = doc.get("mods")
    if not isinstance(mods, dict) or not mods:
        raise ValueError(
            f"{path} 缺少 `mods` 非空物件（實得 {type(mods).__name__}）"
            "——頂層形狀為 {\"_comment\": str, \"mods\": {wid: entry}}"
        )

    out: dict[str, dict] = {}
    for wid in sorted(mods):
        entry = mods[wid]
        if not (isinstance(wid, str) and wid.isdigit()):
            raise ValueError(f"mod_registry: wid `{wid}` 須為純數字字串（Workshop id）")
        if not isinstance(entry, dict):
            raise ValueError(
                f"mod_registry: wid {wid} 的 entry 須為物件，實得 {type(entry).__name__}"
            )
        for field in _REQUIRED_STR:
            val = entry.get(field)
            if not (isinstance(val, str) and val.strip()):
                raise ValueError(
                    f"mod_registry: wid {wid} 的 `{field}` 為必填非空字串，實得 {val!r}"
                )
        if entry["status"] not in VALID_STATUS:
            raise ValueError(
                f"mod_registry: wid {wid} 的 `status` 僅可為 "
                f"{'/'.join(VALID_STATUS)}，實得 {entry['status']!r}"
            )
        for field in _OPTIONAL_STR:
            if field in entry and not isinstance(entry[field], str):
                raise ValueError(
                    f"mod_registry: wid {wid} 的 `{field}` 須為字串，"
                    f"實得 {type(entry[field]).__name__}"
                )
        if "mod_ids" in entry:
            ids = entry["mod_ids"]
            if not isinstance(ids, list):
                raise ValueError(
                    f"mod_registry: wid {wid} 的 `mod_ids` 須為字串陣列，"
                    f"實得 {type(ids).__name__}"
                )
            for item in ids:
                if not (isinstance(item, str) and item.strip()):
                    raise ValueError(
                        f"mod_registry: wid {wid} 的 `mod_ids` 含非字串／空項 {item!r}"
                    )
        out[wid] = entry
    return out


def write_mod_registry(path: Path, doc: dict) -> None:
    """名冊寫回：先以 loader 同一套 schema 驗過再落盤，壞形不得寫出。"""
    tmp = Path(path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    try:
        load_mod_registry(tmp)
    except ValueError:
        tmp.unlink()
        raise
    tmp.replace(path)
