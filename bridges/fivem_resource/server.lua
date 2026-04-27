-- Lucy OS v5 — FiveM Bridge Server Script
-- Handles all server-side Lucy↔FiveM communication
-- Heartbeat, command polling, status reporting, write operations

local Lucy  = {}
local Queue = { pending = {}, results = {} }
local State = {
    connected        = false,
    lastHeartbeat    = 0,
    commandsExecuted = 0,
    commandsFailed   = 0,
    startTime        = os.time(),
}

-- ─────────────────────────────────────────────
-- HTTP Helpers
-- ─────────────────────────────────────────────

local function LucyPost(endpoint, body, cb)
    local url     = Config.LucyUrl .. endpoint
    local headers = {
        ["Content-Type"]     = "application/json",
        ["X-Lucy-Version"]   = Config.Version,
        ["X-Lucy-Timestamp"] = tostring(os.time()),
    }
    PerformHttpRequest(url, function(code, resp, hdrs)
        if cb then
            cb(code, resp)
        end
    end, "POST", json.encode(body), headers)
end

local function LucyGet(endpoint, cb)
    local url = Config.LucyUrl .. endpoint
    PerformHttpRequest(url, function(code, resp, hdrs)
        if cb then
            local data = nil
            if code == 200 and resp then
                pcall(function() data = json.decode(resp) end)
            end
            cb(code, data)
        end
    end, "GET", "", {["X-Lucy-Version"] = Config.Version})
end

-- ─────────────────────────────────────────────
-- Heartbeat
-- ─────────────────────────────────────────────

local function SendHeartbeat()
    local payload = {
        type          = "heartbeat",
        version       = Config.Version,
        timestamp     = os.time(),
        player_count  = #GetPlayers(),
        uptime        = os.time() - State.startTime,
        commands_ok   = State.commandsExecuted,
        commands_fail = State.commandsFailed,
    }
    LucyPost("/fivem/heartbeat", payload, function(code, resp)
        if code == 200 then
            State.connected   = true
            State.lastHeartbeat = os.time()
            if Config.Debug then
                print("[LucyBridge] Heartbeat OK")
            end
        else
            State.connected = false
            print("[LucyBridge] Heartbeat FAILED: " .. tostring(code))
        end
    end)
end

CreateThread(function()
    while true do
        Wait(Config.HeartbeatInterval * 1000)
        SendHeartbeat()
    end
end)

-- ─────────────────────────────────────────────
-- Command Polling
-- ─────────────────────────────────────────────

local function ExecuteCommand(cmd)
    local ok, reason = LucySafety.ValidateLucyCommand(cmd)
    if not ok then
        print("[LucyBridge] BLOCKED command: " .. tostring(reason))
        State.commandsFailed = State.commandsFailed + 1
        return false, reason
    end

    local cmdType = cmd.command
    local payload = cmd.payload or cmd

    -- Rate limit check
    ok, reason = LucySafety.CheckRateLimit(cmdType, 20)
    if not ok then
        print("[LucyBridge] RATE LIMITED: " .. reason)
        return false, reason
    end

    -- spawn_npc
    if cmdType == "spawn_npc" then
        TriggerEvent("lucy:spawnNPC", payload)
        State.commandsExecuted = State.commandsExecuted + 1
        return true, "spawned"
    end

    -- create_mission
    if cmdType == "create_mission" then
        TriggerEvent("lucy:createMission", payload)
        State.commandsExecuted = State.commandsExecuted + 1
        return true, "mission_created"
    end

    -- repair_resource
    if cmdType == "repair_resource" then
        local resource = payload.resource
        if GetResourceState(resource) then
            StopResource(resource)
            Wait(500)
            StartResource(resource)
            State.commandsExecuted = State.commandsExecuted + 1
            return true, ("resource_restarted:" .. resource)
        end
        return false, ("resource_not_found:" .. tostring(resource))
    end

    -- dispatch_event
    if cmdType == "dispatch_event" then
        TriggerEvent("lucy:dispatchEvent", payload)
        State.commandsExecuted = State.commandsExecuted + 1
        return true, "dispatch_sent"
    end

    -- balance_economy
    if cmdType == "balance_economy" then
        TriggerEvent("lucy:balanceEconomy", payload)
        State.commandsExecuted = State.commandsExecuted + 1
        return true, "economy_adjusted"
    end

    -- kick_player
    if cmdType == "kick_player" then
        local pid    = tonumber(payload.player_id)
        local reason = payload.reason or "Lucy OS action"
        if pid and GetPlayerName(pid) then
            DropPlayer(pid, reason)
            State.commandsExecuted = State.commandsExecuted + 1
            return true, ("player_kicked:" .. tostring(pid))
        end
        return false, "player_not_found"
    end

    -- heartbeat / status_request — handled elsewhere
    return true, "acknowledged"
end

-- Poll Lucy for pending commands
CreateThread(function()
    Wait(5000) -- initial delay on startup
    while true do
        Wait(Config.CommandPollInterval * 1000)
        LucyPost("/fivem/poll", { type = "command_poll" }, function(code, resp)
            if code == 200 and resp then
                local data = nil
                pcall(function() data = json.decode(resp) end)
                if data and data.commands then
                    for _, cmd in ipairs(data.commands) do
                        local ok, result = ExecuteCommand(cmd)
                        if Config.Debug then
                            print(("[LucyBridge] cmd=%s ok=%s result=%s"):format(
                                tostring(cmd.command), tostring(ok), tostring(result)
                            ))
                        end
                    end
                end
            end
        end)
    end
end)

-- ─────────────────────────────────────────────
-- Status Reporting (Lucy reads these)
-- ─────────────────────────────────────────────

local function BuildStatusReport(category)
    local report = { category = category, timestamp = os.time() }

    if category == "resource_list" then
        local resources = {}
        for i = 0, GetNumResources() - 1 do
            local name  = GetResourceByFindIndex(i)
            local state = GetResourceState(name)
            table.insert(resources, { name = name, state = state })
        end
        report.resources = resources

    elseif category == "player_jobs" then
        local jobs = {}
        for _, pid in ipairs(GetPlayers()) do
            local ped = GetPlayerPed(pid)
            -- job data requires ESX/QB export; gracefully degrade
            table.insert(jobs, { player_id = pid, name = GetPlayerName(pid) })
        end
        report.players = jobs

    elseif category == "empty_rp_detection" then
        local suspects = {}
        for _, pid in ipairs(GetPlayers()) do
            -- Simple heuristic: player has been idle for > 5 min
            -- Full implementation would track last action timestamp
            table.insert(suspects, { player_id = pid, name = GetPlayerName(pid), idle_check = true })
        end
        report.suspects = suspects

    elseif category == "economy_signals" then
        report.signal = "economy_data_requires_framework_integration"

    elseif category == "gang_state" then
        report.signal = "gang_data_requires_framework_integration"

    elseif category == "police_state" then
        local on_duty = {}
        for _, pid in ipairs(GetPlayers()) do
            -- job check requires ESX/QB; gracefully degrade
        end
        report.signal = "police_state_requires_framework_integration"

    else
        report.signal = "category_available:" .. category
    end

    return report
end

-- HTTP handler — Lucy calls these endpoints
AddEventHandler('onResourceStart', function(resourceName)
    if resourceName == GetCurrentResourceName() then
        print("[LucyBridge v5] Starting — connecting to Lucy OS at " .. Config.LucyUrl)
        Wait(2000)
        SendHeartbeat()
    end
end)

-- ─────────────────────────────────────────────
-- Net Events (from Lucy client)
-- ─────────────────────────────────────────────

RegisterNetEvent("lucy:statusRequest")
AddEventHandler("lucy:statusRequest", function(category)
    local source = source
    local report = BuildStatusReport(category)
    TriggerClientEvent("lucy:statusResponse", source, report)
    -- Also forward to Lucy backend
    LucyPost("/fivem/status-report", report, nil)
end)

RegisterNetEvent("lucy:clientReady")
AddEventHandler("lucy:clientReady", function()
    local source = source
    if Config.Debug then
        print("[LucyBridge] Client ready: " .. GetPlayerName(source))
    end
end)

-- ─────────────────────────────────────────────
-- Lucy-triggered server events
-- ─────────────────────────────────────────────

AddEventHandler("lucy:spawnNPC", function(payload)
    -- Delegate to client via broadcast
    TriggerClientEvent("lucy:doSpawnNPC", -1, payload)
end)

AddEventHandler("lucy:createMission", function(payload)
    TriggerClientEvent("lucy:doCreateMission", -1, payload)
end)

AddEventHandler("lucy:dispatchEvent", function(payload)
    TriggerClientEvent("lucy:doDispatch", -1, payload)
    print(("[LucyBridge] Dispatch: type=%s location=%s"):format(
        tostring(payload.event_type),
        json.encode(payload.location or {})
    ))
end)

AddEventHandler("lucy:balanceEconomy", function(payload)
    print(("[LucyBridge] Economy balance: type=%s amount=%s"):format(
        tostring(payload.adjustment_type),
        tostring(payload.amount)
    ))
    -- Full implementation requires ESX/QB Money integration
    TriggerEvent("lucy:economyAdjusted", payload)
end)

-- ─────────────────────────────────────────────
-- Console commands for admin/debug
-- ─────────────────────────────────────────────

RegisterCommand("lucy_status", function(source, args, rawCmd)
    if source ~= 0 then return end -- server console only
    print("[LucyBridge] Status:")
    print("  Connected:    " .. tostring(State.connected))
    print("  Last HB:      " .. tostring(State.lastHeartbeat))
    print("  Cmds OK:      " .. tostring(State.commandsExecuted))
    print("  Cmds Failed:  " .. tostring(State.commandsFailed))
    print("  Players:      " .. tostring(#GetPlayers()))
end, true)

RegisterCommand("lucy_heartbeat", function(source, args, rawCmd)
    if source ~= 0 then return end
    SendHeartbeat()
    print("[LucyBridge] Manual heartbeat sent")
end, true)

print("[Lucy OS v5 Bridge] Server script loaded — version " .. Config.Version)