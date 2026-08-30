# /// script
# requires-python = ">=3.10"
# ///
"""`sources/mod_registry.json` 共用 loader（wid 級 MOD 名冊）。

**為什麼需要這份名冊**：改造前追蹤器的 watchlist 只含「已經在 `sources/mods/` 有歸屬結果」
的 wid，形成新 MOD 的 bootstrap 死結——沒進 watchlist 就不會抽 `sources/en` 語料，
沒有語料就永遠不會被歸屬。現行 watchlist 改取 metadata、active registry 與 As1 的聯集，
名冊把「我方要追蹤哪些 wid」從衍生產物裡拆成可審核的人工真相。

**名冊不是鍵歸屬證據**：`split_sources.py` 的 owner 一律只認 `sources/en` 的第一手
鍵證據（上游自帶 EN 檔／script DisplayName）。名冊只提供 metadata facts（顯示名、
mod_ids）與追蹤意圖，絕不能拿來把鍵掛到某個 wid 上——否則「我覺得這個 mod 有這個鍵」
會變成事實，那正是本次改造要消滅的東西。

schema（頂層 `{"_comment": str, "mods": {wid: entry}}`）：
  * wid          — 純數字字串（Workshop id）
  * status       — 必填，僅 `active` / `retired`
  * source       — 必填非空字串：這筆 wid 是怎麼進來的（人工來源說明）
  * verified     — 必填非空字串：最後一次人工核實的依據／日期
  * name         — 選配字串（split metadata 的顯示名）
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
