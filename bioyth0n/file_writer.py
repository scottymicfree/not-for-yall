"""
Bioyth0n — Governed File Writer
Executes approved file write operations through a strict path whitelist.
No reasoning. No decisions. Only validated, approved writes.
"""

from __future__ import annotations
import os
import time
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("bioyth0n.file_writer")

# ─────────────────────────────────────────────
# Approved write root paths (relative to workspace)
# ─────────────────────────────────────────────
APPROVED_WRITE_ROOTS = [
    "lucy-os/",
    "lucy-os/bridges/fivem_resource/",
    "lucy-os/dashboard/",
    "lucy-os/unr5/",
    "lucy-os/logs/",
    "lucy-os/data/",
    "ue5_workspace/Content/LucyGenerated/",
    "unity_workspace/Assets/LucyGenerated/",
    "fivem_resources/",
    "output/",
]

# These extensions are writable
ALLOWED_EXTENSIONS = {
    ".py", ".lua", ".json", ".yaml", ".yml", ".txt", ".md",
    ".html", ".css", ".js", ".ts", ".cfg", ".ini", ".log",
    ".umap", ".uasset",   # UE5
    ".unity", ".cs",      # Unity
    ".sql", ".csv",
}

# These paths are NEVER writable regardless of approval
FORBIDDEN_PATHS = [
    "lucy-os/bioyth0n/executor.py",
    "lucy-os/safety/",
    "lucy-os/mesh/event_bus.py",
    "lucy-os/unr5/delta_vault.py",
    ".env",
    ".git/",
    "secrets/",
    "credentials/",
]

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024    # 5 MB write limit per call
_write_lock = threading.RLock()


class GovernedFileWriter:
    """
    Governs all file write operations for Bioyth0n.
    NEVER called directly — always invoked through BioyTh0nExecutor.
    """

    def _resolve_path(self, file_path: str) -> tuple[bool, str, Path]:
        """Returns (allowed, reason, resolved_path)."""
        # Normalise
        clean = file_path.replace("\\", "/").lstrip("/")
        p = Path(clean)

        # Check forbidden first
        for forbidden in FORBIDDEN_PATHS:
            if clean.startswith(forbidden) or str(p).startswith(forbidden):
                return False, f"forbidden_path:{forbidden}", p

        # Check approved roots
        in_approved = any(clean.startswith(root) for root in APPROVED_WRITE_ROOTS)
        if not in_approved:
            return False, f"path_not_in_approved_roots:{clean}", p

        # Check extension
        if p.suffix and p.suffix not in ALLOWED_EXTENSIONS:
            return False, f"extension_not_allowed:{p.suffix}", p

        # Path traversal guard
        try:
            resolved = p.resolve()
            for root in APPROVED_WRITE_ROOTS:
                root_resolved = Path(root).resolve()
                try:
                    resolved.relative_to(root_resolved)
                    return True, "ok", p
                except ValueError:
                    continue
            # If no root matched the resolved path, check using string prefix
            return True, "ok", p
        except Exception as e:
            return False, f"path_resolve_error:{e}", p

    def write(
        self,
        file_path:   str,
        content:     str,
        append_mode: bool = False,
        encoding:    str  = "utf-8",
    ) -> dict[str, Any]:
        """
        Write content to file_path.
        Returns result dict with success/error fields.
        """
        allowed, reason, path = self._resolve_path(file_path)
        if not allowed:
            logger.error(f"[FileWriter] DENIED write to '{file_path}': {reason}")
            return {"success": False, "error": reason, "file_path": file_path}

        if len(content.encode(encoding, errors="replace")) > MAX_FILE_SIZE_BYTES:
            return {
                "success": False,
                "error":   f"content_exceeds_limit:{MAX_FILE_SIZE_BYTES}bytes",
                "file_path": file_path,
            }

        with _write_lock:
            try:
                # Create parent dirs if needed
                path.parent.mkdir(parents=True, exist_ok=True)

                mode = "a" if append_mode else "w"
                with open(path, mode, encoding=encoding) as f:
                    f.write(content)

                stat = path.stat()
                logger.info(
                    f"[FileWriter] wrote '{file_path}' "
                    f"mode={'append' if append_mode else 'write'} "
                    f"bytes={stat.st_size}"
                )
                return {
                    "success":    True,
                    "file_path":  str(path),
                    "bytes":      stat.st_size,
                    "mode":       "append" if append_mode else "write",
                    "timestamp":  time.time(),
                }

            except Exception as e:
                logger.error(f"[FileWriter] write error '{file_path}': {e}")
                return {"success": False, "error": str(e), "file_path": file_path}

    def read(
        self,
        file_path:  str,
        max_bytes:  int = 1024 * 1024,
        encoding:   str = "utf-8",
    ) -> dict[str, Any]:
        """Read a file (no approval required for reads)."""
        path = Path(file_path.replace("\\", "/").lstrip("/"))
        try:
            if not path.exists():
                return {"success": False, "error": "file_not_found", "file_path": file_path}
            with open(path, "r", encoding=encoding, errors="replace") as f:
                content = f.read(max_bytes)
            return {
                "success":   True,
                "file_path": str(path),
                "content":   content,
                "bytes":     len(content.encode(encoding, errors="replace")),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "file_path": file_path}

    def create_directory(self, dir_path: str, parents: bool = True) -> dict[str, Any]:
        """Create a directory under an approved root."""
        clean = dir_path.replace("\\", "/").lstrip("/")
        in_approved = any(clean.startswith(root) for root in APPROVED_WRITE_ROOTS)
        if not in_approved:
            return {"success": False, "error": f"path_not_approved:{clean}"}
        try:
            Path(clean).mkdir(parents=parents, exist_ok=True)
            logger.info(f"[FileWriter] created directory '{clean}'")
            return {"success": True, "dir_path": clean}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_directory(
        self,
        dir_path:   str,
        recursive:  bool = False,
        filter_ext: str  = "",
    ) -> dict[str, Any]:
        """List directory contents (no approval required)."""
        path = Path(dir_path.replace("\\", "/").lstrip("/"))
        try:
            if not path.exists():
                return {"success": False, "error": "directory_not_found"}
            if recursive:
                files = [
                    str(p) for p in path.rglob("*")
                    if p.is_file() and (not filter_ext or p.suffix == filter_ext)
                ]
            else:
                files = [
                    str(p) for p in path.iterdir()
                    if not filter_ext or p.suffix == filter_ext
                ]
            return {"success": True, "dir_path": str(path), "entries": files, "count": len(files)}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
governed_file_writer = GovernedFileWriter()