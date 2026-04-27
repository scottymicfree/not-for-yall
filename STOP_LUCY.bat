@echo off
setlocal
set "PORT=4173"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=(Get-NetTCPConnection -State Listen -LocalPort %PORT% -ErrorAction SilentlyContinue); if($p){$p | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction Stop; Write-Output ('Stopped process ' + $_) } catch {} }} else { Write-Output 'No Alpha Delta Vualt preview server found.' }"
pause
