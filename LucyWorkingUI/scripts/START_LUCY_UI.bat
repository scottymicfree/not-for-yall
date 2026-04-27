@echo off
cd /d "%~dp0.."
if not exist data\runtime mkdir data\runtime >nul 2>nul
start "Lucy Working UI Server" cmd /c node server.js
powershell -NoProfile -Command "$p='data/runtime/port.txt'; $limit=(Get-Date).AddSeconds(20); while((Get-Date) -lt $limit){ if(Test-Path $p){ $port=(Get-Content $p -Raw).Trim(); if($port){ Start-Process ('http://127.0.0.1:' + $port); exit 0 } }; Start-Sleep -Milliseconds 300 }; Write-Host 'Lucy did not start in time. Check that Node.js is installed.'"
