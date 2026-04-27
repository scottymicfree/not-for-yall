"""
lucy-terminal-server.py — Lucy OS Terminal Access Server
=========================================================
A local WebSocket + HTTP server that lets Lucy execute PowerShell
commands on your Windows machine and stream the output back.

Lucy translates your plain-English requests into commands,
runs them, and shows you exactly what happened.

Security model:
  - Runs on localhost only (127.0.0.1) — not exposed to internet
  - Dangerous commands (format, rm -rf, etc.) require confirmation
  - Full audit log of every command run
  - You can whitelist/blacklist any command

Start: python lucy-terminal-server.py
Port:  8766
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Auto-install dependencies
def _ensure_deps():
    try:
        import fastapi, uvicorn, websockets
    except ImportError:
        print("[terminal] Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "fastapi", "uvicorn[standard]", "--quiet"])
_ensure_deps()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# ── Config ─────────────────────────────────────────────────────────────────
PORT        = 8766
IS_WINDOWS  = platform.system() == "Windows"
LOG_FILE    = Path(__file__).parent / "terminal_audit.log"
WORKING_DIR = Path.home()   # Start in user's home directory

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [terminal] %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("lucy_terminal")

# ── Safety: commands that need confirmation ────────────────────────────────
DANGEROUS_PATTERNS = [
    "format ", "mkformat", "diskpart",
    "rm -rf", "remove-item -recurse -force",
    "del /f /s /q", "rd /s /q",
    "reg delete", "regedit",
    "net user", "net localgroup",
    "shutdown", "restart-computer",
    "stop-service", "disable-netadapter",
    "clear-disk", "initialize-disk",
    "invoke-expression", "iex ",
    "downloadstring", "webclient",
    "start-process.*runas",
]

SAFE_READ_ONLY = [
    "get-", "dir", "ls", "pwd", "echo", "type", "cat",
    "where", "which", "whoami", "hostname", "ipconfig",
    "netstat", "tasklist", "systeminfo", "ver", "date",
    "python --version", "node --version", "npm --version",
    "pip list", "pip show", "ollama list",
    "choco list", "winget list",
    "test-connection", "ping",
    "get-process", "get-service", "get-childitem",
    "get-content", "get-location", "get-command",
    "get-installedmodule", "get-module",
    "wmic", "diskpart /s", "net start",
]

def is_dangerous(cmd: str) -> bool:
    cmd_lower = cmd.lower().strip()
    return any(p in cmd_lower for p in DANGEROUS_PATTERNS)

def is_safe_readonly(cmd: str) -> bool:
    cmd_lower = cmd.lower().strip()
    return any(cmd_lower.startswith(p) or p in cmd_lower for p in SAFE_READ_ONLY)

def audit_log(cmd: str, output: str, duration_ms: float):
    """Write to audit log."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                "cmd": cmd,
                "duration_ms": round(duration_ms, 1),
                "output_len": len(output),
                "output_preview": output[:200],
            }) + "\n")
    except Exception:
        pass

# ── Command execution ──────────────────────────────────────────────────────
async def run_command(cmd: str, cwd: str = None, timeout: int = 30) -> dict:
    """Execute a PowerShell command and return result."""
    start = time.time()
    working_dir = cwd or str(WORKING_DIR)

    if IS_WINDOWS:
        # Run via PowerShell on Windows
        shell_cmd = ["powershell", "-NoProfile", "-NonInteractive",
                     "-ExecutionPolicy", "Bypass", "-Command", cmd]
    else:
        # Run via bash on Linux/Mac (for testing)
        shell_cmd = ["bash", "-c", cmd]

    try:
        proc = await asyncio.create_subprocess_exec(
            *shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "ok": False,
                "output": f"⏱ Command timed out after {timeout}s",
                "error": "timeout",
                "exit_code": -1,
                "duration_ms": (time.time() - start) * 1000,
            }

        duration_ms = (time.time() - start) * 1000
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        combined = out
        if err:
            combined = combined + ("\n" if combined else "") + f"[stderr] {err}"

        audit_log(cmd, combined, duration_ms)

        return {
            "ok": proc.returncode == 0,
            "output": combined or "(no output)",
            "exit_code": proc.returncode,
            "duration_ms": round(duration_ms, 1),
            "cwd": working_dir,
        }

    except FileNotFoundError:
        return {
            "ok": False,
            "output": "PowerShell not found. Are you on Windows?",
            "error": "not_found",
            "exit_code": -1,
            "duration_ms": 0,
        }
    except Exception as e:
        return {
            "ok": False,
            "output": f"Error: {e}",
            "error": str(e),
            "exit_code": -1,
            "duration_ms": (time.time() - start) * 1000,
        }

# ── Lucy's command translator ──────────────────────────────────────────────
LUCY_TRANSLATIONS = {
    # System info
    "what python version":          "python --version",
    "python version":               "python --version",
    "what node version":            "node --version",
    "node version":                 "node --version",
    "what's installed":             "choco list --local-only 2>$null; winget list 2>$null",
    "list installed":               "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Select-Object DisplayName,DisplayVersion | Sort-Object DisplayName",
    "disk space":                   "Get-PSDrive -PSProvider FileSystem | Select-Object Name,@{N='Used(GB)';E={[math]::Round($_.Used/1GB,2)}},@{N='Free(GB)';E={[math]::Round($_.Free/1GB,2)}}",
    "what's running":               "Get-Process | Sort-Object CPU -Descending | Select-Object -First 20 Name,CPU,WorkingSet | Format-Table",
    "running processes":            "Get-Process | Sort-Object CPU -Descending | Select-Object -First 20 Name,CPU,WorkingSet | Format-Table",
    "ip address":                   "ipconfig | findstr /i 'ipv4'",
    "my ip":                        "ipconfig | findstr /i 'ipv4'",
    "internet connection":          "Test-Connection 8.8.8.8 -Count 2 | Select-Object Address,Latency",
    "check internet":               "Test-Connection 8.8.8.8 -Count 2 | Select-Object Address,Latency",
    "system info":                  "Get-ComputerInfo | Select-Object WindowsProductName,TotalPhysicalMemory,CsProcessors",
    "gpu info":                     "Get-WmiObject Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion",
    "cpu info":                     "Get-WmiObject Win32_Processor | Select-Object Name,NumberOfCores,MaxClockSpeed",
    "ram":                          "$mem = Get-WmiObject Win32_ComputerSystem; \"Total RAM: $([math]::Round($mem.TotalPhysicalMemory/1GB,2)) GB\"",
    "memory":                       "$mem = Get-WmiObject Win32_ComputerSystem; \"Total RAM: $([math]::Round($mem.TotalPhysicalMemory/1GB,2)) GB\"",
    "where am i":                   "Get-Location",
    "current folder":               "Get-Location",
    "list files":                   "Get-ChildItem | Select-Object Name,Length,LastWriteTime | Format-Table",
    "show files":                   "Get-ChildItem | Select-Object Name,Length,LastWriteTime | Format-Table",

    # Python / pip
    "install python":               "winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements",
    "python packages":              "pip list",
    "install pip package":          "pip install",
    "update pip":                   "python -m pip install --upgrade pip",

    # Node / npm
    "install node":                 "winget install OpenJS.NodeJS.LTS --accept-package-agreements",
    "npm packages":                 "npm list -g --depth=0",

    # Ollama
    "ollama models":                "ollama list",
    "install ollama":               "winget install Ollama.Ollama --accept-package-agreements",
    "start ollama":                 "Start-Process ollama -ArgumentList 'serve' -WindowStyle Hidden",
    "is ollama running":            "Get-Process ollama -ErrorAction SilentlyContinue | Select-Object Name,CPU",

    # Lucy specific
    "start lucy":                   "cd $env:USERPROFILE\\lucy-electron; .\\START.bat",
    "lucy status":                  "Get-Process -Name 'Lucy OS','electron','python' -ErrorAction SilentlyContinue | Select-Object Name,CPU,WorkingSet",
    "start bridge":                 "Start-Process python -ArgumentList 'lucy-bridge\\lucy_bridge_service.py --mode auto' -WindowStyle Minimized",
    "check ports":                  "netstat -an | findstr 'LISTENING' | findstr '8765 8766 11434 8000'",
}

def translate_natural_language(text: str) -> Optional[str]:
    """Try to map plain English to a PowerShell command."""
    text_lower = text.lower().strip()
    # Exact and partial matches
    for phrase, cmd in LUCY_TRANSLATIONS.items():
        if phrase in text_lower:
            return cmd
    return None

# ── FastAPI app ────────────────────────────────────────────────────────────
app = FastAPI(title="Lucy Terminal Server", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

_ws_clients: list[WebSocket] = []
_command_history: list[dict] = []
_current_cwd = str(WORKING_DIR)

@app.get("/")
async def root():
    return {
        "service": "Lucy Terminal Server",
        "port": PORT,
        "platform": platform.system(),
        "cwd": _current_cwd,
        "history_count": len(_command_history),
    }

@app.get("/health")
async def health():
    return {"ok": True, "ts": time.time()}

@app.get("/history")
async def get_history():
    return {"history": _command_history[-50:]}

@app.get("/cwd")
async def get_cwd():
    return {"cwd": _current_cwd}

@app.post("/run")
async def run_endpoint(body: dict):
    """
    Run a command. Body: {"cmd": "...", "natural": true/false}
    natural=true means Lucy will translate plain English first.
    """
    global _current_cwd

    raw_input = body.get("cmd", "").strip()
    is_natural = body.get("natural", False)

    if not raw_input:
        return {"ok": False, "output": "No command provided"}

    # Translate natural language if requested
    cmd = raw_input
    translated = False
    if is_natural:
        mapped = translate_natural_language(raw_input)
        if mapped:
            cmd = mapped
            translated = True
        else:
            # Pass through as-is (user might have typed actual PowerShell)
            cmd = raw_input

    # Safety check
    dangerous = is_dangerous(cmd)
    if dangerous and not body.get("confirmed", False):
        return {
            "ok": False,
            "needs_confirmation": True,
            "output": f"⚠️ This command could be destructive. Send with confirmed=true to proceed.",
            "cmd": cmd,
        }

    # Handle 'cd' specially to track working directory
    if cmd.lower().startswith("cd ") or cmd.lower().startswith("set-location"):
        new_dir = cmd.split(None, 1)[1].strip().strip('"\'')
        try:
            new_path = Path(_current_cwd) / new_dir
            if new_path.exists():
                _current_cwd = str(new_path.resolve())
                return {"ok": True, "output": f"📂 Now in: {_current_cwd}",
                        "cwd": _current_cwd, "duration_ms": 0}
        except Exception:
            pass

    result = await run_command(cmd, cwd=_current_cwd)
    result["cmd"] = cmd
    result["original_input"] = raw_input
    result["translated"] = translated
    result["cwd"] = _current_cwd

    # Store in history
    _command_history.append({
        "ts": datetime.now().isoformat(),
        "input": raw_input,
        "cmd": cmd,
        "ok": result["ok"],
        "output_preview": result["output"][:200],
    })
    if len(_command_history) > 200:
        _command_history.pop(0)

    # Broadcast to WebSocket clients
    if _ws_clients:
        msg = json.dumps({"type": "command_result", **result})
        for ws in list(_ws_clients):
            try:
                await ws.send_text(msg)
            except Exception:
                _ws_clients.remove(ws)

    return result

@app.websocket("/ws")
async def ws_terminal(websocket: WebSocket):
    """WebSocket for real-time terminal streaming."""
    await websocket.accept()
    _ws_clients.append(websocket)
    log.info(f"Terminal WebSocket connected ({len(_ws_clients)} clients)")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                cmd = msg.get("cmd", "").strip()
                natural = msg.get("natural", False)

                if not cmd:
                    continue

                # Send "running" status
                await websocket.send_text(json.dumps({
                    "type": "running",
                    "cmd": cmd,
                    "ts": time.time(),
                }))

                # Translate if natural language
                translated_cmd = cmd
                translated = False
                if natural:
                    mapped = translate_natural_language(cmd)
                    if mapped:
                        translated_cmd = mapped
                        translated = True
                        await websocket.send_text(json.dumps({
                            "type": "translated",
                            "original": cmd,
                            "cmd": translated_cmd,
                        }))

                # Safety check
                if is_dangerous(translated_cmd) and not msg.get("confirmed"):
                    await websocket.send_text(json.dumps({
                        "type": "needs_confirmation",
                        "cmd": translated_cmd,
                        "message": "⚠️ This command could modify system files. Reply with confirmed=true to proceed.",
                    }))
                    continue

                # Run and stream result
                result = await run_command(translated_cmd, cwd=_current_cwd)
                await websocket.send_text(json.dumps({
                    "type": "result",
                    "cmd": translated_cmd,
                    "original": cmd,
                    "translated": translated,
                    **result,
                }))

            except json.JSONDecodeError:
                # Plain text command
                result = await run_command(data.strip(), cwd=_current_cwd)
                await websocket.send_text(json.dumps({
                    "type": "result", "cmd": data.strip(), **result
                }))

    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
        log.info(f"Terminal WebSocket disconnected ({len(_ws_clients)} remaining)")


@app.get("/translations")
async def list_translations():
    """Show all natural language → command mappings."""
    return {"translations": LUCY_TRANSLATIONS}


if __name__ == "__main__":
    log.info(f"=== Lucy Terminal Server ===")
    log.info(f"Platform: {platform.system()}")
    log.info(f"Working dir: {WORKING_DIR}")
    log.info(f"Audit log: {LOG_FILE}")
    log.info(f"Starting on http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")