# Changelog

所有重要的變更都會記錄在此檔案中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)，版本號遵循 `{PZ版本}-{Mod主版本}.{次版本}.{修訂}` 格式。

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
