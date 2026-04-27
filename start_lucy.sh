#!/usr/bin/env bash
# ============================================================================
#  Lucy OS v5 — One-Click Starter (Linux / macOS / WSL)
# ============================================================================
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

clear
echo -e "${CYAN}"
echo '  ██╗     ██╗   ██╗ ██████╗██╗   ██╗     ██████╗ ███████╗'
echo '  ██║     ██║   ██║██╔════╝╚██╗ ██╔╝    ██╔═══██╗██╔════╝'
echo '  ██║     ██║   ██║██║      ╚████╔╝     ██║   ██║███████╗'
echo '  ██║     ██║   ██║██║       ╚██╔╝      ██║   ██║╚════██║'
echo '  ███████╗╚██████╔╝╚██████╗   ██║       ╚██████╔╝███████║'
echo '  ╚══════╝ ╚═════╝  ╚═════╝   ╚═╝        ╚═════╝ ╚══════╝'
echo -e "${NC}"
echo -e "${BOLD}  =====================================================================${NC}"
echo -e "   Lucy OS v5  |  137-Node Cognitive Mesh  |  NVIDIA Earth-2  |  AME"
echo -e "${BOLD}  =====================================================================${NC}"
echo ""

# ── Script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
echo -e "  ${GREEN}[✓]${NC} Working directory: $SCRIPT_DIR"

# ── Find Python
PYTHON=""
for cmd in python3 python py; do
    if command -v "$cmd" &>/dev/null; then
        VER=$($cmd --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        MAJOR=$(echo $VER | cut -d. -f1)
        MINOR=$(echo $VER | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ] 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    # Try any python3
    if command -v python3 &>/dev/null; then
        PYTHON="python3"
    elif command -v python &>/dev/null; then
        PYTHON="python"
    else
        echo -e "  ${RED}[✗] Python 3.10+ not found. Please install Python.${NC}"
        echo "      https://www.python.org/downloads/"
        exit 1
    fi
fi

echo -e "  ${GREEN}[✓]${NC} Python: $($PYTHON --version)"

# ── Check / install dependencies
echo -e "  ${YELLOW}[*]${NC} Checking dependencies..."
if ! $PYTHON -c "import fastapi, uvicorn" &>/dev/null; then
    echo -e "  ${YELLOW}[*]${NC} Installing required packages..."
    $PYTHON -m pip install fastapi "uvicorn[standard]" python-multipart aiofiles --quiet
    echo -e "  ${GREEN}[✓]${NC} Packages installed."
else
    echo -e "  ${GREEN}[✓]${NC} Dependencies OK."
fi

# ── Kill any process on port 8000
echo -e "  ${YELLOW}[*]${NC} Checking port 8000..."
if command -v lsof &>/dev/null; then
    PID=$(lsof -ti:8000 2>/dev/null || true)
    [ -n "$PID" ] && kill -9 $PID 2>/dev/null && echo -e "  ${YELLOW}[*]${NC} Killed existing process on port 8000."
elif command -v fuser &>/dev/null; then
    fuser -k 8000/tcp 2>/dev/null || true
fi
echo -e "  ${GREEN}[✓]${NC} Port 8000 clear."

# ── Auto-open browser after 3s
echo ""
echo -e "${BOLD}  =====================================================================${NC}"
echo -e "   STARTING LUCY OS v5..."
echo -e "${BOLD}  =====================================================================${NC}"
echo ""
echo -e "  ${CYAN}[*]${NC} Booting 137-node cognitive mesh..."
echo -e "  ${CYAN}[*]${NC} Initialising AME EventBus + LTE Telemetry..."
echo -e "  ${CYAN}[*]${NC} Loading NVIDIA Earth-2 TwinEarth engine..."
echo -e "  ${CYAN}[*]${NC} Arming Bioyth0n blind executor..."
echo -e "  ${CYAN}[*]${NC} Server starting on ${BOLD}http://localhost:8000${NC}"
echo ""
echo -e "  ${GREEN}  Dashboard → http://localhost:8000/dashboard/index.html${NC}"
echo -e "  ${GREEN}  API Root  → http://localhost:8000/health${NC}"
echo ""

# Open browser in background
(sleep 3 && \
  (xdg-open "http://localhost:8000/dashboard/index.html" 2>/dev/null || \
   open "http://localhost:8000/dashboard/index.html" 2>/dev/null || \
   true)) &

# ── Launch server
$PYTHON dashboard/backend.py

echo ""
echo -e "  ${RED}[!]${NC} Lucy OS v5 has stopped."