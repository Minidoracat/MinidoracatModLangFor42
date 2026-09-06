[h1]🌏 [B42]繁體簡體模組翻譯 By Minidoracat 如一漢化組[/h1]
[h3]By Minidoracat × 如一漢化組（As1）[/h3]

[hr][/hr]

[h2]✨ 功能特色[/h2]
[list]
[*] 670+ 個 Workshop 模組（830+ 個模組 ID）的中文翻譯
[*] 有效覆蓋率 100.0%（截至 2026-09-06）——現行有效上游翻譯鍵 113,169 個中已覆蓋 113,163 個；餘 6 鍵只存在於已下架、無法重新下載的 FR Operator。上游每天更新，新增文本由追蹤器偵測後持續補譯，故此數字會隨上游浮動。另有少數模組把文字寫死在程式碼裡，任何翻譯包都補不了（已於支援清單逐一標註）
[*] 不覆蓋遊戲本體的官方翻譯——撞到本體代號的鍵一律不出貨（詳見下方說明）
[*] 繁體中文（台灣用語）/ 簡體中文 雙語支援
[*] 每日自動追蹤各模組文本更新，持續維護校對
[*] 新收錄與後續維護採 JSON-only——不新增 Lua 覆寫、不改動任何 MOD 檔案；僅保留早期既有的 BanditsWeekOne 開日貼圖 Lua 相容層（凍結，不再擴充）
[/list]

[hr][/hr]

[h2]🛡️ 不覆蓋遊戲本體的翻譯[/h2]
Project Zomboid 把所有 MOD 的翻譯檔載入[b]同一張全域字串表[/b]、後載入者勝——所以翻譯包只要出貨一個與本體同名的代號，就會全域改寫官方譯文，[b]連沒裝那個 MOD 的玩家都會被改到[/b]。

本包的硬性原則：[b]每次建置都掃描 MOD 的代號有沒有撞到遊戲本體（英文／繁中／簡中三語聯集），撞到就不出貨那個代號，一個都不例外。[/b]那些文字一律交由遊戲本體自己的官方譯文顯示。

[b]代價要講清楚：[/b]如果你裝的 MOD 重製了原版物品（例如把原版霰彈槍換成真實槍型），那個物品在物品欄會顯示[b]本體的官方名稱[/b]，而不是該 MOD 的重製名稱——這不是漏翻，是刻意的取捨。JSON 全域字串表做不到「只在某個 MOD 啟用時生效」；若為了裝了該 MOD 的玩家出貨那個代號，所有沒裝的玩家都會看到被改掉的官方文字。哪個 MOD 會動到多少官方鍵，可在支援清單的「覆寫本體」欄查到。

[hr][/hr]

[h2]📋 支援清單與問題回報[/h2]
[url=https://github.com/Minidoracat/MinidoracatModLangFor42/blob/main/SUPPORTED_MODS.md]👉 完整支援 MOD 清單（含中文名稱與摘要）[/url]
[url=https://github.com/Minidoracat/MinidoracatModLangFor42/blob/main/RECIPE_COVERAGE_AUDIT.md]📐 配方名覆蓋率稽核（製作選單還缺哪些配方中文、成因分類與清償進度）[/url]
[url=https://github.com/Minidoracat/MinidoracatModLangFor42/issues]🐛 GitHub 問題回報[/url]
[url=https://github.com/Minidoracat/MinidoracatModLangFor42/issues/new?template=translation-request.yml]🙋 申請新 MOD 翻譯（附 Workshop 連結與理由即可）[/url]
[url=https://discord.gg/Gur2V67]💬 Discord 交流與回報[/url]
想要的 MOD 還沒中文？歡迎透過上方連結申請，收錄順序將參考需求熱度、文本量與上游活躍度；「統一模組漢化」已涵蓋的 MOD 會隨同步自動加入，不需申請。

[hr][/hr]

[h2]🔍 翻譯邊界與上游回報責任[/h2]
本包只維護 Project Zomboid 的 JSON 翻譯檔（[i]Translate/CH[/i]、[i]Translate/CN[/i]）。有些文字在技術上任何翻譯包都碰不到：
[list]
[*] 模組把文字寫死在 Lua 程式碼裡，不經遊戲的翻譯機制
[*] 模組自建文字系統，不讀遊戲的字串表
[*] 英文只放在 Build 42 已不再讀取的舊格式檔（[i]*_EN.txt[/i]），或鍵名前綴不在引擎的路由表上
[*] 兩個模組用同一個代號指向不同的東西，沒有對雙方都成立的譯名
[/list]
遇到這類情況，我們會把可驗證的檔名、鍵名、上游原文與機制原因查清楚並公開記錄，讓你能直接拿去跟作者溝通：
[url=https://github.com/Minidoracat/MinidoracatModLangFor42/blob/main/OWNER_CONFLICTS.md]⚖️ 模組間代號衝突裁決紀錄（哪些鍵不出貨中文、各模組抑制後會顯示英文還是代號）[/url]

[b]但責任歸屬要講清楚：本包不代為向模組作者回報，也不代為追蹤上游是否修復。[/b]需要該模組中文化的玩家——實際使用者或翻譯申請者——請自行拿上述資訊向原作者反映；本包負責的是把成因查清楚並記錄，不負責催上游。上游把文字改成標準的 JSON 翻譯機制、或把撞名的代號改開之後，本包就能接手翻譯；在那之前這些文字會維持英文或顯示代號。

[hr][/hr]

[h2]🧩 姊妹作：本體完全翻譯[/h2]
本包涵蓋其他 Workshop 模組的文本；遊戲本體的完整翻譯請搭配訂閱：
[url=https://steamcommunity.com/sharedfiles/filedetails/?id=3386633401]👉 [B42]繁體簡體中文完全翻譯 By Minidoracat 如一漢化組[/url]
兩者搭配即為完整中文體驗。

[hr][/hr]

[h2]🤝 授權與致謝[/h2]
本 MOD 為如一漢化組（As1）[url=https://steamcommunity.com/sharedfiles/filedetails/?id=3556540080]「[B42]統一模組漢化」[/url]的授權繁體中文版，掛名如一漢化組。
授權範圍內的簡體文本逐字保留原包內容；原創翻譯的模組則由本包逐鍵自撰簡體。繁體文本全部逐鍵人工維護——對照英文原文與術語表校訂，不使用自動簡繁轉換。
感謝如一漢化組授權與長期維護的翻譯成果。

[hr][/hr]

[h2]📋 MOD 資訊[/h2]
[list]
[*] [b]Mod ID:[/b] CatModLangFor42
[*] [b]支援版本:[/b] Build 42.20.4+
[*] [b]Mod 版本:[/b] 42.20.4-1.26.0
[*] [b]Workshop ID:[/b] 3765907717
[/list]

[hr][/hr]

[h2]☕ 支持作者[/h2]
MOD 永遠免費。喜歡的話可以請我喝杯咖啡，贊助會用在伺服器與 MOD 開發上；原始碼公開在 GitHub。
[url=https://ko-fi.com/minidoracat][img]https://raw.githubusercontent.com/Minidoracat/workshop-resources/refs/heads/main/badges/badge_kofi.png[/img][/url] [url=https://github.com/Minidoracat/MinidoracatModLangFor42][img]https://raw.githubusercontent.com/Minidoracat/workshop-resources/refs/heads/main/badges/badge_github.png[/img][/url]

[b]#Build42 #繁體中文 #簡體中文 #漢化 #翻譯 #Minidoracat #如一漢化組[/b]

Tags: Build 42;Language/Translation;Multiplayer
