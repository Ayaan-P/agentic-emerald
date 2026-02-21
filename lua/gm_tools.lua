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
local BAG_ITEMS_OFFSET = 0x0560
local BAG_POKEBALLS_OFFSET = 0x0600
local BAG_TMS_OFFSET = 0x0640
local BAG_BERRIES_OFFSET = 0x0740
local BAG_KEYITEMS_OFFSET = 0x06A0

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

-- Common items shortcuts
function GM.givePokeballs(quantity) return GM.giveItem(4, quantity, GM.POCKET.POKEBALLS) end    -- Poke Ball
function GM.giveGreatBalls(quantity) return GM.giveItem(3, quantity, GM.POCKET.POKEBALLS) end   -- Great Ball
function GM.giveUltraBalls(quantity) return GM.giveItem(2, quantity, GM.POCKET.POKEBALLS) end   -- Ultra Ball
function GM.giveMasterBall() return GM.giveItem(1, 1, GM.POCKET.POKEBALLS) end                  -- Master Ball
function GM.giveRareCandy(quantity) return GM.giveItem(68, quantity) end                        -- Rare Candy
function GM.givePotion(quantity) return GM.giveItem(17, quantity) end                           -- Potion
function GM.giveSuperPotion(quantity) return GM.giveItem(26, quantity) end                      -- Super Potion
function GM.giveHyperPotion(quantity) return GM.giveItem(25, quantity) end                      -- Hyper Potion
function GM.giveMaxPotion(quantity) return GM.giveItem(24, quantity) end                        -- Max Potion
function GM.giveFullRestore(quantity) return GM.giveItem(23, quantity) end                      -- Full Restore
function GM.giveRevive(quantity) return GM.giveItem(28, quantity) end                           -- Revive
function GM.giveMaxRevive(quantity) return GM.giveItem(29, quantity) end                        -- Max Revive

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
    modifyFn(pokemon)
    
    -- Step 5: If personality changed, recompute key
    local newKey = pokemon.personality ~ otId
    
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

-- Set EVs (0-255 each, total max 510)
function GM.setEVs(slot, hp, atk, def, spd, spatk, spdef)
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
