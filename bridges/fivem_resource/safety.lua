-- Lucy OS v5 — Bridge Safety Layer
-- Validates all incoming commands from Lucy before execution
-- No command executes without passing this validator

local Safety = {}

-- HMAC-SHA256 signature verification
-- Requires server-side crypto library or native FiveM hash
function Safety.VerifySignature(payload, signature, secret)
    if not payload or not signature or not secret then
        return false, "missing_signature_fields"
    end
    -- In production: implement HMAC-SHA256 verification
    -- For now: check signature is non-empty and has correct length (64 hex chars)
    if type(signature) ~= "string" or #signature ~= 64 then
        return false, "invalid_signature_format"
    end
    return true, "ok"
end

-- Timestamp freshness check (prevent replay attacks)
function Safety.VerifyTimestamp(timestamp, maxAgeSeconds)
    maxAgeSeconds = maxAgeSeconds or 30
    if not timestamp then
        return false, "missing_timestamp"
    end
    local ts = tonumber(timestamp)
    if not ts then
        return false, "invalid_timestamp"
    end
    local age = os.time() - ts
    if age > maxAgeSeconds or age < -5 then
        return false, ("timestamp_too_old_or_future:" .. age .. "s")
    end
    return true, "ok"
end

-- Command type whitelist check
function Safety.ValidateCommandType(commandType)
    if not commandType then
        return false, "missing_command_type"
    end
    for _, allowed in ipairs(Config.CommandWhitelist) do
        if commandType == allowed then
            return true, "ok"
        end
    end
    return false, ("command_not_whitelisted:" .. tostring(commandType))
end

-- Payload type validation per command
function Safety.ValidatePayload(command, payload)
    if not payload then
        return false, "missing_payload"
    end

    -- spawn_npc
    if command == "spawn_npc" then
        if type(payload.model) ~= "string" then
            return false, "spawn_npc:missing_model"
        end
        if type(payload.coords) ~= "table" then
            return false, "spawn_npc:missing_coords"
        end
        if not payload.coords.x or not payload.coords.y or not payload.coords.z then
            return false, "spawn_npc:invalid_coords"
        end
        return true, "ok"
    end

    -- create_mission
    if command == "create_mission" then
        if type(payload.mission_type) ~= "string" then
            return false, "create_mission:missing_type"
        end
        if type(payload.mission_data) ~= "table" then
            return false, "create_mission:missing_data"
        end
        return true, "ok"
    end

    -- repair_resource
    if command == "repair_resource" then
        if type(payload.resource) ~= "string" then
            return false, "repair_resource:missing_name"
        end
        return true, "ok"
    end

    -- dispatch_event
    if command == "dispatch_event" then
        if type(payload.event_type) ~= "string" then
            return false, "dispatch_event:missing_type"
        end
        if type(payload.location) ~= "table" then
            return false, "dispatch_event:missing_location"
        end
        return true, "ok"
    end

    -- balance_economy
    if command == "balance_economy" then
        if type(payload.adjustment_type) ~= "string" then
            return false, "balance_economy:missing_type"
        end
        if type(payload.amount) ~= "number" then
            return false, "balance_economy:missing_amount"
        end
        return true, "ok"
    end

    -- kick_player
    if command == "kick_player" then
        if not payload.player_id then
            return false, "kick_player:missing_id"
        end
        return true, "ok"
    end

    -- status_request / heartbeat — no payload requirements
    if command == "status_request" or command == "heartbeat" then
        return true, "ok"
    end

    return true, "ok"
end

-- Full command validation pipeline
function Safety.ValidateLucyCommand(data)
    if type(data) ~= "table" then
        return false, "invalid_data_type"
    end

    -- 1. Command type check
    local ok, reason = Safety.ValidateCommandType(data.command)
    if not ok then return false, reason end

    -- 2. Timestamp check
    ok, reason = Safety.VerifyTimestamp(data.timestamp)
    if not ok then return false, reason end

    -- 3. Signature check
    ok, reason = Safety.VerifySignature(data, data.signature, Config.SharedSecret)
    if not ok then return false, reason end

    -- 4. Payload validation
    ok, reason = Safety.ValidatePayload(data.command, data.payload or data)
    if not ok then return false, reason end

    return true, "ok"
end

-- Rate limiter (simple per-command-type counter)
local _rateCounts = {}
local _rateWindow = 0

function Safety.CheckRateLimit(commandType, maxPerMinute)
    maxPerMinute = maxPerMinute or 20
    local now = math.floor(os.time() / 60)
    if now ~= _rateWindow then
        _rateCounts  = {}
        _rateWindow  = now
    end
    _rateCounts[commandType] = (_rateCounts[commandType] or 0) + 1
    if _rateCounts[commandType] > maxPerMinute then
        return false, ("rate_limit_exceeded:" .. commandType)
    end
    return true, "ok"
end

_G.LucySafety = Safety
return Safety