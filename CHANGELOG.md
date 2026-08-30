# Changelog

所有重要的變更都會記錄在此檔案中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 `{PZ版本}-{Mod主版本}.{次版本}.{修訂}` 格式。

## [Unreleased]

### Added

- **#325 As1 v3.8.0 同步**：逐鍵審核 22,919 個新增鍵與 16 個改值鍵，CH 全數依現行 EN、
  As1 CN、專案術語與既有定名人工／多模型複核；`ch_review_state.json` 同步登記。
- **自有 MOD 追蹤 bootstrap**：新增 `sources/mod_registry.json`，watchlist 取 registry active
  與 `sources/mods` metadata 聯集；新 MOD 可先登記 wid、回填 EN，再由 split 自動閉環。
- **#327 ModernFirearmsSystem 更新**：補齊 39 個現行 JSON／物品名缺口與 14 個新增
  craftRecipe 顯示名；繁中、簡中逐項獨立翻譯，口徑、型號、發數與 UI 動作方向均經
  Claude／Grok 雙模型覆核及人工仲裁。
- **#319–#324、#326 追蹤器 issue 清償**：補齊 743 個現行 JSON 翻譯鍵，涵蓋
  Authentic Z 背包、Herbalist 製作分類、ETW 新特質與 350 項沙盒設定、RealFirearms、
  Organized Categories、GaelGunStore 的武器資訊頁與控制介面；#324 現行鍵已全數覆蓋。

### Changed

- **歸屬改為 evidence-first**：`split_sources.py` 不再依賴停更的外部 helper，改以
  `sources/en/<wid>.json` 中 runtime-effective `.json` `translate_en` 與
  `script_item_dn` 證據重建 516 個 As1 owner 目錄；6,161 條只來自 B41 `.txt`、
  mod 根目錄或已被新版覆蓋分支的舊 owner edge 經全量稽核後移除（有效 edge 誤刪 0）。
  地圖 `title`／`description` 僅按同檔名歸屬，避免跨地圖交叉污染。
- **支援清單與上游追蹤擴充**：相較同步前新增 86 個受支援 Workshop 項目；
  77 個已有 runtime-effective owner metadata，9 個先以 registry-only 保留追蹤身分。
  metadata 與 active registry 聯集目前共 674 項，watchlist 675 項；registry-only 鍵數
  顯示 `?`，直到 EN→owner 閉環。新收 MOD 的 EN mirror、hash baseline、繁中名稱與摘要
  均已納管。
- **own lane 清理**：22 個已被 As1 納管的 origin:own 目錄退役，1,129 個仍屬原創的鍵遷入
  `own_translations.json`，另移除 6,107 個已由 As1 供值的重複原創鍵。
- **#327 上游改值複核**：逐項比對 99 個 `translate_en` 改值；82 個現行譯文仍準確，
  17 個依新 EN 修正（含 7.62×51mm 100 發彈鼓、AK-103／AK-12、AMB-17、M110 SASS、
  CMMG Mk47 Mutant、VSSM、IPSC 補償器與 .50 BMG 彈藥盒）。
- **#321／#326 上游改值複核**：逐項比對 48 個 `translate_en` 改值；43 個現行譯文
  仍準確或屬 vanilla 抑制鍵，5 個依新 EN 修正（Gym Rat 完整機制、M1917 Enfield、
  Mosin-Nagant M1891、Springfield M1903 與鹿彈彈丸）。

### Fixed

- 補正本批 37 個 `ItemName_` 與 7 個 `Recipe_` B41 前綴死鍵：有現行 script 實據者補裸鍵，
  無法精確確認 module 者依「禁止 suffix 猜測」原則登記 allowlist。
- own map 的 `title`／`description` vanilla collision 改採檔域判定；一般 own 鍵仍維持
  跨檔裸鍵防線。本機 PZ 的 48,718 個本體 `(檔,鍵)` 仍維持零覆寫。
- `lint_ch.py` 的 A/B/E 棘輪重新清零；藥物「交互作用」、技術「用戶端／登錄檔」、
  餐飲「菜單」等台灣合法語境以附值錨點的 lint exemption 固化。
- 補齊證據鏈 fail-closed：tracker runtime 會逐次重算 metadata／registry expected universe，
  stale watchlist 在 API／下載前即阻斷；verify [13] 獨立驗 expected wid ↔ current state ↔
  EN mirror 的 rid/hash exact closure，部分鏡像遺失不再被降級成 WARN。
- EN 空檔／壞 rid／非有效分支、上游 Translate 壞 JSON、vanilla 基準空 bucket、
  CH corpus 缺失與 worklist entry 壞 schema 均改為阻斷；manifest 對 metadata 目錄缺失、
  source mod 子目錄缺 metadata、或 zero-row universe 都不再 no-op 回成功。泛用
  `title`／`description` allowlist 也精確到 `檔名|鍵`。
- **owner 衝突收斂**：#319 新增的 16 個 owner 衝突以不綁物品類型／MOD 名稱的中性
  動作與快捷鍵名稱背書；#327 的 `Sandbox_ADWWF` 與 `Base.FedorovAvtomat` 同樣完成
  中性裁決。owner decision gate 增至 1,000 筆。遠端 tracker merge 另使 Authentic Z
  68 個歷史 `ItemName_` 前綴失去 DisplayName 實據；已以現行 exact `script_item`＋既有
  裸鍵對帳後登記，未猜 module。

### Verification

- `verify_dist.py` 16/16 PASS；確定性雙跑 183 個檔案零 diff。
- 18 支 repo 回歸測試與 `tracker.py self-test` 16 情境全過；owner decision gate
  1,000 筆背書、lint A/B/C/E/F 全零、本機 vanilla 48,718 個 `(檔,鍵)` 零覆寫。
- 合併並清償 #319–#327 最新 tracker universe 後，有效覆蓋率為
  **104,809 / 111,998＝93.6%**；八張 tracker issue 的現行 actionable gap 均為 0，
  其餘 7,189 個缺口屬其他原始 MOD。

## [42.20.4-1.21.0] - 2026-08-30

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **一次補上 2,457 個新翻譯鍵，並更新 352 筆既有譯文。** 其中 1,740 個新鍵來自 34 張「可能過時」issue、106 個來自 Puffin's Retro Relics，另有 611 個是本次正式服清查後補上的 JSON 翻譯。
- **正式服目前啟用但原本未納入本包的 22 個 Workshop MOD，現在都已列入支援。** 新增 610 個繁中／簡中鍵，涵蓋 AllTheInfo、兩款 Ford 車輛、Lawnmower、InspectUI、Campers、Oshkosh M911、Alice's Weapon Sling、Working Gun Rack、Plysken Solar Revolution 等；只處理能由 `Translate/*.json` 生效的文字，沒有新增或修改 Lua 覆寫。
- **截圖裡的三個英文改裝配方已補齊。** `ATAJeepBumper`、`ATASamaraHoodItem`、`ATAMustangHoodItem` 現在會顯示「切割吉普牧馬人保險桿」、「切割雪佛蘭薩馬拉引擎蓋」、「切割福特野馬引擎蓋」。
- **Dreams 的 207 篇夢境與 1 句醒來台詞全部重新翻譯。** 上游不是只改標點，而是把整批故事全文重寫；舊中文已對不上情節。本版逐篇依現行英文重譯，保留所有段落、數字與格式標記。
- **新增 Puffin's Retro Relics 原創繁中／簡中翻譯。** 收錄 101 個懷舊收藏品名稱與 5 個分類／背包掛載名稱，包括瘋狂球、絨毛玩偶、桌遊、球隊三角旗與摔角夥伴玩偶。
- **進一步避免不同 MOD 共用同一代號時顯示錯名。** owner 衝突裁決由 402 筆增至 983 筆；無法同時對多個 MOD 成立的文字不再出貨，讓各 MOD 顯示自己的英文，而不是把另一個 MOD 的車名、槍名、職業說明或彈藥口徑蓋上去。唯一已知例外是 FRAcceptableGunsDemo 的 `ContextMenu_FireMode_Safe`：該 MOD 把英文留在 B42 不載入的舊格式檔，抑制衝突中文後會顯示字面鍵名；這項低影響殘留已接受。
- **Workshop 封面更新。** 替換 `poster.png` 與 `preview.png`；安裝方式、Mod ID 與最低支援版本不變，仍只支援 Build 42.20.4+。

### Added

- **相對 `v42.20.4-1.20.0` 新增 2,457 個出貨翻譯鍵**（以 dist CH 鍵集實算）：
  - **#283–#292 共 10 張可能過時 issue**：補齊 403 鍵，最大批為 GaelGunStore 及其彈藥／配方相容內容（329 鍵）；另含 Fitness Overhaul、organizedCategories、bodilyfunctions 等。
  - **#294–#312、#314–#318 共 24 張可能過時 issue**：補齊 1,337 個直接缺口，包含 HydeCo Clay 1,148 鍵、Guns of 93 56 鍵、More Builds 25 鍵、AmmoConverter 23 鍵、Dreams 11 鍵，以及多個沙盒、車輛、分類與 UI 更新。
  - **#313 Puffin's Retro Relics（Workshop 3788360646）106 鍵**：own-mod lane 原創 CH／CN（`ItemName` 101、`IG_UI` 5），As1 未收錄、零 vanilla 碰撞、零 owner 衝突。
  - **正式服 22 個新支援 Workshop 項目 610 鍵**：AllTheInfo 337、Crown Victoria 37、Elgin Street Sweeper 37、Lawnmower 32、InspectUI 31、Campers 29、Oshkosh M911 24、Refillable Propane Tanks 24、Alice's Weapon Sling 15、Working Gun Rack 9、TheShortcut 8、Plysken Solar Revolution 7，其餘 10 個 MOD 合計 20 鍵。
  - **Autotsar Tuning Atelier - Fjord Mustard 1 鍵**：補上 B42 `craftRecipe ATAMustangHoodItem` 的配方名稱。
- **22 個新 own-mod lane 與 tracker baseline**：新增 23 個 mod ID、20 個新 tracker state baseline 與 19 份 EN mirror；UsefulMetal 只有非文字型 script records，依 tracker 契約不建立空 mirror。
- **支援清單擴充**：相對 1.20.0，在架 Workshop MOD 548→571、mod ID 715→739；另有 16 個已下架項目保留翻譯。watchlist 565→588，所有新收錄 MOD 後續改文都會由每日排程追蹤。

### Fixed

- **Dreams（1945359259）208 個既有鍵重譯**：`IGUI_Dream1..207` 與 `IGUI_Dream19_Say` 全文依現行 EN 重寫；CN 以 `cn_overrides.json` 錨定 As1 原值，CH 更新 corpus，並逐鍵登記 `ch_review_state.json`。
- **352 筆既有出貨值更新（含上述 Dreams 208 筆）**：其餘 144 筆為槍械框架與相容清單、車輛零件、陶藝材料與流程、沙盒檢查間隔、Aegis 時間口徑、Bodily Functions 佔位設定、More Builds 模組名稱及其他上游改義文本的修正／同步。
- **Alice's Weapon Sling 的 4 個快捷欄名稱搬到正確檔案**：上游把 `IGUI_HotbarAttachment_*` 放在 `UI.json`，但 PZ 只會從 `IG_UI.json` 路由 `IGUI_` 鍵；本包已重新歸位，避免譯文存在卻永遠顯示英文。
- **Plysken Solar Revolution 的 3 個英文殘留**：補上抽水機、氣象站與蓄電池組；另外 4 個相關鍵已由該 MOD 自帶 CH／CN 翻譯，未重複收錄。
- **owner 衝突治理**：裁決台帳 402→983；`unshipped_keys` 236→280。新增 581 筆完整 owner census 背書，44 個無誠實中性譯名的鍵登記不出貨；連同上游改名自然退場的 2 鍵，dist CH 本版淨移除 43 鍵。
- **HydeCo Clay 的 B41 `ItemName_` 死鍵**：36 個前綴鍵已有正確裸 fullType 出貨，依現行 `script_item` 實據登記 allowlist。
- **SF2／MK／TMNT／運動球隊與影視專名交叉複核**：Puffin 收藏品 106 鍵經全量審核，修正海外版《快打旋風 II》Balrog／Vega／M. Bison 對應、EyeXombie 品牌名與 Waldo 簡中定名。

### Changed

- **封面資產縮小並更新**：`poster.png`／`preview.png` 由 419,804 bytes 更新為 297,282 bytes。
- **Workshop 長期描述與支援清單同步**：公開數字更新為 580+ 個 Workshop MOD、730+ 個 mod ID；SUPPORTED_MODS、README 與 `workshop.txt` 同步重生。
- **公開 JSON／Lua 邊界說明修正**：README、Steam 長期描述與 `workshop.txt` 現在明確區分「新收錄與後續維護一律 JSON-only」和早期既有、已凍結的 BanditsWeekOne 開日貼圖 Lua 相容層，不再以「完全不掛 Lua」概括實際出貨內容。
- **tracker state 跟進 8/27–8/30 上游更新**：只保留 JSON／script 可形成翻譯的語料；純 tracker 狀態變動不影響玩家出貨內容。

### 已裁決不跟進

- **Lua 寫死文字與自有文字系統不複寫**：本次只新增 PZ `Translate/{CH,CN}/*.json` 能處理的文字；沒有為任何 MOD 新增 Lua consumer 相容層。
- **純格式安全變動不重譯**：上游僅把 `%` 改成 `%%`、大小寫或撇號者，既有 dist 已符合 formatted() 安全契約時維持原譯。
- **無玩家可見 JSON 文本者零動作**：只新增／刪除 script 區塊識別字、失效版本夾或來源路徑搬移的 issue，不建立死翻譯。
- **跨 MOD 同鍵新內容不強行套用**：Detailed Descriptions（#316）的衝突職業描述保留安全舊值或依 owner 裁決不出貨，不把單一 MOD 的內容全域灌給其他玩家。

### 驗證

- 18 支本機 `test_*.py` 全過；CI 所列 17 支純 repo 回歸測試全過；`tracker.py self-test` 15 情境全過。
- `build_mod.py build` 通過；`verify_dist.py` **16/16 PASS**（FAIL 0）。
- 確定性雙跑 **181 個檔案零 diff**。
- `verify_dist.py --cn-diff v42.20.4-1.20.0`：**2,808 個 CN 值變動，待複核 0**。
- owner decision gate：**983 筆背書、0 blocking**；`OWNER_CONFLICTS.md` 同步。
- `lint_ch.py` 五類棘輪全零；本機 PZ 本體 **48,718 個 `(檔,鍵)`** 與 dist CH/CN 零交集。
- `test_serialization.py`：**3,989 個受版控 JSON** 全合規；`manifest --check` 無漂移。
- 有效覆蓋率重算：**86,480 / 88,213＝98.0%**，Workshop 長期描述的「約 98%」仍成立。

## [42.20.4-1.20.0] - 2026-08-26

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **修好 Build 42.20.4 之後報紙／傳單／日記頁的圖片不見的問題。** 42.20.4 改了遊戲讀取這類圖文版面的方式，本包 19 筆版面資料還是舊寫法，玩家打開疾管署公告、研究員日記（6 頁）、迪克西加油站與李施德霖傳單、幸運籤文（10 張）時，圖片位置只剩一塊素色方塊。全部改成新寫法後恢復正常。
- **疾管署公告（CDC）的版面資料本來就是壞的，這次一併補完整。** 上游授權包的這一筆從中間就斷掉了，任何版本都讀不到圖，不是 42.20.4 才壞的。缺少的材質路徑已依上游原始 MOD 的英文原文補回。
- **最低支援版本提高到 Build 42.20.4。** 新舊寫法互不相容，42.20.3 及更早的版本讀不懂新寫法，所以必須提版；本包一向只支援最新穩定版。
- 翻譯文字與標題一個字都沒動，只有版面資料的寫法改變。

### Fixed

- **`Print_Media.json` 的 19 個 `*_info` 全數遷移為 42.20.4 契約**（CH／CN 各 19 筆）。
  42.20.4 的 `PrintMedia.lua` 重寫了 rich-text 解析器：`texture` 直接進
  `getTexture(value)`、`font` 直接進 `UIFont.FromString(value)`、其餘 key 直接進
  `tonumber(value)`，**不再 eval Lua 表達式**；同版把 Lua 全域 `loadstring`／`loadstream`
  移除（反編譯比對：`LuaCompiler.register()` 與 `J2SEPlatform.java:59` 的唯一呼叫點在
  42.20.3→42.20.4 之間整段消失）。舊值 `texture:getTexture("X")` 於此版被當成材質路徑
  字面查詢、必然查無，且三條失效路徑全部靜默（`Texture.getSharedTexture` 吃例外回 null、
  `UIFont.FromString` 未知名稱回 null、`tonumber` 失敗回 nil），故 build／CH parity／lint
  三道原本全綠。遷移為純機械去殼——只移除 `getTexture(" ")` 外殼，材質路徑、版面數值與
  As1 原有的空白排版逐字不動。
  - **As1 lane 7 鍵**（`Print_Media_CDC1_info`、`Print_Media_DiaryPage1..6_info`）：CN 走
    `cn_overrides.json` 登記（帶 `as1_value` 錨點），CH 改 `sources/ch/Print_Media.json`，
    並依 registry 背書 gate 於 `ch_review_state.json` 登記 7 筆有效 CN hash
    （DiaryPage 6 筆為更新、CDC1 為新增）。**未手改 `sources/mods/**`**。
  - **own lane 12 鍵**（`DixieGasCoke`、`ListerineConvenience`、`Fortune1..10`）：改
    `own_translations.json` 的 `ch`／`cn`；`en` 欄是「擷取當時上游原文」錨點，上游
    （`3409143790` 有效分支 `42.20.0`）尚未跟上 42.20.4，故刻意不動並以 `_note` 記錄。
- **`Print_Media_CDC1_info` 的上游截斷值補完整**。As1 原值在 `texture:getTexture (` 處
  斷掉、連 `>` 都沒有；斷點正好落在 `getTexture("` 的內嵌雙引號前（研判為上游轉檔未逸出該引號），
  **任何遊戲版本都取不到材質**——不是 42.20.4 才壞。完整材質路徑
  `media/textures/printMedia/FlyerPics/CDC1.png` 取自 `sources/en/3403180543.json`
  （BanditsWeekOne 的 `42.18` 與 `42.20` 兩分支同值），與 As1 截斷值前綴逐字相符。

### Changed

- **`42/mod.info` 的 `versionMin` 42.20.1 → 42.20.4**（相容性必要條件，非政策性提版）：
  42.20.4 才把解析器由「eval 值裡的 Lua 表達式」改成直接呼叫，兩種格式互不相容——
  新格式的裸路徑交給舊解析器 eval 會失敗（`media/textures/...` 在 Lua 文法下是連續除法
  與欄位存取，執行期必然踩 nil operand，不是單純的語法錯誤），舊格式在 42.20.4 則被當成
  材質路徑字面查詢。README 的「支援版本」與 `STEAM_DESCRIPTION.md` 同步為 Build 42.20.4+，
  `workshop.txt` 的 `description` 由 `manifest` 重生。`modversion` 未動。

### Added

- **`verify_dist.py` 第 [17] 項「Print Media 42.20.4 契約」**（15→16 項 gate，編號 5 保留空缺）。
  以 Java 語意重跑一次解析器（`string.split` 是 `String.split(regex)`、`string.trim` 是
  `String.trim()`，見 `StringLib.java:1405-1421`），對 dist CH／CN 的 `Print_Media.json`
  逐個 `*_info` 驗：值須以 `<` 開頭、每個元素須有 `>` 收尾、`type` ∈ {parent, text, texture}、
  每個欄位須恰好一個 `:`（多的會被引擎靜默丟棄）、key 不得重複或為空（後值靜默覆寫）、
  `type:text` 須有非空正文（`#data[2]` 對 nil 會拋錯）、parent／texture 的 `>` 之後不得有
  內容（不會被使用）、`texture` 須為非空裸路徑、`font` 須為 34 個 `UIFont` enum 常值之一、
  其餘 key 須為純十進位**有限**數值常值，並驗 CN／CH 的 `_info` 鍵集對稱。
  數值規則刻意**比 `tonumber` 嚴格**——PZ 的 `tonumber` 是 `Double.parseDouble` 加 nan／inf
  fallback（`KahluaUtil.java:290-303`），`1.5f`／`Infinity`／`abcinf`／`1e309` 那類
  「解析得出來」的值出現在座標欄一律是缺陷。另對 `shadow`／`visible`／`enabled` 出 WARN：
  消費端是 Java `boolean` 欄位（`AtomUIText.java:23`、`AtomUI.java:22-23`），而本格式只
  產得出 Double／nil，這些 key 寫什麼都不生效（本體自己就有 20 處 `shadow:true`）。
  校準證據：對本體 42.20.4 自己的 161 個 `_info`（1,016 個元素）只命中那 20 處
  `shadow:true`（`tonumber("true")`＝nil ⇒ 陰影無效），其餘全數放行、零 WARN。
- **`scripts/test_print_media_contract.py`**（回歸測試，已納入 `tests.yml`，16→17 支）。
  鎖住 Java 字串語意（`"texture:".split(":")` 尾端空欄位被丟棄＝觸發 RICH TEXT ERROR；
  `String.trim()` **不去**全形空白，用 Python `str.strip()` 會漏放行 `texture:\u3000media/...`）、
  28 種禁止形式（`getTexture(`、`UIFont.`、`145/255.0`、`12+165`、`960/2`、`true`／`false`、
  空／截斷 texture、引號殘留、未知 type、未知字型、多重冒號、重複／空 key、text 缺正文、
  JDK 專屬數值形式、指數溢位…）、5 種合法形式（含本體的 textureless 彩色方塊與負小數
  pivot／angle）、boolean key 的 WARN-not-FAIL 分級，以及現況出貨檔 19×2 鍵全綠。

### 驗證

- `build_mod.py build` 通過；`verify_dist.py` **16/16 PASS**（新增 [17]，FAIL 0）。
- 確定性雙跑 `--compare-dist` 零 diff。
- 17 支純 repo 回歸測試全過（新增 `test_print_media_contract`）。
- `lint_ch.py` 棘輪全零；`manifest --check` 無漂移；`test_serialization.py` 行尾正規形式全過。
- 本機 PZ 本體 CH／CN 零覆蓋（`test_vanilla_no_override.py`）。
- 分析經 Claude／Codex／Grok 三方交叉核實，兩處原始推論被修正：
  - Grok／Codex 都指出「42.20.4 才移除 `loadstring`」不足以單獨證成版本邊界。補查後
    確立三層證據：(a) `LuaCompiler.register()` 與其唯一呼叫點 `J2SEPlatform` 在
    42.20.3→42.20.4 之間整段消失；(b) 本機 mtime——`PrintMedia.lua`、`ISReadABook.lua`
    與本體 `Translate/EN/Print_Media.json` 三者同為 42.20.4 更新當下的
    `2026-08-26 19:37:21`，而 `ISPrintMediaTextPanel.lua`／`PrintMediaDefinitions.lua`
    仍是 2026-04-21；(c) 姊妹專案 `MinidoracatLangFor42` 的 `HARDCODE_REGISTRY.md` 以
    **Steam depot manifest 42.20.3→42.20.4 逐檔 delta（舊檔 SHA1 由 manifest 驗證）**
    記載：改值範圍只有 `projectzomboid.jar`、4 份 Lua 與 18 語系的 `Print_Media.json`，
    官方 EN 162 筆改值全在 `Print_Media.json`、`<type:text>` 內文逐段零變更、只遷移標記，
    根因即「`PrintMedia.lua` 與 `ISReadABook.lua` 移除翻譯值內的 `loadstring` 執行」。
  - Codex 指出材質載不到時 `AtomUITexture` 會把 null texture 視為 ready 並畫純色矩形
    （`AtomUITexture.java:37-63,122-143`），不是「什麼都不畫」；玩家摘要據此改為
    「圖片位置只剩一塊素色方塊」。同批依 Codex 的 Q5 建議補強 gate（多重冒號、重複／空
    key、text 正文、`>` 後殘留內容、有限性檢查、boolean key WARN）。

### 尚未執行

- 實機驗證（進遊戲讀報紙／傳單／日記頁確認圖片顯示）。
- `3403180543`／`3615135168`／`3405131820` 三個上游 MOD 本機未訂閱，材質檔存在性僅由
  上游 EN 鏡像的路徑一致性佐證（本體 `FlyerPics/` 135 檔中確認無同名檔，故確為 MOD 自帶）；
  `3409143790` 的 `Fortune1..10.png` 已於本機 workshop 有效分支 `42.20.0` 實體確認存在。

## [42.20.2-1.19.0] - 2026-08-25

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **清償 #275–#282 共 8 張「可能過時」issue，補譯 573 個鍵。** 最大一批是 N&C's Narcotics——這個 MOD 原本幾乎沒有中文（我方只有 1 個鍵），本次以它的上游改值為觸發點做了全 MOD 盤點，補了 422 鍵。
- **修正 4 組會讓玩家看到錯誤內容的既有翻譯。** 右鍵選單的「注射」原本顯示成模組名稱「注射針劑模組」；RealFirearms 兩個沙盒選項的原版槍械對應互相錯位；物品欄的製作分類漏掉「材料」；SapphCooking 的手沖咖啡漏掉沖煮方式、會與法式濾壓版混淆。
- **統一 SapphCooking 與大麻類 MOD 的既有譯名。** 燉煮系菜名統一用「燉」（原本部分寫「燴」）、銅湯鍋與平底煎鍋的料理成品標出容器、水菸壺／錫罐菸斗／菸斗／捲菸／夾鏈袋改用與遊戲本體及其他 MOD 一致的名稱。部分既有物品因此改名。
- **MinimalDisplayBars 確認不用改。** 上游只是移除了遊戲根本不會載入的舊版本資料夾，實際生效的內容沒變。
- **修正治理報告的來源標註錯誤。** 有兩個 MOD 明明有可用的英文檔卻被標成「死檔」，會讓後續「要不要出貨這個鍵」的判斷誤估代價。

### Added

- **#279 N&C's Narcotics（3404956403）422 鍵**：以本 issue 的 16 筆 Tooltip 改值為觸發點做全 MOD 盤點。含大麻品種（AK-47／北極光／酸柴油／大麻花粉）、吸食器具、毒品與製毒實驗器材、大麻食品、成癮特質與狀態說明。
- **#276 organizedCategories_core（3370707195）63 鍵**：`IGUI_OC_SortOrder_*` 排序方案管理 UI、`IGUI_OC_ChangeDisplayCategory_*` 對話框、新增分類名。
- **#280 SapphCooking_B42（3409143790）47 鍵**：乳酪與凝乳製程、銅鍋料理成品、咖啡濾紙族與相關配方。
- **#281 BurdSurvivalJournals（3639628777）16 鍵**：志向（Ambitions）系統 UI、Lifestyle: Hobbies 相容性沙盒選項、技能重學時間縮放三選項。
- **#278 bodilyfunctions（3396456841）15 鍵**：擦拭用品家族與生理需求物品。另補 5 個裸 craftRecipe 鍵——上游用 B41 的 `Recipe_<X>` 鍵形，而 B42 的 `Translator.getRecipeName()` 只查裸區塊名，去前綴後 5 個名稱精確對上該 MOD 有效分支的現行區塊名。
- **#275 RealFirearms（3238830225）3 鍵**：Sten MK II (S) 消音衝鋒槍、其彈匣與沙盒選項。
- **#282 ImprovisedSilencers（3779164273）2 鍵**：動態消音器與噪音降低 Tooltip。

### Fixed

- **`ContextMenu.json|ContextMenu_Inject`**：As1 CN 把動詞 `Inject` 誤譯成「注射针剂模组」（即 mod 名稱），對 6 個 owner 全不成立，玩家會在右鍵選單看到模組名。CH 改 corpus、CN 走 `cn_overrides` 登記為「注射」。已核對六個 owner 的鍵集，無任何一家另設「標示注射物」的子選單。
- **`IG_UI.json|IGUI_ItemCat_*_material` 11 鍵**：上游加上 `- Material` 後綴，我方譯文漏「材料」。依同族既有 `survivalTrapping_material`＝「生存 (陷阱, 材料)」的格式補齊。
- **`Sandbox_RealFirearmsOptions_{556x45_RF_Mini14,762x51_RF_M14}`**：上游把「Vanilla: JS-14 - 」前綴在兩鍵之間搬移，我方譯文停在舊版本、兩鍵前綴錯位互換，沙盒選項顯示錯誤的原版槍械對應。
- **`SapphCooking Brew Coffee*` 11 鍵**：上游由 `Brew Coffee` 改為 `Brew Pour-Over Coffee`，我方漏「手沖」語意；該 MOD 另有 French Press 與 Thermos 等別的沖煮法配方會混淆。
- **譯名對齊同 MOD 既有出貨值**（多模型交叉複核後修正）：slow-cook 系 10 類「燴」→「燉」（Stew／Risotto／Feijoada／Stroganoff／Arborio Rice）、Paella→西班牙海鮮飯、Noodle Soup→湯麵、Mac and Cheese→乳酪通心粉、Cheese 族→乳酪；SapphCooking 容器 27 鍵（`SaucepanCopper*` 家族 25/25 統一「裝有X的銅湯鍋」、`FryingPanForged_*` 4 鍵「平底煎鍋 (X)」、`PanForged_Oil` CH/CN 平行化）——既有不變式是「key 名含容器→譯文標容器」，與 en 是否寫容器無關；Bong→水菸壺 41 鍵（對齊 `Greenfire.Bong_*`）、Can Pipe→錫罐菸斗（本體 `Base.CanPipe`）、Pipe→菸斗、Joint→捲菸、Baggie→夾鏈袋／自封袋（對齊 `KD.*`）、Crack CN→快克；anabolic steroids→CH 同化性類固醇／CN 合成代谢类固醇；Opium Seeds→罌粟種子；CN Cured／Curing 族 9 鍵熟成→醇化。
- **`prep_mod_strings.converge_owner` 的 `src` 優先序**：`src`（抑制後 runtime fallback 來源）原本沿用值層的分支優先序，導致有效版本夾的死檔 `_EN.txt` 覆蓋 `common` 的可載入 `.json`。`3437429771/Injectors` 與 `3650035249/CAExtendedCategories` 因此在 `OWNER_CONFLICTS.md` 被錯標「死檔」，錯告方向是「把有英文底層的說成沒有」，讓維護者以為 unship 後玩家看到字面鍵名、代價被高估。新增 `_src_rank`（可載入 JSON > script > 死檔），只在同等級才沿分支優先序覆寫；`out` 的值覆寫與 `census_signature` 輸入均未變，既有 402 條裁決 signature 不漂移。補 4 個回歸情境。

### 已裁決不跟進

- **#277 MinimalDisplayBarsNutritionsB42（3388844542）零動作**：99 筆「刪除」的 record 路徑全在 `mods/.../42.15/`，而 state 現行 98 筆全在 `42.20/`。依 `ZomboidFileSystem.loadMod()` 只疊加唯一最佳版本夾，`42.20` 早已是有效分支且內容未變、`42.15` 一直失效。prep 有效缺口 0。
- **`UI_OC_AlphabeticalCategorySort_tooltip`（#276 上游刪鍵）保留**：上游已刪但 own 層仍出貨。本機未訂閱 `3370707195`、無法查證 Lua consumer，故刻意保留並在 `_note` 記錄完整摘除清單與 Lua 搜尋詞——移除有「玩家看到字面鍵名」的退化風險，保留最壞只是出貨死資料（該前綴為 organizedCategories 專屬、撞名風險極低）。

### 驗證

- `build_mod.py build` 通過；`verify_dist.py` **15/15 PASS**（FAIL 0）。
- 確定性雙跑 **181 個檔案零 diff**。
- `verify_dist.py --cn-diff v42.20.2-1.18.1`：**602 個 CN 值變動，待複核 0**。
- 16 支純 repo 回歸測試全過（`test_owner_json_en` 37→42 項，新增 4 個 `src` 優先序情境）。
- owner decision gate：**402 筆背書、0 blocking**；`OWNER_CONFLICTS.md` 同步。
- `lint_ch.py` 五類棘輪全零（[A]0 [B]0 [C]0 [E]0 [F]0）。
- 本機 PZ 本體 **48,718 個 `(檔,鍵)`** 與 dist CH/CN 零交集。
- `test_serialization.py`：**3,906 個受版控 JSON** 全合規。
- `manifest --check` 無漂移；內容 commit `13756dd`。
- 譯文經 Claude／Codex／Grok 三方分工產出後交叉對抗複核，再以 `review-plus` deep／strict 跑三輪多 lane review（共 14 條 finding 全部修正）。

## [42.20.2-1.18.1] - 2026-08-24

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **清償 #261–#273 共 13 張「可能過時」issue。** 依有效版本夾、JSON 載入規則與現行 EN 重算後，補譯 127 鍵、同步 4 個既有譯文。
- **補齊多個近期更新 MOD 的介面與設定。** 包含 organizedCategories、N&C's Narcotics、Long-Term Preservation、The Only Cure、Way More Cars、Take A Bath And Shower、Beanie Babies、UH-1B 與 TT Power Plant。
- **修正 OCsChallengeTraits 與 Horse 的過時說明。** 房屋火災特質改為沙盒關火時帶燒傷開局；Horse 更新幼馬與肉丸警告文案。
- **TrueSmoking 與 TrapManager 經複核確認不用改譯。** 前者只是有效版本路徑複本，後者只是將百分號改成已相容的 `%%` 寫法。
- **已下架的 Rain 的斧與刃維持翻譯保留。** Workshop 頁仍無法存取；既有訂閱者與側載玩家仍可使用翻譯，日後重新上架會自動恢復追蹤。

### Added

- **#261 TT Power Plant**：補譯改名後的鍛造石灰漿物品名。
- **#262 organizedCategories**：補譯 24 個本次新增／修改的分類操作與設定鍵。
- **#263 N&C's Narcotics**：補譯 22 個本次新增／修改的美沙酮、類固醇狀態與除錯設定鍵。
- **#264 UH-1B Helicopter**：補譯雙掛鉤掛載貨物操作。
- **#266 Way More Cars**：補譯 2 個禁止原版車輛生成的沙盒設定鍵。
- **#268 Beanie Babies**：補譯 Seamore the Seal 的物品名、標籤與拆標籤配方，共 3 鍵；`bb_dummy` 維持內部佔位、不出貨。
- **#269 The Only Cure**：補譯 3 個新增特質說明。
- **#270 Take A Bath And Shower**：補譯自動／手動模式 2 鍵。
- **#271 Long-Term Preservation Extended**：補譯 69 鍵，包括 42 個 Sandbox、4 個 Recipes，以及從不可載入 `UI_EN.json` 救回正確 `UI.json` 的 23 個 UI 鍵。

### Fixed

- **#272 OCsChallengeTraits**：同步 2 個上游改文；補回 House Fire 特質並改正「多人無效」的過時說明。
- **#273 Horse**：同步 2 個上游改文，更新幼馬類型與肉丸警告。
- **#265 TrueSmoking**：155 筆 headline 新增經確認是 42.20 路徑複本；有效 149 鍵早已完整出貨，無需改檔。
- **#267 TrapManager**：18 筆 headline 修改中，有效 9 鍵只改百分號逸出；CH/CN 原本已使用 `%%`，無需改檔。

### 已裁決不跟進

- **#274 Rain 的斧與刃**：Steam Workshop 實開仍為無法存取。依下架預設政策保留翻譯與 watchlist，不清除 source tree；若重新上架，追蹤器會自動恢復。

### 驗證

- `build_mod.py build` 通過；`verify_dist.py` **15/15 PASS**。
- 確定性雙跑 **181 個檔案零 diff**。
- `verify_dist.py --cn-diff v42.20.2-1.18.0`：**131 個 CN 值變動，待複核 0**。
- 16 支純 repo 回歸測試全過；tracker self-test 15 情境全過。
- owner decision gate：396 筆背書、0 blocking；`OWNER_CONFLICTS.md` 同步。
- `lint_ch.py` 五類棘輪全零。
- 本機 PZ 本體 48,718 個 `(檔,鍵)` 與 dist CH/CN 零交集。
- `test_serialization.py`：3,906 個受版控 JSON 全合規。
- `manifest --check` 無漂移；內容 commit `443e038` 的 CI 綠燈。

## [42.20.2-1.18.0] - 2026-08-24

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **同步如一漢化組 As1 v3.7.1：新增 75 個 MOD，As1 唯一鍵淨增 42,489。** 新增與更新內容均完成繁中真相層、簡中出貨、追蹤清單、支援清單及確定性重建。
- **新支援 Chopper Drop、Aegis Panel、More Builds。** 本包新增 2,431 個真相鍵：Chopper Drop 原創 1 鍵、Aegis Panel 1,092 鍵、More Builds 1,338 鍵；Chopper Drop 另承接 As1 已收錄的 90 鍵，實際涵蓋 91 鍵。
- **物品名確證缺口歸零。** #221 首批補譯 2,543 鍵，#231 再補 3,522 鍵；另逐鍵確認 398 個渲染載體、分類哨兵、dummy、placeholder 與音效代理屬內部實作，不應翻譯。
- **清償 66 張「可能過時」issue，共補譯 2,096 鍵。** 三個批次為 34 張／867 鍵、18 張／543 鍵、10 張／23 鍵；另完成 AmmoConverter 378、HydeCo 自動車庫門 191、Conditional-Speech 76、RotatorsLib 18 鍵。
- **多 MOD 共用鍵改為可稽核治理。** 396 筆 owner 衝突裁決均以 signature 與對應出貨／抑制錨點背書，`OWNER_CONFLICTS.md` 公開記錄，發版閘門為 0 blocking。
- **發版前再做一次跨模型複核。** 修正 More Builds 111 個簡中舊場景／材質名、MarzGuns 5 個 crate 量詞與 24 個配方名；Burd Journals 全審 210 個 CN 差異，登記 174 筆已審 hash、22 筆 CN override，並修正 27 筆 CH。

### Added

- **As1 v3.7.1 同步**（#239）：新增 75 個 MOD，`as1_unique_keys` 淨增 42,489；保留 As1 CN canonical import，CH 逐鍵人工維護，不使用簡繁機轉。
- **Chopper Drop（`3678109350`）混合收錄**（#246）：本包原創 `Base.ChopperDropRadio` 1 鍵；另有 As1 `_unsorted` 90 鍵，實際出貨 91 鍵。新增 metadata 使其納入 watchlist 與支援清單。
- **Aegis Panel（`3766508989`）原創翻譯 1,092 鍵**（#213）：UI 1,025、Sandbox 67；簡中逐鍵對 EN 修正 24 筆上游誤譯，繁中人工翻譯。Lua 寫死的說明與紀錄依 JSON-only 邊界不處理，已於支援清單揭露。
- **More Builds（`515555911`）原創翻譯 1,338 鍵**（#185）：ContextMenu 1,044、Tooltip 230、UI 45、Sandbox 19。260 個 `craftRecipe` 全部 `ignoreFromBuildMenu`，顯示名走 MOD 自有 ContextMenu，故不新增 `Recipes.json`。
- **物品名補譯兩批**：#221 補譯 2,543 鍵；#231 補譯 3,522 鍵並將確證玩家可見缺口歸零。
- **`sources/untranslatable_keys.json`**：登記 398 個已查證的內部／測試／渲染鍵；prep 與 coverage 共用 canonical identity，壞損資料 fail-closed。
- **Owner conflict 公開治理**（#245）：新增 `has_json_en`／`en_source`、`OWNER_CONFLICTS.md`、`--owner-report-check` 與 CI 同步閘門。
- **Tracker schema 9→10**：script 物品名改用完整 fullType；追蹤範圍收斂為可形成 JSON 翻譯的來源，Lua-only 變動不再開 issue。
- **行尾／編碼棘輪**：`test_serialization.py` 驗證 3,906 個受版控 JSON 為 LF、UTF-8 無 BOM。

### Fixed

- **三批 stale issue 清償**：34 張補譯 867 鍵、改譯 45 鍵；18 張補譯 543 鍵、完成 15 筆 owner 裁決與 19 值上游同步；10 張補譯 23 鍵、同步 7 值並完成 2 筆 owner 裁決。
- **#184 Frockin Splendor**：補譯 37 個服裝物品名與 1 個缺失的分類鍵；確認根因是翻譯鍵缺口，而非載入順序或 Lua 寫死文字。
- **#247 AmmoConverter**：補譯 378 個彈藥轉換配方，收斂 27 個既有核心配方及 3 筆 owner 裁決；Grok 複核後再統一 5 個 MarzGuns crate 量詞與 24 個 recipe 產物名。
- **#259 HydeCo Automatic Garage Doors**：補譯 191 鍵，統一車庫門、鏈傳動元件、遙控器、電池與狀態用詞。
- **#254 Conditional-Speech**：補譯 76 鍵，新增 15 個觸發事件族的分類與角色自語；最終有效鍵 568/568 涵蓋。
- **#249 RotatorsLib**：補譯 18 鍵；三軸車 Middle 部件改為「中」並與真 Rear 部件區分；修正軍用車生成倍率預設值 0.5。
- **#230／#232 owner 衝突清償**：無誠實中性譯名者改為不出貨，避免單一全域 JSON 值覆蓋另一個 MOD 的實體。
- **More Builds 回顧性校正**：修正 111 個簡中舊品牌、舊場景、木材、顏色與家具類型名稱。
- **Burd Journals 發版差異**：逐鍵複核 210 個 CN 變動；22 筆必要偏離改走 `cn_overrides`，修正作者句型、來源 tooltip、Worn／Damaged 區分、函式識別字空格、lore 反義與破句等 27 筆 CH。

### Changed

- **ItemName／prep／coverage 身分統一**：`ItemName_Base.Foo` 與 runtime `Base.Foo` 使用同一 canonical identity；`stale_schema` 正確列入「重抽即消除」分類。
- **Owner decision gate**：現況 396 筆裁決背書、0 blocking；`OWNER_CONFLICTS.md` 與來源同步。
- **JSON-only 邊界明文化**：不新增／修改 MOD Lua 覆寫；Lua 寫死文字、自有 UI 與不可載入檔名只做範圍揭露或回報上游。

### 已裁決不跟進

- **Aegis Panel 的 `AegisHelpContent` 與部分 moderation log**：上游 Lua 寫死英文，沒有 JSON key；依專案邊界不新增 Lua 覆寫。
- **More Builds 上游三組 name／tooltip 自身矛盾**：各自依 EN 保守翻譯，不猜 sprite 或改寫 MOD 行為。
- **無法以單一全域 JSON 誠實表達的 owner 衝突**：維持不出貨；玩家由各 MOD 自己的英文 fallback，避免把另一個 MOD 的專屬譯文套過去。

### 驗證

- `build_mod.py build` 通過；`verify_dist.py` **15/15 PASS**，未使用 `--allow-missing-as1`。
- 確定性雙跑 **181 個檔案零 diff**。
- `verify_dist.py --cn-diff v42.20.2-1.17.0`：**51,939 個 CN 值變動，待複核 0**。
- 16 支純 repo 回歸測試全過；tracker self-test 15 情境全過。
- owner decision gate：396 筆背書、0 blocking；`OWNER_CONFLICTS.md` 同步。
- `lint_ch.py` 五類棘輪全零。
- 本機 PZ 本體 48,718 個 `(檔,鍵)` 與 dist CH/CN **零交集**。
- `test_serialization.py`：3,906 個受版控 JSON 全合規。
- `manifest --check` 無漂移；`main` 的 `tests` workflow 綠燈。

## [42.20.2-1.17.0] - 2026-08-16

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **跟上 28 個模組的上游更新，補譯 629 個文字。** 大宗是 **Burd 生存日記** 227 個（日記外觀自訂、多人權限管理、筆記編輯器）、**死靈法術** 189 個（遺物效果、研究樹細節、法術檢視面板、附魔後綴）、**PZLinux** 74 個（契約零件名與訓練課程）、**整盒整箱彈藥掉落** 60 個（新武器掉落子模組的沙盒選項）、**空間避難所** 27 個、**Gore's SVU4** 18 個（消音器配方）。
- **修好 65 個配方名一直顯示英文的問題。** 這些配方我方其實早就譯好了，但譯文掛在 Build 41 時代的舊鍵名上，Build 42 根本不會去讀——玩家在製作選單看到的還是英文。涵蓋養蜂、製陶、太陽能板、義肢、萬能膠帶、槍械維修、彈藥裝箱等 20 多個模組。同時新增自動檢查，防止同類問題再發生。
- **消音器與煞車的名稱改成跟遊戲本體一致。** 原本做出「重型高性能消声器」裝上車卻顯示「消声器 (高级)」，同一個東西兩個名字。現在製作選單與成品名稱統一用官方譯名（繁中「老舊／普通／高性能剎車」、簡中「制动器 (老式/普通/高级)」）。
- **路障傷害殭屍的設定說明改對了。** 車輛傷害的預設值與說明文字一直沿用舊版（寫「按生命值百分比計算」、預設 5%），但上游早就改成固定扣血模型（預設 15，實際扣 0.15 點血，不是 15%）；兩個已停用的冷卻時間選項也補上「已棄用」標示。
- **簡體中文的用詞在地化。** 修正 12 類台灣說法：核准→批准、检视→查看、重新命名→重命名、重新整理→刷新、栏位→槽位、载入→加载、套用→应用、储存→保存、拖曳→拖动、选取→选中等。
- **`.357` 子彈的繁中名稱跟上本體**（麥格農→馬格南）。本體自己 `.44` 用「麥格農」、`.357` 用「馬格南」，我方逐鍵跟各自的官方譯名，以玩家實際在遊戲裡看到的為準。

### Added

- **`verify [16]` Recipes 死鍵 gate**（`scripts/verify_dist.py`）。`Recipe_<X>` 是 B41 `Recipes_EN.txt` 時代的鍵形，`craftRecipe_<X>` 是上游在 B42 端多加了 script 類型名當前綴；兩者 B42 都不讀——配方顯示名走 `Translator.getRecipeName(name)` → `recipe.get(name)` 裸區塊名查表（`CraftRecipe.java:362`，`ScriptBucket` 只 trim 不去空格）。前綴鍵去前綴後對得上上游現行區塊名、卻沒出貨該裸鍵即 FAIL。四道設計要點各對應一個實測過的失效模式：(a) **濾有效版本分支**（沿用 `tracker.resolve_effective_branches()`／`is_effective()`，不另寫第二套）——8,816 個區塊名有 1,889 個只存在死分支，首版漏了這道濾網就誤把 Firearms 的 `ConvertAmmo`／`DetractStock`／`ExtendStock` 判成缺口（現行 42.16 已改名 `ToggleStock`）；(b) **還原方向不可寫成 `body.replace("_", " ")`**——上游區塊名會混用空格與底線（`SVRP_CB_Pack Metal Arrows`），全換空格會把區塊本來就有的底線也換掉而漏報，改以區塊名底線化後當索引鍵、原形也收（JSON 鍵允許空格）、精確命中優先；(c) **歧義 fail-closed**——`Foo Bar_Baz` 與 `Foo_Bar Baz` 底線化後會自然撞名，只記 WARN 會放行真缺口，故候選中有任一未出貨即 FAIL 要求人工裁決；(d) **實據殘缺 fail-closed**——`mods` 形狀壞損／`records` 非 dict／濾後區塊名少於 `RECIPE_BLOCKS_MIN`(1000)／allowlist `entries` 形狀壞損都擲例外轉 FAIL，因為空 blocks 會讓判定全部回空、gate 綠燈，那是最危險的失效模式（比照 `[12]` 對 vanilla keys 的量級門檻）。另對 `extractor_schema < 5` 的 mod 出 WARN 讓已知的局部漏報盲區可見（schema 5 起才掃全部 `media/scripts` 目錄；現況 2 個停在 schema 3），刻意不判 FAIL——schema 落後是正常狀態，mod 沒更新就不會重抽。
- **`sources/recipe_dead_allowlist.json`** 人工真相層（`[16]` 的豁免登記，schema `{"entries": {"<裸區塊名>": "<理由>"}}`）。目前留空：唯一符合條件的 `Dismantle Headphones` 撞本體 vanilla，由 `vanilla_keys.scoped_keys` 基準自動放行——登記反而會被反向棘輪報過時，且基準日後移除該鍵時過時豁免會靜默接手放行。
- **`scripts/test_recipe_dead_keys.py`** 30 組情境回歸測試，**含對 checked-in dist 實跑一次**——其餘全是 synthetic fixture，只有它們的話真實 dist 新增死鍵時 CI 仍會全綠（`[16]` 不依賴 As1 快照，CI 上跑得動，不像 `[8]`）。納入 `tests.yml`（9→10 支）。
- **補譯 629 鍵**（28 張「可能過時」issue #155–#183 的實際缺口）：Burd 生存日記 227（`sources/mods/3639628777/CN/` own lane，含新增 `ContextMenu.json`／`Sandbox.json` 兩檔）、Dead Magic 189、PZLinux 74（契約零件名與訓練課程技能名逐鍵吻合本體 `ItemName`／`IGUI_perks_*`，含刻意的繁簡不對稱；`{1}`／`{2}` 佔位符原樣保留，不誤轉 `%1`）、AmmoLootDrop 60、Spatial Refuge 27、Gore's SVU4 18、AmmoConverter 9（口徑名 CH 跟本體 CH、CN 跟本體 CN，兩者刻意不對稱）、WayMoreCars 5、LFB42／LSB42 各 3、P4MySoCalledSnack 3、CleanUI 2、QAMARK 2、TABAS 1、ModManager 1、SVRP ClassicBows 4。
- **清償 65 個既有裸配方鍵缺口**（`[16]` 上線後盤點所得）。這些鍵的譯文早已存在、卻掛在永不被查的前綴鍵上，玩家在製作選單看到英文。`en` 錨點一律取有效分支的上游值（`firearmsOpenBoxOfBullets20`／`50` 原本誤取 42.12 舊分支的 `Open Box of Bullets`，現行 42.16 是 `Open Box (20 Bullets)`／`(50 Bullets)`）；多 owner 共用的 4 鍵附 `_note` 記裁決理由（`Make DIY Battery`／`Make Inverter`／`Make Solar Panel` 屬 Immersive Solar Arrays 原版與其 B42.13 fork，`firearmsOpenBoxOfBullets20` 屬 Firearms 與已停更的 CJ Firearm，值對每個 owner 都成立）。涵蓋 12 個 MOD（Authentic Z 14、Firearms 11、傳奇薙刀 11、ISA 原版與 B42.13 fork 12、Hepha 7、FR Used Cars 4、信用卡提款 3、PZK VLC 2、Spongie 敞開外套 2、唯一療法 2、CJ 槍械 1），`RECIPE_COVERAGE_AUDIT.md` 的逐 MOD 缺口數與進度清單已同步；另有 3 鍵經有效分支過濾判定為假缺口（只存在 42.12–42.13 死分支、現行已改名 `ToggleStock`）不補。

### Fixed

- **#170 SVRP ClassicBows 的 4 鍵誤用 B41 前綴鍵形**（雙邊 review 攔下的 blocking）。`Recipe_Craft_{Metal,Wooden}_{Arrows,Bolts}_from_Plank` 改為上游現行裸 craftRecipe 區塊名 `Craft Metal Arrows from Plank` 等，以 `tracker-state` 的 `script_craftRecipe` 記錄逐一核實（`sha256(區塊名)[:12]` 對得上，非推測）。原本玩家用木板製箭那 4 列仍顯示英文，而 build／verify 14 項／lint 三道全綠——這正是本版新增 `[16]` 的直接由來。metadata note 同步更正上游 EN 鍵數（Recipes 33→37、`Recipe_*` 21→25、JSON 死鍵 81→85，並註明 legacy `Sandbox_EN.txt` 11 鍵不計，B42 完全不讀 `.txt`）。
- **#169 Gore SVU4 同一製作選單內兩套用詞**。等級與車型詞一律對齊本體 `ItemName`：CH「老舊／普通／高性能」＋「剎車／消音器／備用引擎零件」、CN「老式／普通／高级」＋「制动器／消声器／引擎零件」（本體自身繁簡不對稱是刻意的，各語言各自跟本體）。原本 CN 新鍵寫「高性能」而本體是「消声器 (高级)」、既有煞車鍵已寫「高级」；CH 側則是煞車鍵停在「老式／高階」而本體是「老舊／高性能」。連帶修正車型詞（新鍵「重型／標準」→沿用既有「商用型／標準型」）與 `Tooltip_GSEPC_*` 三鍵的等級敘述。
- **#160 BarricadesHurtZombies 只修一半**。補齊車輛側鄰鍵 `VehicleBaseDamage`（預設 5%%→15%%）／`_tooltip`（改寫為「固定扣 0.15 點血、基礎金屬車 0.1875、**不是** 15%」）／`VehicleDamageCooldown` 與 `ThumpDamageCooldown` 標籤（補「已棄用, 不再生效」）。原本同一設定頁裡結構傷害說「固定 HP」、車輛傷害說「按生命值百分比」，且預設值 5 是上游從未有過的數字。CN 走 `cn_overrides` 帶 `as1_value` 錨點。
- **own 層 CN 殘留台灣用語 12 類**。核准→批准、检视→查看、重新命名→重命名、重新整理→刷新、栏位→槽位、载入→加载、套用→应用、物件→物体、储存→保存、拖曳→拖动、选取→选中、关掉→关闭。判準是 As1 CN 語料詞頻（「重新命名」全庫 0:22、「检视」0:107、「套用」1:154、「栏位」5:108），**非機械替換**：「小物件」「实体储存」與敘事口吻的「关掉」屬大陸同樣成立，「把袜子按颜色重新整理」（動詞整理）、「当防水套用的避孕套」（分詞誤判）一律不動。`verify [14]` 只擋 著／牠／妳／「」，詞級在地化無法機械判定——這是 `AGENTS.md` 真相模型第 6 條點名的盲區。
- **CH `.357` 彈藥名跟本體**（麥格農→馬格南，5 鍵）。本體 `Base.Bullets357` 是「.357馬格南子彈」而 `Base.Bullets44` 是「.44 麥格農子彈」，本體自身不對稱；我方逐鍵跟各自的官方譯名，`.44` 保持不動。
- **倒裝語病**「每具你擊殺的殭屍」→「你每擊殺一具殭屍」（CH/CN 同步，2 鍵 ×2 語言）。
- **`AGENTS.md` 的 `[15]` schema 敘述**：寫成頂層 `{"<裸fullType>": "<理由>"}`，實際是 `{"entries": {...}}`（既有文件錯誤，順手更正；該檔不進版控故不在 commit 內）。

### Changed

- **退役 3 個誤補的死分支裸鍵**：`ConvertAmmo`／`DetractStock`／`ExtendStock`（Firearms `2256623447`）只存在 42.12–42.13 分支，現行有效分支 42.16 已改名 `ToggleStock`，出貨無用。屬我方自有資料、不受 `split_sources` 不變式限制，連同 `ch_review_state` 對應登記一併移除。
- **`ch_review_state` 新增 728 筆、更新 15 筆**（`git diff v42.20.2-1.16.0..HEAD -- sources/ch_review_state.json` 可複驗）。除新譯與改譯外，也涵蓋 registry 背書 gate 要求的 `cn_overrides` 命中鍵——漏登則日後 CN 漂移不受 `verify [11]` 監測而 gate 全綠。

### 驗證

兩個內容 commit（`cd372e2`／`17be975`）**各自**跑過完整鏈，不是只有最終狀態綠：build → `verify_dist`（14/14 → 15/15 PASS，未帶 `--allow-missing-as1`）→ 冪等雙跑 `--compare-dist` 零 diff（173 檔）→ `lint_ch` 棘輪全零 → 回歸測試（9 支 → 10 支）→ `test_vanilla_no_override` 對本機本體 48,718 個 (檔,鍵) 零覆蓋 → `tracker.py self-test` 十四情境 → `manifest --check` 同步。release 前另跑 `--cn-diff v42.20.2-1.16.0`：CN 值變動 725 鍵、**待複核 0**。CI `tests` workflow 於 `17be975` 綠燈（含新增測試對 checked-in dist 的實跑）。

## [42.20.2-1.16.0] - 2026-08-15

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **新支援三個模組、共 1,147 個文字。** **職場知識（Working Knowledge）** 754 個：檔案櫃與辦公桌裡的 372 種職場文件，讀一次給對應技能一次性經驗，文件名與說明全翻。**死靈法術（Dead Magic）** 383 個：法術、儀式、附魔、遺物與奧術研究樹的完整介面。**臨時消音器（Improvised Silencers）** 10 個：金屬管、手電筒、水瓶自製的消音器與配方。
- **修好動態背包升級的合成表**（玩家回報）。那個模組的 8 個配方名一直顯示英文，原因是它自己附的中文（含繁體）在 Build 42 掛不上去——連模組作者自己的翻譯都沒生效。我方以正確方式重新提供，就修好了。
- **死靈法術有三個儀式名一直是錯的，這次改對了。** 「枯萎凋零」其實是**伐木**儀式（一次放倒範圍內所有樹）、「鷹眼視域」其實是**亡者視域**（標記視線外的殭屍）、「電湧領域」其實是**電力領域**（像發電機一樣為附近建築供電）。另外把「魔法書」與「法術書」分開——前者是可以收錄法術的載體，後者是記載單一法術、可以抄進前者的書。
- **跟上 18 個模組的上游更新：補譯 77 個文字、修正 6 個過時譯文。** 大宗是 **Pack Mule** 的沙盒選項整組改版（52 個）與 **軍用工具組** 的雪曼戰車部件。同時清掉 30 條上游早已改名、已經用不到的舊翻譯。
- **PZLinux 的涵蓋範圍說明更正了。** 該模組的銀行餘額、契約與出售狀態提示、駭客訊息等文字是直接寫在程式裡的，任何翻譯包都改不了——支援清單上已標註，訂閱前就能知道。

### Added

- **Working Knowledge（`3717099183`）754 鍵原創翻譯**（issue #153）。ItemName 372（職場文件名）＋Tooltip 372（說明＋`Trains: 技能`）＋Sandbox 10。上游有完整簡中、無繁中且鍵形正確，故**簡中直取上游**（僅把全形標點正規化為本包慣例的半形，377 筆），CH 由 Workflow 八批分譯＋對抗複核產出。三項判讀：(a) `Trains: X` 的技能名以 **mod 的 Lua 實際給的技能**為準而非 EN 字面——`Running`→`Sprinting`「衝刺」、`Agriculture`→`Farming`「耕作」、`Animal Care`→`Husbandry`「畜牧」、`Welding`→`MetalWelding`「金工」、`Knapping`→`FlintKnapping`「石器」，31 個技能名跨八批一致；(b) EN 的句中軟換行在 CH 側比照上游 CN 合併掉、只留段落分隔，繁簡排版才一致；(c) 50 個 `WK_Doc_*` placeholder **不收**——`WK_LootReplace.lua` 在容器生成當下就 `container:AddItem` 換成真文件，玩家永遠看不到，其 `DisplayName` 一律是 `Document`。
- **Dead Magic（`3686883520`）383 鍵原創翻譯**（issue #154）。**As1 其實已收 97 鍵，但 attribution helper 歸不了屬、全落在 `sources/_unsorted`**，因此該 mod 從未有自己的目錄、也從未被 `gen-watchlist` 監看；本次建 own lane 目錄一併解除該盲區（97 鍵留在 `_unsorted` 不動，split 不變式）。實收＝`translate_en` 缺口 369 ＋ 14 個上游未建 ItemName 鍵的附魔標記物品（script `DisplayName`，module 為 `Base` 故鍵形是 `Base.DM_Enchant*Token`，已對 `vanilla_keys` 核實零碰撞）。`Mod.json` 2 鍵不收（`readModTranslation()` 只讀 mod 自己的檔，我方出貨對其零作用）；`lua_gettext` 的 `ContextMenu_Read`／`IGUI_ZombiePopulation_TeleportHere` 為本體鍵，依 vanilla 鐵律不收；2 條 `lua_literal` 是 `getText(K) or "fallback"` 形，翻譯鍵優先、不構成涵蓋缺口。
- **Improvised Silencers（`3779164273`）10 鍵原創翻譯**（issue #152）。有效分支僅 `common`（`42.0` 夾只有 `.keep` 佔位）。上游 12 個 `translate_en` 鍵的鍵形全部正確，簡中玩家原本就看得到，缺的只有繁中；CN 直取上游、僅正規化標點。**`Tooltip_Silencer` 與 `Tooltip_MetalPipeSilencer` 不收**——兩者是跨 mod 共用鍵（前者同屬 Firearms `2256623447` 與 Simple Silencers `3309896124`），且數值不一致（Simple 的金屬管消音器 50%、本 mod 60%），寫任一方的專屬全文都會砸掉另一方。
- **Dynamic Backpack Upgrades（`2996978365`）8 個 B42 配方顯示名**（issue #151）。上游 8 種語言的 `Recipes.json`（含它自帶的繁中）**全部只有 B41 的 `Recipe_X_Y` 前綴鍵**，B42 的配方顯示名鍵＝`craftRecipe` 原名無前綴（`Translator.getRecipeName()` 直查），故連上游自己的中文都不生效。我方補正確鍵形即修好；譯名依各配方 `outputs` 的產出物既有譯名定名。同型於 issue #125，屬 `RECIPE_COVERAGE_AUDIT.md` 的 Class B。
- **補譯 77 鍵、改譯 6 鍵**（issue #133–#150 十八張「可能過時」的實際缺口）：Pack Mule 沙盒選項重構 52、Military Tool Kit 戰車部件 7、TakeABathAndShower 8、Gore's SVU4 引擎零件分級 5、其餘 Herbalist／SimpleSilencers／RepairableWindows／ZVirusVaccine／ERS 各 1–2。

### Fixed

- **Dead Magic 三個儀式名誤譯**（As1 lane，CH 改 corpus ＋ CN 走 `cn_overrides` 帶錨點）。逐條以上游 EN 敘述複驗：`Ritual_Fell` 的 `Fell`＝伐倒樹木（"Brings down every tree in the ritual radius"／"A woodcutting rite"），原譯「枯萎凋零」把 fell 誤解為 fall/wither；`Ritual_GraveSight` 的 `Grave Sight`＝亡者（"Marks all zombies…reveals nearby dead in spectral outline"），原譯「鷹眼視域」屬增譯且與同 mod `Farsight`「千里眼」語意重疊；`Ritual_PowerField` 的 `Power Field`＝供電力場（"powers nearby structures like a generator"），原譯「電湧領域」是 power surge 的語意、錯置。
- **Grimoire 與 Spellbook 術語分流**。上游是兩種不同物品（前者可收錄法術、分學徒／中階／大師三階，後者記載單一法術且可銘刻進前者），原本都譯「法術書」會產生「可以銘刻進法術書的法術書」的句子。統一為 **Grimoire＝魔法書、Spellbook＝法術書**，連同兩個既有 As1 鍵一併調整。
- **PZK VLC 的侵權警告譯文跟上上游改寫**（issue #136）：上游把長版（含移除要求與法律行動威嚇）改為單句陳述，譯文同步縮短，不保留已被刪除的主張。
- **`Recipe_MakeLargeSheetMold` 改名後的新鍵補譯**（issue #140）：EN 短標 `Press Large Sheet Mold` 省略了 clay，但依 `outputs` 產出物 `Large Clay Sheet Mold (Unfired)` 補回「黏土」，與同族 `FireClayLargeSheetMold`「燒製大型黏土板模具」一致。
- **PZLinux 涵蓋範圍 note 更正**（issue #141）：原本只看了新增的 5 條 `lua_literal`（都在 admin 選單）就寫「玩家可見介面皆已涵蓋」，逐條複核有效分支全部 32 條後發現多數是一般玩家會看到的（銀行／錢包餘額、契約與出售服務狀態、駭客小遊戲訊息、連線提示），已移除該保證。
- **lint 棘轮命中逐條處置**：污→汙（4）、祕→秘（2）、批量→批次、信號→訊號、搜索→搜尋、數據→紀錄、應用→用法、未通過→未通過考核，共 12 處。「藥物交互作用」是台灣醫藥標準術語（衛福部藥品仿單與健保用藥指引通用），屬 `交(\s*)互` pattern 誤中，登記 `lint_exemptions` 帶 `ch_value` 錨點。
- **合併英文軟換行造成的標點沾黏**：移除 EN 句中折行後，「句號＋下一句」會黏成「機率.截跡」，102 筆受影響，已補做標點正規化（512 處）。

### Changed

- **汰除 30 個作廢鍵**（issue #143）：`own_translations` 中的 `Sandbox_Mule*` 30 鍵（2026-08-11 處理 #101 時補的）本輪已被上游全數改名，對現行有效鍵集命中 0。屬我方自有資料、不受 `split_sources` 不變式限制，連同 `ch_review_state` 對應登記一併移除；另有 32 個殭屍鍵落在 As1 衍生層，依不變式保留。
- **`ch_review_state` 清理與擴充**：移除 2 筆已從真相層完全消失的登記（`IGUI_perks_Metalworking`／`UI_B42MP`，2026-08-12 vanilla 三語聯集基準的殘留）；本版累計新增 1,271 筆、更新 3 筆、移除 32 筆（`git diff v42.20.2-1.15.0..HEAD -- sources/ch_review_state.json` 可複驗）。登記範圍除新譯與改譯外，也涵蓋「判定譯文仍成立」的 EN 錨點刷新（#137／#138）——後者同樣是一次裁決，漏登則日後 CN 漂移不受 verify `[11]` 監測而 gate 全綠。
- **`cn_overrides` 錨點複核**：`Stash_P4StealthCamoMap1_Text3` 的上游本次只是把「伸向了腰带」打成疊字「伸向了了腰带」、未修正語意，override 續留、錨點同步更新。
- **`gen-watchlist` 納管三個新 wid**，上游 EN 更新後會照常開「可能過時」issue；`manifest` 重生（485→488 個 MOD，三者皆帶〔原創翻譯〕徽章）。

### 已裁決不跟進

- **`Tooltip_Silencer`／`Tooltip_MetalPipeSilencer` 的數值差異**（issue #152）：跨 mod 共用鍵且兩個消音器 mod 的降噪數值不同（50% vs 60%），JSON 全域表做不到條件式生效，維持現行來自 As1 已收 mod 的譯文。要各自精確須走 `isModActive` Lua 覆寫或獨立子包。
- **PZLinux 的 32 條 `lua_literal`**（issue #141）：無翻譯鍵、JSON 蓋不掉，依現行方針不新增 `sources/lua/` 覆寫，改以支援清單的涵蓋範圍 note 揭露。
- **`HEADER_Sandbox_EN_81deloreanDMC12` 的「DMC-1」缺字**（issue #137）：`HEADER_` 前綴不在 `getTextInternal()` 路由表，玩家看不到，屬低優先資料清理，本輪不處理。

## [42.20.2-1.15.0] - 2026-08-13

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **新支援兩個模組、共 160 個文字。** **MRE Mod（即食口糧）** 112 個：1993 與 2026 兩種年份、合計 36 道菜的美軍即食口糧，連整盒包裝、拆封配方與生成率／營養值的沙盒設定都翻了。**[SVRP] 經典弓箭** 48 個：複合弓、獵弓、中世紀弓與多款十字弩，加上木質／金屬／碳製的箭矢與弩箭、戰術箭袋，以及打包與拆包配方。
- **弓弩的名字跟你可能已經在用的另一個弓箭模組完全一致。** 這個模組有 24 件物品的英文名與弓術中心（GaelGunStore）完全相同，我們逐字沿用既有譯名，不會出現同一把弓在兩個模組叫不同名字的情況。
- **補譯 Hepha 職業與特質、PZLinux、LockInteriors 共 54 個文字**，並清掉 6 張上游更新通知。占大宗的是 Hepha 的職業與特質敘述 42 條。
- **有一張翻譯申請查證後決定不收：LG Extended Plumbing。** 該模組作者已於 8/12 自行補上含繁體、簡體在內的 27 種語言，本包若跟著出貨反而會蓋掉作者自己寫的譯文。如果你看到的仍是英文，請更新該模組並重開遊戲。

### Added

- **MRE Mod（`3765409550`）112 鍵原創翻譯**（issue #123）。上游只出 EN、無任何中文，有效分支 `42/`。物品名 43 鍵的上游**沒有 EN `ItemName.json`**，鍵取自 `media/scripts` 的 item `DisplayName`，以裸 fullType `bdtmre.<item>` 落地（module 名須讀 script 實證，不可由 mod id 推測）。配方 7 鍵同樣無上游 EN 檔，鍵＝`craftRecipe` 裸區塊名，譯名依 `outputs` 的產出物定名。MRE 一律譯「即食口糧／即食口粮」，錨定本包 SapphCooking 既有譯法；43 個 Tooltip 統一為「\<盒\> 盒，\<年\> 年版第 N 號餐」句式。
- **[SVRP] ClassicBows（`3776949545`）48 鍵原創翻譯**（issue #124）。上游只出 EN／ES。**上游 EN 檔的 81 個鍵全是引擎死鍵、一個都不收**：`ItemName.json` 48 鍵是 B41 的 `ItemName_` 前綴形，`Recipes.json` 的 `Recipe_*` 21 與 `craftRecipe_*` 12 也都取不到。42.20.2 反編譯佐證：`Translator.java:597` 以裸 fullType 查物品名、`:675` 以裸名稱查配方名、`ScriptBucket.java:97` 只 trim 外側空白（故 9 個含空格的配方名如 `Craft Medieval Bow` 須原樣保留）。實收＝script `DisplayName` 推得的 27 個 `Base.SVRP_CB_*` ＋ 21 個 craftRecipe 裸區塊名。24 個物品名與 GaelGunStore（`3616176188`）的 `own_translations` 條目 EN 全同，**逐字沿用**避免同一件物品在兩個模組出現兩套名稱；Bow String Silencer／Arrow／Bolt 三鍵為新譯。該 mod 另有 4 處 `getText` 取本體鍵（`ContextMenu_Add/Remove_Weapon_Upgrade`、`IGUI_JobType_Load/UnloadBulletsIntoFirearm`），本體 CH/CN 皆有官方譯文，依 vanilla 鐵律不收。
- **補譯 54 鍵 / 7 檔**（issue #127–#132 六張「可能過時」的實際缺口）：ItemName 32、Recipes 8、IG_UI 8、Sandbox 3、Fluids／Tooltip／ContextMenu 各 1。issue 內文的增刪計數全部不可直接採信——`extractor_schema` 7→8 全量重抽與 CI 隔天用自己下載的包比對，加上上游改動版本夾，數字被路徑搬家灌爆；濾有效分支＋正規化後 #128／#131 實為零變動，#127 是上游把 B42 分支由 legacy `_EN.txt` 換成 `.json`（舊分支那 332 鍵從來沒生效過，談不上過時）。
- **`.github/workflows/tests.yml`（新檔）**：push／PR／手動觸發，跑 9 支純 repo 回歸測試＋`tracker.py self-test`＋`lint_ch.py` 棘輪。此前 repo 唯一的 workflow 只跑 tracker，`scripts/test_*.py` 全靠人工在收尾階段記得跑。`test_vanilla_no_override.py` 與 build/verify 全鏈**刻意不納入**：前者是對本機 PZ 安裝現況的端到端斷言且 fail-closed 無豁免旗標，後者的 verify `[8]` 需要 Steam 管理的 As1 快照樹，CI 上帶 `--allow-missing-as1` 的 PASS 等於沒驗 As1 端。

### Fixed

- **追蹤器刷新 EN 鏡像後會把 `SUPPORTED_MODS.md` 靜默改成過期**。「覆寫本體」欄由 `sources/en/<wid>.json` 對 `vanilla_keys.json` 算出，而 `sources/en/**` 正是排程每日刷新並 commit 的東西——刷了卻從不重跑 manifest，而 build／verify／lint 沒有任何一道驗生成物新鮮度。實例 `c8f5064`：Hepha 把 B42 分支換成 `.json`，三個撞本體的 `UI_prof_*` 首次進入有效集，該列本該從 `—` 變 `⚠️ ≥3` 卻錯了一整天而三道 gate 全綠。`cmd_run`／`cmd_issue` 現於 `_persist_state()` 後呼叫 `refresh_manifest()`，生成物與 state 併入**同一個 commit**；重生失敗不阻斷 state 推進（追蹤器停擺的代價更大且 state 自癒），改以非零退出碼讓 CI 轉紅。
- **`Base.OutcastBox` 譯名與同 mod 既有 Tooltip 自相矛盾**（codex 複核發現）：原譯「邊緣人便當盒」錨的是本體 `Base.Lunchbox`，但本鍵是該 mod 自有物品、且同 mod 的 `Tooltip_OutcastBox` 已作「復古午餐盒」。改為「邊緣人午餐盒」後，本包 CH 全庫的午餐盒 21 : 便當盒 1 矛盾歸零。

### Changed

- **`RECIPE_COVERAGE_AUDIT.md` 依 CI 追蹤器更新重算**：缺口 2,260 → 2,261（相異 2,124 → 2,125）；Class A 1,681→1,674 / 38→37 MOD、Class B 579→587 / 29→30 MOD。分類移動來自上游新增 EN `Recipes` 檔（Class A → B）。出貨內容零變動。
- **`tracker.py` 的 state commit pathspec 收斂為單一來源**：`cmd_run`／`cmd_issue` 原本各自 hardcode 一份，改走 `state_add_paths()`；self-test 情境 6b 一併改用同一函式並加驗 manifest 生成物確實在 pathspec 內。

### 已裁決不跟進

- **LG Extended Plumbing（`3779561845`）不收錄**（issue #126，已關閉）。上游 2026-08-12 的 v3.2.0 已自行補上含繁中／簡中在內的 27 種語言（更新紀錄：`27 languages. Nothing is hardcoded in English any more.`），現行版有效分支 `42.20/` 的 CH 三檔（ContextMenu 14／Sandbox 9／Mod 2）逐鍵齊全。PZ 把所有 mod 的 `Translate` 檔併進同一張全域表、後載入者勝，本包載入順序在一般 mod 之後，收錄等同蓋掉作者譯文。另 `Mod.json` 的 `name`／`description` **任何第三方翻譯包都補不了**——`Translator.readModTranslation()` 只讀該 mod 自己的 common／版本夾。
- **`coverage_survey.py` 對 SVRP ClassicBows 恆報 0%** 屬工具口徑、不修。該工具不做 `ItemName_` 前綴正規化（`tracker.py` 的 `_canon_key` 有做，self-test 情境 12），上游那 81 個死鍵全被算成缺口；權威口徑是 `tracker.py coverage` 的 `lua_gap`＝0。已記入該 mod 的 `metadata.json` note，避免日後被當成真缺口追。

## [42.20.2-1.14.0] - 2026-08-13

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **修掉 26 個「連沒裝任何模組也會被改掉」的原版官方文字——本版最重要的修正。** PZ 把所有模組的翻譯檔併進同一張表、後載入者勝，所以某些模組改寫原版譯文之後，本包跟著出貨就等於全域改掉官方文字。實際被改掉的包括：多人測試的歡迎與警告畫面被換成某模組作者的募款文案、原版「MSR700 彈匣」被改成特定槍械模組的專屬名稱（吊帶、機械瞄具、.223 彈藥等 7 項同類）、職業「竊賊」的說明被加上原版沒有的偷竊潛行能力、特質「體態優良」的說明被清空成一個空白。這類鍵現在一律不出貨，交還給遊戲本體。
- **製作頁面補上 164 個配方名。** 起因是玩家回報 More Traits 的製作頁面全是英文，查出來是一整類系統性漏收——模組定義了配方，但沒附英文配方檔（或上游自己也漏建鍵），我們的收錄流程就整組跳過，而且既有的覆蓋率統計完全看不出來。這一版先補完**正式伺服器實際啟用的所有模組**，另加 Jigga's Green Fire（大麻模組）68 個與 Pomp's Items（小馬模組）26 個。
- **Pomp's Items 的 8 隻小馬有中文名了**，連帶 24 個絨毛玩具與服裝的物品名。其中 Fancy Pants 採官方配音譯名「花俏公子」。
- **PompsItems 有 1,766 個文字先前完全沒被追蹤到。** 該模組的翻譯檔有多餘的逗號，PZ 自己讀得下去、我們的追蹤器讀不下去，於是整個檔案在我們眼中等於不存在——而所有檢查都是綠的。修好後其中 104 個玩家看得到、我們沒出貨的文字才浮現。
- **清償 14 張「可能過時」issue：新譯 81 鍵、修正 16 條過時譯文。** 比較有感的：Stealth 模組的「透明度」其實是不透明度（原譯讓 0 與 10 的刻度整個反過來）、竊賊→盜賊、隱身技能→潛行技能。
- **支援清單新增兩欄。** 「覆寫本體」讓你知道某個模組本身會動到幾個官方翻譯（目前 73 個模組有標記）；「涵蓋範圍」標註哪些模組有翻譯包補不了的英文——目前登記 Gore's SVU4 Core、Dynamic Trading、More Traits 三個。

### Added

- **`RECIPE_COVERAGE_AUDIT.md`（新檔）**：`craftRecipe` 配方顯示名的全庫覆蓋率稽核。B42 的配方顯示名鍵＝`craftRecipe` 原名（**含空格、無 `Recipe_` 前綴**，`Recipe_X_Y` 是 B41 形、在 B42 完全失效）：`ISRecipeScrollingListBox.lua:351` → `CraftRecipe.Load():362` → `Translator.getRecipeName():676` 的 `recipe.get(name)` 直查。`en_corpus_hashes`（schema 8）已記 `script_craftRecipe`，全庫可從版控資料直接算、不必下載 483 個 mod；方法以 8 個實際下載的 MOD 交叉驗證，逐一相符。**數字為上限**——MOD 可能自帶活的 `Translate/CH/Recipes.json`（追蹤器只記 EN，看不到），已實證 More Guitars 自帶 166 個活繁中配方名；反之只有 legacy `Recipes_CH.txt` 者仍算缺口（B42 只讀 `.json`）。
- **配方顯示名 164 鍵**，分三批：
  - **issue #125 More Traits（`1299328280`）16 鍵**。上游只附韓文 `Recipes.json`、沒有 EN 檔，As1 的 EN 驅動擷取整組漏收；該 MOD 五個 EN 檔都是 100%，覆蓋率統計完全看不出這個缺口。上游韓文檔用的是 B41 的 `Recipe_` 前綴形，在 B42 失效，未照抄其鍵名。
  - **正式服啟用中的 51 個 runtime 鍵**（拉 `pzserver.ini` 的 `WorkshopItems` 交叉比對）。44 鍵沿用既有譯文——Beetle 23、M998 19 經 recipe body 逐一比對確認為上游把點號拿掉的真改名；M101A2 2 鍵**不是改名**，是上游 common EN JSON 的無點號鍵與實際 recipe 名不符、那個舊鍵本就取不到。7 鍵新譯，全部依 `outputs` 的產出物 DisplayName 定名。
  - **Jigga's Green Fire 68 鍵**，術語全部錨定本包既有的 240 個 `Greenfire.*` 物品名。語意不明者一律查 script 實證：`CutCannabis`（剪刀）／`TearCannabis`（徒手）／`GrindCannabis`（研磨器）產出同一個 `CannabisShake`，分別作剪碎／撕碎／研磨；`MakeFlyCure` 產出 `Base.GardeningSprayCigarettes` ＝本體「除蟲噴霧」。
  - **Pomp's Items 26 鍵**（見下）。
- **Pomp's Items 8 隻小馬定名 ＋ 24 個物品名**。本包既有 420 個小馬 Plushie 譯名中僅 3% 保留拉丁字母且多為縮寫，預設意譯。`Fancy Pants`→花俏公子／范西潘為**官方配音譯名**（兩地維基百科《彩虹小馬》角色列表次要角色節載明並附配音員資料）；`Sixer`→六號／六号 沿用同 mod 既有 `PINumberNine*`→九號／九号 的完全同型先例；`Mulberry Merlot`→桑椹梅洛／桑葚梅洛（Merlot 錨 `Fluid_Name_VFX_Merlot`「梅洛紅葡萄酒」，mulberry 為台灣桑椹／大陸桑葚的詞級分歧）。句型全部沿用既有 `PINumberNine*` 與 `PIVeenSundown*` 的物品／配方格式，未自創。
- **`SUPPORTED_MODS.md` 新增「覆寫本體」欄**，由 `vanilla_override_counts()` 計算而非人工登記：取「上游 EN 鏡像 ∪ 本包收錄的該 mod CN 譯文」聯集對 `scoped_keys` 取交集。仍是**下限**（上游自帶 CN/CH 檔我方無鏡像），故渲染為 `≥N`。目前 73 個 MOD 有標記，15 個標 `?`。
- **`SUPPORTED_MODS.md` 新增「涵蓋範圍」欄**：上游把文字放在 PZ 翻譯表取不到的位置時登記，讓玩家訂閱前就知道。頁首明寫這是**遇到才查證**的登記、非全庫普查。
- **清償 14 張「可能過時」issue（#109-#122）新譯 81 鍵**：#117 PZLinux 21、#122 MirageWardrobe 29、#111 PompsItems 9、#110 ThiefExpansion 8、#121 TABAS 6、#109 BetterSorting 4、#116 W900 2、#119 LegendaryBackpack 2。issue 內文的 1,565 筆宣稱變更經 `resolve_effective_branches()` ＋ `kind::檔名|鍵` 正規化後收斂為 180 筆真變更，其中 5 張零真變更。
- **`scripts/test_vanilla_no_override.py`**：不看快照、直接讀本機 PZ 安裝現況驗 dist 零覆蓋。**不認 `keep` 豁免、無降級旗標**——「因為讀不到本體所以通過」的綠燈正是這裡最該擋住的東西。

### Fixed

- **本體鍵基準改 `EN ∪ CH ∪ CN` 三語聯集，26 個被全域改寫的官方字串停止出貨**。`extract_vanilla_keys.py` 過去只從本體 **EN** 目錄擷取，漏掉本體**只在中文檔定義、EN 沒有**的 1,465 個鍵——而那正是我方 CH/CN 檔會直接覆寫掉的本體譯文（`Translator.java:353` 全域 `map.put()`、後載入者勝）。其他語言（PTBR/AR/…）只在該語言檔出現的鍵**刻意不納入**：我方只出貨 CH/CN，納入只會白白砍掉模組譯文（實例：`UI_CraftCat_*` 37 鍵僅存在於本體 PTBR 檔、本體 Lua 零引用，卻有多個模組實際在用）。副作用是 `verify [12]` 副閘門攔到 4 個 own 鍵，一律退役而非登記豁免。
- **上游 JSON 尾逗號改容錯解析，修掉「整檔翻譯鍵靜默消失」的盲區**。`_iter_translate_records` 遇 `JSONDecodeError` 只印一行 stderr 就跳過整檔；PZ 自己的解析器容忍結尾多餘逗號、Python 不容忍，於是那個檔的每一個翻譯鍵對追蹤器、`sources/en/` 鏡像、coverage／gap／survey **全部不存在，而所有 gate 都是綠的**。新增 `load_upstream_json`：只刪解析器自己停下位置的那一個逗號再重試，逐次收斂——**不可**改用全文 `re.sub` 替換，那會把字串值裡的 `"list is [x,] here"` 一起改掉＝靜默竄改上游原文。**行尾兩種都要處理**：CPython 對 LF 檔報 `Illegal trailing comma` 並停在逗號，對 CRLF 檔報 `Expecting property name` 並停在 `}`。`EXTRACTOR_SCHEMA` 7→8。
- **容錯解析的過度寬鬆缺陷**（codex review blocking）：`_drop_trailing_comma` 原本只確認「解析器停在逗號上」就刪，反例 `[1,,2]`→`[1,2]`、`{,"a":1}`→`{"a":1}` 等於偽造上游原文。改為候選逗號**後面接收尾括號、前面接一個完整的值**兩邊都檢查。另修 `_TRAILING_COMMA_LIMIT` 的 off-by-one。
- **零覆蓋 gate 的 fail-open**（codex review blocking）：`test_vanilla_no_override.py` 對不存在的 dist 目錄讀到空集合後仍判通過。改為先驗目錄存在、檔數與鍵數達量級門檻、兩側檔案集合一致。
- **`gen_steam_changelog` 把維護者向內容貼進 Workshop**：本 repo 的白話版集中在 `### 玩家摘要` 節，但腳本只剝 `>` 引用塊，於是三個技術節原封不動被貼上公開頁面（1.13.0 產出 6,200 位元組 21 條，含鍵名與行號引用）。修為：版本區塊內若有 `### 玩家摘要` 就收斂到該小節。產出 6,200 → 855 位元組。
- **譯文修正 12 鍵**：P4 Stash 5 鍵（EN 確有敘事事實變動）；`Tooltip_Silencer` 共用鍵改中性文案（同屬槍械擴充與簡易消音器兩個 owner，原譯採後者專屬數值對前者不成立）；字面反斜線 2 鍵改中文引號；`SoundVolumeStealingFumble_Tooltip` 補回「失手」條件；MirageWardrobe CN 的 Undo 3 鍵「撤回」→「撤销」。
- **16 鍵過時譯文**，只挑 EN 真的動到資訊者：`StealthAlpha_Name/_Tooltip`（EN `Transparency`→`Opacity`，原譯「透明度」與 0=完全透明/10=完全不透明的刻度自相矛盾）、`EasyToFind_Tooltip` 補兩項新資訊、`Stash_*Map1_Text3` 受詞改變、MirageWardrobe 分組重構、術語一致（竊賊→盜賊、隱身技能→潛行技能、全域開關→總開關）。
- **`3635333613` Dynamic Trading 的涵蓋範圍 note 補上寫死於程式碼的 139 句**：原 note 只寫了 UI／對話 533 句，漏掉管理員 debug 選單等 139 句連翻譯鍵都沒有。

### Changed

- **`keep` 豁免通道焊死**（使用者裁決 2026-08-12）：每次都要掃 MOD 的鍵有沒有跟本體 EN/CH/CN 衝突，撞到就取消該鍵出貨，**不得覆蓋本體任何一個 key**。`build_mod.load_vanilla_scoped()` 與 `verify_dist._load_vanilla_basis()` 改為只要 `keep` 非空就直接失敗；要處理個別鍵請走 `unshipped_keys.json`。
- **全庫 EN 鏡像重抽（schema 8）**：schema 演進後 467/468 份鏡像仍是舊 schema、數字不可信。`backfill-en --force` 全量重抽 468/468 零失敗，**全庫 75 個上游檔靠新的容錯才讀得到**。重算 coverage：上游 EN 鍵 72,391、缺口 1,086，其中確證玩家可見且可補的只有 11 個。
- **`ch_review_state.json` +151 筆**，含「EN 變動但譯文經核對仍成立」的裁決，以及 `Recipes.json|PIFrozenPizzaCheese` 沿用同族既有裁決的登記（hash 與三個同族鍵完全相同）。不登記則未來 CN 漂移不受 `verify [11]` 監測而 gate 全綠。
- **`test_manifest_fresh.py` 欄數合約 6/7 → 7/8**，並新增欄數齊一情境：前六組都是「生成器輸出 vs 生成物」比對，兩邊一起錯照樣綠。

### 已裁決不跟進

- **`UI_trait_lightdrink`／`UI_trait_harddrink`（＋desc）4 鍵不收**（codex 獨立 review 指出）：唯一 producer `MoreTraitsMainCreationMethods.lua:413-414` 位於該檔第 1 行 `--[[` 至第 426 行 `--]]` 的整檔註解內、永不執行，且 `ToadTraits.txt` 未以 `character_trait_definition` 補回，屬死鍵。**教訓：以 regex 掃 `getText(` 判定活引用時必須先排除 Lua 註解區塊。**
- **7 個 `tsarslib` 配方鍵不收**（codex 獨立 review 指出）：`common/` 與版本夾**不是取聯集，是相對路徑覆蓋**——`ZomboidFileSystem.loadMod()` 先掃 `common/` 以相對路徑為鍵寫 `activeFileMap`，再掃版本夾以同一個鍵覆寫（原始碼會印 `mod "X" overrides <rel>`），`ScriptManager` 再按相對路徑去重載入。該 mod 的 `ata2_items.txt` 在 `common/` 是空白形、在 `42.17/` 是底線形，runtime 只有後者存在。**`resolve_effective_branches()` / `is_effective()` 目前不處理這件事，影響所有 kind，已記入報表建議節待根治。**
- **More Guitars（`3410974338`）的 7 個 Flying V 配方鍵不補**：該 MOD 自帶 166 個活的繁中配方名，玩家看得到中文，屬版控估算的已知誤差。
- **Class A 的 1,681 鍵本版不動**：上游無 EN 可對照，須逐 MOD 下載讀 script 自 `outputs` 定名，另行分批。

## [42.20.2-1.13.0] - 2026-08-11

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **17 個模組跟上上游最新版，補進 50 條新的選項與訊息。** 大宗是 B42 Pack Mule 的沙盒選項（作者這次大改名，還多了口袋、護肩、眼鏡三個新槽位），其餘散在 Clean UI、每日報告日誌、沉浸式停電、撬門模組等。
- **Knox Drugs 有兩則物品說明本來顯示「NEEDTOBERENAMED」，現在有中文了。** 那是上游自己留的佔位符，這次它填上真文本，我們跟著補。
- **「保鮮盒 (菲圖奇尼寬麵)」裡面其實裝的是筆管麵。** Vanilla Foods Expanded 這兩個物品名一直是錯的，已修正。
- **修掉兩個老錯字：「番茄幹」→「番茄乾」、「香腸」→「西班牙辣香腸」。**

### Added

- **17 張「可能過時」issue（#92–#108）清償，補譯 50 鍵入 `own_translations.json`**：
  - **#101 B42PackMule 30 鍵**。上游做了一輪 sandbox 鍵改名，拆解後為 10 組改名（`MuleWrist`→`MuleAccessory`、`MuleEarProtection`→`MuleEarProtector`、`MuleLowerBack`→`MuleLooseBack`、`MulePocket`→`MuleWallet`、`MuleRifleCase`→`MuleOverShoulder`、`MuleWebbing{Large,LargeCrafted,Medium,Small,SmallCrafted}`→`MuleWebbing_{ALICE,Framepack,HikingBag,SchoolBag,CrudeBag}`）＋ 10 組真新增（口袋／護肩／眼鏡槽位、Auto-Pouch／Auto-Wallet）。改名者沿用舊譯並跟進 EN 增補處（`or suit heads`、`(Singleplayer only)`）；舊鍵仍在 As1 衍生層並繼續出貨，須待 As1 上游自己改名後隨快照重釘清除。
  - **#98 B42_PZLinux 的 `IGUI_PZLinux_Betting_BlackjackBetRange`**：placeholder 契約以 steamcmd 重抓的現行版查證 consumer——`PZLinuxFormatText()`（`shared/ISPZLinuxVariablesTables.lua:207`）走 `getText(key)` 取回譯文後**自行** `gsub`，`%s` 優先、`%N` 為 fallback，故譯文維持 `%s` 不轉編號。本機 Steam 訂閱副本是舊版、查無此鍵，未採信。
  - **#104 Daily Report Journal 的 tooltip 含 `<LINE>`**，標籤前保留 ASCII 空白：`ISRichTextPanel.lua` 以空白切 token，token 內同時含 `<` 與 `>` 即整個進 tag 分支，缺空白會讓前一整段文字不顯示。
  - 其餘：#92 P4TidyUpMeister 2、#95 PZKCarzoneWorkshop 1、#99 CleanUI 2、#100 BreakBigRocks 2、#103 STA_PryOpen 4、#105 ImmersiveBlackouts 2、#106 OCsPacking 1、#108 KnoxDrugs 3。CH／CN 逐鍵對照 EN 分別直寫，未經任何簡繁轉換器。

### Fixed

- **`Tooltip_KD_Grinder`／`Tooltip_KD_Syringe`（#108）**：上游原值是佔位符 `NEEDTOBERENAMED`、我方照樣出貨，這次上游填了真文本後跟進。該 mod 另有多個 tooltip 仍是上游未填的佔位符，維持原樣等上游。
- **`VFX.FoodStorageContainerPenne`／`VFX.MetalFoodStorageContainerPenne`（#102）**：誤譯為「菲圖奇尼寬麵」，實際物品是 Penne——上游把自己的 EN 由 `Container with Fettuccine` 修正為 `Container with Penne` 才讓錯誤浮現。
- **`VFX.JarSundriedTomatoesOpen`（#102）**：CH 為「番茄**幹**」，OpenCC 一簡對多繁誤轉的殘留，改為「番茄乾」。
- **`VFX.Chorizo`（#102）**：EN 由 `Sausage` 改為 `Chorizo`，原譯「香腸」既漏掉品項，也與同 mod `ItemName.json|VFX.Chorizo`「西班牙辣香腸」自相矛盾。
- 另修 `ContextMenu_EvolvedRecipe_VFX_GreekYogurtHomemade`（`Yogurt`→`Greek Yogurt`）、`VFX_OpenPizzaRollBox`（盒→袋，ItemName 側早已作「袋」）、`VFX_OpenPuddingBox`（盒→連包）、`Sandbox_DestroyBoulder_ToolUsesPerConditionLoss` 及其 tooltip（上游改寫並補上「與原版鎬／大錘同機制」的說明）。CH 改 `sources/ch/`、CN 走 `cn_overrides.json`（帶 `as1_value` 錨點）。

### Changed

- **`ch_review_state.json` +71 條**，其中 16 條是「上游 EN 變動但譯文經核對仍成立」的裁決。那同樣是一次裁決，不登記則日後 CN 漂移不受 `verify [11]` 監測，而 build／verify／lint 三道全綠——由 codex review 以 blocking 指出後補登。
- **`IGUI_CraftingCategories_Packing`（#108）裁決不收**：撞 `vanilla_keys.json` 的 `scoped_keys["IG_UI.json"]`。PZ 的翻譯表是全域的，出貨即等於改寫本體譯文、連沒裝該 mod 的玩家都會看到。
- **`Sandbox_MuleOverShoulder`／`Sandbox_MuleEarProtector_tooltip`／`Sandbox_MuleGlasses_tooltip` 用詞校正**（codex review 採納）：`Cloth Gun Case` 補回「布製／布制」修飾（本體作「布制槍箱」）；CH 的「全盔」改為「全罩式頭盔」（本體 CH 零命中「全盔」、用「頭盔」32 次）。同一輪駁回兩項——`Duffel Bag Slot` 要求繁簡分流成「圓筒包／行李袋」，但本包 CH 已有 211 處「行李袋」，單鍵改動只會製造局部矛盾（記為全庫術語議題）；「佩戴→配戴」，本包 CH 佩戴 41 : 配戴 2。

### 已裁決不跟進

- **VFE 上游去商標化改名**（`Cocoa Puffs`→`Choco-Roos`、`Wheaties`→`Wheat Flakes`、`Honey Oaty O's`→`Honey O's`、`Toaster Strudel`→`Pop Strudel`）：上游自身尚未一致（`Base.VFXCocoaPuffsBowlEvolved` 仍為舊名），跟進得連動 4 族十幾鍵才不矛盾，且玩家看到的品項未變。
- **VFE 演化食譜成分標籤的統一簡化**（`Apple Pie Filling`→`Apple`、`Mango Slices`→`Mango` 等）：我方譯文比新 EN 更具體，不致誤導。
- 兩項理由均已寫入 issue #102 的關閉留言，日後翻案有紀錄可循。

## [42.20.2-1.12.0] - 2026-08-11

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **954 個物品名第一次真的變成中文。** 這批譯文其實一直都在包裡，但用的是 B41 時代的舊鍵格式（`ItemName_模組.物品`），B42 的遊戲引擎根本不會去讀它——玩家看到的一直是英文。這次全數改成 B42 讀得到的寫法，涵蓋 3D 列印機、拾荒技能、進階醫療系統、Zomboid Storylines、True Music 隨身聽等模組的物品。
- **Barrels Expanded 的 41 則提示訊息救回來了——這個連英文版都是壞的。** 該模組把訊息放在 PZ 不會載入的檔案裡，所有語言的玩家看到的都是「UI_BarrEx_TransferRejection_BarrelEmpty」這種鍵名。我們把譯文放進正確的檔案就修好了，等於順手幫上游修了 bug。另外 Super Bulldozer 3 則、Last Cup Coffee 4 則也用同樣方式救回。
- **新增支援 2 個模組（481 → 483 個）**：Better Sorting（物品分類）與 Gore's SVU4 Core（車輛裝甲改裝，含 4 個子模組）。兩者都是玩家申請的——前者工作坊雖然寫著支援簡中，但那些中文檔是 B41 遺留、B42 完全讀不到；後者則是自帶的中文檔裡面全是英文。
- **繁中的「喪屍」全部統一成「殭屍」**（130 處）。殭屍是繁中正字，之前混用純屬歷史殘留。簡中維持大陸慣例不動。
- **支援清單現在會標註「這個模組我們補不了」。** 有些模組把文字放在遊戲翻譯機制取不到的地方，任何翻譯包都無能為力。與其讓玩家訂閱後才發現，不如先寫清楚——目前標註了 Dynamic Trading (w/ NPC) 與 Dynamic Emergency TV Channel 兩個。

### Added

- **收錄 #76 Better Sorting（`2313387159`）36 鍵、#77 Gore's SVU4 Core（`3730070661`）247 鍵**，均為 own lane 原創翻譯（`origin:"own"`）。
  - #76 上游中文檔失效原因雙重：檔案留在 **mod 根目錄 `media/`**（`loadMod()` 只搜 `common/` 與版本夾）且為 **legacy `_CH.txt` 格式**（`tryFillMapFromFile()` 路徑寫死 `.json`），兩者各自即足以致命；`42/` 分支只有 EN 80 鍵，故該 mod 在 B42 是全語言失效而非僅中文。80 鍵零 vanilla 碰撞，44 鍵本包既有覆蓋，補譯 36 鍵。
  - #77 單一 Workshop 項目含 4 個 mod，上游自帶 CH/CN 八檔逐一比對確認 **全為 EN 原文空殼**。排除 9 個 `Base.LightBulb*` vanilla 覆寫鍵，補 9 個上游未建鍵的 script `DisplayName` 物品。`Recipes.json` 裸鍵經 42.20.2 反編譯確證為活鍵（`CraftRecipe.java:362` → `Translator.getRecipeName()` → `recipe.get(name)` 裸鍵查表）。同系列 `3760377708`／`3742291546` 為純模型掛件包不收錄；前者另有 6 句寫死於自訂 UI 的英文，無鍵可譯、已裁決不加 Lua 覆寫。
- **`verify_dist [15]` ItemName 死鍵閘門**：`ItemName_<Module>.<Item>` 前綴形在 B42 完全不被讀取（`tryFillMapFromFile():362-366` 原封 `map.put`、`getItemNameFromFullType():601` 只查裸 `Module.Item`）。對不在 `itemname_dead_allowlist.json`、又非 vanilla 的死鍵判 FAIL。回歸測試 `scripts/test_itemname_dead_keys.py`。
- **`sources/unshipped_keys.json` 已裁決不出貨登記機制**：適用於「鍵落在 PZ 不載入的檔名、且找不到正確落點」者。真相層照樣保留（`_unsorted/CN` 是 As1 忠實鏡像，刪掉會讓 tracker layer-B 永遠報差異），抑制只在出貨那一步，與 vanilla 出貨抑制共用 `suppressed_pairs()`。`as1_value` 錨點在上游動過時出 warning ＝重查訊號。回歸測試 `scripts/test_unshipped_keys.py`。
- **`mod_names_zh.json` 選配 `note` 欄位**：標註「上游把文字放在 PZ 翻譯表取不到的位置、任何翻譯包都補不了」的涵蓋範圍例外，渲染於 SUPPORTED_MODS.md 摘要之後（慣例 ⚠️ 起頭）。只登記已查證到機制的個案，不拿覆蓋率比值反推。
- **`scripts/gen_steam_changelog.py`**：由 CHANGELOG 版本區塊生成 Workshop 更新註記；CHANGELOG 每版新增「玩家摘要」節作為其來源。
- **`own_translations.json` 條目支援選配 `_note`**，記該鍵的人工裁決理由（build 只驗 en/ch/cn 非空，底線開頭欄位忽略）。

### Fixed

- **954 個 `ItemName_` 前綴死鍵補上對應裸鍵**，分三輪落地並各自修正前一輪的錯誤判斷：
  - 首輪 101 鍵。module 名不可猜——靠 steamcmd 下載 11 個 mod、以大括號深度界定 `module X {` 逐檔解析，才發現 `3DPrinter`→`Printer3D`、`ScavengerSkill`→`ScavengingSkill`、`BetterSafehouse_X`→`BetterSafehouse.X` 三處猜錯。
  - 次輪 820 鍵。首輪宣稱「872 個 `Base.*` 死鍵是 vanilla 抑制副產物、死但無害」是**推論不是查證**且錯誤：以 `scoped_keys["ItemName.json"]` 核對，872 個中只有 29 個真是 vanilla，其餘 843 個是 MOD 往 `module Base` 加的物品（`Base.44Clip20` 是高容量彈匣、vanilla 只有 `Base.44Clip`）。真缺口是 1,034 而非 191。
  - 末輪 33 鍵。前輪把 118 個殘餘一律登記「查無來源」是**把工具限制當成事實**：DisplayName 抽取器寫壞（只抽到 255 筆、實際 4,298 筆）、沒去讀 mod 自帶的 `Translate/EN/ItemName.json`（且 PZ mod JSON 常帶尾逗號會讓 `json.loads` 拋錯後被 silent skip）、兩個 mod 的 wid 沒指認出來。
- **41 個 BarrEx 訊息從 PZ 不載入的檔名救回，順帶修掉上游自己的 bug**。Barrels Expanded（`3727387302`，Workshop 標題搜不到、須用搜尋端點查內部 id）把 40 個轉移失敗訊息定義在 `Translate/EN/TransferMessages.json`，但該檔名不在 `Translator.BY_NAME` 白名單、PZ 從不載入，而 `BarrEx_Main.lua:254` 用 `getText()` 消費它們——**這批訊息對所有語言（含英文）都是壞的**，玩家看到原始鍵名。我方把鍵放進自己的 `UI.json` 即修復。
- **Super Bulldozer 3 鍵、Last Cup Coffee 4 鍵救回**：先前判「mod 已下架」是搜尋方式錯誤，兩者都還在。
- **5 鍵 placeholder 契約修正**（`%s`/`%d` → `%1`）：以**上游現行 Lua** 證實契約已從 `string.format` 轉為 `getText` 帶參數，停在舊寫法會讓玩家看到字面佔位符。本機 Steam 副本可能是舊版，hash 不符時不可採信。另修 19 鍵過時簡中。
- **43 張「可能過時」issue 清償**：issue 內文的增刪改計數不可直接採信（record id 帶相對路徑，上游搬檔會被算成大量 added+removed），改由 git 歷史重建真實 diff；**必須先濾有效版本分支**，本次若略過此步會漏判 49 個鍵。
- **`verify [13]` 不再把「已由改名後繼者涵蓋」的死鍵報成缺陷**，並修正誤導的警告文字。
- **錨點漂移比對補套過度逸出還原**——6 條登記全是假警報。
- 修正兩處回歸：rich-text `<LINE>` 前後空白不可壓縮；共用鍵不得寫入單一 mod 的專屬全文。

### Changed

- **術語錨定基準修正（本次最大宗值變更，120 鍵）**：#77 首版譯文錨在**遊戲內建** CH/CN 檔，此為錯誤基準——玩家並用本體翻譯包 MinidoracatLangFor42 時，該包後載入覆寫全域字串表，內建值不是所見值。全面改對本體包定案：引擎蓋→引擎罩、制動器→煞車、懸掛→懸吊、座位→座椅、後車蓋→後備箱蓋、老舊/一般/性能→老式/普通/高階；技能名機械→技工、金屬加工→金工（後者尤重：CN「金属加工」在本體是 Metalworking 另一技能，會讓玩家找錯技能欄）。120 個車輛配方**逐部件建映射而非全域替換**——本體包 CN 對輪胎 `Old` 作「廉价」、煞車作「老式」，機械替換會抹平此差異。
- **CH 側 zombie 統一為「殭屍」**（106 鍵、130 處）。CN 欄刻意不動：大陸用 丧尸/僵尸 與繁中正字無關，本包 CN 現況的不一致源自 As1 自身，依規則跟隨個別 mod 錨點。
- **`terminology.json` re-vendor 至本體 `5ef995c`**（rules 171→176），`lint_ch [D]` 轉為同步 ✓。帶進 `喪屍→殭屍`（為此在本體新增，作防回歸棘輪）、`大米→白米`、`蒜蓉→蒜末`、`黃油→奶油`、`梁→樑` 五條；新規則在本包既有命中 15 鍵，只動 CH。
- **`IGUI_ItemCat_Misc` 改中性文案「其他」**：多 owner 共用鍵，Better Sorting 作一般雜項（實測其 `BaseCategories.lua` 指派 21 件雜物）、武器 mod 4 家作「武器配件雜項」。JSON 全域表無法條件式生效，取兩邊皆成立的寫法。
- **WolfBond 2 鍵停止出貨**：Workshop 端點搜尋、本機訂閱庫全掃、`en_corpus_hashes` 三處皆無此 mod，依裁決登記 `unshipped_keys.json`。
- **AmmoLootDrop 兩則 tooltip 標點改半形**，對齊 Sandbox corpus 慣例（3,172 半形 vs 106 全形）。
- 清理 12 條失效登記（dist 零變動實證，出貨不受影響）；補登 13 個已審鍵、還原 ETW en 錨點 provenance。
- `tracker` sync issue 內文的版本樹改由 `snapshot.json` 帶入，不再寫死。

### Notes

- **出貨鍵數 95,576 → 96,889（+1,313）**：ItemName 裸鍵補齊為主要來源，另含受困鍵救回與本次兩個新模組的 283 鍵。
- **支援 MOD 481 → 483 個。**
- **有效覆蓋率 70,449 / 71,155（99.0%）**，上版 98.9%。零覆蓋 mod 0 個。剩餘 706 個缺口中 406 個集中於單一 mod（`3414697768`，46.6%），為上游新增字串，列為下一輪補譯目標。
- 驗證：build 綠、`verify_dist` **14/14 PASS**（不帶 `--allow-missing-as1`）、冪等雙跑零 diff（173 檔）、`manifest --check` 同步、`lint_ch` 棘輪 [A][B][C][E][F] 全 0、`--cn-diff v42.20.2-1.11.0` 待複核 0、9 支回歸測試全過。
- **`scripts/test_*.py` 仍非自動 gate**：repo 無 CI 執行它們（唯一 workflow 只跑 `tracker.py`），全靠收尾驗證階段人工跑。要讓它真的攔得住漏跑，得另外接 CI——列為獨立工作包。

## [42.20.2-1.11.0] - 2026-08-10

### 玩家摘要

> 本節為 Workshop 更新註記用的白話版；以下各節為維護者向的技術細節。

- **修正：本包會擅自改掉「原版」物品名稱與介面文字。** 感謝玩家回報——即使沒有訂閱任何槍械替換 MOD，原版的 JS-2000 霰彈槍也會被改名成「雷明頓M870霰彈槍」。這類問題共 **328 處**，除了槍械，還包括原版的紅酒被寫成「夏多內白葡萄酒」、4 倍瞄準鏡被寫成「8 倍」、抗生素的說明被換成完全不同的內容。這些原版文字現在一律交還給遊戲本體的官方中文，本包不再插手。
- **請留意這個取捨**：如果你**有**訂閱 Firearms、Vanilla Firearms Expansion 這類會重製原版槍的 MOD，之後這些槍會顯示原版名稱（JS-2000），而不是 MOD 的真實槍名。遊戲的翻譯機制無法做到「裝了才生效」，兩者只能擇一；要兼顧的話得另外拆一個獨立子包，之後再評估。
- **上游停止支援的模組，本包繼續翻譯。** 這次同步時，如一漢化組移除了 Burd's Survival Journals、Printer3D、Hanksie's Musical Wonders 等模組的譯文，本包把這些譯文接手保留，玩家端沒有任何中文消失。支援模組數維持 **481 個**。
- **同步上游時擋下一批會讓數字變亂碼的寫法。** 上游這次調整了文字格式，若原樣採用，部分提示會把數字顯示成字面的「%1」（例如「攻擊速度: %1」）。本包已自動還原，玩家不會遇到。

### Fixed

- **本包會改掉遊戲原版的物品名與文字（328 鍵）—— 已全數停止出貨**。玩家回報：未安裝任何槍械替換 MOD，原版 JS-2000 霰彈槍卻顯示為「雷明頓M870霰彈槍」，移除本包即恢復（[Workshop 留言](https://steamcommunity.com/sharedfiles/filedetails/?id=3765907717)）。
  成因是 PZ 的 `Translator.tryFillMapFromFile()` 把**每個 mod 的 Translate 檔併進同一張全域字串表**、後載入者覆寫前者——沒有「只在某 MOD 啟用時生效」這回事。As1 上游收錄了 Firearms（`2256623447`）、Vanilla Firearms Expansion（`3611718925`）等**重製原版槍**的 MOD 譯文，這些 MOD 直接改寫 `ItemName.json|Base.Shotgun` 等本體鍵，於是全體玩家的原版物品跟著被改名。
  影響範圍不只槍械：槍械／彈藥／配件 66 鍵、食物酒類鞋襪 74 鍵、UI／Tooltip／ContextMenu／Fluids 等 188 鍵。其中對原版玩家明確有害者包括 `Base.Wine2`（Red Wine）→「夏多內**白**葡萄酒」、`Base.x4Scope`（x4）→「LVPO **8倍**」、`Tooltip_Antibiotics`（抗傷口感染、不能防變殭屍）→「用於製作抗生素.」。
  另有 10 鍵連來源 MOD 自己的現行英文都對不上（`Base.Shotgun` 上游現為 Mossberg 500、`Base.x4Scope` 現為 ACOG 4x32），即使裝了該 MOD 也是錯的。
- **這些原版字串現在改由遊戲本體／本體翻譯包提供**，本包不再插手。副作用：有裝上述槍械 MOD 的玩家會看到原版名稱而非 MOD 重製名——JSON 全域表無法做條件式生效，要兩邊兼顧只能拆成依賴該 MOD 的獨立翻譯子包，尚未實作。

### Added

- **`build_mod.suppress_vanilla()` 出貨抑制**：所有 gate 之後、寫出之前，把命中本體鍵名基準的 (檔,鍵) 自 CN/CH 對稱剔除。真相層不動——As1 CN 仍是 canonical import、`sources/ch` corpus 仍是人工真相，抑制只發生在出貨那一步。要刻意保留某個覆寫須登記 `vanilla_keys.json` 的 `keep`（帶出貨值錨點，值一改豁免即失效）。
- **`verify_dist [12]` 自 report-only 升為 blocking**：獨立重掃 dist CN/CH，殘留任何非 `keep` 的本體同名鍵即 FAIL。原本 As1 lane 只出 WARN、且其中 327 鍵全登記在 `as1_overlap_known` 裡當通行證（另 1 鍵走 own lane 的 `allowlist`），等於防線完全靜音——這正是問題存在近半年沒被攔下的原因。
- **`scripts/extract_vanilla_keys.py`**：自本機 PZ 安裝重生本體鍵名基準，新增**檔域**欄位 `scoped_keys`（`{檔名:[鍵]}`）。舊基準只有扁平裸鍵集，無法區分「同名鍵在不同檔案不互撞」，故無法拿來做精確抑制。**遊戲大版本更新後必跑。**
- **`scripts/test_vanilla_suppress.py`** 回歸測試 9 組：對稱剔除、`keep` 豁免與錨點漂移（build 與 oracle 各驗一次）、基準殘缺 fail-closed（含「整個 bucket 消失」與「同鍵灌水」兩種假 fail-closed）、dist 洩漏偵測、檔域語意不退化成跨檔比對、[13] 不把抑制鍵誤報成受困鍵。

### Changed

- 退役 `own_translations.json` 的 `IG_UI.json|IGUI_SearchMode_Categories_WildHerbs`（en/ch/cn 與官方逐字相同，抑制後永遠不會落地）及其 `allowlist` 豁免登記。
- `sources/vanilla_overlap_triage.json` 降為歷史紀錄：出貨抑制後，值層裁決不再決定「要不要出貨」。（該台帳本身也已被證實有誤——`Base.x4Scope` 的裁決是靠 hash 反推「Firearms 改名為 LVPO 系」，取得上游 EN 實文後確認實際是 `ACOG 4x32`。）

### Changed（As1 快照重釘 42.20）

- **`verify_dist [8] As1 來源漂移` 恢復可驗證**，連續兩次發布的盲區關閉。快照 `source_tree` 自 `42.19` 改為 `42.20`——Steam 於 2026-08-05 直接以 `42.20/` 覆蓋 `42.19/` 且 Workshop 不提供舊版下載，被釘的樹永久消失。上游 `42/` 與 `42.20/` 內容逐位元組相同、`version.txt` 同為 v3.11.0；釘 `42.20` 是因 PZ B42 只載入「≤ 遊戲版本的唯一最佳版本資料夾」。
- **同步差異：新增 1、值變更 2,010、移除 5,264，實質文字變更 0。** 2,010 筆值變更全是 `%` 逸出差異——613 筆與我方 sanitize 後等價，1,203 筆把已安全的 `%1`/`%s`/`%.2f` 又逸出一次，194 筆全域 `%`→`%%` 連合法字面 `%%` 都變成 `%%%%`。後兩類照收會讓佔位符變成字面文字（玩家看到「攻擊速度: %1」）。
- **改以機械反向正規化處理，而非 1,397 筆逐鍵登記**：新增 `build_mod.normalize_over_escape()`（`%%`+安全 token → `%`、`%%%%` → `%%`，迭代至定點），於合併後、registry 與錨點快照之前執行；`verify_dist.as1_expectation()` 為獨立實作。兩份實作對 As1 42.20 全量 64,541 值零分歧且冪等，還原後與現行出貨值對 2,010 筆變更全數逐字相同。安全性實證：我方 145,595 個正確值中 `%%` 緊接安全 token 起始者 0 筆、含 `%%%%` 者 0 筆。
- **上游移除的 5,264 鍵依「是否還在用」分流，支援清單零流失（維持 481 個 MOD）**：
  - 2,102 鍵屬 8 個被 As1 整包放棄的模組（Burd's Survival Journals 961、Printer3D 628、Hanksie's Musical Wonders 428、Fred's NVG、Forged by Combat、Military Ponchos 等）→ 改列 own lane 的 `sources/mods/<wid>/`（`origin:"own"`）。放這裡而非 `own_translations.json`，是為了保住 `SUPPORTED_MODS.md` 列名與 `gen-watchlist` 上游監看——只放後者會讓這 8 個模組從兩份清單同時消失。
  - 783 鍵為零星移除 → `own_translations.json`。
  - 2,375 鍵上游查無同名鍵（2,357 屬 `_unsorted`）→ 跟著刪，As1 是在清理作廢鍵。
  - 4 鍵值為 `'  '`（As1 的空白佔位）→ 不再出貨；玩家因此看到英文原文而非一片空白。
- 新增的 1 鍵為上游畸形資料（整行英文被當成鍵名），忠實鏡像進 corpus。
- 登記同步：`ch_review_state` 清 278 條陳舊條目、`as1_overlap_known` 重算為 325 條、`cn_overrides`／`placeholder_exceptions` 共 16 筆 `as1_value` 錨點重錨。`lint_ch` 改為排除出貨抑制鍵——其 [C] 以 dist CN 值查已審台帳，抑制鍵查不到會讓已裁決鍵全數退回待裁決而炸掉棘輪。

### Notes

- **本次為近期首次 `verify_dist` 13 項全 PASS、退出碼 0**（不帶 `--allow-missing-as1`）。build 冪等雙跑零 diff（181 檔）、`verify_mod` 10 PASS、`lint_ch` 棘輪 [A][B][C][E][F] 全 0、`--cn-diff v42.20.2-1.10.0` 待複核 0、6 支測試全過。
- **出貨鍵數 98,276 → 95,576（−2,700）**：vanilla 出貨抑制 321、上游作廢鍵清理 2,375、撞 vanilla 的 own 鍵 4。
- **有效覆蓋率 70,075 / 70,883（98.9%）**。824 個缺口中 **820 個在本次之前即存在**——1.10.0 宣告的 100% 是對當時快照而言，之後上游各模組新增了字串（最大宗：`3414697768` 502 鍵）。本次同步未造成覆蓋率回歸，該缺口列為下一輪補譯目標。
- **`lint_ch [D]` 提示 terminology vendor 與本體不同步**（本體 repo 已更新術語表）。不在棘輪內、不阻斷；重新 vendor 可能帶進新術語而觸發新的 [C] 待裁決，列為獨立工作包。

## [42.20.2-1.10.0] - 2026-08-08

### Added

- **有效翻譯覆蓋率 68.6% → 100%**（69,900 / 69,900 鍵、453 個 mod）。新增約 **29,000 個原創翻譯鍵**，涵蓋 Authentic Z、Sapph's Cooking、Guns93、Emergency TV Channel、PZLinux、Better Traps、BurdJournals 等大型模組的物品名、配方、UI、沙盒選項、電台台詞與劇情文本。所有原創譯文皆對照上游英文原文人工撰寫（繁中台灣用語 + 簡中），非機器轉換。
- **新度量：有效覆蓋率普查（`coverage_survey.py`）**。舊口徑問「這個鍵名我方收了嗎」，新口徑問「**這個鍵在遊戲裡會不會顯示成中文**」——套三道濾網：只算 PZ 實際載入的分支、鍵必須落在前綴路由對應的檔名、排除上游值為空字串的鍵。它揭露了「掛名支援但玩家全看英文」的模組，是本次補譯的選材依據。
- **`verify_dist` 新增兩項 gate**：`[13] 檔名可載入性`（有前綴路由的鍵不得只存在於 PZ 不會載入的檔案裡——放錯就永遠取不到，玩家看到鍵名）、`[14] own 層 CN 用字`（擋 `opencc` 抓不到的台灣字形殘留：助詞「著」須寫「着」、「牠」「妳」、直角引號）。
- **補譯管線三支腳本**：`prep_mod_strings.py`（多 mod 有效缺口抽取）、`apply_wf_result.py`（工作流產出落地，內建 null 與截斷兩道防護）、`reanchor_registries.py`（標點正規化後的登記簿錨點重算，非純標點變動一律拒絕重錨）。

### Fixed

- **管線根因：B42 有效分支解析**。PZ Build 42 只載入 `common/` 加上**唯一一個**最佳版本資料夾（`≥42000` 且 `≤` 遊戲版本），模組根目錄的 `media/` 完全不讀。先前的模型同時弄錯兩個方向（把不會載入的根目錄算進來、又漏掉一定會載入的 `common/`），導致選材與覆蓋率統計失真。修正後 `tracker.py` 與各度量腳本共用同一套判定。
- **簡中欄全庫用語稽核，595 鍵**。原創層的簡中欄有 81.2% 是拿繁中跑 `opencc t2s` 生成的，而 t2s **只換字形不換詞彙**——「字是簡體了，但詞還是台灣說法」。以官方遊戲自帶簡中（48,695 值）與 As1 簡中語料（48,874 值）雙重交叉驗證詞頻後，確認 48 條詞對需替換（洋装→连衣裙、连身→连体、运作→运行、烹煮→烹饪、点选→点击、后车厢→后备箱、针筒→注射器、抱著→抱着…），另 32 條判定為誤報（预设值 EN 實為 preset 非 default、弹夹 EN 實為 Clip 非 Magazine、安全帽為大陸國標用詞…）。
- **標點正規化**。判準是「有沒有跟隨上游」而非「該不該用半形」：繁中全形標點 1,551 鍵中 1,391 鍵跟隨上游故不動，只修我方偏離的 111 鍵 + 原創層 104 欄；半形標點後缺空格同理只修 8 鍵 + 原創層 373 欄。頓號「、」與省略號「…」依既有規則保留。
- **131 個從未生效的譯文歸位**。上游把鍵放在 PZ 不會載入的檔名（`UI_EN.json`、`Compendium.json` 等），我方忠實鏡像後那些譯文從未顯示過。
- **63 個 CI 新增鍵補譯**，並經 Claude 與 codex 雙邊獨立 review 修正詞級殘留與同模組用詞不一致。

### Changed

- **移除 395 個真孤兒鍵**（連 PZ 會載入的分支都沒出現）。過程中修正了「孤兒」的判準：上游沒有執行期英文定義**不代表**我方譯文無效——`Translator` 是按鍵查譯文的。若照原判準會誤刪 735 個正在生效的翻譯。
- **新增 report-only 偵測：上游改名遺留的作廢鍵**（1,550 鍵 / 36 個模組）。這些鍵落在正確檔名、卻已被上游改名，照樣出貨但玩家永遠看不到。不自動移除——清除須配合 As1 快照重釘。

### Notes

- **`versionMin` 維持 42.20.1**；PZ 版本標示跟進 42.20.2（本體翻譯包已確認 42.20.2 零缺鍵相容）。
- **`verify_dist [8] As1 來源漂移` 本次為 SKIP**，因 Steam 已用 `42.20` 覆蓋快照所釘的 `42.19` 資料夾（舊版無法重新下載）。該項的目的是偵測 As1 上游漂移，本次改以**人工逐鍵重算比對**替代並記錄結論：As1 `42.20` 樹相對我方現況為 **0 筆實質內容變動**、1,332 筆過度逸出（`%1`→`%%1`、`%s`→`%%s`，會使佔位符顯示成字面文字）、678 筆正確的裸 `%` 逸出（我方早已完成）、移除 6,069 鍵、另有 1 個格式損壞的鍵名。**結論：不予採納**，重釘會淨損覆蓋率並匯入損壞的佔位符。其餘 12 項 gate 全數 PASS。

## [42.20.1-1.9.0] - 2026-08-05

### Fixed

- **PZ 42.20.1 主選單黑畫面（崩潰級）**：42.20.1 起 `zombie.core.Translator` 於載入期對每個譯值跑 `formatFixer`（只認 `%%` 與 `%1`-`%9`），`getText` 再對結果強制跑 `String.formatted(args)` 且**僅捕捉 `MissingFormatArgumentException`**——文法外的 `%`（裸 `%`、`%i`、`%F`…）會拋 `UnknownFormatConversionException` 炸穿而使主選單黑畫面。本包 CH/CN 各 856 個值含此類序列（含 `Compendium`、`ContextMenu`、`IG_UI`、`Tooltip`、`UI` 等檔）。管線新增 `sanitize_format_tokens` 全量逸出，**dist 殘留歸零**。
- **`%N$s` 顯示損壞**：`formatFixer` 對 `%N` 一律補 `$s`，值裡若已寫 Java 完整位置參數會疊成 `%1$s$s`，輸出變成「值$s」。`$s` 不含 `%`，任何以 `%` 為起點的掃描都看不到它，故另設獨立檢查。`own_translations` 的 `UI_BurdJournals_BatchAlreadyClaimedSummary` 已改為 PZ 簡寫 `%1/%2`。
- **上游 EN 致死鍵 fallback 補洞 5 鍵**：第三方 mod 自帶 EN 若仍是裸 `%`（作者未更新），我方未收錄的鍵會 fallback 到 EN 而崩潰。補譯 ETW 草藥雜誌計數器 2 鍵、Somewhat Traits 變異性 2 鍵（新增出貨檔 `Sandbox_EN.json` 的原創層 entry）、Dead Man's Dossier `Tooltip_DMD_MilitaryPage1` 1 鍵（上游已將鍵名 `Lore_`→`Tooltip_`，沿用 As1 既有審定譯文）。**未覆蓋致死鍵歸零。**

### Added

- **`sanitize_format_tokens`（build 期，機械冪等）**：CN 真相為 As1 快照不可手改，故於合併後全量逸出；安全 token 為 `%%`／`%1`-`%9`／`%s`／`%d`／`%.Nf`／`%+.Nf`。**printf 刻意不轉編號**（與本體 repo 修法分歧）——第三方 mod 靠 Lua `string.format(getText(...))` 消費，轉編號會被 `formatFixer` 改寫成 `%N$s` 反而炸掉 mod 端。
- **format 安全 gate（build）**：CH corpus／`own_translations` 的 `ch`＋`cn`／`origin=own` 的 mod CN 三個人工真相層不受 build 期機轉保護，值須直寫安全形式，不安全即擋並附建議值。
- **`lint_ch.py` [F] 棘輪**：CH 真相層危險 `%` 序列雷達，基線 0，讓問題在翻譯工作流早期可見。
- **`scripts/test_format_tokens.py`**：sanitize 語意與冪等、builder／oracle／lint 三份獨立實作等價、verify [4] 必炸殘留與 `%N$` 殘留、multiset 的 `%%` 兩分法、build format gate 三真相層掃描域。

### Changed

- **`versionMin` 42.19.0 → 42.20.1（只支援最新穩定版）**：42.20.0 及更早無載入期 `formatFixer`，且**無參** `getText(desc)` 不跑 `.formatted()`，逸出後的 696 個純字面百分號值在舊版會顯示雙百分號。42.20.1 不修＝黑畫面完全不能玩，嚴重度不對等，故跟上最新版、不保留舊版相容分支。README／STEAM_DESCRIPTION／workshop.txt 的「支援版本」同步為 Build 42.20.1+。
- **verify [1] CN parity 改對 `sanitize(As1 原值/登記值)` 核對**；[4] dist 兩側殘留文法外 `%` 一律 FAIL。「有效 CN 值」口徑自此指 sanitize 後的出貨值（registry 背書 gate、`ch_review_state` hash、`--cn-diff` 皆同）。
- **token multiset 的 `%%` 兩分法**：獨立字面 `%%` 排除比對（容許「50%」譯成「百分之五十」）；**緊接佔位符的 `%%`（`%1%%`、`%.1f%%`）整體吸收為單一 token 並強制 CN/CH 配對**——它是數值的單位，CH 漏掉即「數值單位消失」而鍵集與 parity 全無感（現況 284 處全一致）。

### Notes

- **一次性遷移 967 值**：CH corpus 747、`own_translations` 的 ch/cn 218、`origin=own` 的 mod CN 2；`ch_review_state` 同步遷移 117 個 hash（口徑改為 sanitize 後出貨值）。全部值皆精確等於 `sanitize(舊值)`，零鍵集／結構／非目標欄位漂移。
- **反編譯確證**：修法依據取自 42.20.1 快照的 `Translator.formatFixer`／`reportMissingArgumentsFromPastAbuse`／`fixupArgs`，並逐字模擬其 regex 替換驗證推導；42.18／42.19／42.20.0 交叉比對確認 `formatFixer` 為 42.20.1 新增。
- **已知現象（非缺陷）**：42.20.1 對「無參 `getText` ＋ 值含 printf token」會記一行 Warning 後原文返還，這正是 mod 端 `string.format` 能運作的機制；逸出 printf 反而會炸掉消費端。
- gate 全綠：build 冪等雙跑零 diff（171 檔）、`lint_ch` [A]0 [B]0 [C]0 [E]0 [F]0、`cn-diff` 對 v42.19.0-1.8.0 待複核 0、dist 必炸殘留 0 ／ `%N$` 殘留 0。
- **`verify_dist` [1][8] 無法直跑**：`sources/snapshot.json` 釘定的 As1 42.19 本機樹已被 Steam 更新覆蓋（追蹤器 issue #30「待同步」）。改以版控中的 `sources/mods/*/CN` 建代理樹跑 [1] 完整比對邏輯（先驗 As1 lane 對 HEAD 零變更才成立），PASS：80 檔／69,804 鍵，與 snapshot 釘定的 `as1_filekeys` 一致。**代理不替代 [8] 的來源 provenance**，該盲區待 As1 同步後消除；其餘 [2][3][4][6][7][9][10][11][12] 全 PASS 零 WARN。
- Claude 四 lane 與 codex 六輪 review 獨立審查後收斂至 APPROVE。codex 抓出四項本地未見的缺陷：`%1$s` 三份實作共同漏檢、`\d` 為 Unicode-aware 使 `%.١f` 誤判為安全（JDK 拋 `UnknownFormatConversionException`）、sanitize 用全域 `re.sub` 會穿透字面 `%%`、以及**修了 sanitize 卻漏修 verify 殘留檢查**的同源第二落點。另修 positional regex 的 flags/width 重疊造成的 O(N²) 回溯（N=4000 由 0.162s 降至 0.0007s）。
- 順手清償：`SUPPORTED_MODS.md` 的 Better Safehouse 鍵數 116→121——`55e8608` 改了該 mod 的 CN 鍵數卻漏跑 `build_mod.py manifest`（AGENTS.md 列為「gate 管不到、漏做即靜默失守」的例行動作），本次重跑補正。
- 已知未關缺口：ETW／Somewhat Traits／Dead Man's Dossier 另有 103／127／60 個**非致死**缺翻譯鍵（顯示英文但不崩潰），屬獨立的覆蓋率補完任務。

## [42.19.0-1.8.0] - 2026-08-04

### Added

- **damnlib（that DAMN Library, 3171167894）script 物品名 196 鍵**——玩家回報「Small Modern Roofrack」在安裝選單與物品欄顯示英文、tooltip 直接顯示鍵名 `Tooltip_item_damnRoofrack`。根因是 damnlib 把物品名寫死在 script 的 `DisplayName`，自帶 `Translate/EN` 只有 Fluids/IG_UI/Recipes/Sandbox/Tooltip 五類、**沒有 ItemName.json**，As1 因此抓不到：208 個 script 物品僅覆蓋 9。配方名有翻是因為它走 `Recipes.json` 的另一個 map，故出現「配方有名字、物品沒名字」。譯名鍵為裸 `module.item`（`Translator.java` 的 JSON loader 不補 `ItemName_` 前綴，與 vanilla ItemName.json 5137 鍵格式一致）。略過 4 個明示不可生成的 dummy/debug。**連帶效果：本機 Workshop 有 49 個 mod 直接相依 damnlib 且全部引用這批 library 物品，修一次全部受惠。**
- **`Tooltip_item_damnRoofrack` 1 鍵**：上游 bug——script 宣告了此鍵但 damnlib 自己的 EN Tooltip.json（43 鍵）未定義，42.0／42.13 亦同，故任何語言都顯示原始鍵名。四種車頂行李架共用，本包定義 CH/CN 即生效；`en` 欄由本包擬定，tracker 會列為查無上游錨點的偵測盲區（report-only）。
- **三 MOD 上游追蹤缺口補譯 81 鍵**（追蹤器 issue #28／#29／#31 收尾）：AutoMechanics 11、WayMoreCars 57、myspatialrefuge 13。除 issue 報的 delta 外，一併清償同批 MOD 的既有覆蓋缺口（WayMoreCars 的 CarBomb 族、TireStack 族、`CraftVanillaVehicle*` 車窗／輪胎配方 33 鍵等）。
- **新增出貨檔 `RecipeGroups.json`**（CH/CN）：本包首次輸出該檔名，格式比照原版扁平物件。

### Fixed

- **標準／重型部件譯名相同致物品欄無法辨認**（codex review 抓出）：`80chevyCKseriesTire1/2`、`90chevyCKseriesTire1/2`、`86chevyCUCVTire1/2`、`85gmBbodyTire3/4`、`85gmBbodyWagonBumperRear1/2` 五組上游 DisplayName 本就相同，照譯即複製歧義；依各自配方（`製作雪佛蘭CUCV標準/重型輪胎` 等）正名，連帶修正 3 個既有鍵。
- **譯名未對齊該物品自己的既有配方名**：福特維多利亞皇冠→福特CVPI（語料 34:19）、旅行版→旅行車（93:9）、多用途→通用貨箱（4:0）、輪胎N型→N型輪胎、軍用水桶→軍用儲水桶、龐蒂亞克拉力I/II→Rally I/II、分體式→分離式（3:1）。CN 側另修 `后车厢盖`→`后备箱盖`（110:3）、`(100 入)`→`(100个装)`（「入」為台灣包裝用語）。
- **車窗物品名去歧義**：`CraftVanillaVehicle{Front,Rear}Window*` 12 個配方由「車前窗／車後窗」改為**前側車窗／後側車窗**。遊戲資料實證為側窗——`part WindowFrontLeft { area = SeatFrontLeft }`、`item FrontWindow1 { Icon = SideWindow }`（Windshield 用 `CarWindshield`）；避開「車前窗」被讀成擋風玻璃、「後車窗」在台灣車廠手冊常指後擋玻璃的雙重歧義，並符合公路局隔熱紙法規「前側窗／後側窗」分類。本體包 MinidoracatLangFor42 同批對齊（`Base.{Front,Rear}Window{1,2,3}`）。
- **`ExtractSteelFrom{LargePlus,VeryLarge}Item` 錨定錯誤**：原譯「從…中提取鋼材」錨到鐵製品族的 outlier，改為鋼製品族的「廢鋼熔鑄 (…)」。
- **AutoMechanics 沙盒選項標題去歧義**：`跳過無經驗部件`→`跳過不給經驗的部件`（原偏正結構易讀成「部件本身沒有經驗」）。
- **CH 真相層存量術語債清償 62 鍵**（新 gate 導入後首次全量清償）：異體字 9（污→汙、祕→秘）、select 逐鍵裁決 3 修 33 keep、replace 規則 13 修（點擊→點選、磁盤→磁碟、查看→檢視、信號→訊號 等），regex 誤中 4 鍵登記 `lint_exemptions`（含羈絆義的「聯繫」、「彩色光＋標記」）。

### Changed

- **`lint_ch.py` 棘輪涵蓋 `own_translations.json` 的 `ch` 欄**：原本只掃 `sources/ch` corpus，3,262 個原創翻譯值完全在 gate 之外。兩層 (檔名|鍵) 命名空間互斥（實測撞名 0），故 `lint_exemptions` 與 `ch_review_state` 的查找對兩層一致適用；撞名時 fail-loud。報告加 `[own]` 標記指明該回哪層修。
- **`lint_ch.py` 新增 [E] 掃 `terminology.json` 的 `mode=replace` 規則**：129 條已核准規則（literal 79＋regex 50）原本**兩個真相層都不掃**——[A] 掃的是 `opencc_fixes` 的 post_fixes、[C] 只掃 `mode=select` 且 literal 型。CH 凍結後本 repo 不跑 terminology 引擎，[E] 是這些規則唯一的落地檢查。誤中走 `lint_exemptions`（帶 `ch_value` 錨點），不吃 `ch_review_state`——replace 語意為一律替換，開放台帳 keep 等於留後門。

### Notes

- 兩道新 gate 於 damnlib 批次首次生效：[C] 擋下「極致性能車指南」，依規則 note「汽車性能；系統效能」判 keep 並登記台帳。
- gate 接線以注入真違規實測（非只看綠燈）：[A]/[B]/[C]/[E] 正向皆 exit 1、豁免生效不報、`ch_value` 錨點失效重新計入、未知 pattern 判 schema error、真相層重疊 fail-loud。過程中抓到 [E] 初版把類別加進「總計」顯示卻漏加進棘輪判定的靜默失守。
- gate 全綠：build 冪等雙跑零 diff（171 檔）、verify_dist 11/11 PASS（原創鍵 4,258）、lint_ch [A]0 [B]0 [C]0 [E]0、cn-diff 對 v42.19.0-1.7.0 待複核 0。
- Claude 與 codex 雙邊 review 獨立審查；codex 對 damnlib 批次判 REQUEST CHANGES 並抓出標準／重型同名缺陷，修正後全數落地（駁回 1 項：座椅骨架→框架，語料 3:2 與 `Tooltip_item_damnSeatFrame` 皆站骨架）。
- 已知未關缺口：全包尚有約 1,950 個 script `DisplayName` 未覆蓋（跨 60 個 mod，同 damnlib 根因），其中 199 個上游寫死的是簡體字、41 個為 SFX/debug、57 個 DisplayName 等於 item id。

## [42.19.0-1.7.0] - 2026-08-04

### Added

- **新增 6 個 MOD 的翻譯支援，合計 224 鍵**（玩家於正式服回報未翻譯字串後逐案核准收錄）：
  - **CleanUI**（3437629766）53 鍵〔原創翻譯〕：取代原版物品欄／戰利品面板的 UI mod，玩家回報的「Equipped Items」即出自此包。上游打包六個版本分支（鍵數 49/50/50/53/53/53），PZ 42.20 只載入 42.19，舊三分支僅有 legacy `UI_EN.txt` 不生效。
  - **Neat Crafting**（3502080466）69 鍵〔原創翻譯〕：取代整個製作視窗側欄，開製作介面即全螢幕英文。排除已由 As1 出貨的 `IGUI_XP_NC_SetPanelMinSize_tooltip` 不重複收。
  - **Mysterious Vehicle Claim Key**（3643840023）87 鍵〔原創翻譯〕：多人服車輛認領系統。claim/unclaim 定名「認領／取消認領」（收錄前 corpus 認領 72 : 登記 32，AVCS 為孤例；MVCK 實際建立所有權，「認領」較精確）。
  - **Nepenthe's Dismantle Any Car**（3428369137）11 鍵、**Craft Propane**（3634065654）3 鍵、**小型皮革合併**（3576417449）1 鍵〔皆原創翻譯〕。
- **既有支援 MOD 補譯 52 鍵**入 own_translations：
  - **KI5 車輛輪胎 32 鍵＋W900 配方 2 鍵**：`Convert_KI5Tire_To_Vanilla` 的所需物品欄依 `rSemiTruck_KI5_TireConvert.lua` 的 `Tire2`/`Offroad2` 規則做版本夾感知掃描，實為 32 個 fullType 全缺（來源 20 個 mod 皆已支援），非表面可見的 1～2 鍵。
  - **製作分類 16 鍵**：`IGUI_CraftCategory_*` 供 Neat 家族側欄（查找鏈 `UI_CraftCat_` → `IGUI_CraftCategory_` → `IGUI_perks_` → `ContextMenu_`）、`IGUI_CraftingCategories_*` 供原版製作 UI（`ISWidgetRecipeCategories.lua` 走 `getText` 無 fallback，查不到會顯示原始鍵名）。兩組譯名逐字一致，避免同一分類在兩種 UI 下顯示不同名稱。注意 `MetalWorking`（大寫 W）與本體 `Metalworking` 是不同鍵，其唯一 consumer 為 Craft Propane，故隨該 mod 走 own lane。
  - Bag Upgrade Plus 缺名 2 鍵（`SchoolbagPlus` 上游連 EN DisplayName 都未定義、`Fluid_Container_HydrationBackpackPlus` 上游無 `Fluids.json`）、School's Out 過膝襪 2 鍵。

### Fixed

- **繁中既有債 5 鍵**：`Base.SheetSlingBagPlus` 布**制**→布**製**（簡體殘留漏網）；Hydration 家族 4 鍵「水合背包」→「水袋背包」（原為 Hydration 直譯，與本體譯名不一致）。CN 側受 As1 逐字 parity gate 限制維持原文，語意類更新待上游同步帶入。
- **`IGUI_CraftingCategories_Mechanics` 錯置**：鍵名前綴與檔名不符（放在 `ContextMenu.json` 桶），搬回 `IG_UI.json`——原位置的鍵遊戲永遠查不到。

### Changed

- **製作分類 `UI_CraftCat_*` 譯名一律跟隨 Neat Building 自帶繁中**：本包載入順序在 mod 之後會覆蓋 mod 自帶值，若採本體 `IGUI_perks_*` 那套會造成 18 個分類名對玩家無預警變動（護甲→防具、金工→金屬加工、裁縫→縫紉，且 Survival/Survivalist 整組對調）。副作用：Neat 家族日後自行修訂繁中會被本包壓住，屬 JSON 全量共存模型的固有取捨。

### Notes

- 玩家回報以正式服伺服器設定檔的 `WorkshopItems` 為查證基準（本地訂閱清單含大量未上服 mod），相關 runbook 已補入 AGENTS.md。
- 回報中的鑰匙圈英文（`IGUI_KeyRingName`）為遊戲本體鍵，受 vanilla 覆寫鐵律限制不由本包處理，已於本體翻譯包解決。
- gate 全綠：build 冪等雙跑零 diff、verify_dist 11/11 PASS、lint_ch 0/0/0、cn-diff 對 v42.19.0-1.6.0 待複核 0。
- Claude 與 codex 雙邊 review-plus 獨立審查；codex 四輪複核後 APPROVE（期間修正 provenance lane 分流 1 處、metadata 事實記載 5 處）。

## [42.19.0-1.6.0] - 2026-08-03

### Added

- **ModernFirearmsSystem（3633421539）全量補譯 1,276 鍵**入 own_translations（含 BackpackSystem／BladesmithSystem 子 mod；IG_UI 110、ItemName 771、Tooltip 165、Sandbox 154、Recipes 55、UI 11、ContextMenu 10）；5 個 vanilla 碰撞鍵依收錄鐵律排除。

### Fixed

- **共用 IGUI 鍵三裁決**（Steam 玩家回報查證屬實）：`IGUI_Barrel` 燃料桶→槍管（9 owner 中 8 個槍械 mod 多數裁決）、`IGUI_Barrel_Shroud` 補「護木/护木」、`IGUI_Barrels`→個桶（GenPlus 計數量詞）、`IGUI_ItemCat_Stock` 高湯→武器配件-槍托。MFS 雙邊 review findings 全數修正：13 組品牌譯名 ItemName↔Sandbox 統一、16 筆 `_Large` 誤標修正、55 鍵全形標點半形化、術語對齊。
- **Tooltip 114 鍵 `<LINE>`→`<br>` 正規化**（本體側玩家回報藥品描述出現字面 `<LINE>`，未裝 EHR 亦可見——本包 Tooltip.json 全域載入）：上游譯文（As1＋EHR 自帶 CN）把僅 richText 面板認得的 `<LINE>` 用在物品欄純文字 tooltip；統一改為官方慣例 `<br>`（兩種消費端皆安全）。`<RGB:>` 標記分治：EHR 藥品 28 鍵刪除（純文字端原樣顯示）、CSR 躲藏系 8 鍵＋Inventions 1 鍵保留（richText 端）。CN 走 cn_overrides +114 條（含 as1_value 錨點）、CH 直改 corpus、ch_review_state 114 鍵背書。

### Notes

- 本次與本體 MOD `42.20.0-1.14.1` 同日發布（本體側同批修復：休息選單父項 Moveables 5 鍵、技能描述 tooltip、crafting entity 名稱等，詳見本體 CHANGELOG）。
- gate 全綠：build 冪等雙跑零 diff、verify_dist 11/11 PASS、lint_ch 0/0/0、cn-diff 對 v42.19.0-1.5.0 待複核 0。

## [42.19.0-1.5.0] - 2026-08-02

### Added

- **新增 4 個 MOD 的翻譯支援，合計 1,195 鍵**：
  - **Burd's Survival Journals**（3639628777）733 鍵：上游 7/30 改版後 As1 尚未跟上的詛咒日記、聖誕日記、Sandbox 選項與 lore 敘事文本。該 MOD 雖自帶 `CH` 目錄，實為簡體複製品（1,675 鍵中 1,311 鍵與 CN 逐字相同），繁中支援名存實亡；EN 依據以 tracker baseline 逐鍵核實（`translate_en` 5,205 筆零 diff）。
  - **Better Safehouse**（3634569678）116 鍵〔原創翻譯〕：SubOwner 副屋主、Expansion 擴建、PrimaryRespawn 主重生點、SidePanel 側邊面板等新功能。As1 已收 114 鍵但全落 `_unsorted`，這 116 鍵上游零翻譯，簡中亦為原創直寫。
  - **B42 Scavenging Skill**（3645462965）62 鍵〔原創翻譯，issue #27〕：技能名定名「拾荒」（本體二字體例；「搜尋」已被 B42 `PlantScavenging` 佔用）、0–10 級發現機率與額外戰利品沙盒選項、5 本雙關書名技能書（意譯保留趣味）。
  - **Mirage Wardrobe 幻裝衣櫥**（3770186452）284 鍵〔原創翻譯〕：多人連線換裝模組，CH 經四視角評審＋對抗覆核，40 筆鍵級覆寫（套用家族 21 鍵、`Worn/carried` 與 vertical panning 漏譯修復等）。
- **既有 MOD 補譯 419 鍵**：More Traits 整塊動態特徵沙盒選項 167 鍵（申請者回報查證屬實）、追蹤器「可能過時」issue 清償批 13 個 MOD 共 252 鍵（#10–#26，含 TchernoLib 版本目錄遮蔽的雙鍵、chevy 車輛部件）。
- **vanilla 覆寫治理**：As1 lane 與遊戲本體同名的 331 鍵全量裁決並建立逐鍵台帳（`sources/vanilla_overlap_triage.json`，含 verdict／值錨點／裁決理由），`verify_dist.py` 新增 [12] vanilla 鍵碰撞 gate——原創翻譯鍵不得撞本體鍵名（會影響未安裝該 MOD 的使用者）。
- **`sources/en/` 上游英文全文落地**：追蹤器偵測到變更時順手保存該 MOD 的完整 EN 語料，日後補譯不必再依賴 steamcmd 下載（該途徑有整日全面失敗的實例）。
- **品質防線**：`verify_dist.py --cn-diff <ref>` 出口匯流複核（列出 CN 值變動而繁中真相層未跟進、亦無審查背書的鍵）、`lint_ch.py` 零基線棘輪（品質單調劣化即非零退出）。

### Changed

- **CH 斷絕 OpenCC 機轉，遷移為人工真相 corpus**（架構級單向門）：繁中不再由簡中機器轉換再生，`sources/ch/`（83 檔 70,201 鍵）成為唯一真相，自現行輸出**零 diff 凍結**（dist 逐 byte 不變，僅更換生成機制）。build 降為純合併＋五道 gate（corpus 鍵集、同步 worklist、registry 背書、CH 值層、placeholder）；`ch_overrides.json` 退役（6,537 筆凍入 corpus）、`opencc_fixes.json` 降級為 lint 資料。
- **CN 修正層加上游值錨點**：`cn_overrides.json` 與 `placeholder_exceptions.json` 的登記須帶 `as1_value`，上游若已自行修正會列過時警告，避免 override 靜默永久壓過。
- **追蹤器偵測層強化**（extractor schema 4→5）：改掃全部 `media/scripts` 目錄（實測 99/324 個 MOD 有多目錄、長期部分失明）、物品區塊獨立抽取 `DisplayName`。
- **`ch_value_gate` 接回 build 主流程**：該防線（阻斷簡體專用字殘留與「CN 有文而 CH 空值」）自定義以來唯一呼叫者是單元測試，主流程從未呼叫——文件描述的 gate 實際斷開。斷絕 OpenCC 後 CH 轉為純人工維護，此防線正是為該風險而設。

### Fixed

- **譯名一致性債務清償 118 鍵**：技能名全面對齊遊戲本體面板顯示名 84 鍵（健身→體格、機械→技工、電氣技能→電工、裁縫→縫紉、長/短鈍器→長/短棍、金屬加工→金工，並保護「健身狂」等特質名與「機械師」等職業名不誤傷）；Absorb 語意族統一「領悟」18 鍵——該 MOD 的 Learn 與 Absorb 是不同動作，舊譯與「學習」撞名、「掌握」又與 already-known 撞名，同面板並存四種說法；深傷口、Tarp/Burlap 等統一。
- **審查債首批償還**：310 鍵逐項語境裁決，修正 34 鍵（質量→品質、計算機→電腦、型別→類型、運行→執行、添加→新增等），305 鍵登記已審台帳；合法語境（開罐頭、遠程武器、用戶端等）不誤殺。
- **vanilla 覆寫有害項 16 鍵**：繁中 11 鍵落 corpus（取消→否、彈匣誤譯雜誌、10倍→八倍鏡、雕刻蝙蝠→球棒等），簡中 16 筆走 `cn_overrides` 回填本體官方值。
- **全庫台灣用語 sweep**：四族用語 270 處逐項分類＋對抗覆核，46 筆語境例外覆寫；字典新增 9 條規則（擴充套件→擴展、全域性→全域、聯機→連線、只讀→唯讀、丟失→遺失等 s2twp 誤轉與在地化）。
- **上游機翻繼承的簡中錯譯**：Burd's 敘事文本 5 筆（crossed the lake→過馬路、red envelope→紅包、the notes→音符、three houses down→三棟房子）——根因是「簡中以上游為底逐字保留」的規則繼承了上游機翻缺陷，原創翻譯層不受 CN parity 限制，改依英文重譯；另修 4 筆 Sandbox 說明漏譯或多述不存在的「消耗」行為。
- **Cheat Menu Phoenix 誤譯 2 鍵**：`cheat`→「聊天」誤譯，重譯為「未找到套用作弊效果的物品」。
- **追蹤器每日狀態寫入失敗**：零 EN 落地日 `git add` pathspec 導致 rc=128，狀態 commit 寫了出不去；補 `.gitkeep` 佔位並加回歸測試。

### Notes

- **Better Safehouse 補上追蹤盲區**：該 MOD 的鍵因 attribution helper 無法歸屬而全落 `_unsorted`，導致它從未有 `sources/mods/` 目錄、也從未進入每日監看清單（`gen-watchlist` 只讀各 MOD 的 metadata，補跑無效）。本次建立 own-mod 目錄納管，watchlist 475→476。全庫盤點確認此為唯一真盲區——另有 98 個無 MOD 前綴的裸鍵（`Base.*`／`WaterPipes.*`）雖查無錨點，經 script 記錄反查其所屬 5 個 workshop id 均已在監看。

## [42.19.0-1.4.0] - 2026-07-30

### Added

- **`sources/cn_overrides.json` CN 人工修正層**（第五個人工真相檔）：用來修 As1 上游的 CN 錯字／疊字。schema `{"檔名|鍵": {"value", "reason"}}`；`build_mod.py` 在 **CH 再生之前**套用（故修正會一併帶到 CH），優先序低於 placeholder 例外（安全性最後把關）。與 placeholder 例外共用泛化後的 `apply_cn_registry()`。
- **`verify_dist.py` 支援 CN 修正層**：`check_cn_parity()` 的 CN 一致性判定從「**絕對等於 As1 快照**」改為「**除登記例外外等於**」——oracle 效力保留，但每一處偏離都必須逐案登記，未命中的登記會 WARN。在此之前 CN 完全不可修：直接改 `sources/mods/*/CN/` 會被 `split_sources` 從快照重生，而刪掉 parity 檢查等於丟掉一個有效的 oracle。

### Fixed

- **疊字誤植 11 鍵**（`sources/ch_overrides.json`，與本體 `698c262` 同期同流程）：`全身性感染期感染期`、`突然突然切換為疾跑`、`靠近飛飛鏢靶`、`在飛飛鏢靶旁`、`建造一個抽抽水機`、`多車連環連環相撞`、`蓮花花苞花苞`、`玩家每次每次倖存`、`木木吉他琴頸` 等。
- **CN 側疊字與錯字 49 鍵**（上游錯誤，CH 側早已正確）：`制作剑鞘剑鞘`、`启用强制强制兼容模式`、`沙皇福特野马野马车`、`则需要需要一根`、`过滤滤芯`（散在 9 個鍵／含 `*_EN.json`）、`弩箭箭杆`（5 鍵）、`乓乓球游戏光盘`→`乒乓球`（錯字）、`UNSC陆战队大腿护甲甲`、`拖车存储箱箱`、`转换为为`、`伸向了了腰带`、`你已拥有有血契眷属`、`简单单纯`、`每日刷新新阵营`，以及尾端殘留未清的英文碎片 `礼服夹克 (肯塔基州警警监)Dress`（3 鍵）。
- **CN 語意錯誤 4 鍵**（CH/CN 交叉稽核）：`HDF.StrainedSyrup` 原譯「一锅水煮甜菜根」是別的物品、`UI_BetLock_LockpickDoorBobbyPin` 原譯「带开锁工具的门」語意不符、`Sandbox_FruitTreeChop_AutoToGroundWhenHeavy` 與 `IGUI_UW_Radio_Awareness_03` 兩筆與 mod 自帶中文（`*_EN.json`）不一致。
- **逐字空格排版 431 筆**（`sources/ch_overrides.json` 的人工覆寫值，遊戲中字間有縫）：CN 與 `sources/` 來源端本來就 0 筆，故空格全來自 CH 覆寫層。只剝 CJK↔CJK 之間的空白，保留 `%1%`、`%s`、`<...>` 等標記；括號內側一併收緊（`半 紮 髮 髻 ( 黑 )` → `半紮髮髻 (黑)`）。刻意保留 2 筆刻意斷續的台詞（`噗 噼 噼 嗒噼`、`不 不 不…嗬 嗬 嗬`）。

### Changed

- **字典護欄同步本體**（`sources/opencc_fixes.json`）：`圖標→圖示` 加 lookbehind 防吃掉「地圖+標記/標籤」、`里面→裡面` 防吃掉人名「阿里+面前」，並新增預防性規則 `許可權→權限`（本包語料 0 筆命中）。

## [42.19.0-1.3.0] - 2026-07-27

### Added

- **原創翻譯機制（own-mod lane）**：As1 未收錄的 MOD 現可收錄原創翻譯——`origin:"own"` 標記目錄為人工真相，split 重跑保留、verify 以原創 CN 為 oracle 逐鍵核對、tracker 自動監控上游更新、支援清單標示「〔原創翻譯〕」。附負向回歸測試（6 案例）。
- **首個原創翻譯 MOD：Project Gurashi: Megurigaoka**（《學園孤島》地圖模組，Workshop 3318210146）：113 個 mod 自有鍵——日系食品（愛茶瓶裝綠茶、BOSS牌罐裝黑咖啡、奇巧特巧克力、普奇餅乾棒等）、日本文學與漫畫書名（台版譯名：航海王、影子籃球員、FAIRY TAIL 魔導少年、科學超電磁砲、獵人等）、沙盒選項、職業與出生點描述。SurvivorNames 與 vanilla 覆寫鍵依共存原則排除（不影響未安裝該 MOD 的使用者）。
- **MOD 翻譯申請流程**：GitHub issue 模板 `translation-request`——歡迎玩家申請將其他 MOD 加入翻譯（README 有入口與收錄原則）。

### Fixed

- **Evolving Traits World**（issue #6）：上游把 Axpert 特質家族改名 Axeman，沿用既有譯文補齊（斧頭專家家族）；`Blacksmith` 選項名跟上上游改為「鐵匠知識」（繁中；簡中待 As1 同步）。
- **Printer3D**（issue #7）：上游新增拆除功能 5 鍵補譯（拆除3D列印機／回收機、運轉中無法拆除等）。
- **76chevyKseries**（issue #8）：補譯車斗與車頂備胎零件名（貨箱備胎／車頂備胎，As1 未收錄）。

### Changed

- OpenCC 巡檢排除清單與本體字典同步（幹/髮/里 15 項），配合本體新增的跨專案字典一致性檢查。

## [42.19.0-1.2.2] - 2026-07-21

### Changed

- **同步本體泥作家族用語**：貼磚／壁紙 tooltip「抹灰的牆壁」→「已上灰泥的牆壁」（「抹灰」為大陸用語；本體 `PlasterTrowel` 依玩家反饋由「鏝刀」改回「抹刀」後，本包「需要抹刀」自然一致）。

### Fixed

- 「桌布膠」／「用於將桌布貼在牆上」→「**壁紙膠**」／「將**壁紙**貼在牆上」：wallpaper paste 誤譯——台灣「桌布」指桌巾或電腦桌面背景，非牆面壁紙。

## [42.19.0-1.2.1] - 2026-07-20

### Changed

- **manifest 反映 CHIMERA V11 下架**（2026-07-18 偵測）：458 支援／605 mod ID／13 已下架（翻譯保留）。
- **watchlist 重生成**：納入 42.19 同步新增的 8 個模組（464→472，補監看盲區）。
- Steam 描述模組數口徑更新 460+→470+（458 在架＋13 已下架的總翻譯數）。

### Fixed

- **Evolving Traits World（ETW）「Handy」技能需求提示跟上上游 v12.1.0**：繁中「維護+木工」→「木工+雕刻+維護+石工」（技能名採本體官方譯名；簡中依 CN parity 保留 As1 原文待上游同步）。

## [42.19.0-1.2.0] - 2026-07-20

### Added

- **As1 42.19 新包同步**（2026-07-17 快照）：+5,263 鍵／0 刪／0 改，支援模組覆蓋持續擴充。

### Changed

- **全量深度潤色**（一簡對多繁 62 組字表掃描＋6.8 萬鍵逐句審讀，6,900+ 條修正）：誤譯修正（播放器→玩家、倍頻器→出現倍率、砍樹掉落果實、生成地點警察局）、漫畫台版正名（鏈鋸人、死亡筆記本、給不滅的你、殺手阿一、Re:從零開始的異世界生活、哥布林殺手外傳二：鍔鳴的太刀、鋼彈、頑皮豹、魔鬼終結者、阿達一族、瑪利歐）、迴圈→循環（音樂／槍機語境）、字形統一（櫃臺→櫃檯、妖后／王后→後、復雜→複雜、回覆→回復 Recovery 系、糖醋薑、狗娘養的）。
- **118 詞對全域台灣化**（2,076 鍵）：後備箱→後車廂、軟盤→軟碟片、斯巴魯→速霸陸、雅馬哈→山葉、伯萊塔→貝瑞塔、懲教署→矯正署、米德縣→米德郡、鱷梨／牛油果→酪梨、金槍魚→鮪魚、三文魚→鮭魚、蛋黃醬→美乃滋、芝士→起司、酸奶→優酪乳、槍支→槍枝、閾值→門檻值、超時→逾時、貨箱→貨斗、說唱→饒舌、氯菊酯→百滅寧、朗姆酒→蘭姆酒、金酒→琴酒、赤霞珠→卡本內蘇維濃等（葡萄酒／食材／車輛／軟體用語全面在地化）。
- **同步本體術語字典** 50+ 條規則（含語境分岔紀錄：「手柄」因本包 handle 把手語境 13 處不同步、「外掛」譯「模組」）。

### Fixed

- 規則誤傷防護實證修正：「縫合並包扎」lookbehind、「車輛外掛背包」保留、「有限制作」個案；「一起搶劫→一樁」量詞、「計過時→計時過」語序、電腦／右鍵選單／分頁術語（PZLinux／TABAS／TrueMusic 系 MOD）。

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
