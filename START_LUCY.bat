@echo off
setlocal
cd /d "%~dp0"

set "PORT=4173"
set "URL=http://127.0.0.1:%PORT%"
set "VITE_CMD=node_modules\.bin\vite.cmd"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js is required to run Alpha Delta Vualt.
  echo Install Node.js 18+ and run this file again.
  pause
  exit /b 1
)

if not exist "%VITE_CMD%" (
  echo Installing Alpha Delta Vualt dependencies...
  call npm install
  if errorlevel 1 (
    echo npm install failed.
    pause
    exit /b 1
  )
)

if not exist "dist\index.html" (
  echo Building Alpha Delta Vualt...
  call npm run build
  if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=(Get-NetTCPConnection -State Listen -LocalPort %PORT% -ErrorAction SilentlyContinue); if($p){$p | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction Stop } catch {} }}" >nul 2>nul

start "Alpha Delta Vualt" /min cmd /c "cd /d "%~dp0" && call "%VITE_CMD%" preview --host 127.0.0.1 --port %PORT% --strictPort"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$url='%URL%'; for($i=0;$i -lt 80;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 2; if($r.StatusCode -ge 200){ exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo Alpha Delta Vualt did not start in time.
  echo Try opening %URL% manually.
  pause
  exit /b 1
)

where msedge >nul 2>nul
if not errorlevel 1 (
  start "" msedge --app=%URL%
  exit /b 0
)

where chrome >nul 2>nul
if not errorlevel 1 (
  start "" chrome --app=%URL%
  exit /b 0
)

start "" %URL%
exit /b 0
