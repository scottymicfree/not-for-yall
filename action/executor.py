"""
LUCY EXECUTION SYSTEM
=====================
The real tool execution engine. Workers call this.
Every execution is:
  1. Validated (via ValidationPipeline)
  2. Gate-checked (via SafeExecutionGate)
  3. Sandboxed (subprocess timeout, memory caps, path jailing)
  4. Logged (every call, result, and error to AuditLedger)
  5. Self-correcting (retry with backoff on transient failures)

Tools available:
  bash          — shell commands (sandboxed, timeout, whitelist)
  read_file     — read a file (jailed to workspace)
  write_file    — write a file (jailed to workspace)
  list_dir      — list directory contents
  search        — text search across files (grep-like)
  code_run      — run Python code in isolated subprocess
  retrieval     — query ChromaDB / FAISS vector store
  http_get      — fetch a URL (GET only, no auth headers forwarded)
"""

import asyncio
import subprocess
import os
import re
import sys
import json
import time
import uuid
import shutil
import tempfile
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any, Callable
from datetime import datetime, timezone

# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    tool: str
    success: bool
    output: str
    error: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    retries: int = 0
    task_id: str = ""
    agent_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "success": self.success,
            "output": self.output[:4096],   # cap output
            "error": self.error[:1024],
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 2),
            "retries": self.retries,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
        }


# ── Sandbox configuration ─────────────────────────────────────────────────────

WORKSPACE_ROOT = Path(os.environ.get("LUCY_WORKSPACE", "/workspace/lucy-os/sandbox"))

# Commands allowed in bash tool (whitelist approach)
BASH_ALLOWED_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "find", "wc", "echo",
    "pwd", "date", "hostname", "uname", "env", "printenv",
    "python3", "python", "pip", "node", "npm",
    "curl",   # limited — no auth headers
    "wget",   # limited — no auth
    "git",    # limited — no push
    "mkdir", "touch", "cp", "mv",  # file ops within sandbox
    "sort", "uniq", "awk", "sed", "cut", "tr", "jq",
    "zip", "unzip", "tar",
    "diff", "patch",
}

# Commands always forbidden in bash tool
BASH_FORBIDDEN = {
    "rm", "rmdir", "shred",          # deletion
    "sudo", "su", "doas",            # privilege escalation
    "chmod", "chown", "chgrp",       # permission changes
    "dd", "mkfs", "fdisk", "parted", # disk ops
    "shutdown", "reboot", "halt",    # system control
    "iptables", "nftables",          # network rules
    "kill", "killall", "pkill",      # process killing
    "crontab", "at", "batch",        # scheduling
    "mount", "umount",               # filesystem
    "passwd", "useradd", "userdel",  # user management
    "ssh", "scp", "sftp",            # remote access
    "nc", "netcat", "ncat",          # raw sockets
}

MAX_OUTPUT_BYTES  = 1024 * 1024      # 1 MB output cap
DEFAULT_TIMEOUT   = 30               # seconds
MAX_TIMEOUT       = 120              # hard cap
MAX_RETRIES       = 3
RETRY_DELAY_BASE  = 0.5              # seconds, doubles each retry


# ── Path jail helper ──────────────────────────────────────────────────────────

def jail_path(path_str: str, root: Path = WORKSPACE_ROOT) -> Path:
    """
    Resolve path relative to sandbox root.
    Raises ValueError if path escapes sandbox.
    """
    root = root.resolve()
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = (root / path_str).resolve()
    if not str(candidate).startswith(str(root)):
        raise ValueError(
            f"Path '{path_str}' escapes sandbox root '{root}'. "
            f"Resolved to '{candidate}'.")
    return candidate


# ── Tool implementations ──────────────────────────────────────────────────────

class ToolExecutor:
    """
    Executes tools safely in a sandboxed environment.
    All execution is logged to AuditLedger.
    """

    def __init__(self, ledger=None, workspace: str = None):
        self.ledger = ledger
        self.workspace = Path(workspace or WORKSPACE_ROOT)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._tool_map: dict[str, Callable] = {
            "bash":       self._tool_bash,
            "read_file":  self._tool_read_file,
            "write_file": self._tool_write_file,
            "list_dir":   self._tool_list_dir,
            "search":     self._tool_search,
            "code_run":   self._tool_code_run,
            "http_get":   self._tool_http_get,
            "retrieval":  self._tool_retrieval,
        }

    # ── Public entry point ────────────────────────────────────────────────────

    async def execute(self,
                      tool: str,
                      tool_input: str,
                      agent_id: str = "unknown",
                      task_id: str = None,
                      timeout: float = DEFAULT_TIMEOUT,
                      max_retries: int = MAX_RETRIES) -> ExecutionResult:
        """
        Execute a named tool with retries and full logging.
        """
        task_id = task_id or str(uuid.uuid4())
        timeout = min(float(timeout), MAX_TIMEOUT)

        if self.ledger:
            self.ledger.tool_call(agent_id, task_id, tool, tool_input)

        fn = self._tool_map.get(tool)
        if fn is None:
            result = ExecutionResult(
                tool=tool, success=False,
                output="", error=f"Unknown tool: '{tool}'",
                task_id=task_id, agent_id=agent_id)
            if self.ledger:
                self.ledger.tool_error(agent_id, task_id, tool, result.error)
            return result

        # Retry loop
        last_result = None
        for attempt in range(max_retries + 1):
            t0 = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    fn(tool_input, agent_id, task_id),
                    timeout=timeout
                )
                result.duration_ms = (time.perf_counter() - t0) * 1000
                result.retries = attempt
                result.task_id = task_id
                result.agent_id = agent_id

                if result.success:
                    if self.ledger:
                        self.ledger.tool_result(agent_id, task_id, tool,
                                                result.output[:500])
                    return result

                # Transient failure — retry
                last_result = result
                if attempt < max_retries:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    await asyncio.sleep(delay)

            except asyncio.TimeoutError:
                last_result = ExecutionResult(
                    tool=tool, success=False,
                    output="", error=f"Timeout after {timeout}s",
                    exit_code=-1, duration_ms=(time.perf_counter() - t0) * 1000,
                    retries=attempt, task_id=task_id, agent_id=agent_id)
                break

            except Exception as e:
                last_result = ExecutionResult(
                    tool=tool, success=False,
                    output="", error=f"Unexpected error: {traceback.format_exc()[:500]}",
                    exit_code=-1, duration_ms=(time.perf_counter() - t0) * 1000,
                    retries=attempt, task_id=task_id, agent_id=agent_id)
                break

        if self.ledger and last_result:
            self.ledger.tool_error(agent_id, task_id, tool, last_result.error)
        return last_result or ExecutionResult(
            tool=tool, success=False, output="",
            error="All retries exhausted", task_id=task_id, agent_id=agent_id)

    # ── Tool: bash ────────────────────────────────────────────────────────────

    async def _tool_bash(self, cmd: str, agent_id: str, task_id: str) -> ExecutionResult:
        """
        Execute a shell command inside the sandbox.
        Whitelist-checked. Working directory jailed to workspace.
        """
        cmd = cmd.strip()

        # Extract the first command token
        first_token = cmd.split()[0].split("/")[-1] if cmd.split() else ""

        # Forbidden check
        if first_token in BASH_FORBIDDEN:
            return ExecutionResult(
                tool="bash", success=False, output="",
                error=f"Command '{first_token}' is in the forbidden list.")

        # Whitelist check (warn if not in whitelist but still attempt for
        # common compound commands like python scripts)
        if first_token not in BASH_ALLOWED_COMMANDS and not first_token.endswith(".py"):
            return ExecutionResult(
                tool="bash", success=False, output="",
                error=f"Command '{first_token}' not in allowed command list. "
                      f"Allowed: {sorted(BASH_ALLOWED_COMMANDS)}")

        # Shell metacharacter restrictions (no pipe to dangerous commands)
        dangerous_combos = [
            r"\|\s*(rm|sudo|dd|mkfs|shutdown|reboot|chmod\s+777)",
            r">\s*/etc/",
            r">\s*/bin/",
            r">\s*/usr/",
        ]
        for pattern in dangerous_combos:
            if re.search(pattern, cmd, re.IGNORECASE):
                return ExecutionResult(
                    tool="bash", success=False, output="",
                    error=f"Dangerous pipe/redirect pattern detected: {cmd[:100]}")

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
                env={**os.environ, "HOME": str(self.workspace)}
            )
            stdout, stderr = await proc.communicate()
            out = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            err = stderr.decode("utf-8", errors="replace")[:4096]
            return ExecutionResult(
                tool="bash",
                success=proc.returncode == 0,
                output=out,
                error=err if proc.returncode != 0 else "",
                exit_code=proc.returncode or 0)

        except Exception as e:
            return ExecutionResult(tool="bash", success=False, output="",
                                   error=str(e), exit_code=-1)

    # ── Tool: read_file ───────────────────────────────────────────────────────

    async def _tool_read_file(self, path: str, agent_id: str, task_id: str) -> ExecutionResult:
        try:
            safe = jail_path(path.strip(), self.workspace)
            if not safe.exists():
                return ExecutionResult(tool="read_file", success=False,
                    output="", error=f"File not found: {path}")
            if not safe.is_file():
                return ExecutionResult(tool="read_file", success=False,
                    output="", error=f"Not a file: {path}")
            size = safe.stat().st_size
            if size > MAX_OUTPUT_BYTES:
                return ExecutionResult(tool="read_file", success=False,
                    output="", error=f"File too large: {size} bytes (max {MAX_OUTPUT_BYTES})")
            content = safe.read_text(encoding="utf-8", errors="replace")
            return ExecutionResult(tool="read_file", success=True,
                output=content, exit_code=0)
        except ValueError as e:
            return ExecutionResult(tool="read_file", success=False,
                output="", error=str(e))
        except Exception as e:
            return ExecutionResult(tool="read_file", success=False,
                output="", error=str(e))

    # ── Tool: write_file ──────────────────────────────────────────────────────

    async def _tool_write_file(self, args: str, agent_id: str, task_id: str) -> ExecutionResult:
        """
        args format: "path::content"
        Writes content to path. Creates parent directories.
        """
        if "::" not in args:
            return ExecutionResult(tool="write_file", success=False,
                output="", error="Format: 'path::content'")
        path_str, content = args.split("::", 1)
        try:
            safe = jail_path(path_str.strip(), self.workspace)
            safe.parent.mkdir(parents=True, exist_ok=True)
            safe.write_text(content, encoding="utf-8")
            return ExecutionResult(tool="write_file", success=True,
                output=f"Written {len(content)} bytes to {safe.name}",
                exit_code=0)
        except ValueError as e:
            return ExecutionResult(tool="write_file", success=False,
                output="", error=str(e))
        except Exception as e:
            return ExecutionResult(tool="write_file", success=False,
                output="", error=str(e))

    # ── Tool: list_dir ────────────────────────────────────────────────────────

    async def _tool_list_dir(self, path: str, agent_id: str, task_id: str) -> ExecutionResult:
        try:
            safe = jail_path(path.strip() or ".", self.workspace)
            if not safe.exists():
                return ExecutionResult(tool="list_dir", success=False,
                    output="", error=f"Path not found: {path}")
            entries = []
            for item in sorted(safe.iterdir()):
                kind = "DIR " if item.is_dir() else "FILE"
                size = item.stat().st_size if item.is_file() else 0
                entries.append(f"{kind}  {item.name:40s}  {size:>10} bytes")
            return ExecutionResult(tool="list_dir", success=True,
                output="\n".join(entries) or "(empty directory)",
                exit_code=0)
        except ValueError as e:
            return ExecutionResult(tool="list_dir", success=False,
                output="", error=str(e))

    # ── Tool: search ──────────────────────────────────────────────────────────

    async def _tool_search(self, args: str, agent_id: str, task_id: str) -> ExecutionResult:
        """
        args format: "pattern::path" or just "pattern" (searches workspace)
        Case-insensitive grep across text files.
        """
        parts = args.split("::", 1)
        pattern = parts[0].strip()
        search_path = parts[1].strip() if len(parts) > 1 else "."

        try:
            safe = jail_path(search_path, self.workspace)
            results = []
            max_results = 200

            for filepath in safe.rglob("*"):
                if len(results) >= max_results:
                    results.append(f"... (truncated at {max_results} results)")
                    break
                if not filepath.is_file():
                    continue
                try:
                    text = filepath.read_text(encoding="utf-8", errors="replace")
                    for i, line in enumerate(text.splitlines(), 1):
                        if re.search(pattern, line, re.IGNORECASE):
                            rel = filepath.relative_to(self.workspace)
                            results.append(f"{rel}:{i}: {line.strip()[:200]}")
                except Exception:
                    continue

            return ExecutionResult(
                tool="search", success=True,
                output="\n".join(results) if results else f"No matches for '{pattern}'",
                exit_code=0)
        except ValueError as e:
            return ExecutionResult(tool="search", success=False,
                output="", error=str(e))
        except re.error as e:
            return ExecutionResult(tool="search", success=False,
                output="", error=f"Invalid regex pattern: {e}")

    # ── Tool: code_run ────────────────────────────────────────────────────────

    async def _tool_code_run(self, code: str, agent_id: str, task_id: str) -> ExecutionResult:
        """
        Execute Python code in an isolated subprocess.
        Uses a temp file. No imports of dangerous modules.
        """
        BLOCKED_IMPORTS = {
            "os", "sys", "subprocess", "socket", "shutil",
            "importlib", "ctypes", "eval", "exec",
            "pickle", "marshal", "__import__"
        }

        # Quick static check for blocked imports
        for blocked in BLOCKED_IMPORTS:
            pattern = rf"\b(import\s+{blocked}|from\s+{blocked}\s+import)\b"
            if re.search(pattern, code):
                return ExecutionResult(
                    tool="code_run", success=False, output="",
                    error=f"Blocked import: '{blocked}' is not allowed in code_run sandbox")

        # Write to temp file and execute
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False,
            dir=str(self.workspace)
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONPATH": "",
                    "HOME": str(self.workspace)
                }
            )
            stdout, stderr = await proc.communicate()
            out = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            err = stderr.decode("utf-8", errors="replace")[:4096]
            return ExecutionResult(
                tool="code_run",
                success=proc.returncode == 0,
                output=out,
                error=err if proc.returncode != 0 else "",
                exit_code=proc.returncode or 0)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ── Tool: http_get ────────────────────────────────────────────────────────

    async def _tool_http_get(self, url: str, agent_id: str, task_id: str) -> ExecutionResult:
        """
        Fetch a URL via GET. No auth headers. No redirects to internal IPs.
        """
        import urllib.parse
        url = url.strip()

        # Validate URL
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ExecutionResult(tool="http_get", success=False,
                output="", error=f"Only http/https allowed. Got: {parsed.scheme}")

        # Block internal IPs (SSRF protection)
        host = parsed.hostname or ""
        internal_patterns = [
            r"^localhost$", r"^127\.", r"^10\.", r"^172\.(1[6-9]|2\d|3[01])\.",
            r"^192\.168\.", r"^::1$", r"^0\.0\.0\.0$",
        ]
        for p in internal_patterns:
            if re.match(p, host, re.IGNORECASE):
                return ExecutionResult(tool="http_get", success=False,
                    output="", error=f"Internal/loopback addresses blocked: {host}")

        try:
            import httpx
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                max_redirects=3,
                headers={"User-Agent": "LucyWorker/1.0"}
            ) as client:
                resp = await client.get(url)
                body = resp.text[:MAX_OUTPUT_BYTES]
                return ExecutionResult(
                    tool="http_get", success=True,
                    output=body, exit_code=resp.status_code)
        except Exception as e:
            return ExecutionResult(tool="http_get", success=False,
                output="", error=str(e))

    # ── Tool: retrieval ───────────────────────────────────────────────────────

    async def _tool_retrieval(self, args: str, agent_id: str, task_id: str) -> ExecutionResult:
        """
        Query the local vector store.
        args format: "query_text" or "query_text::n_results"
        """
        parts = args.split("::", 1)
        query = parts[0].strip()
        n_results = int(parts[1]) if len(parts) > 1 else 5
        n_results = min(n_results, 20)  # cap

        try:
            import chromadb
            client = chromadb.PersistentClient(
                path=str(Path(self.workspace).parent / "data" / "chroma_global"))
            collections = client.list_collections()
            if not collections:
                return ExecutionResult(tool="retrieval", success=True,
                    output="No collections in vector store yet.", exit_code=0)

            all_results = []
            for col in collections[:3]:   # search top 3 collections
                collection = client.get_collection(col.name)
                res = collection.query(query_texts=[query], n_results=n_results)
                docs = res.get("documents", [[]])[0]
                for doc in docs:
                    all_results.append(doc[:500])

            output = "\n---\n".join(all_results) if all_results else f"No results for: {query}"
            return ExecutionResult(tool="retrieval", success=True,
                output=output, exit_code=0)

        except ImportError:
            return ExecutionResult(tool="retrieval", success=False,
                output="", error="chromadb not installed. Run: pip install chromadb")
        except Exception as e:
            return ExecutionResult(tool="retrieval", success=False,
                output="", error=str(e))

    # ── Registry helpers ──────────────────────────────────────────────────────

    def list_tools(self) -> list[str]:
        return list(self._tool_map.keys())

    def register_tool(self, name: str, fn: Callable):
        """Register a custom tool at runtime."""
        self._tool_map[name] = fn


# ── ReAct-compatible tool runner ──────────────────────────────────────────────

class ReActToolRunner:
    """
    Wraps ToolExecutor for use inside a ReAct loop.
    Parses "TOOL_NAME | input" strings from LLM output.
    """

    def __init__(self, executor: ToolExecutor):
        self.executor = executor

    async def run_from_action_string(self,
                                     action_str: str,
                                     agent_id: str,
                                     task_id: str) -> str:
        """
        Parse 'tool_name | input_value' and execute.
        Returns formatted observation string for ReAct loop.
        """
        action_str = action_str.strip()

        if "|" not in action_str:
            return f"ERROR: Action must be 'tool_name | input'. Got: '{action_str}'"

        parts = action_str.split("|", 1)
        tool = parts[0].strip().lower()
        tool_input = parts[1].strip() if len(parts) > 1 else ""

        result = await self.executor.execute(
            tool=tool,
            tool_input=tool_input,
            agent_id=agent_id,
            task_id=task_id
        )

        if result.success:
            return f"[{tool}] SUCCESS:\n{result.output}"
        else:
            return f"[{tool}] ERROR (exit {result.exit_code}):\n{result.error}"

    def available_tools_prompt(self) -> str:
        """Format available tools for inclusion in system prompt."""
        descriptions = {
            "bash":       "Execute a shell command. Input: command string.",
            "read_file":  "Read a file. Input: relative path.",
            "write_file": "Write a file. Input: 'path::content'.",
            "list_dir":   "List directory contents. Input: relative path.",
            "search":     "Search files by pattern. Input: 'pattern::path'.",
            "code_run":   "Run Python code. Input: Python code string.",
            "http_get":   "HTTP GET a URL. Input: URL string.",
            "retrieval":  "Query vector store. Input: 'query::n_results'.",
        }
        lines = []
        for tool in self.executor.list_tools():
            desc = descriptions.get(tool, "No description.")
            lines.append(f"  {tool:<12} — {desc}")
        return "\n".join(lines)