# /// script
# requires-python = ">=3.10"
# ///
"""`verify_dist` 第 [17] 項（Print Media 42.20.4 解析契約）的回歸測試。

背景：PZ 42.20.4 改寫了 `PrintMedia.lua` 的 rich-text 解析器，值**不再被 eval**——
`texture` 直接進 `getTexture(value)`、`font` 直接進 `UIFont.FromString(value)`、其餘
key 直接進 `tonumber(value)`。同版把 Lua 全域 `loadstring`／`loadstream` 移除
（`LuaCompiler.register()` 連同 `J2SEPlatform.java:59` 的唯一呼叫點一起消失），舊格式
`texture:getTexture("X")` 於此版一律取不到材質。

為什麼非得有這道 gate：三條失效路徑**全部靜默**——`Texture.getSharedTexture` 吃掉例外
回 null、`UIFont.FromString` 未知名稱回 null、`tonumber` 失敗回 nil。玩家只看到空白圖片
或錯位版面，而 build／CH corpus parity／lint 三道全綠。這正是 `Print_Media_CDC1_info`
能帶著上游截斷值（`texture:getTexture (`）長期出貨而沒人發現的原因。

要鎖住的五件事：
  1. `_java_split`／`_java_trim` 必須是 **Java** 語意，不是 Python 的。
     `string.split` 是 Java 注入的 `String.split(regex)`（`StringLib.java:1410-1421`），
     尾端空欄位會被丟棄——`texture:` 因此切不出 `key:value` 而觸發 RICH TEXT ERROR。
     `string.trim` 是 `String.trim()`，**不去全形空白**；用 Python `str.strip()` 會把
     `texture:\u3000media/...` 誤判成乾淨，而引擎實際拿到帶前導全形空白的路徑。
  2. 禁止形式全部要擋：`getTexture(`、`UIFont.`、算式（`145/255.0`／`12+165`／`960/2`）、
     `true`／`false`、空或截斷的 texture 值。
  3. 本體 42.20.4 自己的語法要照樣放行（pivotX／angle／負小數／textLeading／font／
     autoWidth／textureless 彩色方塊），否則 gate 會逼人把正確資料改壞。
  4. CN／CH 的 `_info` 鍵集必須對稱（[2] 已對全部檔案把關，本項明示本檔）。
  5. **現況出貨檔必須全綠**——把「19 個 `_info` 已遷移完成」變成可執行斷言，
     而不是一次性的人工檢查。

執行：uv run scripts/test_print_media_contract.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_dist  # noqa: E402

check_value = verify_dist._check_print_media_value


def problems(value: str) -> list[str]:
    return check_value(value)[0]


def warnings(value: str) -> list[str]:
    return check_value(value)[1]


cases = 0

# --------------------------------------------------------------------------- #
# 1. Java 字串語意（Python 內建行為與引擎不同的地方）
# --------------------------------------------------------------------------- #
# `String.split` limit=0：無命中回 [原字串]、尾端空欄位全部丟棄。
assert verify_dist._java_split("a", ":") == ["a"]
assert verify_dist._java_split("a:b", ":") == ["a", "b"]
assert verify_dist._java_split("texture:", ":") == ["texture"], "尾端空欄位未丟棄"
assert verify_dist._java_split(":x", ":") == ["", "x"], "開頭空欄位不該丟"
assert verify_dist._java_split(":", ":") == [], "全空欄位應回空陣列（Java 行為）"
assert verify_dist._java_split("", ":") == [""], "無命中時原字串照回"
assert verify_dist._java_split("a::b", ":") == ["a", "", "b"], "中間空欄位須保留"
# `String.trim()` 只去 <= U+0020：全形空白／NBSP 必須留著，否則會漏放行壞路徑。
assert verify_dist._java_trim("  a\t\n") == "a"
assert verify_dist._java_trim("\u3000a") == "\u3000a", "全形空白被誤去掉——會漏報壞材質路徑"
assert verify_dist._java_trim("\u00a0a") == "\u00a0a", "NBSP 被誤去掉——同上"
cases += 1

# --------------------------------------------------------------------------- #
# 2. 合法值（遷移後形狀＋本體 42.20.4 實際語法）
# --------------------------------------------------------------------------- #
OK = [
    # 本包遷移後的形狀（無空白版／As1 帶空白版）
    "<type:parent, width:800, height:1131><type:texture, x:0, y:0,"
    " texture:media/textures/printMedia/FlyerPics/CDC1.png, width:800, height:1131>",
    "<type: parent, width: 1024, height: 1536><type: texture, x: 0, y: 0,"
    " texture: media/textures/printMedia/FlyerPic/DiaryPage1EN.png, width: 1024, height: 1536>",
    # 本體 42.20.4 語法：textureless 彩色方塊＋負小數 pivot／angle
    "<type:parent, width:820, height:810><type:texture, width:805, height:800,"
    " pivotX:-0.012, pivotY:0, angle:0.3, r:0.5686, g:0.5686, b:0.5686>",
    # 本體 42.20.4 語法：text 元素（textLeading 負值、裸 UIFont 名）
    "<type:parent, width:805, height:910>"
    "<type:text, x:35, y:35, r:0, g:0, b:0, a:0.9, scaleX:0.75, scaleY:0.75,"
    " textLeading:-4, font:SdfOldBold>標題文字^第二行",
    # 指數與小數點開頭（tonumber 接受，屬合法版面數值）
    "<type:parent, width:1e3, height:.5>",
]
for value in OK:
    assert check_value(value) == ([], []), f"合法值被誤擋：{value!r} → {check_value(value)}"
cases += 1

# --------------------------------------------------------------------------- #
# 3. 禁止形式（驗收條件逐項對應）
# --------------------------------------------------------------------------- #
PARENT = "<type:parent, width:800, height:1131>"
BAD = {
    # 舊格式外殼——這是本次遷移的主體
    'getTexture(': PARENT + '<type:texture, texture:getTexture("media/x.png"), width:8, height:8>',
    "UIFont.": PARENT + "<type:text, x:0, y:0, font:UIFont.SdfOldBold>文字",
    # 算式：42.20.4 之前靠 eval 才成立，現在一律 nil
    "145/255.0": PARENT + "<type:texture, r:145/255.0, width:8, height:8>",
    "12+165": PARENT + "<type:texture, x:12+165, width:8, height:8>",
    "960/2": PARENT + "<type:texture, width:960/2, height:8>",
    "true": PARENT + "<type:text, x:0, y:0, shadow:true, font:SdfOldBold>文字",
    "false": PARENT + "<type:text, x:0, y:0, autoWidth:false, font:SdfOldBold>文字",
    # 空／截斷的 texture 值（CDC1 的真實病徵）
    "空 texture": PARENT + "<type:texture, x:0, y:0, texture:, width:8, height:8>",
    "截斷": "<type:parent, width:800, height:1131><type:texture, x:0, y:0, texture:getTexture (",
    # 帶引號／括號的路徑（半途去殼的產物）
    "引號殘留": PARENT + '<type:texture, texture:"media/x.png", width:8, height:8>',
    # 前導文字／空元素／未知 type／缺 parent 尺寸
    "前導文字": "垃圾" + PARENT,
    "空元素": PARENT + "<>",
    "未知 type": PARENT + "<type:map, x:0, y:0>",
    "parent 缺 height": "<type:parent, width:800>",
    "parent 非數值": "<type:parent, width:八百, height:1131>",
    # 未知字型名：FromString 靜默回 null
    "未知字型": PARENT + "<type:text, x:0, y:0, font:SdfNotAFont>文字",
    # Java trim 不去全形空白 → 引擎拿到的是帶前導全形空白的路徑
    "全形空白路徑": PARENT + "<type:texture, texture:\u3000media/x.png, width:8, height:8>",
    # tonumber 是 Double.parseDouble：這些「解析得出來」但不是有意的版面數值
    "JDK f 後綴": PARENT + "<type:texture, width:8f, height:8>",
    "Infinity": PARENT + "<type:texture, width:Infinity, height:8>",
    "NaN": PARENT + "<type:texture, width:NaN, height:8>",
    "十六進位": PARENT + "<type:texture, width:0x10, height:8>",
    # 十進位文法合法但 parseDouble 溢位成 Infinity
    "指數溢位": PARENT + "<type:texture, width:1e309, height:8>",
    # 引擎只取 temp[1]/temp[2]，多餘的 `:` 之後靜默丟棄
    "多重冒號": PARENT + "<type:texture, texture:media/x.png:extra, width:8, height:8>",
    # 後值靜默覆寫前值／空 key
    "重複 key": PARENT + "<type:texture, width:8, width:9, height:8>",
    "空 key": PARENT + "<type:texture, :8, height:8>",
    # text 元素的正文：nil 會讓 `#data[2]` 拋錯，多一個 `>` 則第二段之後被丟棄
    "text 缺正文": PARENT + "<type:text, x:0, y:0, font:SdfOldBold>",
    "text 正文多 >": PARENT + "<type:text, x:0, y:0, font:SdfOldBold>前段>後段被丟棄",
    # parent/texture 的 `>` 之後不會被使用＝死資料
    "texture 帶正文": PARENT + "<type:texture, width:8, height:8>多餘文字",
}
for label, value in BAD.items():
    assert problems(value), f"禁止形式未被擋：{label} → {value!r}"
cases += 1

# 消費端是 Java boolean 的 key：數值形式過得了 tonumber，但永遠不生效 → WARN 而非 FAIL
BOOL_KEY = PARENT + "<type:text, x:0, y:0, shadow:1, font:SdfOldBold>文字"
assert not problems(BOOL_KEY), f"boolean key 的數值形式不該判 FAIL：{problems(BOOL_KEY)}"
assert any("boolean" in w for w in warnings(BOOL_KEY)), f"boolean key 未出 WARN：{warnings(BOOL_KEY)}"
cases += 1

# --------------------------------------------------------------------------- #
# 4. check_print_media：檔案／鍵集層面
# --------------------------------------------------------------------------- #
GOOD_VALUE = OK[0]


def run_dirs(cn: dict | None, ch: dict | None):
    """把 CN/CH 的 Print_Media.json 寫進臨時目錄後跑 [17]。None＝不寫該檔。"""
    with tempfile.TemporaryDirectory() as td:
        dirs = {}
        for lang, data in (("CN", cn), ("CH", ch)):
            d = Path(td) / lang
            d.mkdir()
            if data is not None:
                (d / "Print_Media.json").write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8")
            dirs[lang] = str(d)
        return verify_dist.check_print_media(dirs["CN"], dirs["CH"])


ok, fail, warn = run_dirs({"Print_Media_X_info": GOOD_VALUE, "Print_Media_X_title": "標題"},
                          {"Print_Media_X_info": GOOD_VALUE, "Print_Media_X_title": "題"})
assert ok and not fail, f"合法出貨被誤擋：{fail}"

ok, fail, _ = run_dirs({"Print_Media_X_info": GOOD_VALUE, "Print_Media_Y_info": GOOD_VALUE},
                       {"Print_Media_X_info": GOOD_VALUE})
assert not ok and any("僅 CN 有" in line for line in fail), f"CN/CH 鍵集不對稱未報：{fail}"

ok, fail, _ = run_dirs(None, {"Print_Media_X_info": GOOD_VALUE})
assert not ok and any("不存在" in line for line in fail), f"出貨檔消失未報：{fail}"

ok, fail, _ = run_dirs({"Print_Media_X_info": 123}, {"Print_Media_X_info": GOOD_VALUE})
assert not ok and any("值非字串" in line for line in fail), f"非字串值未報：{fail}"

# 沒有任何 _info＝本項等於沒驗到東西，須出聲（否則整檔被清空時會靜默 PASS）
ok, fail, warn = run_dirs({"Print_Media_X_title": "標題"}, {"Print_Media_X_title": "題"})
assert ok and not fail and warn, f"零 _info 未出 WARN：{fail} {warn}"
cases += 1

# --------------------------------------------------------------------------- #
# 5. 現況出貨檔：20 個 _info 已遷移完成（把人工檢查變成可執行斷言）
#    2026-09-06 #417：P4 My So-Called Toy 新增 Spiffotchi 傳單（19→20），上游即為 42.20.4 新格式
# --------------------------------------------------------------------------- #
translate = REPO / ("MOD/MinidoracatModLangFor42/Contents/mods/MinidoracatModLangFor42"
                    "/42/media/lua/shared/Translate")
dist_cn, dist_ch = translate / "CN", translate / "CH"
assert dist_cn.is_dir() and dist_ch.is_dir(), f"dist 不存在（請先 build）：{translate}"
ok, fail, _ = verify_dist.check_print_media(str(dist_cn), str(dist_ch))
assert ok, f"現況出貨檔不符 42.20.4 契約：{fail}"

for lang, directory in (("CN", dist_cn), ("CH", dist_ch)):
    data = json.loads((directory / "Print_Media.json").read_text(encoding="utf-8"))
    infos = {k: v for k, v in data.items() if k.endswith("_info")}
    assert len(infos) == 20, f"{lang} 的 _info 數量變了（{len(infos)}），請確認是刻意的"
    for key, value in infos.items():
        assert "getTexture" not in value, f"{lang}|{key} 仍有 getTexture"
        assert "UIFont." not in value, f"{lang}|{key} 仍有 UIFont."
    cdc = infos["Print_Media_CDC1_info"]
    assert cdc.endswith(">"), f"{lang}|CDC1 仍是截斷值：{cdc!r}"
    assert "media/textures/printMedia/FlyerPics/CDC1.png" in cdc, cdc
cases += 1

print(f"✅ test_print_media_contract：{cases} 組情境全過"
      f"（合法 {len(OK)} 種、禁止 {len(BAD)} 種、出貨 20×2 鍵）")
