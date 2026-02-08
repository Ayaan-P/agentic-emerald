-- ============================================================================
-- Pokemon Emerald GM - State Reading Module
-- FULLY SELF-CONTAINED - No dependencies on Events module
-- ============================================================================

local State = {}

-- ============================================================================
-- ADDRESSES (Pokemon Emerald US / Decomp)
-- ============================================================================

local SAVE_BLOCK1_PTR = 0x03005D8C
local SAVE_BLOCK2_PTR = 0x03005D90
local CALLBACK2_ADDR = 0x03005D04
local BATTLE_CALLBACK = 134460365
local PLAYER_PARTY_ADDR = 0x020244EC
local PARTY_COUNT_ADDR = 0x020244E9
local GBATTLEMONS_ADDR = 0x02024084
local BATTLE_TYPE_FLAGS = 0x02022FEC
local DIALOGUE_BUFFER = 0x02021FC4

-- Note: Emerald uses internal species IDs, not national dex + offset
-- Python loads emerald_species.json which maps internal IDs directly
local SPECIES_OFFSET = 0  -- Don't subtract, send raw internal ID
local POKEMON_SIZE = 100
local BATTLE_MON_SIZE = 88

-- ============================================================================
-- CHARACTER ENCODING
-- ============================================================================

local CHAR_DECODE = {
    [0x00] = " ",
    [0xBB] = "A", [0xBC] = "B", [0xBD] = "C", [0xBE] = "D", [0xBF] = "E",
    [0xC0] = "F", [0xC1] = "G", [0xC2] = "H", [0xC3] = "I", [0xC4] = "J",
    [0xC5] = "K", [0xC6] = "L", [0xC7] = "M", [0xC8] = "N", [0xC9] = "O",
    [0xCA] = "P", [0xCB] = "Q", [0xCC] = "R", [0xCD] = "S", [0xCE] = "T",
    [0xCF] = "U", [0xD0] = "V", [0xD1] = "W", [0xD2] = "X", [0xD3] = "Y",
    [0xD4] = "Z",
    [0xD5] = "a", [0xD6] = "b", [0xD7] = "c", [0xD8] = "d", [0xD9] = "e",
    [0xDA] = "f", [0xDB] = "g", [0xDC] = "h", [0xDD] = "i", [0xDE] = "j",
    [0xDF] = "k", [0xE0] = "l", [0xE1] = "m", [0xE2] = "n", [0xE3] = "o",
    [0xE4] = "p", [0xE5] = "q", [0xE6] = "r", [0xE7] = "s", [0xE8] = "t",
    [0xE9] = "u", [0xEA] = "v", [0xEB] = "w", [0xEC] = "x", [0xED] = "y",
    [0xEE] = "z",
    [0xA1] = "0", [0xA2] = "1", [0xA3] = "2", [0xA4] = "3", [0xA5] = "4",
    [0xA6] = "5", [0xA7] = "6", [0xA8] = "7", [0xA9] = "8", [0xAA] = "9",
    [0xAB] = "!", [0xAC] = "?", [0xAD] = ".", [0xAE] = "-", [0xB8] = ",",
    [0xF0] = ":", [0x5C] = "(", [0x5D] = ")", [0xBA] = "/", [0xB3] = "'",
    [0xFE] = "\n", [0xFA] = " ", [0xFB] = " ",
}

-- Substruct order lookup (0-indexed keys, 1-indexed values)
-- Correct substruct order table from pokeemerald
-- Types: 1=Growth, 2=Attacks, 3=EVs, 4=Misc
-- Array shows which TYPE is at each POSITION
local SUBSTRUCT_ORDER = {
    [0]  = {1,2,3,4}, [1]  = {1,2,4,3}, [2]  = {1,3,2,4}, [3]  = {1,3,4,2},
    [4]  = {1,4,2,3}, [5]  = {1,4,3,2}, [6]  = {2,1,3,4}, [7]  = {2,1,4,3},
    [8]  = {2,3,1,4}, [9]  = {2,3,4,1}, [10] = {2,4,1,3}, [11] = {2,4,3,1},
    [12] = {3,1,2,4}, [13] = {3,1,4,2}, [14] = {3,2,1,4}, [15] = {3,2,4,1},
    [16] = {3,4,1,2}, [17] = {3,4,2,1}, [18] = {4,1,2,3}, [19] = {4,1,3,2},
    [20] = {4,2,1,3}, [21] = {4,2,3,1}, [22] = {4,3,1,2}, [23] = {4,3,2,1}
}

-- ============================================================================
-- BASIC READERS
-- ============================================================================

local function getSaveBlock1()
    return emu:read32(SAVE_BLOCK1_PTR)
end

local function getSaveBlock2()
    return emu:read32(SAVE_BLOCK2_PTR)
end

local function readString(addr, maxLen)
    local chars = {}
    for i = 0, maxLen - 1 do
        local byte = emu:read8(addr + i)
        if byte == 0xFF then break end
        local char = CHAR_DECODE[byte] or ""
        table.insert(chars, char)
    end
    return table.concat(chars)
end

-- ============================================================================
-- PLAYER INFO
-- ============================================================================

function State.getPlayerName()
    local sb2 = getSaveBlock2()
    if sb2 == 0 then return "Unknown" end
    return readString(sb2 + 0x00, 8)
end

function State.getPlayTime()
    local sb2 = getSaveBlock2()
    if sb2 == 0 then return {hours=0, minutes=0, seconds=0} end
    return {
        hours = emu:read16(sb2 + 0x0E),
        minutes = emu:read8(sb2 + 0x10),
        seconds = emu:read8(sb2 + 0x11),
    }
end

function State.getMoney()
    local sb1 = getSaveBlock1()
    if sb1 == 0 then return 0 end
    return emu:read32(sb1 + 0x0490)
end

-- ============================================================================
-- LOCATION
-- ============================================================================

function State.getMapInfo()
    local sb1 = getSaveBlock1()
    if sb1 == 0 then return {group = 0, num = 0, x = 0, y = 0} end
    return {
        group = emu:read8(sb1 + 0x04),
        num = emu:read8(sb1 + 0x05),
        x = emu:read16(sb1 + 0x00),
        y = emu:read16(sb1 + 0x02),
    }
end

function State.getBadges()
    local sb1 = getSaveBlock1()
    if sb1 == 0 then return 0, 0 end
    local flags = emu:read16(sb1 + 0x0EFC)
    local count = 0
    local temp = flags
    while temp > 0 do
        count = count + (temp & 1)
        temp = temp >> 1
    end
    return flags, count
end

-- ============================================================================
-- BATTLE STATE
-- ============================================================================

function State.isBattleActive()
    return emu:read32(CALLBACK2_ADDR) == BATTLE_CALLBACK
end

function State.getBattleInfo()
    if not State.isBattleActive() then
        return {in_battle = false}
    end
    local flags = emu:read32(BATTLE_TYPE_FLAGS)
    return {
        in_battle = true,
        is_wild = (flags & 0x04) ~= 0,
        is_trainer = (flags & 0x08) ~= 0,
        is_double = (flags & 0x01) ~= 0,
        flags = flags
    }
end

-- ============================================================================
-- PARTY POKEMON
-- ============================================================================

function State.getParty()
    local party = {}
    local count = emu:read8(PARTY_COUNT_ADDR)
    if count > 6 then count = 6 end
    
    for slot = 0, count - 1 do
        local addr = PLAYER_PARTY_ADDR + (slot * POKEMON_SIZE)
        local personality = emu:read32(addr)
        
        if personality ~= 0 then
            local otId = emu:read32(addr + 4)
            local key = personality ~ otId
            local secureAddr = addr + 32
            
            local pokemon = {
                slot = slot,
                personality = personality,
                nickname = readString(addr + 8, 10),
                species = 0,
                held_item = 0,
                experience = 0,
                moves = {},
                pp = {},
                evs = {},
                nature = personality % 25,
            }
            
            -- Get substruct positions
            local order = personality % 24
            local positions = SUBSTRUCT_ORDER[order]
            
            -- Safety check
            if not positions then
                positions = {1,2,3,4}  -- Default order if lookup fails
            end
            
            -- Find which position has each substruct type
            local growthPos, attacksPos, evsPos, miscPos = 0, 1, 2, 3  -- Defaults
            for i = 1, 4 do
                local v = positions[i]
                if v == 1 then growthPos = i - 1
                elseif v == 2 then attacksPos = i - 1
                elseif v == 3 then evsPos = i - 1
                elseif v == 4 then miscPos = i - 1
                end
            end
            
            -- Growth substruct (species, item, exp)
            local growthAddr = secureAddr + (growthPos * 12)
            local word0 = emu:read32(growthAddr) ~ key
            local word1 = emu:read32(growthAddr + 4) ~ key
            
            local rawSpecies = word0 & 0xFFFF
            pokemon.species = rawSpecies - SPECIES_OFFSET
            pokemon.held_item = (word0 >> 16) & 0xFFFF
            pokemon.experience = word1
            
            -- Attacks substruct (moves, pp)
            local attacksAddr = secureAddr + (attacksPos * 12)
            local atkWord0 = emu:read32(attacksAddr) ~ key
            local atkWord1 = emu:read32(attacksAddr + 4) ~ key
            local atkWord2 = emu:read32(attacksAddr + 8) ~ key
            
            pokemon.moves = {
                atkWord0 & 0xFFFF,
                (atkWord0 >> 16) & 0xFFFF,
                atkWord1 & 0xFFFF,
                (atkWord1 >> 16) & 0xFFFF,
            }
            pokemon.pp = {
                atkWord2 & 0xFF,
                (atkWord2 >> 8) & 0xFF,
                (atkWord2 >> 16) & 0xFF,
                (atkWord2 >> 24) & 0xFF,
            }
            
            -- EVs substruct
            local evAddr = secureAddr + (evsPos * 12)
            local evWord0 = emu:read32(evAddr) ~ key
            local evWord1 = emu:read32(evAddr + 4) ~ key
            
            pokemon.evs = {
                hp = evWord0 & 0xFF,
                attack = (evWord0 >> 8) & 0xFF,
                defense = (evWord0 >> 16) & 0xFF,
                speed = (evWord0 >> 24) & 0xFF,
                sp_attack = evWord1 & 0xFF,
                sp_defense = (evWord1 >> 8) & 0xFF,
            }
            
            -- Misc substruct (IVs)
            local miscAddr = secureAddr + (miscPos * 12)
            local ivWord = emu:read32(miscAddr + 4) ~ key
            pokemon.ivs = {
                hp = ivWord & 0x1F,
                attack = (ivWord >> 5) & 0x1F,
                defense = (ivWord >> 10) & 0x1F,
                speed = (ivWord >> 15) & 0x1F,
                sp_attack = (ivWord >> 20) & 0x1F,
                sp_defense = (ivWord >> 25) & 0x1F,
            }
            
            -- Unencrypted battle stats
            pokemon.status = emu:read32(addr + 80)
            pokemon.level = emu:read8(addr + 84)
            pokemon.current_hp = emu:read16(addr + 86)
            pokemon.max_hp = emu:read16(addr + 88)
            pokemon.attack = emu:read16(addr + 90)
            pokemon.defense = emu:read16(addr + 92)
            pokemon.speed = emu:read16(addr + 94)
            pokemon.sp_attack = emu:read16(addr + 96)
            pokemon.sp_defense = emu:read16(addr + 98)
            
            if pokemon.species > 0 and pokemon.species <= 500 then
                table.insert(party, pokemon)
            end
        end
    end
    
    return party
end

-- ============================================================================
-- ENEMY POKEMON (IN BATTLE)
-- ============================================================================

function State.getEnemyPokemon()
    if not State.isBattleActive() then return nil end
    
    local addr = GBATTLEMONS_ADDR + BATTLE_MON_SIZE  -- Slot 1 = enemy
    local rawSpecies = emu:read16(addr)
    local species = rawSpecies - SPECIES_OFFSET
    
    if species <= 0 or species > 440 then return nil end
    
    local maxHp = emu:read16(addr + 0x2C)
    local level = emu:read8(addr + 0x2A)
    if maxHp == 0 or maxHp > 999 or level == 0 or level > 100 then return nil end
    
    return {
        species = species,
        level = level,
        hp = emu:read16(addr + 0x28),
        maxHp = maxHp,
        attack = emu:read16(addr + 0x02),
        defense = emu:read16(addr + 0x04),
        speed = emu:read16(addr + 0x06),
        spAttack = emu:read16(addr + 0x08),
        spDefense = emu:read16(addr + 0x0A),
        moves = {
            emu:read16(addr + 0x0C),
            emu:read16(addr + 0x0E),
            emu:read16(addr + 0x10),
            emu:read16(addr + 0x12)
        },
    }
end

-- ============================================================================
-- BAG ITEMS
-- ============================================================================

function State.getBagItems()
    local sb1 = getSaveBlock1()
    if sb1 == 0 then return {} end
    
    local items = {}
    local BAG_ITEMS_OFFSET = 0x0560
    
    for i = 0, 29 do
        local addr = sb1 + BAG_ITEMS_OFFSET + (i * 4)
        local itemId = emu:read16(addr)
        local quantity = emu:read16(addr + 2)
        if itemId > 0 and itemId < 1000 and quantity > 0 and quantity < 1000 then
            table.insert(items, {id = itemId, qty = quantity})
        end
    end
    
    return items
end

-- ============================================================================
-- DIALOGUE
-- ============================================================================

function State.readDialogue()
    local chars = {}
    for i = 0, 199 do
        local byte = emu:read8(DIALOGUE_BUFFER + i)
        if byte == 0xFF then break end
        local c = CHAR_DECODE[byte] or ""
        table.insert(chars, c)
    end
    return table.concat(chars)
end

function State.getDialogueHash()
    local hash = 0
    for i = 0, 63 do
        local byte = emu:read8(DIALOGUE_BUFFER + i)
        if byte == 0xFF then break end
        hash = hash + byte * (i + 1)
    end
    return hash
end

-- ============================================================================
-- FULL STATE (EVERYTHING IN ONE CALL)
-- ============================================================================

function State.getFullState()
    local mapInfo = State.getMapInfo()
    local badges, badgeCount = State.getBadges()
    local battleInfo = State.getBattleInfo()
    local party = State.getParty()
    
    -- Simplify party for JSON
    local partyData = {}
    for _, p in ipairs(party) do
        table.insert(partyData, {
            slot = p.slot,
            species = p.species,
            nickname = p.nickname,
            level = p.level,
            current_hp = p.current_hp,
            max_hp = p.max_hp,
            moves = p.moves,
            pp = p.pp,
            status = p.status,
            nature = p.nature,
            attack = p.attack,
            defense = p.defense,
            speed = p.speed,
            sp_attack = p.sp_attack,
            sp_defense = p.sp_defense,
            held_item = p.held_item,
            experience = p.experience,
        })
    end
    
    return {
        player_name = State.getPlayerName(),
        play_time = State.getPlayTime(),
        money = State.getMoney(),
        map_group = mapInfo.group,
        map_num = mapInfo.num,
        player_x = mapInfo.x,
        player_y = mapInfo.y,
        badges = badges,
        badge_count = badgeCount,
        in_battle = State.isBattleActive(),
        battle_info = battleInfo,
        enemy_pokemon = State.getEnemyPokemon(),
        battle_outcome = emu:read8(0x0202427C),
        party = partyData,
        party_count = #partyData,
        bag_items = State.getBagItems(),
        dialogue_text = State.readDialogue(),
        dialogue_active = State.getDialogueHash() > 0,
    }
end

-- For compatibility with v2 server
function State.setEvents(eventsModule)
    -- No longer needed, but keep for compatibility
end

return State
