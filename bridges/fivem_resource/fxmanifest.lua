-- Lucy OS v5 — FiveM Resource Manifest
-- Upgraded bridge resource for bidirectional Lucy↔FiveM communication

fx_version 'cerulean'
game       'gta5'

name        'lucy_bridge_v5'
description 'Lucy OS v5 — Autonomous AGI Bridge for FiveM'
version     '5.0.0'
author      'Lucy OS v5'

-- Server-side scripts (load order matters)
server_scripts {
    'config.lua',
    'shared_config.lua',
    'safety.lua',
    'commands.lua',
    'server.lua',
}

-- Client-side scripts
client_scripts {
    'client.lua',
}

-- Shared scripts
shared_scripts {
    'shared_config.lua',
}

-- Dependencies
dependencies {
    '/server:5181',
    '/gameBuild:2699',
}