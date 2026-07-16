-- 移植自 As1「[B42]統一模組漢化」42.19 tree（已授權）
-- 目標 MOD：Bandits Week One（Workshop 3403180543，id=BanditsWeekOne）
-- 作用：覆寫 BWOEvents.StartDay，改載入語言後綴的開日貼圖（day_<day>_<lang>.png）
-- 防護：目標 MOD 未啟用即 no-op；貼圖 fallback：<lang> → CN → 原版無後綴

local function isModActive(modId)
    local mods = getActivatedMods()
    for i = 1, mods:size() do
        if mods:get(i - 1) == modId then return true end
    end
    return false
end

-- BanditsDayOne 與 BanditsWeekOne 共用 BWO 前綴框架，任一啟用即生效
if not (isModActive("BanditsWeekOne") or isModActive("BanditsDayOne")) then return end
if BWOEvents == nil then return end

BWOEvents.StartDay = function(params)
    local player = getSpecificPlayer(0)
    if player then
        player:playSound("ZSDayStart")
    end
    if BWOTex == nil then return end

    -- 貼圖 fallback：目前語言（如 CH）→ CN（As1 提供）→ 原版無語言後綴
    local lang = getCore():getOptionLanguageName()
    local tex = getTexture("media/textures/day_" .. params.day .. "_" .. lang .. ".png")
    if tex == nil then
        tex = getTexture("media/textures/day_" .. params.day .. "_CN.png")
    end
    if tex == nil then
        tex = getTexture("media/textures/day_" .. params.day .. ".png")
    end
    if tex == nil then return end

    BWOTex.tex = tex
    BWOTex.speed = 0.011
    BWOTex.mode = "center"
    BWOTex.alpha = 2.4
end
