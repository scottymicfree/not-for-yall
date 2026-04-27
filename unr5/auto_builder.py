"""
AutoBuilder — Natural Language → Plan → Emma-Approved Execution
Python port of builder/autoBuilder.js

Lucy takes a plain text prompt like:
  "build a police station map in UE5"
  "create evidence room scene in Unity"
  "scaffold a new mission module"

AutoBuilder infers the engine, creates a step plan, runs each step
through Emma approval, and records results in DeltaVault.
"""

import re
import time
import random
import string
from typing import Optional

from unr5.emma import emma
from unr5.delta_vault import delta_vault
from unr5.ue5_bridge import ue5_bridge, unity_bridge


def _build_run_id() -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"br_{int(time.time() * 1000)}_{suffix}"


def _to_words(prompt: str) -> list:
    clean = re.sub(r"[^a-zA-Z0-9 ]", " ", prompt)
    return [w for w in clean.split() if w]


STOP_WORDS = {
    "build", "make", "create", "for", "with", "and", "the", "a", "an",
    "map", "scene", "level", "module", "unity", "unreal", "ue5", "in",
    "of", "to", "from", "new", "generate", "please", "can", "you"
}


def _to_pascal_case(words: list, fallback: str = "LucyGenerated") -> str:
    usable = [w for w in words if w.lower() not in STOP_WORDS][:3]
    if not usable:
        return fallback
    return "".join(w.capitalize() for w in usable)


def _infer_engine(prompt: str, ue5_status: dict, unity_status: dict) -> str:
    p = prompt.lower()
    ue5_keywords  = r"(unreal|ue5|unr5|umap|blueprint|landscape|nanite|evidence room|booking desk|police station|prison|courthouse)"
    unity_keywords = r"(unity|scene\b|prefab|gameobject|scriptable|c#|monobehaviour)"

    if re.search(ue5_keywords, p):
        return "ue5"
    if re.search(unity_keywords, p):
        return "unity"

    # Auto-detect from connection state
    ue5_connected   = ue5_status.get("connected", False)
    unity_connected = unity_status.get("connected", False)

    if ue5_connected and not unity_connected:
        return "ue5"
    if unity_connected and not ue5_connected:
        return "unity"
    if ue5_connected:
        return "ue5"
    if unity_connected:
        return "unity"
    return "unknown"


def _create_plan(prompt: str, ue5_status: dict, unity_status: dict) -> dict:
    words   = _to_words(prompt)
    engine  = _infer_engine(prompt, ue5_status, unity_status)
    p_lower = prompt.lower()

    wants_build        = bool(re.search(r"\b(build|compile|package|cook|ship|run build)\b", p_lower))
    wants_scaffold     = bool(re.search(r"\b(build|create|make|scaffold|new|generate)\b", p_lower))
    wants_preview_only = bool(re.search(r"\b(preview|dry.?run|plan only)\b", p_lower))

    if engine == "ue5":
        module_name = f"{_to_pascal_case(words, 'LucyGenerated')}Module"
        steps = [{"id": "ue5-scan", "label": "Scan connected UE5 project", "action": "scan"}]
        if wants_scaffold:
            steps.append({
                "id": "ue5-scaffold",
                "label": f"Create scaffold module {module_name}",
                "action": "scaffold",
                "moduleName": module_name,
            })
        steps.append({
            "id": "ue5-preview",
            "label": "Preview cook/build command" if wants_build else "Preview resave command",
            "action": "preview-task",
            "taskType": "cook-dry-run" if wants_build else "resave-dry-run",
        })
        if wants_build and not wants_preview_only:
            steps.append({
                "id": "ue5-execute",
                "label": "Execute UE5 build task",
                "action": "execute-task",
                "taskType": "cook-content",
            })
        return {
            "engine": engine, "prompt": prompt,
            "moduleName": module_name, "sceneName": None,
            "previewOnly": wants_preview_only, "steps": steps,
        }

    if engine == "unity":
        scene_name = f"{_to_pascal_case(words, 'LucyGenerated')}Scene"
        steps = [{"id": "unity-scan", "label": "Scan connected Unity project", "action": "scan"}]
        if wants_scaffold:
            steps.append({
                "id": "unity-scaffold",
                "label": f"Create scene scaffold {scene_name}",
                "action": "scaffold",
                "sceneName": scene_name,
            })
        steps.append({
            "id": "unity-preview",
            "label": "Preview build command" if wants_build else "Preview refresh command",
            "action": "preview-task",
            "taskType": "build-windows-dry-run" if wants_build else "refresh-dry-run",
        })
        if wants_build and not wants_preview_only:
            steps.append({
                "id": "unity-execute",
                "label": "Execute Unity build task",
                "action": "execute-task",
                "taskType": "build-windows",
            })
        return {
            "engine": engine, "prompt": prompt,
            "moduleName": None, "sceneName": scene_name,
            "previewOnly": wants_preview_only, "steps": steps,
        }

    return {"engine": engine, "prompt": prompt, "previewOnly": True, "steps": []}


def _summarize_result(result: dict) -> dict:
    summary = {"executed": bool(result.get("executed")), "taskType": result.get("taskType")}
    for k in ("moduleName", "sceneName", "createdPaths", "preview"):
        if k in result:
            summary[k] = result[k]
    if "code" in result:
        summary["code"] = result["code"]
    return summary


def _run_approved_action(action_type: str, payload: dict, execute_fn) -> dict:
    full_payload = {**payload, "operatorVisible": True, "requestedBy": "local-operator"}
    approval = emma.review(action_type, full_payload)

    if approval.decision == "rejected":
        return {"ok": False, "blocked": True, "approval": approval.to_dict(), "error": approval.reason}

    result = execute_fn()
    if not result.get("ok"):
        return {"ok": False, "blocked": False, "approval": approval.to_dict(),
                "error": result.get("error", "Tool action failed."), "result": result}

    ledger_entry = delta_vault.append_approved(
        action_type=action_type,
        payload={**payload, "resultSummary": _summarize_result(result)},
        reason=approval.reason,
    )
    return {"ok": True, "blocked": False, "approval": approval.to_dict(),
            "result": result, "ledgerEntry": ledger_entry.to_dict()}


def run_builder(prompt: str) -> dict:
    """Main entry: translate prompt → plan → execute with Emma approval."""
    ue5_status   = ue5_bridge.get_status()
    unity_status = unity_bridge.get_status()
    plan         = _create_plan(prompt, ue5_status, unity_status)
    run_id       = _build_run_id()
    started_at   = int(time.time() * 1000)
    step_results = []
    ok           = True
    blocked_reason = None

    if plan["engine"] == "unknown":
        run = {
            "id": run_id, "startedAt": started_at, "completedAt": int(time.time() * 1000),
            "ok": False, "engine": "unknown", "prompt": prompt,
            "blockedReason": "No connected UE5 or Unity workspace matched this prompt. Connect a workspace first or mention Unreal/Unity explicitly.",
            "plan": plan, "stepResults": [],
        }
        return run

    for step in plan["steps"]:
        if not ok:
            break

        engine = plan["engine"]

        if engine == "ue5":
            if step["action"] == "scan":
                result = ue5_bridge.scan_project()
                entry  = {"stepId": step["id"], "label": step["label"], "ok": result["ok"], "result": result}
                if not result["ok"]:
                    ok = False
                    blocked_reason = result.get("error", "UE5 scan failed.")
                step_results.append(entry)

            elif step["action"] == "scaffold":
                executed = _run_approved_action(
                    "ue5:scaffold",
                    {"moduleName": step["moduleName"], "taskType": "scaffold-map-module"},
                    lambda mn=step["moduleName"]: ue5_bridge.create_map_scaffold(mn)
                )
                if not executed["ok"]:
                    ok = False
                    blocked_reason = executed["error"]
                step_results.append({"stepId": step["id"], "label": step["label"], **executed})

            else:  # preview-task or execute-task
                task_type = step["taskType"]
                executed  = _run_approved_action(
                    "ue5:execute",
                    {"taskType": task_type},
                    lambda tt=task_type: ue5_bridge.execute_task(tt)
                )
                if not executed["ok"]:
                    ok = False
                    blocked_reason = executed.get("error")
                step_results.append({"stepId": step["id"], "label": step["label"], **executed})

        elif engine == "unity":
            if step["action"] == "scan":
                result = unity_bridge.scan_project()
                entry  = {"stepId": step["id"], "label": step["label"], "ok": result["ok"], "result": result}
                if not result["ok"]:
                    ok = False
                    blocked_reason = result.get("error", "Unity scan failed.")
                step_results.append(entry)

            elif step["action"] == "scaffold":
                executed = _run_approved_action(
                    "unity:scaffold",
                    {"sceneName": step["sceneName"], "taskType": "scaffold-scene-module"},
                    lambda sn=step["sceneName"]: unity_bridge.create_scene_scaffold(sn)
                )
                if not executed["ok"]:
                    ok = False
                    blocked_reason = executed["error"]
                step_results.append({"stepId": step["id"], "label": step["label"], **executed})

            else:
                task_type = step["taskType"]
                executed  = _run_approved_action(
                    "unity:execute",
                    {"taskType": task_type},
                    lambda tt=task_type: unity_bridge.execute_task(tt)
                )
                if not executed["ok"]:
                    ok = False
                    blocked_reason = executed.get("error")
                step_results.append({"stepId": step["id"], "label": step["label"], **executed})

    return {
        "id": run_id,
        "startedAt": started_at,
        "completedAt": int(time.time() * 1000),
        "ok": ok,
        "engine": plan["engine"],
        "prompt": prompt,
        "blockedReason": blocked_reason,
        "plan": plan,
        "stepResults": step_results,
    }


def get_builder_status() -> dict:
    return {
        "timestamp": int(time.time() * 1000),
        "connectedEngines": {
            "ue5":   ue5_bridge.get_status()["connected"],
            "unity": unity_bridge.get_status()["connected"],
        },
        "ue5Status":   ue5_bridge.get_status(),
        "unityStatus": unity_bridge.get_status(),
    }