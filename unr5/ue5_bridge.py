"""
UE5 + Unity Bridge — Python port of ue5/bridge.js + unity/bridge.js
Allows Lucy to connect to, scan, scaffold, and execute tasks in
Unreal Engine 5 and Unity projects.

Lucy can build in UE5/Unity with just natural language instructions.
The AutoBuilder translates prompts → plans → Emma-approved steps → execution.
"""

import os
import json
import time
import subprocess
import threading
from pathlib import Path
from typing import Optional, List


# ─── Workspace Store ──────────────────────────────────────────────────────────

class WorkspaceStore:
    """Persistent workspace config per engine."""

    def __init__(self, data_path: str):
        self._path = Path(data_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                pass
        return {"editorPath": "", "projectPath": "", "lastScan": None}

    def _save(self):
        self._path.write_text(json.dumps(self._data, indent=2))

    def get(self) -> dict:
        with self._lock:
            return dict(self._data)

    def save(self, editor_path: str, project_path: str) -> dict:
        with self._lock:
            self._data["editorPath"] = editor_path
            self._data["projectPath"] = project_path
            self._save()
            return dict(self._data)

    def stamp_scan(self):
        with self._lock:
            self._data["lastScan"] = int(time.time() * 1000)
            self._save()


# ─── UE5 Bridge ───────────────────────────────────────────────────────────────

class UE5Bridge:

    def __init__(self, data_dir: str = "data/ue5"):
        self._ws = WorkspaceStore(f"{data_dir}/workspace.json")

    def _find_uproject(self, project_path: str) -> Optional[str]:
        if not project_path:
            return None
        p = Path(project_path)
        if project_path.endswith(".uproject") and p.exists():
            return project_path
        if not p.exists():
            return None
        found = list(p.glob("*.uproject"))
        return str(found[0]) if found else None

    def _list_dirs(self, base: str) -> List[str]:
        p = Path(base)
        if not p.exists():
            return []
        return sorted([d.name for d in p.iterdir() if d.is_dir()])

    def _walk_maps(self, base: Path, rel: str = "") -> List[str]:
        results = []
        full = base / rel if rel else base
        if not full.exists():
            return []
        for entry in full.iterdir():
            next_rel = f"{rel}/{entry.name}" if rel else entry.name
            if entry.is_dir():
                results.extend(self._walk_maps(base, next_rel))
            elif entry.name.lower().endswith(".umap"):
                results.append(next_rel.replace("\\", "/"))
        return sorted(results)[:100]

    def get_status(self) -> dict:
        ws = self._ws.get()
        project_file = self._find_uproject(ws.get("projectPath", ""))
        project_root = str(Path(project_file).parent) if project_file else ws.get("projectPath", "")
        content_dir  = str(Path(project_root) / "Content") if project_root else ""
        editor_exists = Path(ws.get("editorPath", "")).exists() if ws.get("editorPath") else False

        return {
            "workspace": ws,
            "connected": bool(project_file),
            "editorFound": editor_exists,
            "projectFound": bool(project_file),
            "projectFile": project_file,
            "contentDir": content_dir,
            "canScan": bool(project_file),
            "canBuild": editor_exists and bool(project_file),
        }

    def connect_workspace(self, editor_path: str, project_path: str) -> dict:
        self._ws.save(editor_path, project_path)
        return self.get_status()

    def scan_project(self) -> dict:
        status = self.get_status()
        if not status["projectFound"]:
            return {"ok": False, "error": "No UE5 project found. Connect a valid .uproject file or project folder first."}

        project_root = Path(status["projectFile"]).parent
        plugins      = self._list_dirs(str(project_root / "Plugins"))
        source_mods  = self._list_dirs(str(project_root / "Source"))
        maps         = self._walk_maps(project_root / "Content")
        self._ws.stamp_scan()

        return {
            "ok": True,
            "scannedAt": int(time.time() * 1000),
            "projectName": Path(status["projectFile"]).stem,
            "projectFile": status["projectFile"],
            "projectRoot": str(project_root),
            "plugins": plugins,
            "sourceModules": source_mods,
            "maps": maps,
            "hasContent": (project_root / "Content").exists(),
            "hasConfig": (project_root / "Config").exists(),
        }

    def create_map_scaffold(self, module_name: str) -> dict:
        status = self.get_status()
        if not status["projectFound"]:
            return {"ok": False, "error": "Project is not connected."}

        safe_name = "".join(c for c in module_name if c.isalnum() or c in "_-").strip()
        if not safe_name:
            return {"ok": False, "error": "moduleName is required."}

        project_root = Path(status["projectFile"]).parent
        base = project_root / "Content" / "LucyGenerated" / safe_name
        maps_dir       = base / "Maps"
        blueprints_dir = base / "Blueprints"
        maps_dir.mkdir(parents=True, exist_ok=True)
        blueprints_dir.mkdir(parents=True, exist_ok=True)

        readme = base / "README_LUCY.txt"
        if not readme.exists():
            readme.write_text(
                f"Lucy-generated UE5 scaffold: {safe_name}\n"
                "This scaffold was created through the Emma-approved UE5 lane.\n"
                "Add .umap files under Maps and supporting assets under Blueprints or sibling folders.\n"
            )

        return {
            "ok": True,
            "createdAt": int(time.time() * 1000),
            "moduleName": safe_name,
            "createdPaths": [str(maps_dir), str(blueprints_dir), str(readme)],
        }

    def execute_task(self, task_type: str, map_name: str = "") -> dict:
        status = self.get_status()
        if not status["projectFound"]:
            return {"ok": False, "error": "Project is not connected."}

        project_file = status["projectFile"]
        editor_path  = status["workspace"].get("editorPath", "")
        project_root = str(Path(project_file).parent)

        if task_type == "resave-dry-run":
            cmd = f"{editor_path or 'UnrealEditor-Cmd.exe'} {project_file} -run=ResavePackages -ProjectOnly -NoShaderCompile -IgnoreChangelist"
            return {"ok": True, "executed": False, "taskType": task_type, "preview": cmd, "ready": status["canBuild"]}

        if task_type == "cook-dry-run":
            cmd = f"{editor_path or 'RunUAT.bat'} BuildCookRun -project={project_file} -cook -stage -pak -archive -noP4"
            return {"ok": True, "executed": False, "taskType": task_type, "preview": cmd, "ready": status["canBuild"]}

        if task_type == "scaffold-check":
            return {"ok": True, "executed": False, "taskType": task_type,
                    "preview": f"Would create scaffold in {project_root}/Content/LucyGenerated/",
                    "ready": status["canScan"]}

        if not status["canBuild"]:
            return {"ok": False, "error": "Editor path or project file is missing."}

        if task_type == "resave-content":
            args = [editor_path, project_file, "-run=ResavePackages", "-ProjectOnly", "-NoShaderCompile", "-IgnoreChangelist"]
            result = self._run_command(args, project_root)
            return {"ok": result["code"] == 0, "executed": True, "taskType": task_type, **result}

        if task_type == "cook-content":
            args = [editor_path, project_file, "-run=Cook", "-TargetPlatform=Windows", "-Unattended"]
            if map_name:
                args.append(f"-Map={map_name}")
            result = self._run_command(args, project_root)
            return {"ok": result["code"] == 0, "executed": True, "taskType": task_type, **result}

        return {"ok": False, "error": f"Unsupported UE5 task type: {task_type}"}

    def _run_command(self, args: list, cwd: str) -> dict:
        try:
            proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
            return {"code": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
        except subprocess.TimeoutExpired:
            return {"code": -1, "stdout": "", "stderr": "Command timed out after 120s"}
        except Exception as e:
            return {"code": -1, "stdout": "", "stderr": str(e)}


# ─── Unity Bridge ─────────────────────────────────────────────────────────────

class UnityBridge:

    def __init__(self, data_dir: str = "data/unity"):
        self._ws = WorkspaceStore(f"{data_dir}/workspace.json")

    def _find_project_file(self, project_path: str) -> Optional[str]:
        if not project_path:
            return None
        p = Path(project_path)
        # Unity projects are folders containing Assets/ and ProjectSettings/
        if p.exists() and (p / "Assets").exists() and (p / "ProjectSettings").exists():
            return str(p)
        return None

    def get_status(self) -> dict:
        ws = self._ws.get()
        project_dir = self._find_project_file(ws.get("projectPath", ""))
        editor_exists = Path(ws.get("editorPath", "")).exists() if ws.get("editorPath") else False

        return {
            "workspace": ws,
            "connected": bool(project_dir),
            "editorFound": editor_exists,
            "projectFound": bool(project_dir),
            "projectDir": project_dir,
            "canScan": bool(project_dir),
            "canBuild": editor_exists and bool(project_dir),
        }

    def connect_workspace(self, editor_path: str, project_path: str) -> dict:
        self._ws.save(editor_path, project_path)
        return self.get_status()

    def scan_project(self) -> dict:
        status = self.get_status()
        if not status["projectFound"]:
            return {"ok": False, "error": "No Unity project found. Connect a valid Unity project folder first."}

        project_dir = Path(status["projectDir"])
        scenes = list((project_dir / "Assets").rglob("*.unity")) if (project_dir / "Assets").exists() else []
        packages = []
        pkg_file = project_dir / "Packages" / "manifest.json"
        if pkg_file.exists():
            try:
                pkg_data = json.loads(pkg_file.read_text())
                packages = list(pkg_data.get("dependencies", {}).keys())
            except Exception:
                pass

        self._ws.stamp_scan()
        return {
            "ok": True,
            "scannedAt": int(time.time() * 1000),
            "projectName": project_dir.name,
            "projectDir": str(project_dir),
            "sceneCount": len(scenes),
            "scenes": [str(s.relative_to(project_dir)).replace("\\", "/") for s in scenes[:50]],
            "packages": packages[:30],
            "hasAssets": (project_dir / "Assets").exists(),
            "hasPackages": (project_dir / "Packages").exists(),
        }

    def create_scene_scaffold(self, scene_name: str) -> dict:
        status = self.get_status()
        if not status["projectFound"]:
            return {"ok": False, "error": "Project is not connected."}

        safe_name = "".join(c for c in scene_name if c.isalnum() or c in "_-").strip()
        if not safe_name:
            return {"ok": False, "error": "sceneName is required."}

        project_dir = Path(status["projectDir"])
        base = project_dir / "Assets" / "LucyGenerated" / safe_name
        base.mkdir(parents=True, exist_ok=True)
        scenes_dir  = base / "Scenes"
        scripts_dir = base / "Scripts"
        scenes_dir.mkdir(exist_ok=True)
        scripts_dir.mkdir(exist_ok=True)

        readme = base / "README_LUCY.txt"
        if not readme.exists():
            readme.write_text(
                f"Lucy-generated Unity scaffold: {safe_name}\n"
                "This scaffold was created through the Emma-approved Unity lane.\n"
                "Add .unity scene files under Scenes and C# scripts under Scripts.\n"
            )

        return {
            "ok": True,
            "createdAt": int(time.time() * 1000),
            "sceneName": safe_name,
            "createdPaths": [str(scenes_dir), str(scripts_dir), str(readme)],
        }

    def execute_task(self, task_type: str) -> dict:
        status = self.get_status()
        if not status["projectFound"]:
            return {"ok": False, "error": "Project is not connected."}

        editor_path = status["workspace"].get("editorPath", "")
        project_dir = status["projectDir"]

        if task_type == "refresh-dry-run":
            cmd = f"{editor_path or 'Unity.exe'} -batchmode -projectPath {project_dir} -executeMethod AssetDatabase.Refresh -quit"
            return {"ok": True, "executed": False, "taskType": task_type, "preview": cmd}

        if task_type == "build-windows-dry-run":
            cmd = f"{editor_path or 'Unity.exe'} -batchmode -projectPath {project_dir} -buildWindows64Player Build/output.exe -quit"
            return {"ok": True, "executed": False, "taskType": task_type, "preview": cmd}

        if not status["canBuild"]:
            return {"ok": False, "error": "Editor path or project dir is missing."}

        if task_type == "build-windows":
            args = [editor_path, "-batchmode", "-projectPath", project_dir,
                    "-buildWindows64Player", str(Path(project_dir) / "Build" / "output.exe"), "-quit"]
            proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
            return {"ok": proc.returncode == 0, "executed": True, "taskType": task_type,
                    "code": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}

        return {"ok": False, "error": f"Unsupported Unity task type: {task_type}"}


# Singletons
ue5_bridge   = UE5Bridge(data_dir="lucy-os/data/ue5")
unity_bridge = UnityBridge(data_dir="lucy-os/data/unity")