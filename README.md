# [B42]繁體簡體模組翻譯 By Minidoracat 如一漢化組

**By Minidoracat × 如一漢化組（As1）**

為 Project Zomboid Build 42 的其他 MOD 提供**繁體中文 + 簡體中文**翻譯支援。內容源自如一漢化組「[B42]統一模組漢化」，經授權移植為繁中版並保留簡中雙語。

## MOD 資訊

| 項目 | 值 |
|------|-----|
| **Mod ID** | `CatModLangFor42` |
| **支援版本** | Build 42.19.0+ |
| **Mod 版本** | 42.19.0-1.1.0 |
| **Workshop ID** | [3765907717](https://steamcommunity.com/sharedfiles/filedetails/?id=3765907717) |

## 合作與授權

本 MOD 為如一漢化組（As1）「[B42]統一模組漢化」（[Workshop 3556540080](https://steamcommunity.com/sharedfiles/filedetails/?id=3556540080)）的**授權繁體中文版**，掛名如一漢化組。簡中文本逐字保留 As1 原文；繁中文本由簡中經 OpenCC + 台灣用語校正再生。追蹤器每日監看上游包與各支援 MOD 的文本變更並同步更新。

## 安裝方式

於 [Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3765907717) 訂閱本 MOD 後，在遊戲的 Mods 管理啟用即可，翻譯自動生效。

## Load Order 說明

本 MOD 與 As1 原簡中包內容**一致（源自同一版本快照）、無衝突**。若同時訂閱兩者，PZ 對重複翻譯鍵採「**後載入者生效**」，因文本相同故顯示結果一致，不會互相破壞。單獨訂閱本 MOD 即可獲得完整繁中 + 簡中。

## 支援 MOD 清單

以下統計由 `uv run scripts/build_mod.py manifest` 自動生成，請勿手動編輯。

<!-- SUPPORTED_MODS_START -->
共支援 **459 個 Workshop 模組**（607 個 mod ID），另 12 個已下架（翻譯保留），完整清單（含中文名稱與摘要）見 [SUPPORTED_MODS.md](./SUPPORTED_MODS.md)。
<!-- SUPPORTED_MODS_END -->

## 開發

生成物（`MOD/` 與 `sources/mods/`）勿手改，請改人工真相層（`sources/ch_overrides.json`、`sources/opencc_fixes.json`、`sources/lua/`、`sources/placeholder_exceptions.json`）後重跑管線。
