-- ============================================================================
-- Pokemon Emerald GM - Event Detection Module
-- Push-based event system with immediate notifications
-- VERSION: 2026-02-07-v11 (clean battle text)
-- ============================================================================

console:log("📦 Events.lua VERSION: 2026-02-07-final")

local Events = {}

-- ============================================================================
-- CONFIGURATION
-- ============================================================================

-- ROM type detection and species offset
Events.ROM_TYPES = {
    ["605b89b67018abcea91e693a4dd25be3"] = {name = "Retail US", speciesOffset = 0},
    ["6bdfe89e24c53d0a69b1053e8e289939"] = {name = "Decomp Build", speciesOffset = 0},  -- Python handles mapping
}

-- Memory addresses (Pokemon Emerald US)
Events.ADDRS = {
    -- Save blocks
    SAVE_BLOCK1_PTR = 0x03005D8C,
    SAVE_BLOCK2_PTR = 0x03005D90,
    
    -- Battle detection (callback2 is most reliable)
    CALLBACK2 = 0x03005D04,
    BATTLE_CALLBACK = 134460365,     -- Battle active
    OVERWORLD_CALLBACK = 134471537,  -- Overworld active
    
    -- Battle data
    BATTLE_STRUCT = 0x02022FEC,
    BATTLE_OUTCOME = 0x0202427C,
    GBATTLEMONS = 0x02024084,
    BATTLE_MON_SIZE = 88,
    
    -- Enemy party (for trainer battles)
    ENEMY_PARTY = 0x0202402C,
    ENEMY_PARTY_COUNT = 0x02024029,
    
    -- Party
    PLAYER_PARTY = 0x020244EC,
    PARTY_COUNT = 0x020244E9,
    POKEMON_SIZE = 100,
    
    -- Map/location (offsets from saveBlock1)
    MAP_GROUP_OFFSET = 0x04,
    MAP_NUM_OFFSET = 0x05,
    PLAYER_X_OFFSET = 0x00,
    PLAYER_Y_OFFSET = 0x02,
    
    -- Badges/money (offsets from saveBlock1)
    MONEY_OFFSET = 0x0490,
    -- Flags array is at 0x1270, badge flags start at flag 0x867
    -- Byte offset = 0x1270 + (0x867 / 8) = 0x1270 + 0x10C = 0x137C
    BADGE_OFFSET = 0x137C,
    
    -- Dialogue
    GSTRINGVAR4 = 0x02021FC4,
    GDISPLAYEDSTRINGBATTLE = 0x02022E2C,  -- Battle message buffer (300 bytes) - CORRECT ADDRESS
    
    -- Bag/Inventory (offsets from saveBlock1)
    -- Bag pocket offsets from pokeemerald source
    BAG_ITEMS_OFFSET = 0x0560,      -- bagPocket_Items
    BAG_KEYITEMS_OFFSET = 0x05D8,   -- bagPocket_KeyItems
    BAG_POKEBALLS_OFFSET = 0x0650,  -- bagPocket_PokeBalls
    BAG_TMHM_OFFSET = 0x0690,       -- bagPocket_TMHM
    BAG_BERRIES_OFFSET = 0x0790,    -- bagPocket_Berries
}

-- Battle outcome values
Events.BATTLE_OUTCOMES = {
    [0] = "none",
    [1] = "won",
    [2] = "lost",
    [3] = "draw",
    [4] = "ran",
    [5] = "player_teleported",
    [6] = "mon_fled",
    [7] = "caught",
    [8] = "no_safari_balls",
    [9] = "forfeited",
    [10] = "mon_teleported",
}

-- Safari Zone maps (Hoenn)
-- Routes 121-123 and the Safari Zone building
Events.SAFARI_ZONE_MAPS = {
    ["15,4"] = "Route 121",     -- Entrance area
    ["15,5"] = "Route 122",     -- Main area
    ["15,3"] = "Route 123",     -- Exit area
    ["16,2"] = "Safari Zone",   -- Building interior
}

-- Function to detect if current map is Safari Zone
function Events.isSafariZone()
    local mapKey = Events.getMapKey()
    return Events.SAFARI_ZONE_MAPS[mapKey] ~= nil
end

-- ============================================================================
-- TRACKED STATE (for change detection)
-- ============================================================================

Events.tracked = {
    mapKey = nil,           -- "group,num"
    inBattle = false,
    badges = 0,
    partyHash = nil,        -- Quick hash for party change detection
    partySpecies = {},      -- List of species IDs for catch detection
    partyCount = 0,
    dialogueHash = 0,
    lastBattleOutcome = 0,
    battleEndDebounce = 0,  -- Frames to wait before firing battle_end
    pendingOutcome = 0,     -- Captured outcome when battle first ends
    pendingOutcomeName = "none",
    
    -- Exploration buffer (batched events)
    explorationBuffer = {
        startMap = nil,
        itemsGained = 0,
        moneyStart = 0,
        moneyNow = 0,
        dialogueCount = 0,
        dialogueTexts = {},  -- Array of dialogue strings captured
        levelUps = {},       -- {species, oldLevel, newLevel}
        partyLevels = {},    -- Snapshot of party levels at buffer start
    },
    initialized = false,    -- Suppress events until first init complete
    mapTransitionCooldown = 0,  -- Frames since last map transition
    itemCount = 0,          -- Total items in bag (for pickup detection)
}

-- Debounce config
Events.BATTLE_END_DEBOUNCE_FRAMES = 30  -- Wait ~0.5 seconds before confirming battle end

-- ============================================================================
-- ROM DETECTION
-- ============================================================================

function Events.detectROM()
    -- Read game code from ROM header (0x080000AC, 4 bytes)
    local gameCode = ""
    for i = 0, 3 do
        gameCode = gameCode .. string.char(emu:read8(0x080000AC + i))
    end
    
    if gameCode ~= "BPEE" then
        console:log("⚠️  WARNING: Expected BPEE (Emerald US), got " .. gameCode)
    end
    
    -- For now, default to decomp offset since that's what we're using
    -- TODO: Compute actual MD5 and look up in ROM_TYPES table
    Events.SPECIES_OFFSET = 0  -- Use raw internal IDs (Python has emerald_species.json)
    
    console:log("📋 ROM: " .. gameCode .. ", Species Offset: " .. Events.SPECIES_OFFSET)
    return gameCode
end

-- ============================================================================
-- UTILITY FUNCTIONS
-- ============================================================================

function Events.getSaveBlock1()
    return emu:read32(Events.ADDRS.SAVE_BLOCK1_PTR)
end

function Events.getSaveBlock2()
    return emu:read32(Events.ADDRS.SAVE_BLOCK2_PTR)
end

-- ============================================================================
-- STATE READERS
-- ============================================================================

function Events.getMapKey()
    local sb1 = Events.getSaveBlock1()
    if sb1 == 0 then return "0,0" end
    local group = emu:read8(sb1 + Events.ADDRS.MAP_GROUP_OFFSET)
    local num = emu:read8(sb1 + Events.ADDRS.MAP_NUM_OFFSET)
    return group .. "," .. num
end

function Events.getMapInfo()
    local sb1 = Events.getSaveBlock1()
    if sb1 == 0 then return {group = 0, num = 0, x = 0, y = 0} end
    return {
        group = emu:read8(sb1 + Events.ADDRS.MAP_GROUP_OFFSET),
        num = emu:read8(sb1 + Events.ADDRS.MAP_NUM_OFFSET),
        x = emu:read16(sb1 + Events.ADDRS.PLAYER_X_OFFSET),
        y = emu:read16(sb1 + Events.ADDRS.PLAYER_Y_OFFSET),
    }
end

-- Battle callback auto-detection
Events.detectedBattleCallback = nil
Events.callbackCheckCounter = 0

function Events.isBattleActive()
    local callback2 = emu:read32(Events.ADDRS.CALLBACK2)
    
    -- If we've detected the callback, use it
    if Events.detectedBattleCallback then
        return callback2 == Events.detectedBattleCallback
    end
    
    -- Known battle callback addresses for different ROM builds
    local battleCallbacks = {
        134460365,  -- Retail US
        134461233,  -- Decomp build (approx)
    }
    
    for _, cb in ipairs(battleCallbacks) do
        if callback2 == cb then
            Events.detectedBattleCallback = cb
            console:log("🎯 Battle callback detected: " .. cb)
            return true
        end
    end
    
    -- Debug: log unknown callbacks occasionally
    Events.callbackCheckCounter = Events.callbackCheckCounter + 1
    if Events.callbackCheckCounter % 3600 == 1 then  -- Every ~60 seconds
        console:log("📍 Current callback2: " .. callback2 .. " (looking for battle)")
    end
    
    return false
end

function Events.isInOverworld()
    local callback2 = emu:read32(Events.ADDRS.CALLBACK2)
    return callback2 == Events.ADDRS.OVERWORLD_CALLBACK
end

function Events.getBattleInfo()
    local flags = emu:read32(Events.ADDRS.BATTLE_STRUCT)
    return {
        is_wild = (flags & 0x04) ~= 0,
        is_trainer = (flags & 0x08) ~= 0,
        is_double = (flags & 0x01) ~= 0,
        is_safari = Events.isSafariZone(),
        flags = flags,
    }
end

function Events.getBattleOutcome()
    local outcome = emu:read8(Events.ADDRS.BATTLE_OUTCOME)
    return outcome, Events.BATTLE_OUTCOMES[outcome] or "unknown"
end

-- Read battle outcome from memory
function Events.inferBattleOutcome()
    local outcome = emu:read8(Events.ADDRS.BATTLE_OUTCOME)
    local outcomeName = Events.BATTLE_OUTCOMES[outcome] or "unknown"
    
    -- If outcome is still 0, try to infer from tracked state
    if outcome == 0 then
        -- Check if we caught something (party grew)
        if Events.tracked.partyCaughtPokemon then
            return 7, "caught"
        end
        -- Check if enemy was defeated
        if Events.tracked.enemyDefeated then
            return 1, "won"
        end
    end
    
    return outcome, outcomeName
end

function Events.getBadges()
    local sb1 = Events.getSaveBlock1()
    if sb1 == 0 then return 0, 0 end
    -- Read u16 and shift right by 7 to align badge 1 to bit 0
    -- Badge flags are 0x867-0x86E, which means badge 1 is bit 7 of the byte
    local rawFlags = emu:read16(sb1 + Events.ADDRS.BADGE_OFFSET)
    local badges = (rawFlags >> 7) & 0xFF  -- Extract 8 badge bits
    local count = 0
    for i = 0, 7 do
        if (badges >> i) & 1 == 1 then count = count + 1 end
    end
    return badges, count
end

function Events.getPartyCount()
    return emu:read8(Events.ADDRS.PARTY_COUNT)
end

-- Quick hash of party for change detection (species + HP)
function Events.hashParty()
    local hash = 0
    local count = Events.getPartyCount()
    if count > 6 then count = 6 end
    
    for slot = 0, count - 1 do
        local addr = Events.ADDRS.PLAYER_PARTY + (slot * Events.ADDRS.POKEMON_SIZE)
        local personality = emu:read32(addr)
        if personality ~= 0 then
            -- Include species (from growth substruct) and HP
            local otId = emu:read32(addr + 4)
            local key = personality ~ otId  -- 32-bit XOR (CORRECT!)
            local secureAddr = addr + 32
            
            -- Get substruct order
            local order = personality % 24
            local positions = Events.getSubstructPositions(order)
            
            -- Read species from growth substruct
            local growthAddr = secureAddr + (positions[0] * 12)
            local word0 = emu:read32(growthAddr) ~ key
            local species = (word0 & 0xFFFF) - Events.SPECIES_OFFSET
            
            -- Read HP
            local hp = emu:read16(addr + 86)
            local maxHp = emu:read16(addr + 88)
            
            -- Add to hash
            hash = hash + (species * (slot + 1) * 1000) + (hp * (slot + 1))
        end
    end
    
    return hash
end

-- Get list of species IDs in party (for catch detection)
function Events.getPartySpeciesList()
    local species = {}
    local count = Events.getPartyCount()
    if count > 6 then count = 6 end
    
    for slot = 0, count - 1 do
        local addr = Events.ADDRS.PLAYER_PARTY + (slot * Events.ADDRS.POKEMON_SIZE)
        local personality = emu:read32(addr)
        if personality ~= 0 then
            local otId = emu:read32(addr + 4)
            local key = personality ~ otId  -- 32-bit XOR
            local secureAddr = addr + 32
            
            local order = personality % 24
            local positions = Events.getSubstructPositions(order)
            local growthAddr = secureAddr + (positions[0] * 12)
            local word0 = emu:read32(growthAddr) ~ key
            local speciesId = (word0 & 0xFFFF) - Events.SPECIES_OFFSET
            
            if speciesId > 0 and speciesId <= 440 then
                table.insert(species, {slot = slot, species = speciesId})
            end
        end
    end
    
    return species
end

-- Substruct order lookup table
-- Correct substruct order table from pokeemerald
-- Format: position → type (0=Growth, 1=Attacks, 2=EVs, 3=Misc)
Events.SUBSTRUCT_ORDERS = {
    [0]  = {[0]=0,[1]=1,[2]=2,[3]=3}, [1]  = {[0]=0,[1]=1,[2]=3,[3]=2},
    [2]  = {[0]=0,[1]=2,[2]=1,[3]=3}, [3]  = {[0]=0,[1]=2,[2]=3,[3]=1},
    [4]  = {[0]=0,[1]=3,[2]=1,[3]=2}, [5]  = {[0]=0,[1]=3,[2]=2,[3]=1},
    [6]  = {[0]=1,[1]=0,[2]=2,[3]=3}, [7]  = {[0]=1,[1]=0,[2]=3,[3]=2},
    [8]  = {[0]=1,[1]=2,[2]=0,[3]=3}, [9]  = {[0]=1,[1]=2,[2]=3,[3]=0},
    [10] = {[0]=1,[1]=3,[2]=0,[3]=2}, [11] = {[0]=1,[1]=3,[2]=2,[3]=0},
    [12] = {[0]=2,[1]=0,[2]=1,[3]=3}, [13] = {[0]=2,[1]=0,[2]=3,[3]=1},
    [14] = {[0]=2,[1]=1,[2]=0,[3]=3}, [15] = {[0]=2,[1]=1,[2]=3,[3]=0},
    [16] = {[0]=2,[1]=3,[2]=0,[3]=1}, [17] = {[0]=2,[1]=3,[2]=1,[3]=0},
    [18] = {[0]=3,[1]=0,[2]=1,[3]=2}, [19] = {[0]=3,[1]=0,[2]=2,[3]=1},
    [20] = {[0]=3,[1]=1,[2]=0,[3]=2}, [21] = {[0]=3,[1]=1,[2]=2,[3]=0},
    [22] = {[0]=3,[1]=2,[2]=0,[3]=1}, [23] = {[0]=3,[1]=2,[2]=1,[3]=0},
}

function Events.getSubstructPositions(order)
    -- Returns table mapping substruct TYPE to POSITION
    -- e.g., positions[0] = position of growth substruct
    local orderTable = Events.SUBSTRUCT_ORDERS[order]
    local positions = {}
    for pos = 0, 3 do
        local subType = orderTable[pos]
        positions[subType] = pos
    end
    return positions
end

-- Count total items in bag (for pickup detection)
function Events.countBagItems()
    local sb1 = Events.getSaveBlock1()
    if sb1 == 0 or sb1 < 0x02000000 or sb1 > 0x03000000 then 
        return Events.tracked.itemCount  -- Return last known good value
    end
    
    local total = 0
    local pockets = {
        {offset = Events.ADDRS.BAG_ITEMS_OFFSET, slots = 30},      -- Items
        {offset = Events.ADDRS.BAG_KEYITEMS_OFFSET, slots = 30},  -- Key Items
        {offset = Events.ADDRS.BAG_POKEBALLS_OFFSET, slots = 16}, -- Poke Balls
        {offset = Events.ADDRS.BAG_TMHM_OFFSET, slots = 64},      -- TMs/HMs
        {offset = Events.ADDRS.BAG_BERRIES_OFFSET, slots = 46},   -- Berries
    }
    
    for _, pocket in ipairs(pockets) do
        for i = 0, pocket.slots - 1 do
            local itemAddr = sb1 + pocket.offset + (i * 4)
            local itemId = emu:read16(itemAddr)
            local quantity = emu:read16(itemAddr + 2)
            -- Validate: itemId should be reasonable (< 1000), quantity < 100
            if itemId > 0 and itemId < 1000 and quantity > 0 and quantity < 100 then
                total = total + quantity
            end
        end
    end
    
    -- Sanity check: if total is way off from last known, skip update
    if total > 1000 then
        return Events.tracked.itemCount
    end
    
    return total
end

-- Get player's money
function Events.getMoney()
    local sb1 = Events.getSaveBlock1()
    local sb2 = Events.getSaveBlock2()
    if sb1 == 0 or sb2 == 0 then return nil end  -- Return nil for invalid read
    
    -- Validate pointers are in EWRAM range
    if sb1 < 0x02000000 or sb1 > 0x02040000 then return nil end
    if sb2 < 0x02000000 or sb2 > 0x02040000 then return nil end
    
    -- Money is encrypted: value XOR key
    local money = emu:read32(sb1 + 0x0490)
    local key = emu:read32(sb2 + 0xAC)
    local decrypted = money ~ key
    
    -- Sanity check: money should be 0-999999 (max in Pokemon)
    if decrypted < 0 or decrypted > 999999 then
        return nil  -- Invalid read, skip
    end
    
    return decrypted
end

-- Start a new exploration buffer
function Events.startExplorationBuffer()
    local buf = Events.tracked.explorationBuffer
    buf.startMap = Events.tracked.mapKey
    buf.itemsGained = 0
    buf.moneyStart = Events.getMoney() or 0  -- Default to 0 if invalid read
    buf.moneyNow = buf.moneyStart
    buf.dialogueCount = 0
    buf.dialogueTexts = {}
    buf.levelUps = {}
    
    -- Snapshot party levels
    buf.partyLevels = {}
    local party = State and State.getParty() or {}
    for i, p in ipairs(party) do
        buf.partyLevels[i] = {species = p.species, level = p.level}
    end
end

-- Check for level ups by comparing to buffer snapshot
function Events.checkLevelUps()
    local buf = Events.tracked.explorationBuffer
    local party = State and State.getParty() or {}
    
    for i, p in ipairs(party) do
        local old = buf.partyLevels[i]
        if old and old.species == p.species and p.level > old.level then
            table.insert(buf.levelUps, {
                species = p.species,
                oldLevel = old.level,
                newLevel = p.level,
            })
            -- Update snapshot so we don't double-count
            buf.partyLevels[i].level = p.level
        end
    end
end

-- Flush exploration buffer and emit summary
function Events.flushExplorationBuffer(trigger)
    local buf = Events.tracked.explorationBuffer
    
    -- Check for level ups before flushing
    Events.checkLevelUps()
    
    -- Calculate money change (only if both reads are valid)
    local currentMoney = Events.getMoney()
    local moneyChange = 0
    if currentMoney and buf.moneyStart and buf.moneyStart > 0 then
        moneyChange = currentMoney - buf.moneyStart
        buf.moneyNow = currentMoney
    end
    
    -- Only emit if something interesting happened
    local hasContent = buf.itemsGained > 0 or 
                       moneyChange ~= 0 or 
                       buf.dialogueCount > 0 or 
                       #buf.levelUps > 0
    
    if hasContent then
        Events.emit("exploration_summary", {
            trigger = trigger,
            fromMap = buf.startMap,
            toMap = Events.tracked.mapKey,
            itemsGained = buf.itemsGained,
            moneyChange = moneyChange,
            dialogueCount = buf.dialogueCount,
            dialogueTexts = buf.dialogueTexts,  -- Actual dialogue for agent context
            levelUps = buf.levelUps,
        })
    end
    
    -- Reset buffer for next segment
    Events.startExplorationBuffer()
end

-- Get enemy Pokemon data (in battle)
function Events.getEnemyPokemon()
    if not Events.isBattleActive() then return nil end
    
    local addr = Events.ADDRS.GBATTLEMONS + Events.ADDRS.BATTLE_MON_SIZE  -- Slot 1 = enemy
    local rawSpecies = emu:read16(addr)
    local species = rawSpecies - Events.SPECIES_OFFSET
    
    if species <= 0 or species > 440 then return nil end
    
    local hp = emu:read16(addr + 0x28)
    local level = emu:read8(addr + 0x2A)
    local maxHp = emu:read16(addr + 0x2C)
    
    if maxHp == 0 or maxHp > 999 or level == 0 or level > 100 then return nil end
    
    return {
        species = species,
        level = level,
        hp = hp,
        maxHp = maxHp,
        hpPercent = math.floor((hp / maxHp) * 100),
        move1 = emu:read16(addr + 0x0C),
        move2 = emu:read16(addr + 0x0E),
        move3 = emu:read16(addr + 0x10),
        move4 = emu:read16(addr + 0x12),
    }
end

-- Get player's active battle Pokemon data
function Events.getPlayerBattleMon()
    if not Events.isBattleActive() then return nil end
    
    local addr = Events.ADDRS.GBATTLEMONS  -- Slot 0 = player
    local rawSpecies = emu:read16(addr)
    local species = rawSpecies - Events.SPECIES_OFFSET
    
    if species <= 0 or species > 440 then return nil end
    
    local hp = emu:read16(addr + 0x28)
    local level = emu:read8(addr + 0x2A)
    local maxHp = emu:read16(addr + 0x2C)
    local status = emu:read32(addr + 0x4C)  -- Status conditions
    
    if maxHp == 0 or maxHp > 999 or level == 0 or level > 100 then return nil end
    
    return {
        species = species,
        level = level,
        hp = hp,
        maxHp = maxHp,
        status = status,  -- Bit flags for status conditions
    }
end

-- Get enemy trainer's full party info (for trainer battles)
function Events.getEnemyParty()
    if not Events.isBattleActive() then return nil end
    
    local battleInfo = Events.getBattleInfo()
    if not battleInfo.is_trainer then return nil end
    
    local party = {}
    local count = emu:read8(Events.ADDRS.ENEMY_PARTY_COUNT)
    if count == 0 or count > 6 then count = 6 end  -- Fallback
    
    for slot = 0, count - 1 do
        local addr = Events.ADDRS.ENEMY_PARTY + (slot * Events.ADDRS.POKEMON_SIZE)
        local personality = emu:read32(addr)
        if personality ~= 0 then
            -- Read basic info from battle mons if available
            local battleAddr = Events.ADDRS.GBATTLEMONS + (Events.ADDRS.BATTLE_MON_SIZE * (slot + 1))
            local species = emu:read16(battleAddr) - Events.SPECIES_OFFSET
            local level = emu:read8(battleAddr + 0x2A)
            local hp = emu:read16(battleAddr + 0x28)
            local maxHp = emu:read16(battleAddr + 0x2C)
            
            if species > 0 and species < 500 and level > 0 then
                table.insert(party, {
                    slot = slot,
                    species = species,
                    level = level,
                    hp = hp,
                    maxHp = maxHp,
                    fainted = (hp == 0),
                })
            end
        end
    end
    
    return party
end

-- ============================================================================
-- DIALOGUE
-- ============================================================================

function Events.getDialogueHash()
    local hash = 0
    for i = 0, 63 do
        local byte = emu:read8(Events.ADDRS.GSTRINGVAR4 + i)
        if byte == 0xFF then break end
        hash = hash + byte * (i + 1)
    end
    return hash
end

-- Character decoding table for Gen 3
local CHAR_MAP = {
    [0x00] = " ", [0x01] = " ", [0xAB] = "!", [0xAC] = "?", [0xAD] = ".", [0xAE] = "-",
    [0xB0] = "...", [0xB1] = '"', [0xB2] = '"', [0xB3] = "'", [0xB4] = "'",
    [0xB5] = "'", [0xB6] = "'", [0xB8] = ",", [0xB9] = "/", [0xBA] = "/",
    [0xBB] = "A", [0xBC] = "B", [0xBD] = "C", [0xBE] = "D", [0xBF] = "E",
    [0xC0] = "F", [0xC1] = "G", [0xC2] = "H", [0xC3] = "I", [0xC4] = "J",
    [0xC5] = "K", [0xC6] = "L", [0xC7] = "M", [0xC8] = "N", [0xC9] = "O",
    [0xCA] = "P", [0xCB] = "Q", [0xCC] = "R", [0xCD] = "S", [0xCE] = "T",
    [0xCF] = "U", [0xD0] = "V", [0xD1] = "W", [0xD2] = "X", [0xD3] = "Y",
    [0xD4] = "Z", [0xD5] = "a", [0xD6] = "b", [0xD7] = "c", [0xD8] = "d",
    [0xD9] = "e", [0xDA] = "f", [0xDB] = "g", [0xDC] = "h", [0xDD] = "i",
    [0xDE] = "j", [0xDF] = "k", [0xE0] = "l", [0xE1] = "m", [0xE2] = "n",
    [0xE3] = "o", [0xE4] = "p", [0xE5] = "q", [0xE6] = "r", [0xE7] = "s",
    [0xE8] = "t", [0xE9] = "u", [0xEA] = "v", [0xEB] = "w", [0xEC] = "x",
    [0xED] = "y", [0xEE] = "z", [0xA1] = "0", [0xA2] = "1", [0xA3] = "2",
    [0xA4] = "3", [0xA5] = "4", [0xA6] = "5", [0xA7] = "6", [0xA8] = "7",
    [0xA9] = "8", [0xAA] = "9", [0xFE] = "\n", [0xFA] = " ", [0xFB] = " ",
}

function Events.getDialogueText()
    local text = ""
    for i = 0, 255 do
        local byte = emu:read8(Events.ADDRS.GSTRINGVAR4 + i)
        if byte == 0xFF then break end
        text = text .. (CHAR_MAP[byte] or "")
    end
    return text
end

function Events.getBattleText()
    local text = ""
    for i = 0, 299 do
        local byte = emu:read8(Events.ADDRS.GDISPLAYEDSTRINGBATTLE + i)
        if byte == 0xFF then break end
        text = text .. (CHAR_MAP[byte] or "")
    end
    return text
end

-- ============================================================================
-- EVENT CALLBACKS
-- ============================================================================

Events.callbacks = {}

function Events.on(eventType, callback)
    if not Events.callbacks[eventType] then
        Events.callbacks[eventType] = {}
    end
    table.insert(Events.callbacks[eventType], callback)
end

function Events.emit(eventType, data)
    local cbs = Events.callbacks[eventType]
    if cbs then
        for _, cb in ipairs(cbs) do
            cb(data)
        end
    end
    
    -- Also emit to "all" subscribers
    local allCbs = Events.callbacks["all"]
    if allCbs then
        for _, cb in ipairs(allCbs) do
            cb(eventType, data)
        end
    end
end

-- ============================================================================
-- MAIN FRAME HANDLER (Push-based detection)
-- ============================================================================

function Events.checkFrame()
    -- 1. MAP TRANSITIONS
    local currentMap = Events.getMapKey()
    if currentMap ~= Events.tracked.mapKey then
        local oldMap = Events.tracked.mapKey
        
        -- Flush exploration buffer before map change (if not first frame)
        if oldMap ~= nil and Events.tracked.explorationBuffer.startMap ~= nil then
            Events.flushExplorationBuffer("map_change")
        end
        
        Events.tracked.mapKey = currentMap
        Events.tracked.mapTransitionCooldown = 60  -- 1 second cooldown after map change
        
        if oldMap ~= nil then  -- Don't fire on first frame
            Events.emit("map_transition", {
                from = oldMap,
                to = currentMap,
                mapInfo = Events.getMapInfo(),
            })
        end
        
        -- Start new exploration buffer for this map
        Events.startExplorationBuffer()
    end
    
    -- Decrement cooldown
    if Events.tracked.mapTransitionCooldown > 0 then
        Events.tracked.mapTransitionCooldown = Events.tracked.mapTransitionCooldown - 1
    end
    
    -- 2. BATTLE STATE - use callback-based detection with hard locking
    local callback2 = emu:read32(Events.ADDRS.CALLBACK2)
    -- Battle callbacks: wild, trainer, double - check if in battle range
    local isBattleCallback = (callback2 >= 134458305 and callback2 <= 134461233)
    local isOverworldCallback = (callback2 == Events.ADDRS.OVERWORLD_CALLBACK)
    
    -- Track stable frames (callback must be stable for 30 frames to trigger)
    if not Events.tracked.lastCallback then Events.tracked.lastCallback = 0 end
    if not Events.tracked.callbackStableFrames then Events.tracked.callbackStableFrames = 0 end
    
    if callback2 == Events.tracked.lastCallback then
        Events.tracked.callbackStableFrames = Events.tracked.callbackStableFrames + 1
    else
        Events.tracked.callbackStableFrames = 0
        Events.tracked.lastCallback = callback2
    end
    
    -- Only transition on STABLE callback (30+ frames = 0.5 sec)
    local stableThreshold = 30
    
    if isBattleCallback and not Events.tracked.inBattle and Events.tracked.callbackStableFrames >= stableThreshold then
        -- Flush exploration buffer before battle
        if Events.tracked.explorationBuffer.startMap ~= nil then
            Events.flushExplorationBuffer("battle_start")
        end
        
        -- Battle started (immediate)
        Events.tracked.inBattle = true
        Events.tracked.battleStartCooldown = 120  -- 2 second cooldown to prevent flapping
        Events.tracked.battleEndDebounce = 0
        Events.tracked.lastBattleOutcome = 0  -- Reset
        Events.tracked.battleLog = {}  -- Reset battle log
        Events.tracked.battleDialogue = {}  -- All text shown during battle
        Events.tracked.pendingOutcome = 0  -- Reset pending outcome
        Events.tracked.pendingOutcomeName = "none"
        Events.tracked.battleStartPartyCount = Events.getPartyCount()  -- For catch detection
        Events.tracked.partyCaughtPokemon = false
        Events.tracked.enemyDefeated = false
        Events.tracked.battleDuration = 0  -- Track battle length
        Events._battleTextLogged = false  -- Reset for new battle
        Events.tracked.battleEndEmitted = false  -- Prevent double emit
        
        -- Reset text capture for this battle
        Events.tracked.battleTexts = {}
        Events.tracked.textSeen = {}
        Events.tracked.currentBattleMsg = ""
        -- Start counting from current recentText length (only capture battle-specific texts)
        Events.tracked.lastBattleTextCount = #(Events.tracked.recentText or {})
        
        -- Initialize HP tracking
        local playerMon = Events.getPlayerBattleMon()
        local enemyMon = Events.getEnemyPokemon()
        Events.tracked.lastPlayerHP = playerMon and playerMon.hp or 0
        Events.tracked.lastEnemyHP = enemyMon and enemyMon.hp or 0
        Events.tracked.lastEnemyMaxHP = enemyMon and enemyMon.maxHp or 0  -- Save max HP for win detection
        
        local battleInfo = Events.getBattleInfo()
        local enemyParty = nil
        if battleInfo.is_trainer then
            enemyParty = Events.getEnemyParty()
        end
        
        Events.emit("battle_start", {
            battleInfo = battleInfo,
            enemy = Events.getEnemyPokemon(),
            enemyParty = enemyParty,
        })
    elseif isOverworldCallback and Events.tracked.inBattle and Events.tracked.callbackStableFrames >= stableThreshold then
        -- Stable overworld callback = battle ended
        
        -- Check for catch (party grew during battle)
        local currentPartyCount = Events.getPartyCount()
        if currentPartyCount > Events.tracked.battleStartPartyCount then
            Events.tracked.partyCaughtPokemon = true
        end
        
        -- Only emit once
        if not Events.tracked.battleEndEmitted then
            -- Infer outcome from game state
            local outcome, outcomeName = Events.inferBattleOutcome()
            
            -- Confirmed back in overworld with valid outcome
            Events.tracked.inBattle = false
            Events.tracked.battleEndDebounce = 0
            Events.tracked.battleEndEmitted = true  -- Prevent double emit
            
            -- Summary of captured battle texts
            local battleTexts = Events.tracked.battleTexts or {}
            console:log("📜 Battle ended: " .. #battleTexts .. " messages captured")
            Events.emit("battle_end", {
                outcome = outcome,
                outcomeName = outcomeName,
                wasCatch = (outcome == 7),
                battleLog = Events.tracked.battleLog,
                battleDialogue = battleTexts,  -- Battle-specific texts
            })
            Events.tracked.lastBattleOutcome = outcome
            
            -- Reset pending
            Events.tracked.pendingOutcome = 0
            Events.tracked.pendingOutcomeName = "none"
        end
    elseif isBattleCallback and Events.tracked.inBattle then
        -- Still in battle - track enemy HP
        local enemyMon = Events.getEnemyPokemon()
        if enemyMon then
            Events.tracked.lastEnemyHP = enemyMon.hp
            if enemyMon.hp == 0 and not Events.tracked.enemyDefeated then
                Events.tracked.enemyDefeated = true
            end
        end
        
        -- Track party growth (catch detection)
        local currentPartyCount = Events.getPartyCount()
        if currentPartyCount > Events.tracked.battleStartPartyCount then
            Events.tracked.partyCaughtPokemon = true
            -- Catch detected
        end
    end
    
    -- 3. BADGES
    -- Root cause: save block pointer shifts during battles AND PC/box access, causing
    -- the badge offset to read garbage bits. Fix: track badge COUNT (not raw bitmask),
    -- require count to strictly increase, and hold for 60 frames (~1s) before firing.
    local sb1 = Events.getSaveBlock1()
    if sb1 ~= 0 then
        local badges, badgeCount = Events.getBadges()

        -- Initialize on first valid read (don't fire event)
        if Events.tracked.badgesInitialized == nil then
            Events.tracked.badges = badges
            Events.tracked.badgeCount = badgeCount
            Events.tracked.badgesInitialized = true
            Events.tracked.badgePendingCount = nil
            Events.tracked.badgePendingFrames = 0
            console:log("🏅 Badge init: " .. badgeCount .. " badges (first read)")

        -- Only care if the COUNT increased (not just bitmask noise)
        elseif badgeCount > (Events.tracked.badgeCount or 0) then
            -- Debounce: new count must hold for 60 consecutive frames (~1 second)
            if Events.tracked.badgePendingCount == badgeCount then
                Events.tracked.badgePendingFrames = (Events.tracked.badgePendingFrames or 0) + 1
            else
                Events.tracked.badgePendingCount = badgeCount
                Events.tracked.badgePendingFrames = 1
            end

            if Events.tracked.badgePendingFrames >= 60 then
                local oldCount = Events.tracked.badgeCount
                console:log("🏅 Badge confirmed: " .. oldCount .. " → " .. badgeCount)
                Events.tracked.badges = badges
                Events.tracked.badgeCount = badgeCount
                Events.tracked.badgePendingCount = nil
                Events.tracked.badgePendingFrames = 0

                Events.emit("badge_obtained", {
                    oldBadges = oldCount,
                    newBadges = badges,
                    badgeCount = badgeCount,
                })
            end
        else
            -- Count didn't increase (bitmask noise, battle, PC access) — reset pending
            Events.tracked.badgePendingCount = nil
            Events.tracked.badgePendingFrames = 0
            -- If count decreased (save state reload), silently re-sync
            if badgeCount < (Events.tracked.badgeCount or 0) then
                Events.tracked.badges = badges
                Events.tracked.badgeCount = badgeCount
                console:log("🏅 Badge sync (reload?): " .. badgeCount .. " badges")
            end
        end
    end
    -- If sb1 == 0, skip badge processing entirely this frame
    
    -- 4. PARTY CHANGES (including catch detection)
    local partyHash = Events.hashParty()
    local partyCount = Events.getPartyCount()
    
    if partyHash ~= Events.tracked.partyHash then
        Events.tracked.partyHash = partyHash
        
        -- Check for new Pokemon (catch detection)
        local currentSpecies = Events.getPartySpeciesList()
        local oldCount = Events.tracked.partyCount
        local newCount = #currentSpecies
        
        -- Only fire catch event if the last battle outcome was ACTUALLY a catch (code 7)
        if newCount > oldCount then
            -- Party grew notification
            if Events.tracked.lastBattleOutcome == 7 then
                local newMon = currentSpecies[newCount]
                if newMon then
                    Events.emit("pokemon_caught", {
                        species = newMon.species,
                        slot = newMon.slot,
                    })
                    -- Reset so we don't fire again
                    Events.tracked.lastBattleOutcome = 0
                end
            end
        end
        
        -- Also fire general party change
        Events.emit("party_changed", {
            partyCount = newCount,
            species = currentSpecies,
        })
        
        Events.tracked.partyCount = newCount
        Events.tracked.partySpecies = currentSpecies
    end
    
    -- 5. TEXT CAPTURE (every frame) - aggressive capture with deduplication
    if true then
        if not Events.tracked.recentText then Events.tracked.recentText = {} end
        if not Events.tracked.textSeen then Events.tracked.textSeen = {} end
        if not Events.tracked.battleTextBuffer then Events.tracked.battleTextBuffer = "" end
        
        -- Check gStringVar4 (general text) - this is our primary source
        local text1 = Events.getDialogueText()
        if text1 and #text1 > 3 then
            -- Skip HP display text (e.g., "30/30", "42/47")
            local isHpText = text1:match("^%d+/%d+$")
            -- Skip menu items
            local isMenuItem = text1 == "POKMON" or text1 == "AYAAN" or text1 == "OPTION" or text1 == "EXIT" or
                               text1 == "Choose a POKMON." or text1:match("^Do what with")
            
            if not isHpText and not isMenuItem then
                -- Only log if truly new (not seen in last 20 messages)
                local dominated = false
                for _, seen in ipairs(Events.tracked.recentText) do
                    if seen == text1 or string.find(seen, text1, 1, true) then
                        dominated = true
                        break
                    end
                end
                if not dominated and text1 ~= Events.tracked.lastText1 then
                    Events.tracked.lastText1 = text1
                    table.insert(Events.tracked.recentText, text1)
                    Events.tracked.textSeen[text1] = true
                end
            end
        end
        
        -- Read battle text from CORRECT address (0x02022E2C)
        if Events.tracked.inBattle then
            local text2 = Events.getBattleText()
            
            if text2 and #text2 > 10 then
                local prevText = Events.tracked.lastBattleBuffer or ""
                
                -- Only capture if NEW and not seen before
                if text2 ~= prevText and not Events.tracked.textSeen[text2] then
                    -- Minimal filtering: skip incomplete partials
                    local isPartial = text2:match("'$") or text2:match("^What will$")
                    
                    if not isPartial then
                        table.insert(Events.tracked.recentText, text2)
                        if Events.tracked.battleTexts then
                            table.insert(Events.tracked.battleTexts, text2)
                        end
                        Events.tracked.textSeen[text2] = true
                    end
                end
                Events.tracked.lastBattleBuffer = text2
            end
        end
        
        -- Keep buffer limited and clear old "seen" entries
        while #Events.tracked.recentText > 50 do
            local removed = table.remove(Events.tracked.recentText, 1)
            Events.tracked.textSeen[removed] = nil
        end
        
        -- During battle, also track battle-specific texts
        if Events.tracked.inBattle then
            if not Events.tracked.battleTexts then Events.tracked.battleTexts = {} end
            -- Copy only texts added AFTER battle started
            local recentCount = #Events.tracked.recentText
            local lastCount = Events.tracked.lastBattleTextCount or recentCount
            if recentCount > lastCount then
                for i = lastCount + 1, recentCount do
                    table.insert(Events.tracked.battleTexts, Events.tracked.recentText[i])
                end
                Events.tracked.lastBattleTextCount = recentCount
            end
        end
        
        -- Outside battle: check overworld dialogue
        local dialogueHash = Events.getDialogueHash()
        if dialogueHash ~= Events.tracked.dialogueHash and dialogueHash > 0 then
            Events.tracked.dialogueHash = dialogueHash
            
            -- Exploration tracking - only count meaningful NPC dialogue
            if not Events.tracked.inBattle and Events.tracked.explorationBuffer.startMap and 
               Events.tracked.mapTransitionCooldown == 0 then
                local text = Events.getDialogueText()
                -- Only count if it looks like NPC speech (>20 chars, not menu text)
                local isNpcDialogue = text and #text > 20 and 
                                     not text:match("^%d+/%d+") and
                                     not text:match("^Choose") and
                                     not text:match("^Do what")
                if isNpcDialogue then
                    Events.tracked.explorationBuffer.dialogueCount = 
                        Events.tracked.explorationBuffer.dialogueCount + 1
                    -- Capture actual dialogue text
                    if #Events.tracked.explorationBuffer.dialogueTexts < 10 then
                        table.insert(Events.tracked.explorationBuffer.dialogueTexts, text)
                    end
                end
            end
            -- Still emit for real-time dialogue tracking if needed
            Events.emit("dialogue_change", {
                hash = dialogueHash,
            })
        end
    end
    
    -- 6. MOVE USAGE (every frame during battle)
    if Events.tracked.inBattle then
        Events.trackMoveUsage()
    else
        Events.tracked.lastMoveSlot = -1  -- Reset on battle end
    end
    
    -- 7. ITEM PICKUP (check every 30 frames to reduce overhead)
    if Events._frameCount and Events._frameCount % 30 == 0 then
        local currentItems = Events.countBagItems()
        if currentItems > Events.tracked.itemCount and Events.tracked.initialized then
            local gained = currentItems - Events.tracked.itemCount
            -- Buffer item gains instead of emitting
            if Events.tracked.explorationBuffer.startMap then
                Events.tracked.explorationBuffer.itemsGained = 
                    Events.tracked.explorationBuffer.itemsGained + gained
            end
        end
        Events.tracked.itemCount = currentItems
    end
    
    Events._frameCount = (Events._frameCount or 0) + 1
end

-- ============================================================================
-- INITIALIZATION
-- ============================================================================

function Events.init()
    -- Detect ROM type
    Events.detectROM()
    
    -- Initialize tracked state
    Events.tracked.mapKey = Events.getMapKey()
    Events.tracked.inBattle = Events.isBattleActive()
    Events.tracked.badges = Events.getBadges()
    Events.tracked.partyHash = Events.hashParty()
    Events.tracked.partyCount = Events.getPartyCount()
    Events.tracked.partySpecies = Events.getPartySpeciesList()
    Events.tracked.dialogueHash = Events.getDialogueHash()
    Events.tracked.battleEndDebounce = 0
    Events.tracked.mapTransitionCooldown = 60  -- Start with cooldown
    Events.tracked.itemCount = Events.countBagItems()
    
    Events.tracked.initialized = true
    
    -- Initialize exploration buffer
    Events.startExplorationBuffer()
    
    console:log("✅ Events module initialized")
    console:log("   Map: " .. Events.tracked.mapKey)
    console:log("   Battle: " .. tostring(Events.tracked.inBattle))
    console:log("   Party: " .. Events.tracked.partyCount .. " Pokemon")
end

-- ============================================================================
-- MOVE USAGE TRACKING
-- ============================================================================

-- Battle action memory (Emerald US)
Events.ADDRS.CHOSEN_MOVE_POSITIONS = 0x02024080  -- 4 bytes, move slot per battler
Events.ADDRS.LAST_USED_MOVE = 0x02024468  -- Last move used by each battler

Events.tracked.moveUsage = {}  -- {moveId: count}
Events.tracked.lastMoveSlot = -1
Events.tracked.battleLog = {}  -- Array of battle events for current fight
Events.tracked.lastPlayerHP = 0
Events.tracked.lastEnemyHP = 0

function Events.getPlayerMoveSlot()
    -- Returns 0-3 for which move slot the player selected
    return emu:read8(Events.ADDRS.CHOSEN_MOVE_POSITIONS)
end

function Events.getPlayerMoves()
    -- Read player's current Pokemon moves from gBattleMons slot 0
    local addr = Events.ADDRS.GBATTLEMONS  -- Player's Pokemon
    return {
        emu:read16(addr + 0x0C),  -- Move 1
        emu:read16(addr + 0x0E),  -- Move 2
        emu:read16(addr + 0x10),  -- Move 3
        emu:read16(addr + 0x12),  -- Move 4
    }
end

function Events.trackMoveUsage()
    if not Events.tracked.inBattle then return end
    
    local playerMon = Events.getPlayerBattleMon()
    local enemyMon = Events.getEnemyPokemon()
    
    -- Track damage dealt to enemy
    if enemyMon then
        local currentHP = enemyMon.hp or 0
        local maxHP = enemyMon.maxHp or 1
        
        if Events.tracked.lastEnemyHP > 0 and currentHP < Events.tracked.lastEnemyHP then
            local damage = Events.tracked.lastEnemyHP - currentHP
            
            -- Get current move slot to log what move was used
            local slot = Events.getPlayerMoveSlot()
            local moves = Events.getPlayerMoves()
            local moveId = (slot >= 0 and slot <= 3) and moves[slot + 1] or 0
            
            -- Silently track damage
            
            table.insert(Events.tracked.battleLog, {
                type = "attack",
                moveId = moveId,
                damage = damage,
                enemyHP = currentHP,
                enemyMaxHP = maxHP,
            })
            
            -- Track move usage
            if moveId and moveId > 0 and moveId < 1000 then
                Events.tracked.moveUsage[moveId] = (Events.tracked.moveUsage[moveId] or 0) + 1
            end
        end
        Events.tracked.lastEnemyHP = currentHP
    end
    
    -- Track damage taken by player
    if playerMon then
        local currentHP = playerMon.hp or 0
        
        if Events.tracked.lastPlayerHP > 0 and currentHP < Events.tracked.lastPlayerHP then
            local damage = Events.tracked.lastPlayerHP - currentHP
            -- Silently track damage taken
            
            table.insert(Events.tracked.battleLog, {
                type = "damage_taken",
                damage = damage,
                hp = currentHP,
            })
        end
        Events.tracked.lastPlayerHP = currentHP
    end
end

function Events.getMoveUsageStats()
    return Events.tracked.moveUsage
end

return Events
