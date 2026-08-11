[h1][B42]繁體簡體模組翻譯 By Minidoracat 如一漢化組 42.20.2-1.12.0[/h1]
[i]2026-08-11[/i]

[h3]• 玩家摘要[/h3]
[list]
[*] [b]954 個物品名第一次真的變成中文。[/b] 這批譯文其實一直都在包裡，但用的是 B41 時代的舊鍵格式（ItemName_模組.物品），B42 的遊戲引擎根本不會去讀它——玩家看到的一直是英文。這次全數改成 B42 讀得到的寫法，涵蓋 3D 列印機、拾荒技能、進階醫療系統、Zomboid Storylines、True Music 隨身聽等模組的物品。
[*] [b]Barrels Expanded 的 41 則提示訊息救回來了——這個連英文版都是壞的。[/b] 該模組把訊息放在 PZ 不會載入的檔案裡，所有語言的玩家看到的都是「UI_BarrEx_TransferRejection_BarrelEmpty」這種鍵名。我們把譯文放進正確的檔案就修好了，等於順手幫上游修了 bug。另外 Super Bulldozer 3 則、Last Cup Coffee 4 則也用同樣方式救回。
[*] [b]新增支援 2 個模組（481 → 483 個）[/b]：Better Sorting（物品分類）與 Gore's SVU4 Core（車輛裝甲改裝，含 4 個子模組）。兩者都是玩家申請的——前者工作坊雖然寫著支援簡中，但那些中文檔是 B41 遺留、B42 完全讀不到；後者則是自帶的中文檔裡面全是英文。
[*] [b]繁中的「喪屍」全部統一成「殭屍」[/b]（130 處）。殭屍是繁中正字，之前混用純屬歷史殘留。簡中維持大陸慣例不動。
[*] [b]支援清單現在會標註「這個模組我們補不了」。[/b] 有些模組把文字放在遊戲翻譯機制取不到的地方，任何翻譯包都無能為力。與其讓玩家訂閱後才發現，不如先寫清楚——目前標註了 Dynamic Trading (w/ NPC) 與 Dynamic Emergency TV Channel 兩個。
[/list]

[h3]✨ Added[/h3]
[list]
[*] [b]收錄 #76 Better Sorting（2313387159）36 鍵、#77 Gore's SVU4 Core（3730070661）247 鍵[/b]，均為 own lane 原創翻譯（origin:"own"）。
[list]
[*] #76 上游中文檔失效原因雙重：檔案留在 [b]mod 根目錄 media/[/b]（loadMod() 只搜 common/ 與版本夾）且為 [b]legacy _CH.txt 格式[/b]（tryFillMapFromFile() 路徑寫死 .json），兩者各自即足以致命；42/ 分支只有 EN 80 鍵，故該 mod 在 B42 是全語言失效而非僅中文。80 鍵零 vanilla 碰撞，44 鍵本包既有覆蓋，補譯 36 鍵。
[*] #77 單一 Workshop 項目含 4 個 mod，上游自帶 CH/CN 八檔逐一比對確認 [b]全為 EN 原文空殼[/b]。排除 9 個 Base.LightBulb* vanilla 覆寫鍵，補 9 個上游未建鍵的 script DisplayName 物品。Recipes.json 裸鍵經 42.20.2 反編譯確證為活鍵（CraftRecipe.java:362 → Translator.getRecipeName() → recipe.get(name) 裸鍵查表）。同系列 3760377708／3742291546 為純模型掛件包不收錄；前者另有 6 句寫死於自訂 UI 的英文，無鍵可譯、已裁決不加 Lua 覆寫。
[/list]
[*] [b]verify_dist [15] ItemName 死鍵閘門[/b]：ItemName_<Module>.<Item> 前綴形在 B42 完全不被讀取（tryFillMapFromFile():362-366 原封 map.put、getItemNameFromFullType():601 只查裸 Module.Item）。對不在 itemname_dead_allowlist.json、又非 vanilla 的死鍵判 FAIL。回歸測試 scripts/test_itemname_dead_keys.py。
[*] [b]sources/unshipped_keys.json 已裁決不出貨登記機制[/b]：適用於「鍵落在 PZ 不載入的檔名、且找不到正確落點」者。真相層照樣保留（_unsorted/CN 是 As1 忠實鏡像，刪掉會讓 tracker layer-B 永遠報差異），抑制只在出貨那一步，與 vanilla 出貨抑制共用 suppressed_pairs()。as1_value 錨點在上游動過時出 warning ＝重查訊號。回歸測試 scripts/test_unshipped_keys.py。
[*] [b]mod_names_zh.json 選配 note 欄位[/b]：標註「上游把文字放在 PZ 翻譯表取不到的位置、任何翻譯包都補不了」的涵蓋範圍例外，渲染於 SUPPORTED_MODS.md 摘要之後（慣例 ⚠️ 起頭）。只登記已查證到機制的個案，不拿覆蓋率比值反推。
[*] [b]scripts/gen_steam_changelog.py[/b]：由 CHANGELOG 版本區塊生成 Workshop 更新註記；CHANGELOG 每版新增「玩家摘要」節作為其來源。
[*] [b]own_translations.json 條目支援選配 _note[/b]，記該鍵的人工裁決理由（build 只驗 en/ch/cn 非空，底線開頭欄位忽略）。
[/list]

[h3]🔧 Fixed[/h3]
[list]
[*] [b]954 個 ItemName_ 前綴死鍵補上對應裸鍵[/b]，分三輪落地並各自修正前一輪的錯誤判斷：
[list]
[*] 首輪 101 鍵。module 名不可猜——靠 steamcmd 下載 11 個 mod、以大括號深度界定 module X { 逐檔解析，才發現 3DPrinter→Printer3D、ScavengerSkill→ScavengingSkill、BetterSafehouse_X→BetterSafehouse.X 三處猜錯。
[*] 次輪 820 鍵。首輪宣稱「872 個 Base.* 死鍵是 vanilla 抑制副產物、死但無害」是[b]推論不是查證[/b]且錯誤：以 scoped_keys["ItemName.json"] 核對，872 個中只有 29 個真是 vanilla，其餘 843 個是 MOD 往 module Base 加的物品（Base.44Clip20 是高容量彈匣、vanilla 只有 Base.44Clip）。真缺口是 1,034 而非 191。
[*] 末輪 33 鍵。前輪把 118 個殘餘一律登記「查無來源」是[b]把工具限制當成事實[/b]：DisplayName 抽取器寫壞（只抽到 255 筆、實際 4,298 筆）、沒去讀 mod 自帶的 Translate/EN/ItemName.json（且 PZ mod JSON 常帶尾逗號會讓 json.loads 拋錯後被 silent skip）、兩個 mod 的 wid 沒指認出來。
[/list]
[*] [b]41 個 BarrEx 訊息從 PZ 不載入的檔名救回，順帶修掉上游自己的 bug[/b]。Barrels Expanded（3727387302，Workshop 標題搜不到、須用搜尋端點查內部 id）把 40 個轉移失敗訊息定義在 Translate/EN/TransferMessages.json，但該檔名不在 Translator.BY_NAME 白名單、PZ 從不載入，而 BarrEx_Main.lua:254 用 getText() 消費它們——[b]這批訊息對所有語言（含英文）都是壞的[/b]，玩家看到原始鍵名。我方把鍵放進自己的 UI.json 即修復。
[*] [b]Super Bulldozer 3 鍵、Last Cup Coffee 4 鍵救回[/b]：先前判「mod 已下架」是搜尋方式錯誤，兩者都還在。
[*] [b]5 鍵 placeholder 契約修正[/b]（%s/%d → %1）：以[b]上游現行 Lua[/b] 證實契約已從 string.format 轉為 getText 帶參數，停在舊寫法會讓玩家看到字面佔位符。本機 Steam 副本可能是舊版，hash 不符時不可採信。另修 19 鍵過時簡中。
[*] [b]43 張「可能過時」issue 清償[/b]：issue 內文的增刪改計數不可直接採信（record id 帶相對路徑，上游搬檔會被算成大量 added+removed），改由 git 歷史重建真實 diff；[b]必須先濾有效版本分支[/b]，本次若略過此步會漏判 49 個鍵。
[*] [b]verify [13] 不再把「已由改名後繼者涵蓋」的死鍵報成缺陷[/b]，並修正誤導的警告文字。
[*] [b]錨點漂移比對補套過度逸出還原[/b]——6 條登記全是假警報。
[*] 修正兩處回歸：rich-text <LINE> 前後空白不可壓縮；共用鍵不得寫入單一 mod 的專屬全文。
[/list]

[h3]🔄 Changed[/h3]
[list]
[*] [b]術語錨定基準修正（本次最大宗值變更，120 鍵）[/b]：#77 首版譯文錨在[b]遊戲內建[/b] CH/CN 檔，此為錯誤基準——玩家並用本體翻譯包 MinidoracatLangFor42 時，該包後載入覆寫全域字串表，內建值不是所見值。全面改對本體包定案：引擎蓋→引擎罩、制動器→煞車、懸掛→懸吊、座位→座椅、後車蓋→後備箱蓋、老舊/一般/性能→老式/普通/高階；技能名機械→技工、金屬加工→金工（後者尤重：CN「金属加工」在本體是 Metalworking 另一技能，會讓玩家找錯技能欄）。120 個車輛配方[b]逐部件建映射而非全域替換[/b]——本體包 CN 對輪胎 Old 作「廉价」、煞車作「老式」，機械替換會抹平此差異。
[*] [b]CH 側 zombie 統一為「殭屍」[/b]（106 鍵、130 處）。CN 欄刻意不動：大陸用 丧尸/僵尸 與繁中正字無關，本包 CN 現況的不一致源自 As1 自身，依規則跟隨個別 mod 錨點。
[*] [b]terminology.json re-vendor 至本體 5ef995c[/b]（rules 171→176），lint_ch [D] 轉為同步 ✓。帶進 喪屍→殭屍（為此在本體新增，作防回歸棘輪）、大米→白米、蒜蓉→蒜末、黃油→奶油、梁→樑 五條；新規則在本包既有命中 15 鍵，只動 CH。
[*] [b]IGUI_ItemCat_Misc 改中性文案「其他」[/b]：多 owner 共用鍵，Better Sorting 作一般雜項（實測其 BaseCategories.lua 指派 21 件雜物）、武器 mod 4 家作「武器配件雜項」。JSON 全域表無法條件式生效，取兩邊皆成立的寫法。
[*] [b]WolfBond 2 鍵停止出貨[/b]：Workshop 端點搜尋、本機訂閱庫全掃、en_corpus_hashes 三處皆無此 mod，依裁決登記 unshipped_keys.json。
[*] [b]AmmoLootDrop 兩則 tooltip 標點改半形[/b]，對齊 Sandbox corpus 慣例（3,172 半形 vs 106 全形）。
[*] 清理 12 條失效登記（dist 零變動實證，出貨不受影響）；補登 13 個已審鍵、還原 ETW en 錨點 provenance。
[*] tracker sync issue 內文的版本樹改由 snapshot.json 帶入，不再寫死。
[/list]

[h3]📝 Notes[/h3]
[list]
[*] [b]出貨鍵數 95,576 → 96,889（+1,313）[/b]：ItemName 裸鍵補齊為主要來源，另含受困鍵救回與本次兩個新模組的 283 鍵。
[*] [b]支援 MOD 481 → 483 個。[/b]
[*] [b]有效覆蓋率 70,449 / 71,155（99.0%）[/b]，上版 98.9%。零覆蓋 mod 0 個。剩餘 706 個缺口中 406 個集中於單一 mod（3414697768，46.6%），為上游新增字串，列為下一輪補譯目標。
[*] 驗證：build 綠、verify_dist [b]14/14 PASS[/b]（不帶 --allow-missing-as1）、冪等雙跑零 diff（173 檔）、manifest --check 同步、lint_ch 棘輪 [A][B][C][E][F] 全 0、--cn-diff v42.20.2-1.11.0 待複核 0、9 支回歸測試全過。
[*] [b]scripts/test_*.py 仍非自動 gate[/b]：repo 無 CI 執行它們（唯一 workflow 只跑 tracker.py），全靠收尾驗證階段人工跑。要讓它真的攔得住漏跑，得另外接 CI——列為獨立工作包。
[/list]
