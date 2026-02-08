-- ============================================================================
-- Pokemon Emerald AI Game Master - Socket Server v2
-- Push-based event architecture with immediate notifications
-- ============================================================================

console:log("🎮 Pokemon Emerald AI Game Master v2 Starting...")

-- ============================================================================
-- MODULE LOADING
-- ============================================================================

local scriptPath = debug.getinfo(1, "S").source:sub(2):match("(.*/)")
package.path = package.path .. ";" .. scriptPath .. "?.lua"

-- Load modules
local Events, State, Tools

local function loadModule(name, path)
    local ok, mod = pcall(function()
        return dofile(scriptPath .. path)
    end)
    if ok and mod then
        console:log("✅ Loaded: " .. name)
        return mod
    else
        console:log("⚠️  Failed to load " .. name .. ": " .. tostring(mod))
        return nil
    end
end

Events = loadModule("Events", "events.lua")
State = loadModule("State", "state.lua")
Tools = loadModule("Tools", "gm_tools.lua")

if Events and State then
    State.setEvents(Events)
end

-- ============================================================================
-- JSON SERIALIZATION (mGBA has no json library)
-- ============================================================================

local function escapeJson(s)
    if type(s) ~= "string" then return tostring(s) end
    s = s:gsub('\\', '\\\\')
    s = s:gsub('"', '\\"')
    s = s:gsub('\n', '\\n')
    s = s:gsub('\r', '\\r')
    s = s:gsub('\t', '\\t')
    return s
end

local function toJson(val)
    if val == nil then return "null" end
    local t = type(val)
    if t == "boolean" then return val and "true" or "false" end
    if t == "number" then return tostring(val) end
    if t == "string" then return '"' .. escapeJson(val) .. '"' end
    if t == "table" then
        -- Check if array or object
        local isArray = true
        local maxn = 0
        local count = 0
        for k, _ in pairs(val) do
            count = count + 1
            if type(k) == "number" then
                maxn = math.max(maxn, k)
            else
                isArray = false
            end
        end
        if count == 0 then return "{}" end
        if isArray and maxn == count then
            -- Array
            local parts = {}
            for i = 1, count do
                table.insert(parts, toJson(val[i]))
            end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            -- Object
            local parts = {}
            for k, v in pairs(val) do
                table.insert(parts, '"' .. escapeJson(tostring(k)) .. '":' .. toJson(v))
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    end
    return '"' .. tostring(val) .. '"'
end

-- ============================================================================
-- SOCKET SERVER
-- ============================================================================

local server = nil
local clients = {}
local nextClientId = 1
local eventCount = 0

-- Broadcast event to all connected clients
local function broadcast(eventType, eventData)
    eventCount = eventCount + 1
    
    -- Get full state and flatten it into the message (daemon expects flat format)
    local message = State and State.getFullState() or {}
    message.event_type = eventType
    message.event_id = eventCount
    message.timestamp = os.time()
    -- Merge any event-specific data
    if eventData then
        for k, v in pairs(eventData) do
            message[k] = v
        end
    end
    
    local json = toJson(message) .. "\n"
    
    for id, client in pairs(clients) do
        local ok, err = pcall(function()
            client:send(json)
        end)
        if not ok then
            console:log("⚠️  Client " .. id .. " send error: " .. tostring(err))
            clients[id] = nil
            client:close()
        end
    end
end

-- Handle received data from client
local function handleClientData(clientId)
    local client = clients[clientId]
    if not client then return end
    
    while true do
        local data, err = client:receive(4096)
        if data then
            local command = data:match("^(.-)%s*$")
            if command and command ~= "" then
                console:log("📥 Command from " .. clientId .. ": " .. command:sub(1, 80))
                
                -- Execute Lua command
                local success, result = pcall(function()
                    return load(command)()
                end)
                
                -- Send response
                local response
                if success then
                    response = toJson({status = "ok", result = tostring(result)})
                    console:log("✅ Command executed")
                else
                    response = toJson({status = "error", error = tostring(result)})
                    console:log("❌ Command failed: " .. tostring(result))
                end
                client:send(response .. "\n")
            end
        else
            if err ~= socket.ERRORS.AGAIN then
                console:log("Client " .. clientId .. " disconnected")
                clients[clientId] = nil
                client:close()
            end
            return
        end
    end
end

-- Handle client errors
local function handleClientError(clientId, err)
    console:log("⚠️  Client " .. clientId .. " error: " .. tostring(err))
    local client = clients[clientId]
    if client then
        clients[clientId] = nil
        client:close()
    end
end

-- Accept new connections
local function acceptConnection()
    local client, err = server:accept()
    if err then
        console:log("❌ Accept error: " .. tostring(err))
        return
    end
    
    local id = nextClientId
    nextClientId = id + 1
    clients[id] = client
    
    client:add("received", function() handleClientData(id) end)
    client:add("error", function(e) handleClientError(id, e) end)
    
    console:log("✅ Client " .. id .. " connected")
    
    -- Send initial connected event
    broadcast("connected", {
        message = "Game Master server ready",
        speciesOffset = Events.SPECIES_OFFSET,
    })
end

-- Start socket server
local function startServer(port)
    port = port or 8888
    
    while true do
        local s, err = socket.bind(nil, port)
        if err then
            if err == socket.ERRORS.ADDRESS_IN_USE then
                port = port + 1
            else
                console:log("❌ Bind error: " .. tostring(err))
                return nil
            end
        else
            local ok, listenErr = s:listen()
            if listenErr then
                s:close()
                console:log("❌ Listen error: " .. tostring(listenErr))
                return nil
            end
            
            console:log("🚀 Socket server on port " .. port)
            s:add("received", acceptConnection)
            return s
        end
    end
end

-- ============================================================================
-- EVENT WIRING
-- ============================================================================

if Events then
    -- Wire up all events to broadcast to clients
    Events.on("all", function(eventType, data)
        console:log("📤 Event: " .. eventType)
        broadcast(eventType, data)
    end)
    
    -- Inject queued dialogue when new dialogue appears
    Events.on("dialogue_change", function(data)
        if Tools and Tools.dialogueQueue and #Tools.dialogueQueue > 0 then
            -- Small delay to let the game render first, then inject
            Tools.injectFromQueue()
        end
    end)
end

-- ============================================================================
-- PERIODIC STATE BROADCAST
-- ============================================================================

local PERIODIC_INTERVAL = 300  -- 5 seconds at 60fps
local framesSinceLastPeriodic = 0

local function periodicBroadcast()
    framesSinceLastPeriodic = framesSinceLastPeriodic + 1
    if framesSinceLastPeriodic >= PERIODIC_INTERVAL then
        framesSinceLastPeriodic = 0
        broadcast("periodic_state", {})
    end
end

-- ============================================================================
-- CONTINUOUS DIALOGUE INJECTION (every frame while queue has items)
-- ============================================================================

local lastDialogueActive = false
local injectionCounter = 0

local function continuousDialogueInjection()
    if not Tools or not Tools.dialogueQueue then return end
    
    -- Check if dialogue is currently active
    local firstByte = emu:read8(0x02021FC4)
    local dialogueActive = firstByte ~= 0xFF and firstByte ~= 0x00
    
    if #Tools.dialogueQueue > 0 then
        -- ALWAYS inject when we have queued text - before and during dialogue
        injectionCounter = injectionCounter + 1
        if injectionCounter % 2 == 0 then  -- Every other frame to reduce overhead
            local text = Tools.dialogueQueue[1]
            Tools.injectDialogue(text)
        end
        
        -- Pop from queue when dialogue closes after being open
        if lastDialogueActive and not dialogueActive then
            table.remove(Tools.dialogueQueue, 1)
            console:log("📤 Popped dialogue from queue, " .. #Tools.dialogueQueue .. " remaining")
        end
    end
    
    lastDialogueActive = dialogueActive
end

-- ============================================================================
-- MAIN FRAME CALLBACK
-- ============================================================================

callbacks:add("frame", function()
    -- Check for events (push-based)
    if Events then
        Events.checkFrame()
    end
    
    -- Continuous dialogue injection while queue has items
    continuousDialogueInjection()
    
    -- Periodic state broadcast
    periodicBroadcast()
end)

-- ============================================================================
-- EXPOSE TOOLS GLOBALLY
-- ============================================================================

if Tools then
    -- Make all GM functions available globally
    for name, func in pairs(Tools) do
        if type(func) == "function" then
            _G["GM_" .. name] = func
        end
    end
    _G["GM"] = Tools
    console:log("✅ GM Tools available globally")
end

-- ============================================================================
-- INITIALIZATION
-- ============================================================================

-- Initialize events module
if Events then
    Events.init()
end

-- Start socket server
server = startServer(8888)

console:log("✅ Pokemon AI Game Master v2 ready!")
console:log("📡 Waiting for Game Master daemon...")
