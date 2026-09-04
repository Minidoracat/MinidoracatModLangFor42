# [B42]繁體簡體模組翻譯 By Minidoracat 如一漢化組

**By Minidoracat × 如一漢化組（As1）**

為 Project Zomboid Build 42 的其他 MOD 提供**繁體中文 + 簡體中文**翻譯支援。內容源自如一漢化組「[B42]統一模組漢化」，經授權移植為繁中版並保留簡中雙語。

## MOD 資訊

| 項目 | 值 |
|------|-----|
| **Mod ID** | `CatModLangFor42` |
| **支援版本** | Build 42.20.4+ |
| **Mod 版本** | 42.20.4-1.24.3 |
| **Workshop ID** | [3765907717](https://steamcommunity.com/sharedfiles/filedetails/?id=3765907717) |

## 合作與授權

本 MOD 為如一漢化組（As1）「[B42]統一模組漢化」（[Workshop 3556540080](https://steamcommunity.com/sharedfiles/filedetails/?id=3556540080)）的**授權繁體中文版**，掛名如一漢化組。As1 授權範圍內的簡中文本逐字保留原文（少數上游錯字另立登記修正）；原創翻譯的模組則由本包逐鍵自撰簡中。繁中文本全部為逐鍵人工維護的台灣用語譯文（對照英文原文與術語表校訂，不使用自動簡繁轉換）。追蹤器每日監看上游包與各支援 MOD 的文本變更並同步更新。

## 安裝方式

於 [Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3765907717) 訂閱本 MOD 後，在遊戲的 Mods 管理啟用即可，翻譯自動生效。

## Load Order 說明

本 MOD 與 As1 原簡中包內容**一致（源自同一版本快照）、無衝突**。若同時訂閱兩者，PZ 對重複翻譯鍵採「**後載入者生效**」，因文本相同故顯示結果一致，不會互相破壞。單獨訂閱本 MOD 即可獲得完整繁中 + 簡中。

## 支援 MOD 清單

以下統計由 `uv run scripts/build_mod.py manifest` 自動生成，請勿手動編輯。

<!-- SUPPORTED_MODS_START -->
共支援 **656 個 Workshop 模組**（832 個 mod ID），另 18 個已下架（翻譯保留），完整清單（含中文名稱與摘要）見 [SUPPORTED_MODS.md](./SUPPORTED_MODS.md)。
<!-- SUPPORTED_MODS_END -->

## 翻譯範圍（權威政策）

- 本包只維護 PZ `Translate/{CH,CN}/*.json` 文本；上游缺少可載入的 JSON key 時，可由本包補譯。
- 新收錄與後續修補一律不新增、修改或維護 MOD Lua，也不為特定 MOD 建立新的 Lua consumer 相容層；僅保留早期既有的 BanditsWeekOne 開日貼圖 Lua 相容層，該歷史產物已凍結、不再擴充。
- 若未翻譯根因是 Lua 寫死文字、自有 UI、Lua 未使用正確 JSON key 或其他非 JSON 行為，本包只提供可驗證資訊；由 issue 提交者自行向 MOD 作者回報。提交者不回報或上游不修，本包不處理。

## 申請新 MOD 翻譯

想讓某個 Workshop MOD 加入本翻譯包？歡迎透過 [MOD 翻譯申請](../../issues/new?template=translation-request.yml)提出，附上 Workshop 連結與申請理由即可。

- 佇列與進度：見 [translation-request 標籤的 issues](../../issues?q=is%3Aissue+label%3Atranslation-request)。
- 收錄順序將參考需求熱度（👍 反應數）、文本量與上游更新活躍度綜合評估。
- 上游「[B42]統一模組漢化」（As1）已涵蓋的 MOD 會隨同步自動加入，不需申請。

## ☕ 支持作者

MOD 永遠免費。喜歡的話可以請我喝杯咖啡，贊助會用在伺服器與 MOD 開發上。

[![Ko-fi](https://raw.githubusercontent.com/Minidoracat/workshop-resources/refs/heads/main/badges/badge_kofi.png)](https://ko-fi.com/minidoracat)

## 開發

生成物（`MOD/` 與 `sources/mods/`）勿手改（例外：`sources/mods/` 下 `metadata.json` 標 `origin: "own"` 的原創翻譯目錄為人工真相），請改人工真相層（`sources/ch/` 繁中 corpus、`sources/cn_overrides.json`、`sources/placeholder_exceptions.json`）後重跑管線。`sources/lua/` 為凍結歷史產物，不新增、不修改、不維護。繁中已斷絕 OpenCC 機轉，逐鍵人工維護。
