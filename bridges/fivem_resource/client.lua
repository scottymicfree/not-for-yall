-- Lucy OS v5 — FiveM Bridge Client Script
-- Handles client-side NPC spawning, mission injection, dispatch UI

local Lucy = {}

-- ─────────────────────────────────────────────
-- Client Ready
-- ─────────────────────────────────────────────

AddEventHandler("onClientResourceStart", function(resourceName)
    if resourceName == GetCurrentResourceName() then
        TriggerServerEvent("lucy:clientReady")
        if Config.Debug then
            print("[LucyClient] Ready")
        end
    end
end)

-- ─────────────────────────────────────────────
-- NPC Spawning
-- ─────────────────────────────────────────────

RegisterNetEvent("lucy:doSpawnNPC")
AddEventHandler("lucy:doSpawnNPC", function(payload)
    local model    = payload.model or "a_m_m_tourist_01"
    local coords   = payload.coords or { x = 0, y = 0, z = 0 }
    local heading  = payload.heading or 0.0
    local scenario = payload.scenario or ""

    -- Use Config faction defaults if model not specified
    if payload.faction and Config.NPCFactions[payload.faction] then
        local factionData = Config.NPCFactions[payload.faction]
        model    = model == "a_m_m_tourist_01" and factionData.model or model
        scenario = scenario == "" and factionData.scenario or scenario
    end

    RequestModel(model)
    local timeout = 0
    while not HasModelLoaded(model) and timeout < 100 do
        Wait(50)
        timeout = timeout + 1
    end

    if HasModelLoaded(model) then
        local ped = CreatePed(4, model, coords.x, coords.y, coords.z - 1.0, heading, false, true)

        SetPedDefaultComponentVariation(ped)
        SetBlockingOfNonTemporaryEvents(ped, true)
        SetPedFleeAttributes(ped, 0, 0)
        SetPedCombatAttributes(ped, 46, true)

        if scenario ~= "" then
            TaskStartScenarioInPlace(ped, scenario, 0, true)
        end

        if Config.Debug then
            print(("[LucyClient] Spawned NPC model=%s at %.1f,%.1f,%.1f"):format(
                model, coords.x, coords.y, coords.z
            ))
        end

        SetModelAsNoLongerNeeded(model)
    else
        print("[LucyClient] Failed to load NPC model: " .. tostring(model))
    end
end)

-- ─────────────────────────────────────────────
-- Mission Injection
-- ─────────────────────────────────────────────

RegisterNetEvent("lucy:doCreateMission")
AddEventHandler("lucy:doCreateMission", function(payload)
    local missionType = payload.mission_type or "unknown"
    local missionData = payload.mission_data or {}

    if Config.Debug then
        print(("[LucyClient] Mission injected: type=%s"):format(missionType))
    end

    -- Trigger mission started event for framework hooks
    TriggerEvent("lucy:missionStarted", missionType, missionData)

    -- Display notification if target zone specified
    if missionData.target_zone then
        SetNewWaypoint(
            missionData.target_zone.x or 0,
            missionData.target_zone.y or 0
        )
    end

    -- Show HUD notification
    if missionData.title then
        BeginTextCommandThefeedPost("STRING")
        AddTextComponentSubstringPlayerName("~b~Lucy OS~w~: " .. tostring(missionData.title))
        EndTextCommandThefeedPostTicker(false, true)
    end
end)

-- ─────────────────────────────────────────────
-- Dispatch System
-- ─────────────────────────────────────────────

RegisterNetEvent("lucy:doDispatch")
AddEventHandler("lucy:doDispatch", function(payload)
    local eventType  = payload.event_type  or "incident"
    local location   = payload.location    or { x = 0, y = 0, z = 0 }
    local description = payload.description or "Lucy OS Dispatch"
    local priority   = payload.priority    or "medium"

    -- Map priority to colour
    local colourMap = {
        low      = "~g~",
        medium   = "~y~",
        high     = "~o~",
        critical = "~r~",
    }
    local colour = colourMap[priority] or "~w~"

    -- Show dispatch notification
    BeginTextCommandThefeedPost("STRING")
    AddTextComponentSubstringPlayerName(
        colour .. "[DISPATCH] ~w~" .. eventType:upper() .. "\n" .. description
    )
    EndTextCommandThefeedPostTicker(false, true)

    -- Draw blip at location
    if location.x and location.y then
        local blip = AddBlipForCoord(location.x, location.y, location.z or 0)
        SetBlipSprite(blip, 161)    -- alert blip
        SetBlipColour(blip, priority == "critical" and 1 or 5)
        SetBlipScale(blip, 1.2)
        SetBlipAsShortRange(blip, false)
        BeginTextCommandSetBlipName("STRING")
        AddTextComponentSubstringPlayerName(eventType)
        EndTextCommandSetBlipName(blip)
        -- Auto-remove blip after 5 minutes
        CreateThread(function()
            Wait(300000)
            RemoveBlip(blip)
        end)
    end

    if Config.Debug then
        print(("[LucyClient] Dispatch: type=%s priority=%s"):format(eventType, priority))
    end
end)

-- ─────────────────────────────────────────────
-- Empty Roleplay Loop Detection
-- ─────────────────────────────────────────────

local _lastActionTime = GetGameTimer()
local _isIdle         = false

-- Track player activity
CreateThread(function()
    while true do
        Wait(1000)
        local ped = PlayerPedId()
        if IsPedMoving(ped) or
           IsPedInAnyVehicle(ped, false) or
           IsPedShooting(ped) or
           IsPlayerFreeAiming(PlayerId()) or
           IsControlJustPressed(0, 24) -- attack
        then
            _lastActionTime = GetGameTimer()
            _isIdle         = false
        end

        -- Idle for > 10 minutes
        local idleMs = GetGameTimer() - _lastActionTime
        if idleMs > 600000 and not _isIdle then
            _isIdle = true
            TriggerServerEvent("lucy:playerIdleReport", {
                idle_ms   = idleMs,
                player_id = GetPlayerServerId(PlayerId()),
            })
        end
    end
end)

RegisterNetEvent("lucy:idleWarning")
AddEventHandler("lucy:idleWarning", function(message)
    -- Show warning to player
    BeginTextCommandThefeedPost("STRING")
    AddTextComponentSubstringPlayerName("~y~[Lucy OS]~w~ " .. tostring(message))
    EndTextCommandThefeedPostTicker(false, true)
end)

-- ─────────────────────────────────────────────
-- Status Response handler (client-side)
-- ─────────────────────────────────────────────

RegisterNetEvent("lucy:statusResponse")
AddEventHandler("lucy:statusResponse", function(report)
    if Config.Debug then
        print("[LucyClient] Status response: " .. json.encode(report))
    end
end)

print("[Lucy OS v5 Bridge] Client script loaded")