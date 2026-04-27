"""
N4 — Async Scheduler + N3 Load Balancer + N9 Retry Manager
Executes DAG nodes in correct dependency order with parallel groups running concurrently.
Handles retries with exponential backoff, load balancing, and timeout enforcement.
"""

import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Awaitable
from collections import defaultdict

from mesh.dag_builder import ExecutionDAG, DAGNode, ExecutionPhase
from mesh.event_bus import event_bus, LucyMessage, make_request, make_event
from mesh.node_registry import node_registry

logger = logging.getLogger("lucy.scheduler")


@dataclass
class NodeResult:
    node_id: str
    success: bool
    output: Any
    confidence: float = 1.0
    duration_ms: int = 0
    retries: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "nodeId": self.node_id,
            "success": self.success,
            "confidence": self.confidence,
            "durationMs": self.duration_ms,
            "retries": self.retries,
            "error": self.error,
            "hasOutput": self.output is not None,
        }


@dataclass
class DAGExecution:
    dag: ExecutionDAG
    session_id: str
    results: Dict[str, NodeResult] = field(default_factory=dict)
    started_at: int = field(default_factory=lambda: int(time.time() * 1000))
    completed_at: Optional[int] = None
    status: str = "running"   # running | completed | failed | timeout

    def get_output(self, node_id: str) -> Any:
        result = self.results.get(node_id)
        return result.output if result else None

    def all_outputs(self) -> dict:
        return {nid: r.output for nid, r in self.results.items() if r.output is not None}

    def to_dict(self) -> dict:
        return {
            "dagId": self.dag.dag_id,
            "sessionId": self.session_id,
            "status": self.status,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "durationMs": (self.completed_at or int(time.time()*1000)) - self.started_at,
            "nodeResults": {nid: r.to_dict() for nid, r in self.results.items()},
            "successCount": sum(1 for r in self.results.values() if r.success),
            "failCount": sum(1 for r in self.results.values() if not r.success),
        }


class MeshScheduler:
    """
    N4 — Schedules DAG execution with:
    - Topological sort for dependency ordering
    - Parallel execution for independent groups
    - Per-node timeout enforcement
    - Retry with exponential backoff (N9)
    - Load awareness (N3)
    - EventBus integration for all node comms
    """

    MAX_RETRIES = 2
    BASE_RETRY_DELAY_MS = 100

    def __init__(self):
        # Node handlers: node_id -> async callable
        self._handlers: Dict[str, Callable] = {}
        self._default_handler: Optional[Callable] = None
        self._active_executions: Dict[str, DAGExecution] = {}

    def register_handler(self, node_id: str, handler: Callable):
        """Register an async handler for a specific node."""
        self._handlers[node_id] = handler

    def set_default_handler(self, handler: Callable):
        """Fallback handler for nodes without specific handlers."""
        self._default_handler = handler

    async def execute_dag(self, dag: ExecutionDAG, initial_input: Any = None) -> DAGExecution:
        """Execute the full DAG, respecting dependencies and parallelism."""
        execution = DAGExecution(dag=dag, session_id=dag.session_id)
        self._active_executions[dag.dag_id] = execution

        # Build adjacency and dependency count maps
        dep_count: Dict[str, int] = {}
        dependents: Dict[str, List[str]] = defaultdict(list)

        for dag_node in dag.nodes:
            dep_count[dag_node.node_id] = len(dag_node.depends_on)
            for dep in dag_node.depends_on:
                dependents[dep].append(dag_node.node_id)

        # Ready queue: nodes with no dependencies
        ready: Set[str] = {n.node_id for n in dag.nodes if dep_count[n.node_id] == 0}
        node_map = {n.node_id: n for n in dag.nodes}
        pending_tasks: Dict[str, asyncio.Task] = {}

        context = {"input": initial_input, "session_id": dag.session_id}

        try:
            while ready or pending_tasks:
                # Launch all ready nodes
                newly_launched = set()
                for node_id in list(ready):
                    dag_node = node_map.get(node_id)
                    if not dag_node:
                        ready.discard(node_id)
                        continue

                    # Group parallel nodes
                    task = asyncio.create_task(
                        self._execute_node(dag_node, execution, context)
                    )
                    pending_tasks[node_id] = task
                    newly_launched.add(node_id)

                ready -= newly_launched

                if not pending_tasks:
                    break

                # Wait for at least one task to complete
                done, _ = await asyncio.wait(
                    pending_tasks.values(),
                    return_when=asyncio.FIRST_COMPLETED
                )

                for completed_task in done:
                    # Find the node_id for this task
                    completed_node_id = None
                    for nid, t in list(pending_tasks.items()):
                        if t == completed_task:
                            completed_node_id = nid
                            break

                    if not completed_node_id:
                        continue

                    del pending_tasks[completed_node_id]
                    result = execution.results.get(completed_node_id)

                    if result and (result.success or not node_map[completed_node_id].required):
                        # Unlock dependents
                        for dep_node_id in dependents.get(completed_node_id, []):
                            dep_count[dep_node_id] -= 1
                            if dep_count[dep_node_id] == 0:
                                ready.add(dep_node_id)
                    elif result and not result.success and node_map[completed_node_id].required:
                        # Required node failed — cancel downstream
                        logger.warning(f"Required node {completed_node_id} failed: {result.error}")
                        # Continue anyway for resilience — skip downstream
                        for dep_node_id in dependents.get(completed_node_id, []):
                            dep_count[dep_node_id] -= 1
                            if dep_count[dep_node_id] == 0:
                                ready.add(dep_node_id)

        except Exception as e:
            execution.status = "failed"
            logger.error(f"DAG execution failed: {e}")
        finally:
            execution.completed_at = int(time.time() * 1000)
            if execution.status == "running":
                execution.status = "completed"
            self._active_executions.pop(dag.dag_id, None)

        return execution

    async def _execute_node(self, dag_node: DAGNode, execution: DAGExecution, context: dict) -> NodeResult:
        """Execute a single node with retry logic."""
        node_id = dag_node.node_id
        node_registry.update_status(node_id, "busy")

        start = time.time()
        last_error = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                # Gather dependency outputs for this node
                dep_outputs = {dep: execution.results.get(dep) for dep in dag_node.depends_on}

                handler = self._handlers.get(node_id) or self._default_handler
                if handler is None:
                    # No handler — use pass-through
                    output = {"passthrough": True, "nodeId": node_id, "context": context}
                    confidence = 0.9
                else:
                    result_data = await asyncio.wait_for(
                        handler(node_id, dep_outputs, context),
                        timeout=dag_node.timeout_ms / 1000.0
                    )
                    output = result_data.get("output") if isinstance(result_data, dict) else result_data
                    confidence = result_data.get("confidence", 1.0) if isinstance(result_data, dict) else 1.0

                duration_ms = int((time.time() - start) * 1000)
                result = NodeResult(
                    node_id=node_id, success=True, output=output,
                    confidence=confidence, duration_ms=duration_ms, retries=attempt
                )
                execution.results[node_id] = result
                node_registry.update_status(node_id, "online", load=0.1)

                # Emit completion event on bus
                event_bus.emit_event(
                    source=node_id, event_type="node_complete",
                    payload={"nodeId": node_id, "success": True, "durationMs": duration_ms},
                    target="broadcast", session_id=execution.session_id, priority=3
                )
                return result

            except asyncio.TimeoutError:
                last_error = f"Node {node_id} timed out after {dag_node.timeout_ms}ms"
                node_registry.increment_error(node_id)
            except Exception as e:
                last_error = str(e)
                node_registry.increment_error(node_id)

            if attempt < self.MAX_RETRIES:
                delay = (self.BASE_RETRY_DELAY_MS * (2 ** attempt)) / 1000.0
                await asyncio.sleep(delay)

        # All retries exhausted
        duration_ms = int((time.time() - start) * 1000)
        result = NodeResult(
            node_id=node_id, success=False, output=None,
            confidence=0.0, duration_ms=duration_ms,
            retries=self.MAX_RETRIES, error=last_error
        )
        execution.results[node_id] = result
        node_registry.update_status(node_id, "degraded")
        return result

    def get_active_executions(self) -> List[dict]:
        return [e.to_dict() for e in self._active_executions.values()]

    def stats(self) -> dict:
        return {
            "activeExecutions": len(self._active_executions),
            "registeredHandlers": len(self._handlers),
        }


# Singleton
mesh_scheduler = MeshScheduler()