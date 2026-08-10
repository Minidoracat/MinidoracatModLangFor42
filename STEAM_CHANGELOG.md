[h1][B42]繁體簡體模組翻譯 By Minidoracat 如一漢化組 42.20.2-1.11.0[/h1]
[i]2026-08-10[/i]

[h3]• 玩家摘要[/h3]
[list]
[*] [b]修正：本包會擅自改掉「原版」物品名稱與介面文字。[/b] 感謝玩家回報——即使沒有訂閱任何槍械替換 MOD，原版的 JS-2000 霰彈槍也會被改名成「雷明頓M870霰彈槍」。這類問題共 [b]328 處[/b]，除了槍械，還包括原版的紅酒被寫成「夏多內白葡萄酒」、4 倍瞄準鏡被寫成「8 倍」、抗生素的說明被換成完全不同的內容。這些原版文字現在一律交還給遊戲本體的官方中文，本包不再插手。
[*] [b]請留意這個取捨[/b]：如果你[b]有[/b]訂閱 Firearms、Vanilla Firearms Expansion 這類會重製原版槍的 MOD，之後這些槍會顯示原版名稱（JS-2000），而不是 MOD 的真實槍名。遊戲的翻譯機制無法做到「裝了才生效」，兩者只能擇一；要兼顧的話得另外拆一個獨立子包，之後再評估。
[*] [b]上游停止支援的模組，本包繼續翻譯。[/b] 這次同步時，如一漢化組移除了 Burd's Survival Journals、Printer3D、Hanksie's Musical Wonders 等模組的譯文，本包把這些譯文接手保留，玩家端沒有任何中文消失。支援模組數維持 [b]481 個[/b]。
[*] [b]同步上游時擋下一批會讓數字變亂碼的寫法。[/b] 上游這次調整了文字格式，若原樣採用，部分提示會把數字顯示成字面的「%1」（例如「攻擊速度: %1」）。本包已自動還原，玩家不會遇到。
[/list]

[h3]🔧 Fixed[/h3]
[list]
[*] [b]本包會改掉遊戲原版的物品名與文字（328 鍵）—— 已全數停止出貨[/b]。玩家回報：未安裝任何槍械替換 MOD，原版 JS-2000 霰彈槍卻顯示為「雷明頓M870霰彈槍」，移除本包即恢復（[Workshop 留言](https://steamcommunity.com/sharedfiles/filedetails/?id=3765907717)）。
[/list]
成因是 PZ 的 Translator.tryFillMapFromFile() 把[b]每個 mod 的 Translate 檔併進同一張全域字串表[/b]、後載入者覆寫前者——沒有「只在某 MOD 啟用時生效」這回事。As1 上游收錄了 Firearms（2256623447）、Vanilla Firearms Expansion（3611718925）等[b]重製原版槍[/b]的 MOD 譯文，這些 MOD 直接改寫 ItemName.json|Base.Shotgun 等本體鍵，於是全體玩家的原版物品跟著被改名。
影響範圍不只槍械：槍械／彈藥／配件 66 鍵、食物酒類鞋襪 74 鍵、UI／Tooltip／ContextMenu／Fluids 等 188 鍵。其中對原版玩家明確有害者包括 Base.Wine2（Red Wine）→「夏多內[b]白[/b]葡萄酒」、Base.x4Scope（x4）→「LVPO [b]8倍[/b]」、Tooltip_Antibiotics（抗傷口感染、不能防變殭屍）→「用於製作抗生素.」。
另有 10 鍵連來源 MOD 自己的現行英文都對不上（Base.Shotgun 上游現為 Mossberg 500、Base.x4Scope 現為 ACOG 4x32），即使裝了該 MOD 也是錯的。
[list]
[*] [b]這些原版字串現在改由遊戲本體／本體翻譯包提供[/b]，本包不再插手。副作用：有裝上述槍械 MOD 的玩家會看到原版名稱而非 MOD 重製名——JSON 全域表無法做條件式生效，要兩邊兼顧只能拆成依賴該 MOD 的獨立翻譯子包，尚未實作。
[/list]

[h3]✨ Added[/h3]
[list]
[*] [b]build_mod.suppress_vanilla() 出貨抑制[/b]：所有 gate 之後、寫出之前，把命中本體鍵名基準的 (檔,鍵) 自 CN/CH 對稱剔除。真相層不動——As1 CN 仍是 canonical import、sources/ch corpus 仍是人工真相，抑制只發生在出貨那一步。要刻意保留某個覆寫須登記 vanilla_keys.json 的 keep（帶出貨值錨點，值一改豁免即失效）。
[*] [b]verify_dist [12] 自 report-only 升為 blocking[/b]：獨立重掃 dist CN/CH，殘留任何非 keep 的本體同名鍵即 FAIL。原本 As1 lane 只出 WARN、且其中 327 鍵全登記在 as1_overlap_known 裡當通行證（另 1 鍵走 own lane 的 allowlist），等於防線完全靜音——這正是問題存在近半年沒被攔下的原因。
[*] [b]scripts/extract_vanilla_keys.py[/b]：自本機 PZ 安裝重生本體鍵名基準，新增[b]檔域[/b]欄位 scoped_keys（{檔名:[鍵]}）。舊基準只有扁平裸鍵集，無法區分「同名鍵在不同檔案不互撞」，故無法拿來做精確抑制。[b]遊戲大版本更新後必跑。[/b]
[*] [b]scripts/test_vanilla_suppress.py[/b] 回歸測試 9 組：對稱剔除、keep 豁免與錨點漂移（build 與 oracle 各驗一次）、基準殘缺 fail-closed（含「整個 bucket 消失」與「同鍵灌水」兩種假 fail-closed）、dist 洩漏偵測、檔域語意不退化成跨檔比對、[13] 不把抑制鍵誤報成受困鍵。
[/list]

[h3]🔄 Changed[/h3]
[list]
[*] 退役 own_translations.json 的 IG_UI.json|IGUI_SearchMode_Categories_WildHerbs（en/ch/cn 與官方逐字相同，抑制後永遠不會落地）及其 allowlist 豁免登記。
[*] sources/vanilla_overlap_triage.json 降為歷史紀錄：出貨抑制後，值層裁決不再決定「要不要出貨」。（該台帳本身也已被證實有誤——Base.x4Scope 的裁決是靠 hash 反推「Firearms 改名為 LVPO 系」，取得上游 EN 實文後確認實際是 ACOG 4x32。）
[/list]

[h3]• Changed（As1 快照重釘 42.20）[/h3]
[list]
[*] [b]verify_dist [8] As1 來源漂移 恢復可驗證[/b]，連續兩次發布的盲區關閉。快照 source_tree 自 42.19 改為 42.20——Steam 於 2026-08-05 直接以 42.20/ 覆蓋 42.19/ 且 Workshop 不提供舊版下載，被釘的樹永久消失。上游 42/ 與 42.20/ 內容逐位元組相同、version.txt 同為 v3.11.0；釘 42.20 是因 PZ B42 只載入「≤ 遊戲版本的唯一最佳版本資料夾」。
[*] [b]同步差異：新增 1、值變更 2,010、移除 5,264，實質文字變更 0。[/b] 2,010 筆值變更全是 % 逸出差異——613 筆與我方 sanitize 後等價，1,203 筆把已安全的 %1/%s/%.2f 又逸出一次，194 筆全域 %→%% 連合法字面 %% 都變成 %%%%。後兩類照收會讓佔位符變成字面文字（玩家看到「攻擊速度: %1」）。
[*] [b]改以機械反向正規化處理，而非 1,397 筆逐鍵登記[/b]：新增 build_mod.normalize_over_escape()（%%+安全 token → %、%%%% → %%，迭代至定點），於合併後、registry 與錨點快照之前執行；verify_dist.as1_expectation() 為獨立實作。兩份實作對 As1 42.20 全量 64,541 值零分歧且冪等，還原後與現行出貨值對 2,010 筆變更全數逐字相同。安全性實證：我方 145,595 個正確值中 %% 緊接安全 token 起始者 0 筆、含 %%%% 者 0 筆。
[*] [b]上游移除的 5,264 鍵依「是否還在用」分流，支援清單零流失（維持 481 個 MOD）[/b]：
[list]
[*] 2,102 鍵屬 8 個被 As1 整包放棄的模組（Burd's Survival Journals 961、Printer3D 628、Hanksie's Musical Wonders 428、Fred's NVG、Forged by Combat、Military Ponchos 等）→ 改列 own lane 的 sources/mods/<wid>/（origin:"own"）。放這裡而非 own_translations.json，是為了保住 SUPPORTED_MODS.md 列名與 gen-watchlist 上游監看——只放後者會讓這 8 個模組從兩份清單同時消失。
[*] 783 鍵為零星移除 → own_translations.json。
[*] 2,375 鍵上游查無同名鍵（2,357 屬 _unsorted）→ 跟著刪，As1 是在清理作廢鍵。
[*] 4 鍵值為 '  '（As1 的空白佔位）→ 不再出貨；玩家因此看到英文原文而非一片空白。
[/list]
[*] 新增的 1 鍵為上游畸形資料（整行英文被當成鍵名），忠實鏡像進 corpus。
[*] 登記同步：ch_review_state 清 278 條陳舊條目、as1_overlap_known 重算為 325 條、cn_overrides／placeholder_exceptions 共 16 筆 as1_value 錨點重錨。lint_ch 改為排除出貨抑制鍵——其 [C] 以 dist CN 值查已審台帳，抑制鍵查不到會讓已裁決鍵全數退回待裁決而炸掉棘輪。
[/list]

[h3]📝 Notes[/h3]
[list]
[*] [b]本次為近期首次 verify_dist 13 項全 PASS、退出碼 0[/b]（不帶 --allow-missing-as1）。build 冪等雙跑零 diff（181 檔）、verify_mod 10 PASS、lint_ch 棘輪 [A][B][C][E][F] 全 0、--cn-diff v42.20.2-1.10.0 待複核 0、6 支測試全過。
[*] [b]出貨鍵數 98,276 → 95,576（−2,700）[/b]：vanilla 出貨抑制 321、上游作廢鍵清理 2,375、撞 vanilla 的 own 鍵 4。
[*] [b]有效覆蓋率 70,075 / 70,883（98.9%）[/b]。824 個缺口中 [b]820 個在本次之前即存在[/b]——1.10.0 宣告的 100% 是對當時快照而言，之後上游各模組新增了字串（最大宗：3414697768 502 鍵）。本次同步未造成覆蓋率回歸，該缺口列為下一輪補譯目標。
[*] [b]lint_ch [D] 提示 terminology vendor 與本體不同步[/b]（本體 repo 已更新術語表）。不在棘輪內、不阻斷；重新 vendor 可能帶進新術語而觸發新的 [C] 待裁決，列為獨立工作包。
[/list]
