[h1][B42]繁體簡體模組翻譯 By Minidoracat 如一漢化組 42.20.2-1.13.0[/h1]
[i]2026-08-11[/i]

[h3]• 玩家摘要[/h3]
[list]
[*] [b]17 個模組的翻譯跟上了上游最新版，補進 50 條新增的選項與訊息。[/b] 包含 B42 Pack Mule 的沙盒選項（作者這次大改名，順便加了口袋、護肩、眼鏡三個新槽位與自動裝備鑰匙圈的開關）、Clean UI 的隱藏已裝備物品、每日報告日誌的經驗值視窗、沉浸式停電的天氣影響、撬門模組的軟性力量下限等。
[*] [b]Knox Drugs 有兩則物品說明一直顯示「NEEDTOBERENAMED」。[/b] 那是上游自己留的佔位符，我們照樣出貨了，這次上游填上真文本後同步跟進（該模組還有幾則仍是上游未填的佔位符，等它補）。
[*] [b]「保鮮盒 (菲圖奇尼寬麵)」裡面其實裝的是筆管麵。[/b] Vanilla Foods Expanded 的兩個物品名一直是錯的，上游這次修掉自己的英文才讓問題浮現，我們跟著修正。
[*] [b]修掉一個簡繁轉換的老錯字：「番茄幹」→「番茄乾」。[/b] 另外「香腸」改成「西班牙辣香腸」——同一個模組的物品名早就是後者，演化食譜那邊卻沒跟上。
[*] [b]Barrels Expanded 之外，這次也順手確認了 4 個模組的「大量變更」其實是假警報。[/b] 上游只是搬動版本資料夾，遊戲實際載入的內容一個字都沒變。
[/list]

[h3]✨ Added[/h3]
[list]
[*] [b]17 張「可能過時」issue（#92–#108）清償，補譯 50 鍵入 own_translations.json[/b]：
[list]
[*] [b]#101 B42PackMule 30 鍵[/b]。上游做了一輪 sandbox 鍵改名，拆解後為 10 組改名（MuleWrist→MuleAccessory、MuleEarProtection→MuleEarProtector、MuleLowerBack→MuleLooseBack、MulePocket→MuleWallet、MuleRifleCase→MuleOverShoulder、MuleWebbing{Large,LargeCrafted,Medium,Small,SmallCrafted}→MuleWebbing_{ALICE,Framepack,HikingBag,SchoolBag,CrudeBag}）＋ 10 組真新增（口袋／護肩／眼鏡槽位、Auto-Pouch／Auto-Wallet）。改名者沿用舊譯並跟進 EN 增補處（or suit heads、(Singleplayer only)）；舊鍵仍在 As1 衍生層並繼續出貨，須待 As1 上游自己改名後隨快照重釘清除。
[*] [b]#98 B42_PZLinux 的 IGUI_PZLinux_Betting_BlackjackBetRange[/b]：placeholder 契約以 steamcmd 重抓的現行版查證 consumer——PZLinuxFormatText()（shared/ISPZLinuxVariablesTables.lua:207）走 getText(key) 取回譯文後[b]自行[/b] gsub，%s 優先、%N 為 fallback，故譯文維持 %s 不轉編號。本機 Steam 訂閱副本是舊版、查無此鍵，未採信。
[*] [b]#104 Daily Report Journal 的 tooltip 含 <LINE>[/b]，標籤前保留 ASCII 空白：ISRichTextPanel.lua 以空白切 token，token 內同時含 < 與 > 即整個進 tag 分支，缺空白會讓前一整段文字不顯示。
[*] 其餘：#92 P4TidyUpMeister 2、#95 PZKCarzoneWorkshop 1、#99 CleanUI 2、#100 BreakBigRocks 2、#103 STA_PryOpen 4、#105 ImmersiveBlackouts 2、#106 OCsPacking 1、#108 KnoxDrugs 3。CH／CN 逐鍵對照 EN 分別直寫，未經任何簡繁轉換器。
[/list]
[/list]

[h3]🔧 Fixed[/h3]
[list]
[*] [b]Tooltip_KD_Grinder／Tooltip_KD_Syringe（#108）[/b]：上游原值是佔位符 NEEDTOBERENAMED、我方照樣出貨，這次上游填了真文本後跟進。該 mod 另有多個 tooltip 仍是上游未填的佔位符，維持原樣等上游。
[*] [b]VFX.FoodStorageContainerPenne／VFX.MetalFoodStorageContainerPenne（#102）[/b]：誤譯為「菲圖奇尼寬麵」，實際物品是 Penne——上游把自己的 EN 由 Container with Fettuccine 修正為 Container with Penne 才讓錯誤浮現。
[*] [b]VFX.JarSundriedTomatoesOpen（#102）[/b]：CH 為「番茄[b]幹[/b]」，OpenCC 一簡對多繁誤轉的殘留，改為「番茄乾」。
[*] [b]VFX.Chorizo（#102）[/b]：EN 由 Sausage 改為 Chorizo，原譯「香腸」既漏掉品項，也與同 mod ItemName.json|VFX.Chorizo「西班牙辣香腸」自相矛盾。
[*] 另修 ContextMenu_EvolvedRecipe_VFX_GreekYogurtHomemade（Yogurt→Greek Yogurt）、VFX_OpenPizzaRollBox（盒→袋，ItemName 側早已作「袋」）、VFX_OpenPuddingBox（盒→連包）、Sandbox_DestroyBoulder_ToolUsesPerConditionLoss 及其 tooltip（上游改寫並補上「與原版鎬／大錘同機制」的說明）。CH 改 sources/ch/、CN 走 cn_overrides.json（帶 as1_value 錨點）。
[/list]

[h3]🔄 Changed[/h3]
[list]
[*] [b]ch_review_state.json +71 條[/b]，其中 16 條是「上游 EN 變動但譯文經核對仍成立」的裁決。那同樣是一次裁決，不登記則日後 CN 漂移不受 verify [11] 監測，而 build／verify／lint 三道全綠——由 codex review 以 blocking 指出後補登。
[*] [b]IGUI_CraftingCategories_Packing（#108）裁決不收[/b]：撞 vanilla_keys.json 的 scoped_keys["IG_UI.json"]。PZ 的翻譯表是全域的，出貨即等於改寫本體譯文、連沒裝該 mod 的玩家都會看到。
[*] [b]Sandbox_MuleOverShoulder／Sandbox_MuleEarProtector_tooltip／Sandbox_MuleGlasses_tooltip 用詞校正[/b]（codex review 採納）：Cloth Gun Case 補回「布製／布制」修飾（本體作「布制槍箱」）；CH 的「全盔」改為「全罩式頭盔」（本體 CH 零命中「全盔」、用「頭盔」32 次）。同一輪駁回兩項——Duffel Bag Slot 要求繁簡分流成「圓筒包／行李袋」，但本包 CH 已有 211 處「行李袋」，單鍵改動只會製造局部矛盾（記為全庫術語議題）；「佩戴→配戴」，本包 CH 佩戴 41 : 配戴 2。
[/list]

[h3]• 已裁決不跟進[/h3]
[list]
[*] [b]VFE 上游去商標化改名[/b]（Cocoa Puffs→Choco-Roos、Wheaties→Wheat Flakes、Honey Oaty O's→Honey O's、Toaster Strudel→Pop Strudel）：上游自身尚未一致（Base.VFXCocoaPuffsBowlEvolved 仍為舊名），跟進得連動 4 族十幾鍵才不矛盾，且玩家看到的品項未變。
[*] [b]VFE 演化食譜成分標籤的統一簡化[/b]（Apple Pie Filling→Apple、Mango Slices→Mango 等）：我方譯文比新 EN 更具體，不致誤導。
[*] 兩項理由均已寫入 issue #102 的關閉留言，日後翻案有紀錄可循。
[/list]
