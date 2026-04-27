-- Lucy OS v5 — Shared Configuration
-- Loaded by both server and client contexts

Config = Config or {}

-- Lucy backend URL (Python FastAPI)
Config.LucyUrl            = "http://localhost:8000"
Config.SharedSecret       = "lucy-bridge-secret-v5"
Config.HeartbeatInterval  = 30     -- seconds
Config.CommandPollInterval = 5     -- seconds
Config.Version            = "5.0.0"
Config.Debug              = false

-- Command whitelist — only these command types accepted from Lucy
Config.CommandWhitelist = {
    "spawn_npc",
    "create_mission",
    "repair_resource",
    "dispatch_event",
    "balance_economy",
    "kick_player",
    "status_request",
    "heartbeat",
}

-- Status report categories Lucy can query
Config.StatusCategories = {
    "resource_list",
    "resource_status",
    "economy_signals",
    "player_jobs",
    "npc_activity",
    "gang_state",
    "police_state",
    "ems_state",
    "fire_state",
    "mission_state",
    "empty_rp_detection",
}

-- NPC faction definitions
Config.NPCFactions = {
    police  = { model = "s_m_y_cop_01",    scenario = "WORLD_HUMAN_GUARD_STAND" },
    ems     = { model = "s_m_m_paramedic_01", scenario = "WORLD_HUMAN_CLIPBOARD" },
    fire    = { model = "s_m_y_fireman_01", scenario = "WORLD_HUMAN_GUARD_STAND" },
    gang    = { model = "g_m_y_lost_01",   scenario = "WORLD_HUMAN_SMOKING" },
    neutral = { model = "a_m_m_tourist_01", scenario = "WORLD_HUMAN_STAND_MOBILE" },
}

-- Economy adjustment types
Config.EconomyAdjustments = {
    "salary_increase",
    "salary_decrease",
    "bonus_payout",
    "penalty_deduct",
    "market_price_adjust",
    "job_reward_scale",
}

-- Dispatch event types
Config.DispatchTypes = {
    "police_call",
    "medical_emergency",
    "fire_report",
    "robbery",
    "gang_activity",
    "traffic_incident",
    "missing_person",
    "suspicious_activity",
}