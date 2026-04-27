# ============================================================================
#  Lucy OS v5 — One-Click Starter (Windows PowerShell)
#  Right-click → "Run with PowerShell"  OR  double-click START_LUCY.bat
# ============================================================================

$Host.UI.RawUI.WindowTitle = "Lucy OS v5 — 137-Node Cognitive Mesh"

# ANSI colours (Windows 10+)
$ESC = [char]27
function Cyan($t)   { Write-Host "${ESC}[96m$t${ESC}[0m" }
function Green($t)  { Write-Host "${ESC}[92m$t${ESC}[0m" }
function Yellow($t) { Write-Host "${ESC}[93m$t${ESC}[0m" }
function Red($t)    { Write-Host "${ESC}[91m$t${ESC}[0m" }
function Bold($t)   { Write-Host "${ESC}[1m$t${ESC}[0m" }

Clear-Host
Cyan '  ██╗     ██╗   ██╗ ██████╗██╗   ██╗     ██████╗ ███████╗'
Cyan '  ██║     ██║   ██║██╔════╝╚██╗ ██╔╝    ██╔═══██╗██╔════╝'
Cyan '  ██║     ██║   ██║██║      ╚████╔╝     ██║   ██║███████╗'
Cyan '  ██║     ██║   ██║██║       ╚██╔╝      ██║   ██║╚════██║'
Cyan '  ███████╗╚██████╔╝╚██████╗   ██║       ╚██████╔╝███████║'
Cyan '  ╚══════╝ ╚═════╝  ╚═════╝   ╚═╝        ╚═════╝ ╚══════╝'
Write-Host ""
Bold  "  ====================================================================="
Write-Host "   Lucy OS v5  |  137-Node Cognitive Mesh  |  NVIDIA Earth-2  |  AME"
Bold  "  ====================================================================="
Write-Host ""

# ── Set working directory to the script's location
Set-Location $PSScriptRoot
Green "  [✓] Working directory: $PSScriptRoot"

# ── Find Python
$PYTHON = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $PYTHON = $cmd
                break
            }
        }
    } catch {}
}

if (-not $PYTHON) {
    # Fallback: try python regardless of version
    foreach ($cmd in @("python", "python3", "py")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            $PYTHON = $cmd
            break
        }
    }
}

if (-not $PYTHON) {
    Red "  [✗] Python not found. Please install Python 3.10+ and add to PATH."
    Write-Host "      https://www.python.org/downloads/"
    Read-Host "  Press Enter to exit"
    exit 1
}

$pyVer = & $PYTHON --version 2>&1
Green "  [✓] Python: $pyVer"

# ── Check / install dependencies
Yellow "  [*] Checking dependencies..."
$depsOk = & $PYTHON -c "import fastapi, uvicorn; print('ok')" 2>&1
if ($depsOk -ne "ok") {
    Yellow "  [*] Installing required packages (first run only)..."
    & $PYTHON -m pip install fastapi "uvicorn[standard]" python-multipart aiofiles --quiet
    if ($LASTEXITCODE -ne 0) {
        Red "  [✗] Failed to install packages. Check your internet connection."
        Read-Host "  Press Enter to exit"
        exit 1
    }
    Green "  [✓] Packages installed."
} else {
    Green "  [✓] Dependencies OK."
}

# ── Kill any existing process on port 8000
Yellow "  [*] Checking port 8000..."
$portProc = netstat -ano 2>$null | Select-String ":8000 " | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Sort-Object -Unique
foreach ($pid in $portProc) {
    if ($pid -match '^\d+$' -and [int]$pid -gt 0) {
        try { Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue } catch {}
    }
}
Green "  [✓] Port 8000 clear."

# ── Launch
Write-Host ""
Bold  "  ====================================================================="
Write-Host "   STARTING LUCY OS v5..."
Bold  "  ====================================================================="
Write-Host ""
Cyan  "  [*] Booting 137-node cognitive mesh..."
Cyan  "  [*] Initialising AME EventBus + LTE Telemetry..."
Cyan  "  [*] Loading NVIDIA Earth-2 TwinEarth engine..."
Cyan  "  [*] Arming Bioyth0n blind executor..."
Cyan  "  [*] Server starting on http://localhost:8000"
Write-Host ""
Green "      Dashboard → http://localhost:8000/dashboard/index.html"
Green "      API Root  → http://localhost:8000/health"
Write-Host ""

# Open browser after 3 second delay
Start-Job -ScriptBlock {
    Start-Sleep 3
    Start-Process "http://localhost:8000/dashboard/index.html"
} | Out-Null

# ── Run server (blocking — logs stream to this window)
& $PYTHON dashboard\backend.py

Write-Host ""
Red "  [!] Lucy OS v5 has stopped."
Read-Host "  Press Enter to exit"