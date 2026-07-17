# Changelog

所有重要的變更都會記錄在此檔案中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 `{PZ版本}-{Mod主版本}.{次版本}.{修訂}` 格式。

## [42.19.0-1.1.0] - 2026-07-17

### Added

- **原創翻譯層**（`sources/own_translations.json`）：補翻上游自帶英文但 As1 未收錄的 640 鍵——「更多特質描述」「Mixology 調酒」「更詳細的特質說明」三模組從掛名支援變實質全翻，並修復 `Sandbox_ProxInv` 等 raw key 顯示問題。繁簡各自採在地用語（如 三用電表/万用表、通寧水/汤力水）。
- 追蹤器支援 B41 `.txt` 翻譯格式抽取（extractor_schema=4）＋schema 演進靜默重建守門，463 個支援模組監看**全覆蓋**（零盲區）。
- 下架處理：新下架自動開 `[已下架]` issue、`removed_at` 紀錄、`SUPPORTED_MODS.md` 已下架清單（重新上架自動復活）。
- `SUPPORTED_MODS.md` 獨立支援清單：463 個模組全數附中文名稱與一行摘要。

### Changed

- 上游追蹤排程改為每日（原每週）；Workshop 描述加入姊妹作互連與 GitHub 支援清單／問題回報連結。
- 主分支更名 `main`。

### Fixed

- steamcmd 匿名下載兩大失敗模式：workshop manifest（ACF）毒化與大型物品逾時——原地重試＋清 ACF 續傳。
- script 抽取器誤抓 craftRecipe 內文數量指令；`.txt` 同檔重複鍵取後者；「語料為空」模組改建帶標記空基準（止住每日重抓）。

## [42.19.0-1.0.0] - 2026-07-16

初始版本（Workshop `3765907717`）。

### Added

- 移植如一漢化組（As1）「[B42]統一模組漢化」（Workshop `3556540080`）並轉為繁體中文，保留簡體中文雙語。
- 建立 split → build → verify → tracker 管線與專案骨架。
- 雙上游追蹤器（As1 包「待同步」+ 原始 MOD「可能過時」）。
