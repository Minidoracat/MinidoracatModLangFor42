# /// script
# requires-python = ">=3.10"
# ///
"""verify [14] own 層 CN 用字棘輪的回歸測試。

背景：own 層 CN 多數由 CH 跑 `opencc t2s` 生成，而 t2s **只換字形不換詞彙**，
還有幾個字它根本不動——最陰險的是助詞「著」：簡化字表保留「著」(zhù) 用於
著名／著作／顯著／土著，所以「抱著」轉完仍是「抱著」，大陸須寫「抱着」。
簡體專用字集檢查、hash 錨點、token 檢查全部視為合法，只有人讀得出來。

要鎖住的三件事：
  1. 助詞「著」判 FAIL——這是本檢查存在的理由。
  2. zhù 義的「著名／著作／顯著／土著」與句尾署名「由 X 著」**不得誤報**，
     否則 gate 會逼人把正確的簡中改壞（見 memory: 別為了讓 gate 變綠改譯文）。
  3. 掃描域只有 own 層——As1 快照的 CN 我方忠實鏡像（實測 52 鍵用「」與快照
     逐字相同），本檢查不得因此把 As1 的風格判成缺陷。

執行：uv run scripts/test_own_cn_glyphs.py
不依賴測試框架，assert 失敗即測試失敗（exit code != 0）。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_dist  # noqa: E402


def run(entries: dict) -> list[str]:
    """把 entries 寫成臨時 repo 的 own_translations.json，回傳 [14] 的 fail 清單。"""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "sources"
        src.mkdir()
        (src / "own_translations.json").write_text(
            json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
        ok, fail, warn = verify_dist.check_own_cn_glyphs(td)
        assert ok == (not fail), "ok 與 fail 清單不一致"
        assert warn == [], "本檢查不產 WARN"
        return fail


def e(cn: str) -> dict:
    return {"UI.json": {"K": {"en": "x", "ch": "x", "cn": cn}}}


# 1. 助詞「著」必須被抓到（t2s 不動它，是唯一的防線）
for bad in ("抱著一线希望", "他看著你", "上面写著“先抢先赢”", "地下室藏著补给", "地图上画著一个红十字"):
    assert run(e(bad)), f"助詞「著」未被抓到：{bad}"

# 1b. 已知取捨：句尾的「著」一律放行（與署名形無法機械區分）。
#     漏報一個 zhe 遠好過逼人把正確的署名「由 X 著.」改壞。
assert not run(e("你就在这里等著.")), "句尾放行的取捨變了——若改判 FAIL 須同步更新署名白名單"

# 2. zhù 義不得誤報
for good in ("著名的诺克斯县", "由 Kkat 著.", "体格Vol.5《完整指南》尤塞恩・博尔特著",
             "显著提升移动速度", "土著居民", "这本原著小说", "编著者不详"):
    assert not run(e(good)), f"zhù 義誤報：{good}"

# 3. 其餘三類字形
assert run(e("牠们已经很近了")), "「牠」未被抓到"
assert run(e("妳还好吗")), "「妳」未被抓到"
assert run(e("启用「断片」火灾")), "直角引號未被抓到"
assert not run(e("启用“断片”火灾")), "彎引號被誤報"

# 4. 乾淨值不得誤報；非字串 cn 不得炸開
assert not run(e("抱着一线希望. 保持频道畅通.")), "正確簡中被誤報"
assert not run({"UI.json": {"K": {"en": "x", "ch": "x"}}}), "缺 cn 欄應略過而非誤報"
assert not run({}), "空 entries 應為 PASS"

# 5. 掃描域：As1 快照（sources/mods 下無 origin=own 者）不得納入
with tempfile.TemporaryDirectory() as td:
    mods = Path(td) / "sources" / "mods" / "123" / "CN"
    mods.mkdir(parents=True)
    (mods / "UI.json").write_text(json.dumps({"K": "上面写著「测试」"}, ensure_ascii=False),
                                  encoding="utf-8")
    (mods.parent / "metadata.json").write_text(json.dumps({}), encoding="utf-8")  # 無 origin=own
    ok, fail, _ = verify_dist.check_own_cn_glyphs(td)
    assert ok and not fail, f"As1 衍生目錄不該納入掃描：{fail}"

print("✅ test_own_cn_glyphs：5 組情境全過")
