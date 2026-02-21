-- =============================================================================
-- Pokemon Emerald GM Tools
-- Full toolset for AI Game Master control
-- =============================================================================

local GM = {}

-- =============================================================================
-- CONSTANTS & ADDRESSES (Pokemon Emerald US - Decomp Build)
-- =============================================================================

local SPECIES_OFFSET = 25  -- Decomp ROM offset

-- Save blocks
local SAVE_BLOCK1_PTR = 0x03005D8C
local SAVE_BLOCK2_PTR = 0x03005D90

-- Party
local PLAYER_PARTY_ADDR = 0x020244EC
local PARTY_COUNT_ADDR = 0x020244E9
local POKEMON_SIZE = 100

-- Bag offsets (from saveBlock1)
local BAG_ITEMS_OFFSET     = 0x0560  -- 30 slots × 4 bytes
local BAG_KEYITEMS_OFFSET  = 0x05D8  -- 30 slots × 4 bytes (was 0x06A0 — wrong)
local BAG_POKEBALLS_OFFSET = 0x0650  -- 16 slots × 4 bytes (was 0x0600 — wrong)
local BAG_TMS_OFFSET       = 0x0690  -- 64 slots × 4 bytes (was 0x0640 — was writing into KeyItems area!)
local BAG_BERRIES_OFFSET   = 0x0790  -- 46 slots × 4 bytes (was 0x0740 — wrong)

-- Money & badges
local MONEY_OFFSET = 0x0490
-- Flags array at 0x1270, badge flags start at 0x867
-- Byte offset = 0x1270 + (0x867 / 8) = 0x1270 + 0x10C = 0x137C
local BADGE_OFFSET = 0x137C

-- Player position
local PLAYER_X_OFFSET = 0x00
local PLAYER_Y_OFFSET = 0x02
local MAP_GROUP_OFFSET = 0x04
local MAP_NUM_OFFSET = 0x05

-- Event flags (from saveBlock1)
local FLAGS_OFFSET = 0x1270

-- Dialogue
local GSTRINGVAR4 = 0x02021FC4

-- Battle
local GBATTLEMONS_ADDR = 0x02024084
local BATTLE_MON_SIZE = 88

-- =============================================================================
-- MOVE COMPATIBILITY DATABASE
-- Maps species to learnable moves (for validation during teachMove)
-- =============================================================================

local MOVE_COMPAT = {
    -- Fire types (move 57 = Surf is NOT compatible, but 52 = Ember is)
    [252] = { 15, 33, 52, 126, 163 },  -- Treecko: Cut, Tackle, Ember... (type-neutral + Grass)
    [255] = { 15, 33, 52, 126, 172 },  -- Torchic: Cut, Tackle, Ember, Fire Blast, Flame Wheel
    [256] = { 15, 33, 52, 126, 172 },  -- Combusken: similar
    [257] = { 15, 33, 52, 126, 172, 57 },  -- Blaziken: + Surf (egg move potential)
    
    -- Water types
    [258] = { 15, 33, 57, 127 },  -- Mudkip: Waterfall, Surf, etc.
    [259] = { 15, 33, 57, 127 },  -- Marshtomp
    [260] = { 15, 33, 57, 127, 94 },  -- Swampert: + Psychic (egg)
    
    -- Psychic types
    [280] = { 94, 115, 156 },  -- Ralts: Psychic, Reflect, Rest
    [281] = { 94, 115, 156 },  -- Kirlia
    [282] = { 94, 115, 156 },  -- Gardevoir
    
    -- Dragon types
    [371] = { 89, 337 },  -- Bagon: Earthquake, Dragon Claw
    [372] = { 89, 337 },  -- Shelgon
    [373] = { 89, 337, 57 },  -- Salamence: + Surf (rare)
    
    -- Steel types
    [304] = { 89, 70 },  -- Aron: Earthquake, Strength
    [305] = { 89, 70 },  -- Lairon
    [306] = { 89, 70, 337 },  -- Aggron: Dragon Claw (egg)
    
    -- Universal safe moves (any type can learn)
    [0] = { 57, 15, 70, 94, 89, 115, 182, 156, 163, 14 },  -- Surf, Cut, Strength, Psychic, Earthquake, Reflect, Protect, Rest, Slash, Swords Dance
}

-- Universal moves that any Pokemon can safely learn
local UNIVERSAL_MOVES = { 57, 15, 70, 94, 89, 115, 182, 156, 163, 14 }

-- Move ID to name lookup (for logging)
local MOVE_NAMES = {
    [14] = "Swords Dance", [15] = "Cut", [33] = "Tackle", [52] = "Ember", [57] = "Surf",
    [59] = "Blizzard", [70] = "Strength", [76] = "SolarBeam", [89] = "Earthquake",
    [94] = "Psychic", [115] = "Reflect", [126] = "Fire Blast", [127] = "Waterfall",
    [156] = "Rest", [163] = "Slash", [172] = "Flame Wheel", [182] = "Protect",
    [188] = "Sludge Bomb", [247] = "Shadow Ball", [337] = "Dragon Claw",
}

-- =============================================================================
-- MOVE COMPATIBILITY CHECKER
-- =============================================================================

function GM.isMoveLearnable(speciesId, moveId)
    -- Check if move is universal (safe for any Pokemon)
    for _, move in ipairs(UNIVERSAL_MOVES) do
        if move == moveId then return true, "universal" end
    end
    
    -- Check species-specific moves
    if MOVE_COMPAT[speciesId] then
        for _, move in ipairs(MOVE_COMPAT[speciesId]) do
            if move == moveId then return true, "species" end
        end
    end
    
    -- If not found, it's not recommended
    return false, "unknown"
end

function GM.getMoveName(moveId)
    return MOVE_NAMES[moveId] or ("Move #" .. moveId)
end

-- =============================================================================
-- UTILITY FUNCTIONS
-- =============================================================================

local function getSaveBlock1()
    return emu:read32(SAVE_BLOCK1_PTR)
end

local function getSaveBlock2()
    return emu:read32(SAVE_BLOCK2_PTR)
end

-- Pokemon character encoding
local encodeTable = {
    [' '] = 0x00,
    ['A'] = 0xBB, ['B'] = 0xBC, ['C'] = 0xBD, ['D'] = 0xBE, ['E'] = 0xBF,
    ['F'] = 0xC0, ['G'] = 0xC1, ['H'] = 0xC2, ['I'] = 0xC3, ['J'] = 0xC4,
    ['K'] = 0xC5, ['L'] = 0xC6, ['M'] = 0xC7, ['N'] = 0xC8, ['O'] = 0xC9,
    ['P'] = 0xCA, ['Q'] = 0xCB, ['R'] = 0xCC, ['S'] = 0xCD, ['T'] = 0xCE,
    ['U'] = 0xCF, ['V'] = 0xD0, ['W'] = 0xD1, ['X'] = 0xD2, ['Y'] = 0xD3,
    ['Z'] = 0xD4,
    ['a'] = 0xD5, ['b'] = 0xD6, ['c'] = 0xD7, ['d'] = 0xD8, ['e'] = 0xD9,
    ['f'] = 0xDA, ['g'] = 0xDB, ['h'] = 0xDC, ['i'] = 0xDD, ['j'] = 0xDE,
    ['k'] = 0xDF, ['l'] = 0xE0, ['m'] = 0xE1, ['n'] = 0xE2, ['o'] = 0xE3,
    ['p'] = 0xE4, ['q'] = 0xE5, ['r'] = 0xE6, ['s'] = 0xE7, ['t'] = 0xE8,
    ['u'] = 0xE9, ['v'] = 0xEA, ['w'] = 0xEB, ['x'] = 0xEC, ['y'] = 0xED,
    ['z'] = 0xEE,
    ['0'] = 0xA1, ['1'] = 0xA2, ['2'] = 0xA3, ['3'] = 0xA4, ['4'] = 0xA5,
    ['5'] = 0xA6, ['6'] = 0xA7, ['7'] = 0xA8, ['8'] = 0xA9, ['9'] = 0xAA,
    ['!'] = 0xAB, ['?'] = 0xAC, ['.'] = 0xAD, ['-'] = 0xAE, [','] = 0xB8,
}

function GM.encodeString(text)
    local bytes = {}
    for i = 1, #text do
        local c = text:sub(i, i)
        table.insert(bytes, encodeTable[c] or 0xAC)
    end
    table.insert(bytes, 0xFF)  -- EOS
    return bytes
end

-- =============================================================================
-- MONEY
-- =============================================================================

function GM.getMoney()
    local sb1 = getSaveBlock1()
    return emu:read32(sb1 + MONEY_OFFSET)
end

function GM.setMoney(amount)
    local sb1 = getSaveBlock1()
    emu:write32(sb1 + MONEY_OFFSET, amount)
    console:log("💰 Set money to $" .. amount)
    return true
end

function GM.addMoney(amount)
    local current = GM.getMoney()
    return GM.setMoney(math.min(current + amount, 999999))
end

-- =============================================================================
-- BADGES
-- =============================================================================

function GM.getBadges()
    local sb1 = getSaveBlock1()
    -- Badge flags start at bit 7, so shift right to align to bit 0
    local rawFlags = emu:read16(sb1 + BADGE_OFFSET)
    return (rawFlags >> 7) & 0xFF
end

function GM.setBadge(badgeNum, obtained)
    local sb1 = getSaveBlock1()
    local rawFlags = emu:read16(sb1 + BADGE_OFFSET)
    -- Badge bits are at positions 7-14 in the u16
    local bitPos = badgeNum + 7  -- Badge 1 = bit 7, Badge 2 = bit 8, etc.
    if obtained then
        rawFlags = rawFlags | (1 << bitPos)
    else
        rawFlags = rawFlags & ~(1 << bitPos)
    end
    emu:write16(sb1 + BADGE_OFFSET, rawFlags)
    console:log("🏅 Badge " .. badgeNum .. " = " .. tostring(obtained))
    return true
end

function GM.giveAllBadges()
    local sb1 = getSaveBlock1()
    local rawFlags = emu:read16(sb1 + BADGE_OFFSET)
    -- Set bits 7-14 (all 8 badges)
    rawFlags = rawFlags | (0xFF << 7)
    emu:write16(sb1 + BADGE_OFFSET, rawFlags)
    console:log("🏅 Gave all 8 badges!")
    return true
end

-- =============================================================================
-- ITEMS
-- =============================================================================

-- Item pocket constants
GM.POCKET = {
    ITEMS = 0,
    POKEBALLS = 1,
    TMS = 2,
    BERRIES = 3,
    KEYITEMS = 4
}

local pocketOffsets = {
    [0] = {offset = BAG_ITEMS_OFFSET, count = 30},
    [1] = {offset = BAG_POKEBALLS_OFFSET, count = 16},
    [2] = {offset = BAG_TMS_OFFSET, count = 64},
    [3] = {offset = BAG_BERRIES_OFFSET, count = 46},
    [4] = {offset = BAG_KEYITEMS_OFFSET, count = 30},
}

function GM.giveItem(itemId, quantity, pocket)
    pocket = pocket or GM.POCKET.ITEMS
    quantity = quantity or 1
    
    local sb1 = getSaveBlock1()
    local pocketInfo = pocketOffsets[pocket]
    if not pocketInfo then return false end
    
    -- Find empty slot or existing stack
    for i = 0, pocketInfo.count - 1 do
        local addr = sb1 + pocketInfo.offset + (i * 4)
        local existingId = emu:read16(addr)
        local existingQty = emu:read16(addr + 2)
        
        -- Found existing stack
        if existingId == itemId then
            emu:write16(addr + 2, math.min(existingQty + quantity, 99))
            console:log("🎒 Added " .. quantity .. "x item " .. itemId)
            return true
        end
        
        -- Found empty slot
        if existingId == 0 then
            emu:write16(addr, itemId)
            emu:write16(addr + 2, quantity)
            console:log("🎒 Gave " .. quantity .. "x item " .. itemId)
            return true
        end
    end
    
    console:log("❌ Bag pocket full!")
    return false
end

function GM.removeItem(itemId, quantity, pocket)
    pocket = pocket or GM.POCKET.ITEMS
    quantity = quantity or 1
    
    local sb1 = getSaveBlock1()
    local pocketInfo = pocketOffsets[pocket]
    if not pocketInfo then return false end
    
    for i = 0, pocketInfo.count - 1 do
        local addr = sb1 + pocketInfo.offset + (i * 4)
        local existingId = emu:read16(addr)
        local existingQty = emu:read16(addr + 2)
        
        if existingId == itemId then
            local newQty = existingQty - quantity
            if newQty <= 0 then
                emu:write16(addr, 0)
                emu:write16(addr + 2, 0)
            else
                emu:write16(addr + 2, newQty)
            end
            console:log("🎒 Removed " .. quantity .. "x item " .. itemId)
            return true
        end
    end
    
    return false
end

-- Common items shortcuts (IDs sourced from pokeemerald decomp items.h — authoritative)
function GM.givePokeballs(quantity)  return GM.giveItem(4,  quantity, GM.POCKET.POKEBALLS) end  -- Poke Ball    id=4
function GM.giveGreatBalls(quantity) return GM.giveItem(3,  quantity, GM.POCKET.POKEBALLS) end  -- Great Ball   id=3
function GM.giveUltraBalls(quantity) return GM.giveItem(2,  quantity, GM.POCKET.POKEBALLS) end  -- Ultra Ball   id=2
function GM.giveMasterBall()         return GM.giveItem(1,  1,        GM.POCKET.POKEBALLS) end  -- Master Ball  id=1
function GM.giveRareCandy(quantity)  return GM.giveItem(68, quantity, GM.POCKET.ITEMS)     end  -- Rare Candy   id=68
function GM.givePotion(quantity)     return GM.giveItem(13, quantity, GM.POCKET.ITEMS)     end  -- Potion       id=13
function GM.giveSuperPotion(quantity)return GM.giveItem(22, quantity, GM.POCKET.ITEMS)     end  -- Super Potion id=22
function GM.giveHyperPotion(quantity)return GM.giveItem(21, quantity, GM.POCKET.ITEMS)     end  -- Hyper Potion id=21
function GM.giveMaxPotion(quantity)  return GM.giveItem(20, quantity, GM.POCKET.ITEMS)     end  -- Max Potion   id=20
function GM.giveFullRestore(quantity)return GM.giveItem(19, quantity, GM.POCKET.ITEMS)     end  -- Full Restore id=19
function GM.giveRevive(quantity)     return GM.giveItem(24, quantity, GM.POCKET.ITEMS)     end  -- Revive       id=24
function GM.giveMaxRevive(quantity)  return GM.giveItem(25, quantity, GM.POCKET.ITEMS)     end  -- Max Revive   id=25

-- Berries (go in Berry Pouch — pocket 3)
-- IDs from pokeemerald decomp items.h (BPEE USA — authoritative)
function GM.givePechaberry(quantity)  return GM.giveItem(135, quantity, GM.POCKET.BERRIES) end  -- Pecha  id=135 cures poison
function GM.giveSitrusBerry(quantity) return GM.giveItem(142, quantity, GM.POCKET.BERRIES) end  -- Sitrus id=142 restores 1/4 HP
function GM.giveOranBerry(quantity)   return GM.giveItem(139, quantity, GM.POCKET.BERRIES) end  -- Oran   id=139 restores 10 HP
function GM.giveLumBerry(quantity)    return GM.giveItem(141, quantity, GM.POCKET.BERRIES) end  -- Lum    id=141 cures all status
function GM.giveLeppaberry(quantity)  return GM.giveItem(138, quantity, GM.POCKET.BERRIES) end  -- Leppa  id=138 restores PP

-- =============================================================================
-- ITEM LOOKUP TABLE — GM.give("item name", quantity)
-- Use this instead of raw IDs. Names are case-insensitive, spaces/hyphens ok.
-- IDs sourced from pokeemerald decomp: include/constants/items.h
-- Pockets: ITEMS=0, POKEBALLS=1, TMS=2, BERRIES=3, KEYITEMS=4
-- =============================================================================

local ITEM_LOOKUP = {

    -- =========================================================================
    -- POKEBALLS (pocket 1 = POCKET_POKE_BALLS)
    -- =========================================================================
    ["master ball"]   = {id=1,  pocket=1}, ["masterball"]   = {id=1,  pocket=1},
    ["ultra ball"]    = {id=2,  pocket=1}, ["ultraball"]    = {id=2,  pocket=1},
    ["great ball"]    = {id=3,  pocket=1}, ["greatball"]    = {id=3,  pocket=1},
    ["poke ball"]     = {id=4,  pocket=1}, ["pokeball"]     = {id=4,  pocket=1}, ["pokéball"] = {id=4, pocket=1},
    ["safari ball"]   = {id=5,  pocket=1}, ["safariball"]   = {id=5,  pocket=1},
    ["net ball"]      = {id=6,  pocket=1}, ["netball"]      = {id=6,  pocket=1},
    ["dive ball"]     = {id=7,  pocket=1}, ["diveball"]     = {id=7,  pocket=1},
    ["nest ball"]     = {id=8,  pocket=1}, ["nestball"]     = {id=8,  pocket=1},
    ["repeat ball"]   = {id=9,  pocket=1}, ["repeatball"]   = {id=9,  pocket=1},
    ["timer ball"]    = {id=10, pocket=1}, ["timerball"]    = {id=10, pocket=1},
    ["luxury ball"]   = {id=11, pocket=1}, ["luxuryball"]   = {id=11, pocket=1},
    ["premier ball"]  = {id=12, pocket=1}, ["premierball"]  = {id=12, pocket=1},

    -- =========================================================================
    -- MEDICINE / HEALING (pocket 0 = POCKET_ITEMS)
    -- =========================================================================
    ["potion"]         = {id=13, pocket=0},
    ["antidote"]       = {id=14, pocket=0},
    ["burn heal"]      = {id=15, pocket=0}, ["burnheal"]      = {id=15, pocket=0},
    ["ice heal"]       = {id=16, pocket=0}, ["iceheal"]       = {id=16, pocket=0},
    ["awakening"]      = {id=17, pocket=0},
    ["parlyz heal"]    = {id=18, pocket=0}, ["paralyze heal"] = {id=18, pocket=0},
                                            ["paralyzeheal"]  = {id=18, pocket=0}, ["parlyzheal"] = {id=18, pocket=0},
    ["full restore"]   = {id=19, pocket=0}, ["fullrestore"]   = {id=19, pocket=0},
    ["max potion"]     = {id=20, pocket=0}, ["maxpotion"]     = {id=20, pocket=0},
    ["hyper potion"]   = {id=21, pocket=0}, ["hyperpotion"]   = {id=21, pocket=0},
    ["super potion"]   = {id=22, pocket=0}, ["superpotion"]   = {id=22, pocket=0},
    ["full heal"]      = {id=23, pocket=0}, ["fullheal"]      = {id=23, pocket=0},
    ["revive"]         = {id=24, pocket=0},
    ["max revive"]     = {id=25, pocket=0}, ["maxrevive"]     = {id=25, pocket=0},
    ["fresh water"]    = {id=26, pocket=0}, ["freshwater"]    = {id=26, pocket=0},
    ["soda pop"]       = {id=27, pocket=0}, ["sodapop"]       = {id=27, pocket=0},
    ["lemonade"]       = {id=28, pocket=0},
    ["moomoo milk"]    = {id=29, pocket=0}, ["moomoomilk"]    = {id=29, pocket=0}, ["moo moo milk"] = {id=29, pocket=0},
    ["energy powder"]  = {id=30, pocket=0}, ["energypowder"]  = {id=30, pocket=0},
    ["energy root"]    = {id=31, pocket=0}, ["energyroot"]    = {id=31, pocket=0},
    ["heal powder"]    = {id=32, pocket=0}, ["healpowder"]    = {id=32, pocket=0},
    ["revival herb"]   = {id=33, pocket=0}, ["revivalherb"]   = {id=33, pocket=0},
    ["ether"]          = {id=34, pocket=0},
    ["max ether"]      = {id=35, pocket=0}, ["maxether"]      = {id=35, pocket=0},
    ["elixir"]         = {id=36, pocket=0},
    ["max elixir"]     = {id=37, pocket=0}, ["maxelixir"]     = {id=37, pocket=0},
    ["lava cookie"]    = {id=38, pocket=0}, ["lavacookie"]    = {id=38, pocket=0},
    ["berry juice"]    = {id=44, pocket=0}, ["berryjuice"]    = {id=44, pocket=0},
    ["sacred ash"]     = {id=45, pocket=0}, ["sacredash"]     = {id=45, pocket=0},

    -- =========================================================================
    -- VITAMINS & RARE CANDY (pocket 0)
    -- =========================================================================
    ["hp up"]          = {id=63, pocket=0}, ["hpup"]          = {id=63, pocket=0},
    ["protein"]        = {id=64, pocket=0},
    ["iron"]           = {id=65, pocket=0},
    ["carbos"]         = {id=66, pocket=0},
    ["calcium"]        = {id=67, pocket=0},
    ["rare candy"]     = {id=68, pocket=0}, ["rarecandy"]     = {id=68, pocket=0},
    ["pp up"]          = {id=69, pocket=0}, ["ppup"]          = {id=69, pocket=0},
    ["zinc"]           = {id=70, pocket=0},
    ["pp max"]         = {id=71, pocket=0}, ["ppmax"]         = {id=71, pocket=0},

    -- =========================================================================
    -- BATTLE ITEMS (pocket 0)
    -- =========================================================================
    ["guard spec"]     = {id=73, pocket=0}, ["guardspec"]     = {id=73, pocket=0}, ["guard spec."] = {id=73, pocket=0},
    ["dire hit"]       = {id=74, pocket=0}, ["direhit"]       = {id=74, pocket=0},
    ["x attack"]       = {id=75, pocket=0}, ["xattack"]       = {id=75, pocket=0},
    ["x defend"]       = {id=76, pocket=0}, ["xdefend"]       = {id=76, pocket=0},
    ["x speed"]        = {id=77, pocket=0}, ["xspeed"]        = {id=77, pocket=0},
    ["x accuracy"]     = {id=78, pocket=0}, ["xaccuracy"]     = {id=78, pocket=0},
    ["x special"]      = {id=79, pocket=0}, ["xspecial"]      = {id=79, pocket=0},
    ["poke doll"]      = {id=80, pocket=0}, ["pokedoll"]      = {id=80, pocket=0},
    ["fluffy tail"]    = {id=81, pocket=0}, ["fluffytail"]    = {id=81, pocket=0},
    ["super repel"]    = {id=83, pocket=0}, ["superrepel"]    = {id=83, pocket=0},
    ["max repel"]      = {id=84, pocket=0}, ["maxrepel"]      = {id=84, pocket=0},
    ["escape rope"]    = {id=85, pocket=0}, ["escaperope"]    = {id=85, pocket=0},
    ["repel"]          = {id=86, pocket=0},

    -- =========================================================================
    -- EVOLUTION STONES (pocket 0)
    -- =========================================================================
    ["sun stone"]      = {id=93,  pocket=0}, ["sunstone"]      = {id=93,  pocket=0},
    ["moon stone"]     = {id=94,  pocket=0}, ["moonstone"]     = {id=94,  pocket=0},
    ["fire stone"]     = {id=95,  pocket=0}, ["firestone"]     = {id=95,  pocket=0},
    ["thunder stone"]  = {id=96,  pocket=0}, ["thunderstone"]  = {id=96,  pocket=0},
    ["water stone"]    = {id=97,  pocket=0}, ["waterstone"]    = {id=97,  pocket=0},
    ["leaf stone"]     = {id=98,  pocket=0}, ["leafstone"]     = {id=98,  pocket=0},

    -- =========================================================================
    -- SELLABLE ITEMS / MISC (pocket 0)
    -- =========================================================================
    ["tiny mushroom"]  = {id=103, pocket=0}, ["tinymushroom"]  = {id=103, pocket=0},
    ["big mushroom"]   = {id=104, pocket=0}, ["bigmushroom"]   = {id=104, pocket=0},
    ["pearl"]          = {id=106, pocket=0},
    ["big pearl"]      = {id=107, pocket=0}, ["bigpearl"]      = {id=107, pocket=0},
    ["stardust"]       = {id=108, pocket=0},
    ["star piece"]     = {id=109, pocket=0}, ["starpiece"]     = {id=109, pocket=0},
    ["nugget"]         = {id=110, pocket=0},
    ["heart scale"]    = {id=111, pocket=0}, ["heartscale"]    = {id=111, pocket=0},
    ["shoal salt"]     = {id=46,  pocket=0}, ["shoalsalt"]     = {id=46,  pocket=0},
    ["shoal shell"]    = {id=47,  pocket=0}, ["shoalshell"]    = {id=47,  pocket=0},
    ["red shard"]      = {id=48,  pocket=0}, ["redshard"]      = {id=48,  pocket=0},
    ["blue shard"]     = {id=49,  pocket=0}, ["blueshard"]     = {id=49,  pocket=0},
    ["yellow shard"]   = {id=50,  pocket=0}, ["yellowshard"]   = {id=50,  pocket=0},
    ["green shard"]    = {id=51,  pocket=0}, ["greenshard"]    = {id=51,  pocket=0},
    ["blue flute"]     = {id=39,  pocket=0}, ["blueflute"]     = {id=39,  pocket=0},
    ["yellow flute"]   = {id=40,  pocket=0}, ["yellowflute"]   = {id=40,  pocket=0},
    ["red flute"]      = {id=41,  pocket=0}, ["redflute"]      = {id=41,  pocket=0},
    ["black flute"]    = {id=42,  pocket=0}, ["blackflute"]    = {id=42,  pocket=0},
    ["white flute"]    = {id=43,  pocket=0}, ["whiteflute"]    = {id=43,  pocket=0},

    -- =========================================================================
    -- HELD ITEMS (pocket 0)
    -- =========================================================================
    ["bright powder"]  = {id=179, pocket=0}, ["brightpowder"]  = {id=179, pocket=0},
    ["white herb"]     = {id=180, pocket=0}, ["whiteherb"]     = {id=180, pocket=0},
    ["macho brace"]    = {id=181, pocket=0}, ["machobrace"]    = {id=181, pocket=0},
    ["exp share"]      = {id=182, pocket=0}, ["expshare"]      = {id=182, pocket=0}, ["exp. share"] = {id=182, pocket=0},
    ["quick claw"]     = {id=183, pocket=0}, ["quickclaw"]     = {id=183, pocket=0},
    ["soothe bell"]    = {id=184, pocket=0}, ["soothebell"]    = {id=184, pocket=0},
    ["mental herb"]    = {id=185, pocket=0}, ["mentalherb"]    = {id=185, pocket=0},
    ["choice band"]    = {id=186, pocket=0}, ["choiceband"]    = {id=186, pocket=0},
    ["king's rock"]    = {id=187, pocket=0}, ["kings rock"]    = {id=187, pocket=0}, ["kingsrock"] = {id=187, pocket=0},
    ["silver powder"]  = {id=188, pocket=0}, ["silverpowder"]  = {id=188, pocket=0},
    ["amulet coin"]    = {id=189, pocket=0}, ["amuletcoin"]    = {id=189, pocket=0},
    ["cleanse tag"]    = {id=190, pocket=0}, ["cleansetag"]    = {id=190, pocket=0},
    ["soul dew"]       = {id=191, pocket=0}, ["souldew"]       = {id=191, pocket=0},
    ["deep sea tooth"] = {id=192, pocket=0}, ["deepseatooth"]  = {id=192, pocket=0},
    ["deep sea scale"] = {id=193, pocket=0}, ["deepseascale"]  = {id=193, pocket=0},
    ["smoke ball"]     = {id=194, pocket=0}, ["smokeball"]     = {id=194, pocket=0},
    ["everstone"]      = {id=195, pocket=0},
    ["focus band"]     = {id=196, pocket=0}, ["focusband"]     = {id=196, pocket=0},
    ["lucky egg"]      = {id=197, pocket=0}, ["luckyegg"]      = {id=197, pocket=0},
    ["scope lens"]     = {id=198, pocket=0}, ["scopelens"]     = {id=198, pocket=0},
    ["metal coat"]     = {id=199, pocket=0}, ["metalcoat"]     = {id=199, pocket=0},
    ["leftovers"]      = {id=200, pocket=0},
    ["dragon scale"]   = {id=201, pocket=0}, ["dragonscale"]   = {id=201, pocket=0},
    ["light ball"]     = {id=202, pocket=0}, ["lightball"]     = {id=202, pocket=0},
    ["soft sand"]      = {id=203, pocket=0}, ["softsand"]      = {id=203, pocket=0},
    ["hard stone"]     = {id=204, pocket=0}, ["hardstone"]     = {id=204, pocket=0},
    ["miracle seed"]   = {id=205, pocket=0}, ["miracleseed"]   = {id=205, pocket=0},
    ["black glasses"]  = {id=206, pocket=0}, ["blackglasses"]  = {id=206, pocket=0},
    ["black belt"]     = {id=207, pocket=0}, ["blackbelt"]     = {id=207, pocket=0},
    ["magnet"]         = {id=208, pocket=0},
    ["mystic water"]   = {id=209, pocket=0}, ["mysticwater"]   = {id=209, pocket=0},
    ["sharp beak"]     = {id=210, pocket=0}, ["sharpbeak"]     = {id=210, pocket=0},
    ["poison barb"]    = {id=211, pocket=0}, ["poisonbarb"]    = {id=211, pocket=0},
    ["never melt ice"] = {id=212, pocket=0}, ["nevermeltice"]  = {id=212, pocket=0},
    ["spell tag"]      = {id=213, pocket=0}, ["spelltag"]      = {id=213, pocket=0},
    ["twisted spoon"]  = {id=214, pocket=0}, ["twistedspoon"]  = {id=214, pocket=0},
    ["charcoal"]       = {id=215, pocket=0},
    ["dragon fang"]    = {id=216, pocket=0}, ["dragonfang"]    = {id=216, pocket=0},
    ["silk scarf"]     = {id=217, pocket=0}, ["silkscarf"]     = {id=217, pocket=0},
    ["up grade"]       = {id=218, pocket=0}, ["upgrade"]       = {id=218, pocket=0},
    ["shell bell"]     = {id=219, pocket=0}, ["shellbell"]     = {id=219, pocket=0},
    ["sea incense"]    = {id=220, pocket=0}, ["seaincense"]    = {id=220, pocket=0},
    ["lax incense"]    = {id=221, pocket=0}, ["laxincense"]    = {id=221, pocket=0},
    ["lucky punch"]    = {id=222, pocket=0}, ["luckypunch"]    = {id=222, pocket=0},
    ["metal powder"]   = {id=223, pocket=0}, ["metalpowder"]   = {id=223, pocket=0},
    ["thick club"]     = {id=224, pocket=0}, ["thickclub"]     = {id=224, pocket=0},
    ["stick"]          = {id=225, pocket=0},

    -- =========================================================================
    -- CONTEST SCARVES (pocket 0)
    -- =========================================================================
    ["red scarf"]      = {id=254, pocket=0}, ["redscarf"]      = {id=254, pocket=0},
    ["blue scarf"]     = {id=255, pocket=0}, ["bluescarf"]     = {id=255, pocket=0},
    ["pink scarf"]     = {id=256, pocket=0}, ["pinkscarf"]     = {id=256, pocket=0},
    ["green scarf"]    = {id=257, pocket=0}, ["greenscarf"]    = {id=257, pocket=0},
    ["yellow scarf"]   = {id=258, pocket=0}, ["yellowscarf"]   = {id=258, pocket=0},

    -- =========================================================================
    -- KEY ITEMS (pocket 4 = POCKET_KEY_ITEMS)
    -- =========================================================================
    ["mach bike"]      = {id=259, pocket=4}, ["machbike"]      = {id=259, pocket=4},
    ["coin case"]      = {id=260, pocket=4}, ["coincase"]      = {id=260, pocket=4},
    ["itemfinder"]     = {id=261, pocket=4},
    ["old rod"]        = {id=262, pocket=4}, ["oldrod"]        = {id=262, pocket=4},
    ["good rod"]       = {id=263, pocket=4}, ["goodrod"]       = {id=263, pocket=4},
    ["super rod"]      = {id=264, pocket=4}, ["superrod"]      = {id=264, pocket=4},
    ["ss ticket"]      = {id=265, pocket=4}, ["ssticket"]      = {id=265, pocket=4},
    ["contest pass"]   = {id=266, pocket=4}, ["contestpass"]   = {id=266, pocket=4},
    ["wailmer pail"]   = {id=268, pocket=4}, ["wailmerpail"]   = {id=268, pocket=4},
    ["devon goods"]    = {id=269, pocket=4}, ["devongoods"]    = {id=269, pocket=4},
    ["soot sack"]      = {id=270, pocket=4}, ["sootsack"]      = {id=270, pocket=4},
    ["basement key"]   = {id=271, pocket=4}, ["basementkey"]   = {id=271, pocket=4},
    ["acro bike"]      = {id=272, pocket=4}, ["acrobike"]      = {id=272, pocket=4},
    ["pokeblock case"] = {id=273, pocket=4}, ["pokeblockcase"] = {id=273, pocket=4},
    ["letter"]         = {id=274, pocket=4},
    ["eon ticket"]     = {id=275, pocket=4}, ["eonticket"]     = {id=275, pocket=4},
    ["red orb"]        = {id=276, pocket=4}, ["redorb"]        = {id=276, pocket=4},
    ["blue orb"]       = {id=277, pocket=4}, ["blueorb"]       = {id=277, pocket=4},
    ["scanner"]        = {id=278, pocket=4},
    ["go goggles"]     = {id=279, pocket=4}, ["gogoggles"]     = {id=279, pocket=4},
    ["meteorite"]      = {id=280, pocket=4},
    ["root fossil"]    = {id=286, pocket=4}, ["rootfossil"]    = {id=286, pocket=4},
    ["claw fossil"]    = {id=287, pocket=4}, ["clawfossil"]    = {id=287, pocket=4},
    ["devon scope"]    = {id=288, pocket=4}, ["devonscope"]    = {id=288, pocket=4},
    ["magma emblem"]   = {id=375, pocket=4}, ["magmaemblem"]   = {id=375, pocket=4},
    ["old sea map"]    = {id=376, pocket=4}, ["oldseamap"]     = {id=376, pocket=4},

    -- =========================================================================
    -- TMs (pocket 2 = POCKET_TMS_HMS) — Emerald TM list
    -- TM01=Focus Punch TM02=Dragon Claw TM03=Water Pulse TM04=Calm Mind
    -- TM05=Roar TM06=Toxic TM07=Hail TM08=Bulk Up TM09=Bullet Seed TM10=Hidden Power
    -- TM11=Sunny Day TM12=Taunt TM13=Ice Beam TM14=Blizzard TM15=Hyper Beam
    -- TM16=Light Screen TM17=Protect TM18=Rain Dance TM19=Giga Drain TM20=Safeguard
    -- TM21=Frustration TM22=SolarBeam TM23=Iron Tail TM24=Thunderbolt TM25=Thunder
    -- TM26=Earthquake TM27=Return TM28=Dig TM29=Psychic TM30=Shadow Ball
    -- TM31=Brick Break TM32=Double Team TM33=Reflect TM34=Shock Wave TM35=Flamethrower
    -- TM36=Sludge Bomb TM37=Sandstorm TM38=Fire Blast TM39=Rock Tomb TM40=Aerial Ace
    -- TM41=Torment TM42=Facade TM43=Secret Power TM44=Rest TM45=Attract
    -- TM46=Thief TM47=Steel Wing TM48=Skill Swap TM49=Snatch TM50=Overheat
    -- HM01=Cut HM02=Fly HM03=Surf HM04=Strength HM05=Flash HM06=Rock Smash HM07=Waterfall HM08=Dive
    -- =========================================================================
    ["tm01"]  = {id=289, pocket=2}, ["tm1"]   = {id=289, pocket=2}, ["focus punch"]  = {id=289, pocket=2},
    ["tm02"]  = {id=290, pocket=2}, ["tm2"]   = {id=290, pocket=2}, ["dragon claw"]  = {id=290, pocket=2}, ["dragonclaw"] = {id=290, pocket=2},
    ["tm03"]  = {id=291, pocket=2}, ["tm3"]   = {id=291, pocket=2}, ["water pulse"]  = {id=291, pocket=2}, ["waterpulse"] = {id=291, pocket=2},
    ["tm04"]  = {id=292, pocket=2}, ["tm4"]   = {id=292, pocket=2}, ["calm mind"]    = {id=292, pocket=2}, ["calmmind"]   = {id=292, pocket=2},
    ["tm05"]  = {id=293, pocket=2}, ["tm5"]   = {id=293, pocket=2}, ["roar"]         = {id=293, pocket=2},
    ["tm06"]  = {id=294, pocket=2}, ["tm6"]   = {id=294, pocket=2}, ["toxic"]        = {id=294, pocket=2},
    ["tm07"]  = {id=295, pocket=2}, ["tm7"]   = {id=295, pocket=2}, ["hail"]         = {id=295, pocket=2},
    ["tm08"]  = {id=296, pocket=2}, ["tm8"]   = {id=296, pocket=2}, ["bulk up"]      = {id=296, pocket=2}, ["bulkup"]     = {id=296, pocket=2},
    ["tm09"]  = {id=297, pocket=2}, ["tm9"]   = {id=297, pocket=2}, ["bullet seed"]  = {id=297, pocket=2}, ["bulletseed"] = {id=297, pocket=2},
    ["tm10"]  = {id=298, pocket=2}, ["hidden power"] = {id=298, pocket=2}, ["hiddenpower"] = {id=298, pocket=2},
    ["tm11"]  = {id=299, pocket=2}, ["sunny day"]    = {id=299, pocket=2}, ["sunnyday"]    = {id=299, pocket=2},
    ["tm12"]  = {id=300, pocket=2}, ["taunt"]        = {id=300, pocket=2},
    ["tm13"]  = {id=301, pocket=2}, ["ice beam"]     = {id=301, pocket=2}, ["icebeam"]     = {id=301, pocket=2},
    ["tm14"]  = {id=302, pocket=2}, ["blizzard"]     = {id=302, pocket=2},
    ["tm15"]  = {id=303, pocket=2}, ["hyper beam"]   = {id=303, pocket=2}, ["hyperbeam"]   = {id=303, pocket=2},
    ["tm16"]  = {id=304, pocket=2}, ["light screen"] = {id=304, pocket=2}, ["lightscreen"] = {id=304, pocket=2},
    ["tm17"]  = {id=305, pocket=2}, ["protect"]      = {id=305, pocket=2},
    ["tm18"]  = {id=306, pocket=2}, ["rain dance"]   = {id=306, pocket=2}, ["raindance"]   = {id=306, pocket=2},
    ["tm19"]  = {id=307, pocket=2}, ["giga drain"]   = {id=307, pocket=2}, ["gigadrain"]   = {id=307, pocket=2},
    ["tm20"]  = {id=308, pocket=2}, ["safeguard"]    = {id=308, pocket=2},
    ["tm21"]  = {id=309, pocket=2}, ["frustration"]  = {id=309, pocket=2},
    ["tm22"]  = {id=310, pocket=2}, ["solarbeam"]    = {id=310, pocket=2}, ["solar beam"]  = {id=310, pocket=2},
    ["tm23"]  = {id=311, pocket=2}, ["iron tail"]    = {id=311, pocket=2}, ["irontail"]    = {id=311, pocket=2},
    ["tm24"]  = {id=312, pocket=2}, ["thunderbolt"]  = {id=312, pocket=2},
    ["tm25"]  = {id=313, pocket=2}, ["thunder"]      = {id=313, pocket=2},
    ["tm26"]  = {id=314, pocket=2}, ["earthquake"]   = {id=314, pocket=2},
    ["tm27"]  = {id=315, pocket=2}, ["return"]       = {id=315, pocket=2},
    ["tm28"]  = {id=316, pocket=2}, ["dig"]          = {id=316, pocket=2},
    ["tm29"]  = {id=317, pocket=2}, ["psychic"]      = {id=317, pocket=2},
    ["tm30"]  = {id=318, pocket=2}, ["shadow ball"]  = {id=318, pocket=2}, ["shadowball"]  = {id=318, pocket=2},
    ["tm31"]  = {id=319, pocket=2}, ["brick break"]  = {id=319, pocket=2}, ["brickbreak"]  = {id=319, pocket=2},
    ["tm32"]  = {id=320, pocket=2}, ["double team"]  = {id=320, pocket=2}, ["doubleteam"]  = {id=320, pocket=2},
    ["tm33"]  = {id=321, pocket=2}, ["reflect"]      = {id=321, pocket=2},
    ["tm34"]  = {id=322, pocket=2}, ["shock wave"]   = {id=322, pocket=2}, ["shockwave"]   = {id=322, pocket=2},
    ["tm35"]  = {id=323, pocket=2}, ["flamethrower"] = {id=323, pocket=2},
    ["tm36"]  = {id=324, pocket=2}, ["sludge bomb"]  = {id=324, pocket=2}, ["sludgebomb"]  = {id=324, pocket=2},
    ["tm37"]  = {id=325, pocket=2}, ["sandstorm"]    = {id=325, pocket=2},
    ["tm38"]  = {id=326, pocket=2}, ["fire blast"]   = {id=326, pocket=2}, ["fireblast"]   = {id=326, pocket=2},
    ["tm39"]  = {id=327, pocket=2}, ["rock tomb"]    = {id=327, pocket=2}, ["rocktomb"]    = {id=327, pocket=2},
    ["tm40"]  = {id=328, pocket=2}, ["aerial ace"]   = {id=328, pocket=2}, ["aerialace"]   = {id=328, pocket=2},
    ["tm41"]  = {id=329, pocket=2}, ["torment"]      = {id=329, pocket=2},
    ["tm42"]  = {id=330, pocket=2}, ["facade"]       = {id=330, pocket=2},
    ["tm43"]  = {id=331, pocket=2}, ["secret power"] = {id=331, pocket=2}, ["secretpower"] = {id=331, pocket=2},
    ["tm44"]  = {id=332, pocket=2}, ["rest"]         = {id=332, pocket=2},
    ["tm45"]  = {id=333, pocket=2}, ["attract"]      = {id=333, pocket=2},
    ["tm46"]  = {id=334, pocket=2}, ["thief"]        = {id=334, pocket=2},
    ["tm47"]  = {id=335, pocket=2}, ["steel wing"]   = {id=335, pocket=2}, ["steelwing"]   = {id=335, pocket=2},
    ["tm48"]  = {id=336, pocket=2}, ["skill swap"]   = {id=336, pocket=2}, ["skillswap"]   = {id=336, pocket=2},
    ["tm49"]  = {id=337, pocket=2}, ["snatch"]       = {id=337, pocket=2},
    ["tm50"]  = {id=338, pocket=2}, ["overheat"]     = {id=338, pocket=2},
    -- HMs
    ["hm01"]  = {id=339, pocket=2}, ["hm1"]  = {id=339, pocket=2}, ["cut"]        = {id=339, pocket=2},
    ["hm02"]  = {id=340, pocket=2}, ["hm2"]  = {id=340, pocket=2}, ["fly"]        = {id=340, pocket=2},
    ["hm03"]  = {id=341, pocket=2}, ["hm3"]  = {id=341, pocket=2}, ["surf"]       = {id=341, pocket=2},
    ["hm04"]  = {id=342, pocket=2}, ["hm4"]  = {id=342, pocket=2}, ["strength"]   = {id=342, pocket=2},
    ["hm05"]  = {id=343, pocket=2}, ["hm5"]  = {id=343, pocket=2}, ["flash"]      = {id=343, pocket=2},
    ["hm06"]  = {id=344, pocket=2}, ["hm6"]  = {id=344, pocket=2}, ["rock smash"] = {id=344, pocket=2}, ["rocksmash"] = {id=344, pocket=2},
    ["hm07"]  = {id=345, pocket=2}, ["hm7"]  = {id=345, pocket=2}, ["waterfall"]  = {id=345, pocket=2},
    ["hm08"]  = {id=346, pocket=2}, ["hm8"]  = {id=346, pocket=2}, ["dive"]       = {id=346, pocket=2},

    -- =========================================================================
    -- BERRIES (pocket 3 = POCKET_BERRIES) — full Gen III list (IDs 133-175)
    -- Status cures: Cheri(par) Chesto(slp) Pecha(psn) Rawst(brn) Aspear(frz)
    -- PP/HP: Leppa(PP) Oran(10HP) Sitrus(1/4HP) Lum(all status)
    -- EV reducers: Pomeg(HP) Kelpsy(Atk) Qualot(Def) Hondew(SpA) Grepa(SpD) Tamato(Spe)
    -- Pinch berries (raise stat at low HP): Liechi(Atk) Ganlon(Def) Salac(Spe) Petaya(SpA) Apicot(SpD)
    -- =========================================================================
    ["cheri berry"]    = {id=133, pocket=3}, ["cheriberry"]    = {id=133, pocket=3},
    ["chesto berry"]   = {id=134, pocket=3}, ["chestoberry"]   = {id=134, pocket=3},
    ["pecha berry"]    = {id=135, pocket=3}, ["pechaberry"]    = {id=135, pocket=3},
    ["rawst berry"]    = {id=136, pocket=3}, ["rawstberry"]    = {id=136, pocket=3},
    ["aspear berry"]   = {id=137, pocket=3}, ["aspearberry"]   = {id=137, pocket=3},
    ["leppa berry"]    = {id=138, pocket=3}, ["leppaberry"]    = {id=138, pocket=3},
    ["oran berry"]     = {id=139, pocket=3}, ["oranberry"]     = {id=139, pocket=3},
    ["persim berry"]   = {id=140, pocket=3}, ["persimberry"]   = {id=140, pocket=3},
    ["lum berry"]      = {id=141, pocket=3}, ["lumberry"]      = {id=141, pocket=3},
    ["sitrus berry"]   = {id=142, pocket=3}, ["sitrusberry"]   = {id=142, pocket=3},
    ["figy berry"]     = {id=143, pocket=3}, ["figyberry"]     = {id=143, pocket=3},
    ["wiki berry"]     = {id=144, pocket=3}, ["wikiberry"]     = {id=144, pocket=3},
    ["mago berry"]     = {id=145, pocket=3}, ["magoberry"]     = {id=145, pocket=3},
    ["aguav berry"]    = {id=146, pocket=3}, ["aguavberry"]    = {id=146, pocket=3},
    ["iapapa berry"]   = {id=147, pocket=3}, ["iapapaberry"]   = {id=147, pocket=3},
    ["razz berry"]     = {id=148, pocket=3}, ["razzberry"]     = {id=148, pocket=3},
    ["bluk berry"]     = {id=149, pocket=3}, ["blukberry"]     = {id=149, pocket=3},
    ["nanab berry"]    = {id=150, pocket=3}, ["nanabberry"]    = {id=150, pocket=3},
    ["wepear berry"]   = {id=151, pocket=3}, ["wepearberry"]   = {id=151, pocket=3},
    ["pinap berry"]    = {id=152, pocket=3}, ["pinapberry"]    = {id=152, pocket=3},
    ["pomeg berry"]    = {id=153, pocket=3}, ["pomegberry"]    = {id=153, pocket=3},
    ["kelpsy berry"]   = {id=154, pocket=3}, ["kelpsyberry"]   = {id=154, pocket=3},
    ["qualot berry"]   = {id=155, pocket=3}, ["qualotberry"]   = {id=155, pocket=3},
    ["hondew berry"]   = {id=156, pocket=3}, ["hondewberry"]   = {id=156, pocket=3},
    ["grepa berry"]    = {id=157, pocket=3}, ["grepaberry"]    = {id=157, pocket=3},
    ["tamato berry"]   = {id=158, pocket=3}, ["tamatoberry"]   = {id=158, pocket=3},
    ["cornn berry"]    = {id=159, pocket=3}, ["cornnberry"]    = {id=159, pocket=3},
    ["magost berry"]   = {id=160, pocket=3}, ["magostberry"]   = {id=160, pocket=3},
    ["rabuta berry"]   = {id=161, pocket=3}, ["rabutaberry"]   = {id=161, pocket=3},
    ["nomel berry"]    = {id=162, pocket=3}, ["nomelberry"]    = {id=162, pocket=3},
    ["spelon berry"]   = {id=163, pocket=3}, ["spelonberry"]   = {id=163, pocket=3},
    ["pamtre berry"]   = {id=164, pocket=3}, ["pamtreberry"]   = {id=164, pocket=3},
    ["watmel berry"]   = {id=165, pocket=3}, ["watmelberry"]   = {id=165, pocket=3},
    ["durin berry"]    = {id=166, pocket=3}, ["durinberry"]    = {id=166, pocket=3},
    ["belue berry"]    = {id=167, pocket=3}, ["belueberry"]    = {id=167, pocket=3},
    ["liechi berry"]   = {id=168, pocket=3}, ["liechiberry"]   = {id=168, pocket=3},
    ["ganlon berry"]   = {id=169, pocket=3}, ["ganlonberry"]   = {id=169, pocket=3},
    ["salac berry"]    = {id=170, pocket=3}, ["salacberry"]    = {id=170, pocket=3},
    ["petaya berry"]   = {id=171, pocket=3}, ["petayaberry"]   = {id=171, pocket=3},
    ["apicot berry"]   = {id=172, pocket=3}, ["apicotberry"]   = {id=172, pocket=3},
    ["lansat berry"]   = {id=173, pocket=3}, ["lansatberry"]   = {id=173, pocket=3},
    ["starf berry"]    = {id=174, pocket=3}, ["starfberry"]    = {id=174, pocket=3},
    ["enigma berry"]   = {id=175, pocket=3}, ["enigmaberry"]   = {id=175, pocket=3},
}

-- Give item by name — Maren should always use this, not raw IDs
function GM.give(itemName, quantity)
    quantity = quantity or 1
    local key = itemName:lower():gsub("%-", " ")
    local entry = ITEM_LOOKUP[key]
    if not entry then
        console:log("❌ Unknown item: '" .. itemName .. "' — check ITEM_LOOKUP table")
        return false
    end
    GM.giveItem(entry.id, quantity, entry.pocket)
    console:log("🎁 Gave " .. quantity .. "x " .. itemName)
    return true
end

-- =============================================================================
-- SUBSTRUCT ORDER FOR ENCRYPTION
-- =============================================================================

local SUBSTRUCT_ORDER = {
    [0]  = {1,2,3,4}, [1]  = {1,2,4,3}, [2]  = {1,3,2,4}, [3]  = {1,3,4,2}, [4]  = {1,4,2,3}, [5]  = {1,4,3,2},
    [6]  = {2,1,3,4}, [7]  = {2,1,4,3}, [8]  = {2,3,1,4}, [9]  = {2,3,4,1}, [10] = {2,4,1,3}, [11] = {2,4,3,1},
    [12] = {3,1,2,4}, [13] = {3,1,4,2}, [14] = {3,2,1,4}, [15] = {3,2,4,1}, [16] = {3,4,1,2}, [17] = {3,4,2,1},
    [18] = {4,1,2,3}, [19] = {4,1,3,2}, [20] = {4,2,1,3}, [21] = {4,2,3,1}, [22] = {4,3,1,2}, [23] = {4,3,2,1},
}

-- =============================================================================
-- PARTY POKEMON
-- =============================================================================

function GM.getPartyCount()
    return emu:read8(PARTY_COUNT_ADDR)
end

function GM.setPartyCount(count)
    emu:write8(PARTY_COUNT_ADDR, count)
end

-- Get Pokemon address
function GM.getPartyPokemonAddr(slot)
    return PLAYER_PARTY_ADDR + (slot * POKEMON_SIZE)
end

-- Heal a party Pokemon
function GM.healPokemon(slot)
    local addr = GM.getPartyPokemonAddr(slot)
    local maxHp = emu:read16(addr + 88)
    emu:write16(addr + 86, maxHp)  -- Set current HP to max
    emu:write32(addr + 80, 0)       -- Clear status
    console:log("💚 Healed party slot " .. slot)
    return true
end

-- =============================================================================
-- SAFE POKEMON MODIFICATION HELPER (handles encryption properly)
-- =============================================================================
-- This is the CORE helper for any modification that might touch personality.
-- It properly decrypts, allows modifications, re-encrypts, and recalculates checksum.

function GM.modifyPartyPokemon(slot, modifyFn)
    local addr = GM.getPartyPokemonAddr(slot)
    
    -- Step 1: Read personality, otId, compute old key
    local personality = emu:read32(addr)
    local otId = emu:read32(addr + 4)
    local oldKey = personality ~ otId
    
    -- Step 2: Decrypt ALL 4 substructs into a table
    local secureAddr = addr + 32
    local decrypted = {}  -- [0-3][0-2] = 12 words total
    for i = 0, 3 do
        decrypted[i] = {}
        for j = 0, 2 do
            local encrypted = emu:read32(secureAddr + (i * 12) + (j * 4))
            decrypted[i][j] = encrypted ~ oldKey
        end
    end
    
    -- Step 3: Build a pokemon context table for the modifier function
    local pokemon = {
        addr = addr,
        personality = personality,
        otId = otId,
        substruct_order = personality % 24,
    }
    
    -- Get substruct positions (which physical slot has which substruct type)
    local positions = SUBSTRUCT_ORDER[pokemon.substruct_order] or {1,2,3,4}
    local typeToSlot = {}  -- maps type (1-4) to physical slot (0-3)
    for i = 1, 4 do
        typeToSlot[positions[i]] = i - 1
    end
    pokemon.typeToSlot = typeToSlot
    pokemon.decrypted = decrypted
    
    -- Step 4: Call the modifier function (can modify personality!)
    local oldOrder = personality % 24
    modifyFn(pokemon)
    
    -- Step 5: If personality changed, recompute key AND rearrange substructs
    local newKey = pokemon.personality ~ otId
    local newOrder = pokemon.personality % 24
    
    if oldOrder ~= newOrder then
        -- Personality % 24 changed → substruct layout changed.
        -- Physically rearrange decrypted data so each substruct TYPE stays with its data.
        local oldPositions = SUBSTRUCT_ORDER[oldOrder] or {1,2,3,4}
        local newPositions = SUBSTRUCT_ORDER[newOrder] or {1,2,3,4}
        -- Map type → data using old layout
        local typeToData = {}
        for i = 1, 4 do
            typeToData[oldPositions[i]] = decrypted[i-1]
        end
        -- Rebuild physical layout for new order
        local rearranged = {}
        for i = 1, 4 do
            rearranged[i-1] = typeToData[newPositions[i]]
        end
        decrypted = rearranged
        console:log("🔀 Rearranged substructs: order " .. oldOrder .. " → " .. newOrder)
    end
    
    -- Step 6: Re-encrypt all substructs with the (possibly new) key
    for i = 0, 3 do
        for j = 0, 2 do
            local encrypted = decrypted[i][j] ~ newKey
            emu:write32(secureAddr + (i * 12) + (j * 4), encrypted)
        end
    end
    
    -- Step 7: Recalculate checksum from DECRYPTED data
    local checksum = 0
    for i = 0, 3 do
        for j = 0, 2 do
            local word = decrypted[i][j]
            checksum = checksum + (word & 0xFFFF)
            checksum = checksum + ((word >> 16) & 0xFFFF)
        end
    end
    emu:write16(addr + 28, checksum & 0xFFFF)
    
    -- Step 8: Write new personality if changed
    if pokemon.personality ~= personality then
        emu:write32(addr, pokemon.personality)
    end
    
    return true
end

-- Teach a move to a party Pokemon (even impossible ones!)
function GM.teachMove(slot, moveId, moveSlot)
    moveSlot = moveSlot or 1  -- Default to first move slot (1-4)
    if moveSlot < 1 or moveSlot > 4 then moveSlot = 1 end
    
    -- Get Pokemon species for validation
    local partyPtr = emu:read32(PLAYER_PARTY_ADDR)
    local pkmnPtr = partyPtr + (slot * POKEMON_SIZE)
    local speciesId = emu:read32(pkmnPtr) & 0xFFFF
    
    -- Check move compatibility (warning, not blocking)
    local isLearnable, compat = GM.isMoveLearnable(speciesId, moveId)
    local moveName = GM.getMoveName(moveId)
    if not isLearnable then
        console:log("⚠️  Warning: Move #" .. moveId .. " (" .. moveName .. ") may not be learnable by Pokemon #" .. speciesId)
    else
        console:log("✅ Move check: " .. moveName .. " is " .. compat .. " learnable")
    end
    
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- 2 = attacks substruct
        local attacksSlot = pokemon.typeToSlot[2]
        local attacksData = pokemon.decrypted[attacksSlot]
        
        -- Current moves
        local moves = {
            attacksData[0] & 0xFFFF,
            (attacksData[0] >> 16) & 0xFFFF,
            attacksData[1] & 0xFFFF,
            (attacksData[1] >> 16) & 0xFFFF,
        }
        
        -- Set the new move
        moves[moveSlot] = moveId
        
        -- Rebuild words with new move
        attacksData[0] = moves[1] | (moves[2] << 16)
        attacksData[1] = moves[3] | (moves[4] << 16)
        
        -- Set PP for the new move to 99 (generous!)
        local ppBytes = {
            attacksData[2] & 0xFF,
            (attacksData[2] >> 8) & 0xFF,
            (attacksData[2] >> 16) & 0xFF,
            (attacksData[2] >> 24) & 0xFF,
        }
        ppBytes[moveSlot] = 99
        attacksData[2] = ppBytes[1] | (ppBytes[2] << 8) | (ppBytes[3] << 16) | (ppBytes[4] << 24)
    end)
    
    console:log("🎓 Taught " .. moveName .. " to slot " .. slot .. " (move slot " .. moveSlot .. ")")
    return true
end

-- Change a Pokemon's species (evolution/transformation)
function GM.setSpecies(slot, speciesId)
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- 1 = growth substruct
        local growthSlot = pokemon.typeToSlot[1]
        local growthData = pokemon.decrypted[growthSlot]
        
        local heldItem = (growthData[0] >> 16) & 0xFFFF
        -- Apply species offset for decomp ROM
        growthData[0] = (speciesId + SPECIES_OFFSET) | (heldItem << 16)
    end)
    
    console:log("🔄 Changed slot " .. slot .. " to species " .. speciesId)
    return true
end

-- Change a Pokemon's ability
function GM.setAbility(slot, abilityNum)
    -- abilityNum: 0 = first ability, 1 = second ability, 2+ = hidden
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- 4 = misc substruct
        local miscSlot = pokemon.typeToSlot[4]
        local miscData = pokemon.decrypted[miscSlot]
        
        -- Misc substruct byte 0 bits 0-1 control ability
        miscData[0] = (miscData[0] & 0xFFFFFFFC) | (abilityNum & 0x3)
    end)
    
    console:log("⚡ Set slot " .. slot .. " ability to " .. abilityNum)
    return true
end

-- Force a Pokemon to be shiny (properly re-encrypts data)
function GM.setShiny(slot)
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- Generate shiny personality (keep low bits for nature/gender)
        local trainerId = pokemon.otId & 0xFFFF
        local secretId = (pokemon.otId >> 16) & 0xFFFF
        local low = pokemon.personality & 0xFFFF
        local high = trainerId ~ secretId ~ low
        pokemon.personality = (high << 16) | low
    end)
    console:log("✨ Made slot " .. slot .. " SHINY!")
    return true
end

-- Set a Pokemon's nature (0-24)
function GM.setNature(slot, nature)
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- Nature = personality % 25
        -- We need to modify personality to get desired nature
        local currentNature = pokemon.personality % 25
        local diff = nature - currentNature
        pokemon.personality = pokemon.personality + diff
    end)
    console:log("🎭 Set slot " .. slot .. " nature to " .. nature)
    return true
end

-- Set Pokemon nickname (max 10 chars, visible in battle!)
function GM.setNickname(slot, nickname)
    local addr = GM.getPartyPokemonAddr(slot)
    local nicknameAddr = addr + 8  -- Nickname at offset +8, 10 bytes, NOT encrypted
    
    -- Encode the string (max 10 chars)
    local text = nickname:sub(1, 10)
    local bytes = GM.encodeString(text)
    
    -- Write nickname (10 bytes max + terminator)
    for i = 1, 10 do
        local byte = bytes[i] or 0xFF  -- 0xFF = end of string
        emu:write8(nicknameAddr + i - 1, byte)
    end
    
    console:log("📝 Renamed slot " .. slot .. " to: " .. nickname)
    return true
end

-- Restore original nickname (species name)
function GM.resetNickname(slot)
    -- For now, just set to "POKEMON" - would need species name table
    GM.setNickname(slot, "POKEMON")
    return true
end

-- Set IVs (0-31 each)
function GM.setIVs(slot, hp, atk, def, spd, spatk, spdef)
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- 4 = misc substruct
        local miscSlot = pokemon.typeToSlot[4]
        local miscData = pokemon.decrypted[miscSlot]
        
        -- IVs are packed into misc substruct word 1 (bytes 4-7)
        miscData[1] = (hp & 0x1F) | ((atk & 0x1F) << 5) | ((def & 0x1F) << 10) |
                      ((spd & 0x1F) << 15) | ((spatk & 0x1F) << 20) | ((spdef & 0x1F) << 25)
    end)
    console:log("📊 Set slot " .. slot .. " IVs: " .. hp .. "/" .. atk .. "/" .. def .. "/" .. spd .. "/" .. spatk .. "/" .. spdef)
    return true
end

-- setEVs: safe alias — treats non-zero values as ADD, zeros as "no change"
-- This preserves backward compat with old Maren responses while preventing overwrites
function GM.setEVs(slot, hp, atk, def, spd, spatk, spdef)
    if hp    > 0 then GM.addEVs(slot, "hp",    hp)    end
    if atk   > 0 then GM.addEVs(slot, "atk",   atk)   end
    if def   > 0 then GM.addEVs(slot, "def",   def)   end
    if spd   > 0 then GM.addEVs(slot, "spd",   spd)   end
    if spatk > 0 then GM.addEVs(slot, "spatk", spatk) end
    if spdef > 0 then GM.addEVs(slot, "spdef", spdef) end
    console:log("💪 setEVs (additive) slot " .. slot)
    return true
end

-- Reset EVs to exact values (0-255 each) — DESTRUCTIVE, use only for full resets
-- For incremental rewards, use GM.addEVs() instead
function GM.resetEVs(slot, hp, atk, def, spd, spatk, spdef)
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- 3 = EV/condition substruct
        local evSlot = pokemon.typeToSlot[3]
        local evData = pokemon.decrypted[evSlot]
        
        evData[0] = hp | (atk << 8) | (def << 16) | (spd << 24)
        -- Preserve rest of word1 (contest stats)
        evData[1] = (evData[1] & 0xFFFF0000) | (spatk & 0xFF) | ((spdef & 0xFF) << 8)
    end)
    
    console:log("💪 Set slot " .. slot .. " EVs: " .. hp .. "/" .. atk .. "/" .. def .. "/" .. spd .. "/" .. spatk .. "/" .. spdef)
    return true
end

-- Add EVs to a single stat by name (hp/atk/def/spd/spatk/spdef), capped at 255
function GM.addEVs(slot, statName, amount)
    -- Safety: validate slot range
    local count = GM.getPartyCount()
    if slot < 0 or slot >= count then
        console:log("⚠️  addEVs: slot " .. slot .. " out of range (party=" .. count .. "), skipping")
        return false
    end
    local ok, err = pcall(function()
        GM.modifyPartyPokemon(slot, function(pokemon)
            local evSlot = pokemon.typeToSlot[3]
            local evData = pokemon.decrypted[evSlot]
            -- Read current EVs
            local word0 = evData[0]
            local word1 = evData[1]
            local curHp    = word0 & 0xFF
            local curAtk   = (word0 >> 8) & 0xFF
            local curDef   = (word0 >> 16) & 0xFF
            local curSpd   = (word0 >> 24) & 0xFF
            local curSpatk = word1 & 0xFF
            local curSpdef = (word1 >> 8) & 0xFF
            -- Add to target stat
            local s = statName:lower()
            if     s == "hp"    then curHp    = math.min(255, curHp    + amount)
            elseif s == "atk"   then curAtk   = math.min(255, curAtk   + amount)
            elseif s == "def"   then curDef   = math.min(255, curDef   + amount)
            elseif s == "spd"   then curSpd   = math.min(255, curSpd   + amount)
            elseif s == "spatk" then curSpatk = math.min(255, curSpatk + amount)
            elseif s == "spdef" then curSpdef = math.min(255, curSpdef + amount)
            end
            -- Write back
            evData[0] = curHp | (curAtk << 8) | (curDef << 16) | (curSpd << 24)
            evData[1] = (word1 & 0xFFFF0000) | (curSpatk & 0xFF) | ((curSpdef & 0xFF) << 8)
        end)
    end)
    if not ok then
        console:log("⚠️  addEVs failed (mid-evolution?): " .. tostring(err))
        return false
    end
    console:log("💪 addEVs slot " .. slot .. " +" .. amount .. " " .. statName)
    return true
end

-- Set an event flag (unlocks story events, routes, etc.)
function GM.setEventFlag(flagId, value)
    local sb1 = getSaveBlock1()
    local flagAddr = sb1 + FLAGS_OFFSET + math.floor(flagId / 8)
    local bit = flagId % 8
    
    local byte = emu:read8(flagAddr)
    if value then
        byte = byte | (1 << bit)
    else
        byte = byte & ~(1 << bit)
    end
    emu:write8(flagAddr, byte)
    
    console:log("🚩 Set event flag " .. flagId .. " to " .. tostring(value))
    return true
end

-- Give or remove a badge (badge bits are at positions 7-14)
function GM.setBadge(badgeNum, has)
    local sb1 = getSaveBlock1()
    local rawFlags = emu:read16(sb1 + BADGE_OFFSET)
    local bitPos = badgeNum + 7  -- Badge 1 = bit 7, etc.
    
    if has then
        rawFlags = rawFlags | (1 << bitPos)
    else
        rawFlags = rawFlags & ~(1 << bitPos)
    end
    
    emu:write16(sb1 + BADGE_OFFSET, rawFlags)
    console:log("🏅 Badge " .. badgeNum .. " set to " .. tostring(has))
    return true
end

-- Modify an enemy trainer's Pokemon (in battle)
-- This works on gBattleMons which is active during battle
function GM.setEnemySpecies(battleSlot, speciesId)
    -- battleSlot 1 = first enemy (0 = player's first)
    local addr = GBATTLEMONS_ADDR + (battleSlot * BATTLE_MON_SIZE)
    emu:write16(addr, speciesId)
    console:log("👹 Changed enemy slot " .. battleSlot .. " to species " .. speciesId)
    return true
end

function GM.setEnemyLevel(battleSlot, level)
    local addr = GBATTLEMONS_ADDR + (battleSlot * BATTLE_MON_SIZE)
    emu:write8(addr + 0x2C, level)
    console:log("👹 Set enemy slot " .. battleSlot .. " level to " .. level)
    return true
end

function GM.setEnemyMove(battleSlot, moveSlot, moveId)
    local addr = GBATTLEMONS_ADDR + (battleSlot * BATTLE_MON_SIZE)
    emu:write16(addr + 0x0C + ((moveSlot - 1) * 2), moveId)
    console:log("👹 Set enemy slot " .. battleSlot .. " move " .. moveSlot .. " to " .. moveId)
    return true
end

-- Heal all party Pokemon
function GM.healParty()
    local count = GM.getPartyCount()
    for i = 0, count - 1 do
        GM.healPokemon(i)
    end
    console:log("💚 Healed entire party!")
    return true
end

-- Set Pokemon level (non-encrypted display stats)
function GM.setPokemonLevel(slot, level)
    local addr = GM.getPartyPokemonAddr(slot)
    emu:write8(addr + 84, level)
    console:log("📈 Set slot " .. slot .. " to level " .. level)
    return true
end

-- Set Pokemon HP
function GM.setPokemonHP(slot, hp)
    local addr = GM.getPartyPokemonAddr(slot)
    emu:write16(addr + 86, hp)
    return true
end

-- Kill a party Pokemon (set HP to 0)
function GM.faintPokemon(slot)
    local addr = GM.getPartyPokemonAddr(slot)
    emu:write16(addr + 86, 0)
    console:log("💀 Fainted party slot " .. slot)
    return true
end

-- =============================================================================
-- BATTLE MANIPULATION
-- =============================================================================

function GM.getBattlePokemonAddr(slot)
    -- 0 = player active, 1 = enemy active
    return GBATTLEMONS_ADDR + (slot * BATTLE_MON_SIZE)
end

function GM.setBattleHP(slot, hp)
    local addr = GM.getBattlePokemonAddr(slot)
    emu:write16(addr + 0x28, hp)
    console:log("⚔️ Set battle slot " .. slot .. " HP to " .. hp)
    return true
end

function GM.killEnemy()
    GM.setBattleHP(1, 0)
    console:log("💀 Killed enemy Pokemon!")
    return true
end

function GM.setBattleStat(slot, stat, value)
    -- Stats: 0x02=atk, 0x04=def, 0x06=speed, 0x08=spatk, 0x0A=spdef
    local offsets = {
        attack = 0x02,
        defense = 0x04,
        speed = 0x06,
        spatk = 0x08,
        spdef = 0x0A
    }
    local offset = offsets[stat]
    if not offset then return false end
    
    local addr = GM.getBattlePokemonAddr(slot)
    emu:write16(addr + offset, value)
    console:log("⚔️ Set battle " .. stat .. " to " .. value)
    return true
end

-- =============================================================================
-- EVENT FLAGS
-- =============================================================================

function GM.getFlag(flagId)
    local sb1 = getSaveBlock1()
    local byteOffset = math.floor(flagId / 8)
    local bitOffset = flagId % 8
    local byte = emu:read8(sb1 + FLAGS_OFFSET + byteOffset)
    return (byte & (1 << bitOffset)) ~= 0
end

function GM.setFlag(flagId, value)
    local sb1 = getSaveBlock1()
    local byteOffset = math.floor(flagId / 8)
    local bitOffset = flagId % 8
    local byte = emu:read8(sb1 + FLAGS_OFFSET + byteOffset)
    
    if value then
        byte = byte | (1 << bitOffset)
    else
        byte = byte & ~(1 << bitOffset)
    end
    
    emu:write8(sb1 + FLAGS_OFFSET + byteOffset, byte)
    console:log("🚩 Flag " .. flagId .. " = " .. tostring(value))
    return true
end

-- =============================================================================
-- PLAYER POSITION / TELEPORT
-- =============================================================================

function GM.getPlayerPosition()
    local sb1 = getSaveBlock1()
    return {
        x = emu:read16(sb1 + PLAYER_X_OFFSET),
        y = emu:read16(sb1 + PLAYER_Y_OFFSET),
        mapGroup = emu:read8(sb1 + MAP_GROUP_OFFSET),
        mapNum = emu:read8(sb1 + MAP_NUM_OFFSET)
    }
end

function GM.setPlayerPosition(x, y)
    local sb1 = getSaveBlock1()
    emu:write16(sb1 + PLAYER_X_OFFSET, x)
    emu:write16(sb1 + PLAYER_Y_OFFSET, y)
    console:log("📍 Moved player to " .. x .. ", " .. y)
    return true
end

-- Note: Changing map requires more complex warping, position only works within same map

-- =============================================================================
-- DIALOGUE QUEUE (for timed injection)
-- =============================================================================

GM.dialogueQueue = {}

-- Queue dialogue to be injected on next dialogue trigger
function GM.queueDialogue(text)
    table.insert(GM.dialogueQueue, text)
    console:log("📝 Queued dialogue: " .. text:sub(1, 30) .. "...")
    return #GM.dialogueQueue
end

-- Clear the dialogue queue
function GM.clearQueue()
    GM.dialogueQueue = {}
    console:log("🗑️  Dialogue queue cleared")
end

-- Inject next queued dialogue (call this on dialogue_change)
function GM.injectFromQueue()
    if #GM.dialogueQueue > 0 then
        local text = table.remove(GM.dialogueQueue, 1)
        console:log("💬 Injecting queued: " .. text:sub(1, 30) .. "...")
        GM.injectDialogue(text)
        return true
    end
    return false
end

-- =============================================================================
-- DIALOGUE INJECTION
-- =============================================================================

function GM.injectDialogue(text)
    local bytes = {}
    local i = 1
    while i <= #text do
        local c = text:sub(i, i)
        if c == '\\' and i < #text then
            local next = text:sub(i+1, i+1)
            if next == 'n' then
                table.insert(bytes, 0xFE)
                i = i + 2
            elseif next == 'p' then
                table.insert(bytes, 0xFA)
                i = i + 2
            else
                i = i + 1
            end
        elseif c == '{' then
            if text:sub(i, i+7) == '{PLAYER}' then
                table.insert(bytes, 0xFD)
                table.insert(bytes, 0x01)
                i = i + 8
            else
                table.insert(bytes, encodeTable[c] or 0xAC)
                i = i + 1
            end
        else
            table.insert(bytes, encodeTable[c] or 0xAC)
            i = i + 1
        end
    end
    table.insert(bytes, 0xFF)
    
    for j = 1, #bytes do
        emu:write8(GSTRINGVAR4 + j - 1, bytes[j])
    end
    console:log("✏️ Injected dialogue: " .. text:sub(1, 30))
    return true
end

-- =============================================================================
-- INPUT INJECTION
-- =============================================================================

GM.KEY = {
    A = 0, B = 1, SELECT = 2, START = 3,
    RIGHT = 4, LEFT = 5, UP = 6, DOWN = 7,
    R = 8, L = 9
}

function GM.pressKey(key)
    emu:addKey(key)
    console:log("🎮 Pressed key " .. key)
    return true
end

function GM.releaseKey(key)
    emu:clearKey(key)
    return true
end

function GM.pressKeys(keys)
    emu:addKeys(keys)
    return true
end

function GM.releaseAllKeys()
    emu:setKeys(0)
    return true
end

-- =============================================================================
-- SAVE STATES
-- =============================================================================

function GM.saveState(slot)
    emu:saveStateSlot(slot)
    console:log("💾 Saved state to slot " .. slot)
    return true
end

function GM.loadState(slot)
    emu:loadStateSlot(slot)
    console:log("💾 Loaded state from slot " .. slot)
    return true
end

function GM.saveStateToFile(path)
    emu:saveStateFile(path)
    console:log("💾 Saved state to " .. path)
    return true
end

function GM.loadStateFromFile(path)
    emu:loadStateFile(path)
    console:log("💾 Loaded state from " .. path)
    return true
end

-- =============================================================================
-- SCREENSHOTS
-- =============================================================================

function GM.screenshot(filename)
    emu:screenshot(filename)
    console:log("📸 Screenshot saved: " .. (filename or "default"))
    return true
end

-- =============================================================================
-- EXPORT
-- =============================================================================


-- =============================================================================
-- WILD ENCOUNTER MANIPULATION
-- =============================================================================

-- Give wild Pokemon a held item (catchable loot!)
function GM.setWildHeldItem(itemId)
    if not GM.isBattleActive() then return false end
    local addr = GBATTLEMONS_ADDR + BATTLE_MON_SIZE  -- Enemy slot
    emu:write16(addr + 0x2E, itemId)
    console:log("🎁 Wild Pokemon now holds item " .. itemId)
    return true
end

-- Boost wild Pokemon (make it a challenge)
function GM.boostWildPokemon(statMultiplier)
    if not GM.isBattleActive() then return false end
    local addr = GBATTLEMONS_ADDR + BATTLE_MON_SIZE
    local stats = {0x02, 0x04, 0x06, 0x08, 0x0A}  -- atk, def, speed, spatk, spdef
    for _, offset in ipairs(stats) do
        local current = emu:read16(addr + offset)
        local boosted = math.floor(current * statMultiplier)
        emu:write16(addr + offset, math.min(boosted, 999))
    end
    console:log("💪 Wild Pokemon stats boosted by " .. statMultiplier .. "x")
    return true
end

-- Make encounter easier (for struggling player)
function GM.weakenWildPokemon(statMultiplier)
    return GM.boostWildPokemon(statMultiplier)  -- Just use < 1.0
end

-- Check if in battle
function GM.isBattleActive()
    return emu:read32(0x03005D04) == 134460365
end

-- =============================================================================
-- EXPERIENCE & PROGRESSION
-- =============================================================================

-- Add experience to a party Pokemon
function GM.addExperience(slot, amount)
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- 1 = growth substruct
        local growthSlot = pokemon.typeToSlot[1]
        local growthData = pokemon.decrypted[growthSlot]
        
        growthData[1] = growthData[1] + amount
    end)
    
    console:log("📈 Added " .. amount .. " EXP to slot " .. slot)
    return true
end

-- Set friendship/happiness (for evolution, Return power)
function GM.setFriendship(slot, value)
    GM.modifyPartyPokemon(slot, function(pokemon)
        -- 4 = misc substruct
        local miscSlot = pokemon.typeToSlot[4]
        local miscData = pokemon.decrypted[miscSlot]
        
        -- Friendship is byte 1 of misc substruct word 0
        miscData[0] = (miscData[0] & 0xFFFF00FF) | ((value & 0xFF) << 8)
    end)
    
    console:log("❤️ Set slot " .. slot .. " friendship to " .. value)
    return true
end

-- =============================================================================
-- WEATHER CONTROL
-- =============================================================================

-- Weather constants
GM.WEATHER = {
    NONE = 0,
    SUNNY_CLOUDS = 1,
    SUNNY = 2,
    RAIN = 3,
    SNOW = 4,
    THUNDERSTORM = 5,
    FOG_H = 6,
    VOLCANIC_ASH = 7,
    SANDSTORM = 8,
    FOG_D = 9,
    UNDERWATER = 10,
    SHADE = 11,
    DROUGHT = 12,
    DOWNPOUR = 13,
    UNDERWATER_BUBBLES = 14,
    ABNORMAL = 15,
    ROUTE119_CYCLE = 20,
    ROUTE123_CYCLE = 21,
}

-- Set overworld weather
function GM.setWeather(weatherType)
    -- gWeatherPtr at 0x02020004 contains current weather
    local weatherPtr = emu:read32(0x0202F7FE)
    if weatherPtr ~= 0 then
        emu:write8(weatherPtr, weatherType)
        console:log("🌤️ Set weather to " .. weatherType)
    end
    return true
end

-- =============================================================================
-- WILD ENCOUNTER FORCING
-- =============================================================================

-- Force next wild encounter to be specific species
-- This works by modifying the Pokemon AFTER it spawns but before battle text
function GM.setNextWildSpecies(speciesId)
    GM._forcedWildSpecies = speciesId
    console:log("🎯 Next wild encounter will be species " .. speciesId)
    return true
end

function GM.setNextWildLevel(level)
    GM._forcedWildLevel = level
    console:log("🎯 Next wild encounter will be level " .. level)
    return true
end

-- Call this on battle_start to apply forced encounter
function GM.applyForcedEncounter()
    if GM._forcedWildSpecies then
        GM.setEnemySpecies(1, GM._forcedWildSpecies)
        GM._forcedWildSpecies = nil
    end
    if GM._forcedWildLevel then
        GM.setEnemyLevel(1, GM._forcedWildLevel)
        GM._forcedWildLevel = nil
    end
end

-- =============================================================================
-- TRAINER MANIPULATION
-- =============================================================================

-- Trainer party is at gEnemyParty (0x0202402C for battle, different for preview)
local ENEMY_PARTY_ADDR = 0x0202402C

-- Modify trainer's Pokemon during battle
function GM.setTrainerPokemon(slot, speciesId, level)
    if not GM.isBattleActive() then return false end
    local addr = GBATTLEMONS_ADDR + (BATTLE_MON_SIZE * (slot + 1))  -- +1 because slot 0 is player
    
    -- Set species
    local rawSpecies = speciesId + SPECIES_OFFSET
    emu:write16(addr, rawSpecies)
    
    -- Set level
    emu:write8(addr + 0x2A, level)
    
    console:log("👤 Set trainer slot " .. slot .. " to species " .. speciesId .. " L" .. level)
    return true
end

-- Give trainer Pokemon a specific move
function GM.setTrainerPokemonMove(slot, moveSlot, moveId)
    if not GM.isBattleActive() then return false end
    local addr = GBATTLEMONS_ADDR + (BATTLE_MON_SIZE * (slot + 1))
    local moveAddr = addr + 0x0C + (moveSlot * 2)
    emu:write16(moveAddr, moveId)
    console:log("👤 Set trainer slot " .. slot .. " move " .. moveSlot .. " to " .. moveId)
    return true
end

-- =============================================================================
-- ENCOUNTER RATE
-- =============================================================================

-- Repel effect (0 = no repel, otherwise steps remaining)
function GM.setRepelSteps(steps)
    local sb1 = getSaveBlock1()
    emu:write16(sb1 + 0x0A, steps)  -- Repel steps offset
    console:log("🚫 Set repel steps to " .. steps)
    return true
end

-- Force encounter on next step (by setting encounter rate high)
function GM.forceEncounter()
    -- This is tricky - encounters are random
    -- Best we can do is set repel to 0 and hope
    GM.setRepelSteps(0)
    console:log("⚡ Encounter will happen soon")
    return true
end

return GM
