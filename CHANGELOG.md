# Changelog

所有重要的變更都會記錄在此檔案中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 `{PZ版本}-{Mod主版本}.{次版本}.{修訂}` 格式。

## [Unreleased]

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

- 玩家回報以正式服 `pzserver.ini` 的 `WorkshopItems` 為查證基準（本地訂閱清單含大量未上服 mod），相關 runbook 已補入 AGENTS.md。
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
