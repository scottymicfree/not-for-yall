"""
LTE Telemetry Engine — Lucy OS v5
Collects, aggregates, and streams telemetry signals from all subsystems.

Subsystems tracked:
  - emma_mesh  : pipeline latency, block rate, confidence, consensus distribution
  - lucy_prime : LTE rolling avg, synthesis time, dispatch state
  - swarm      : agent load, task queue depth, timeout rate
  - memory     : write rate, hit/miss ratio, vault chain integrity
  - fivem      : bridge latency, player count, error rate
  - earth      : query rate, freshness score, data source health
  - bioyth0n   : execution count, gate pass/fail ratio
  - safety     : override usage, block events, anomaly flags
"""

from __future__ import annotations
import time
import asyncio
import threading
import statistics
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Deque, Callable
from collections import deque, defaultdict
import json

# ── Signal ─────────────────────────────────────────────────────────────────────

@dataclass
class TelemetrySignal:
    subsystem:  str
    metric:     str
    value:      float
    unit:       str = ""
    tags:       Dict[str, str] = field(default_factory=dict)
    timestamp:  float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ── Aggregation Window ─────────────────────────────────────────────────────────

class MetricWindow:
    """Rolling window for a single metric — stores last N values."""

    def __init__(self, maxlen: int = 200) -> None:
        self._data: Deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, v: float) -> None:
        with self._lock:
            self._data.append(v)

    def snapshot(self) -> Dict[str, float]:
        with self._lock:
            data = list(self._data)
        if not data:
            return {"count": 0, "last": 0.0, "min": 0.0,
                    "max": 0.0, "avg": 0.0, "p50": 0.0, "p95": 0.0}
        s = sorted(data)
        n = len(s)
        p50 = s[int(n * 0.50)]
        p95 = s[min(n - 1, int(n * 0.95))]
        return {
            "count": n,
            "last":  round(data[-1], 4),
            "min":   round(s[0],     4),
            "max":   round(s[-1],    4),
            "avg":   round(statistics.mean(data), 4),
            "p50":   round(p50,      4),
            "p95":   round(p95,      4),
        }

    def last(self) -> Optional[float]:
        with self._lock:
            return self._data[-1] if self._data else None


# ── Subsystem Collector ────────────────────────────────────────────────────────

class SubsystemCollector:
    """Holds all MetricWindows for a single subsystem."""

    def __init__(self, name: str) -> None:
        self.name     = name
        self._metrics: Dict[str, MetricWindow] = {}
        self._lock    = threading.Lock()

    def push(self, metric: str, value: float) -> None:
        with self._lock:
            if metric not in self._metrics:
                self._metrics[metric] = MetricWindow()
        self._metrics[metric].push(value)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            keys = list(self._metrics.keys())
        return {k: self._metrics[k].snapshot() for k in keys}

    def last_value(self, metric: str) -> Optional[float]:
        with self._lock:
            w = self._metrics.get(metric)
        return w.last() if w else None


# ── LTE Telemetry Engine ───────────────────────────────────────────────────────

class LTETelemetry:
    """
    Central telemetry engine for Lucy OS v5.

    Usage:
        telemetry.push("emma_mesh", "latency_ms", 42.5)
        telemetry.push("swarm", "agent_load", 0.72)
        snap = telemetry.snapshot()
    """

    SUBSYSTEMS = [
        "emma_mesh", "lucy_prime", "swarm", "memory",
        "fivem", "earth", "bioyth0n", "safety", "lte", "system"
    ]

    _RAW_HISTORY_MAX = 2000   # raw signal ring buffer

    def __init__(self) -> None:
        # Per-subsystem collectors
        self._collectors: Dict[str, SubsystemCollector] = {
            s: SubsystemCollector(s) for s in self.SUBSYSTEMS
        }
        # Raw signal history
        self._raw: Deque[TelemetrySignal] = deque(maxlen=self._RAW_HISTORY_MAX)
        self._lock = threading.Lock()

        # Event listeners: subsystem -> list[callback(signal)]
        self._listeners: Dict[str, List[Callable]] = defaultdict(list)

        # Startup time
        self._boot_time = time.time()

        # Health flags
        self._anomaly_flags: Dict[str, str] = {}

        # Internal counter
        self._push_count = 0

    # ── Push / Record ─────────────────────────────────────────────────────────

    def push(self, subsystem: str, metric: str, value: float,
             unit: str = "", tags: Optional[Dict[str, str]] = None) -> None:
        """Push a telemetry reading into the engine."""
        # Auto-create collector for unknown subsystems
        if subsystem not in self._collectors:
            with self._lock:
                if subsystem not in self._collectors:
                    self._collectors[subsystem] = SubsystemCollector(subsystem)

        self._collectors[subsystem].push(metric, value)

        sig = TelemetrySignal(
            subsystem=subsystem,
            metric=metric,
            value=value,
            unit=unit,
            tags=tags or {},
            timestamp=time.time(),
        )
        with self._lock:
            self._raw.append(sig)
            self._push_count += 1

        # Fire listeners
        for cb in self._listeners.get(subsystem, []):
            try:
                cb(sig)
            except Exception:
                pass
        for cb in self._listeners.get("*", []):
            try:
                cb(sig)
            except Exception:
                pass

        # Auto anomaly detection
        self._check_anomaly(sig)

    def push_signal(self, sig: TelemetrySignal) -> None:
        """Push a pre-built TelemetrySignal."""
        self.push(sig.subsystem, sig.metric, sig.value, sig.unit, sig.tags)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """Full telemetry snapshot across all subsystems."""
        snap: Dict[str, Any] = {}
        for name, collector in self._collectors.items():
            s = collector.snapshot()
            if s:
                snap[name] = s
        return {
            "subsystems": snap,
            "uptime_seconds": round(time.time() - self._boot_time, 2),
            "total_signals":  self._push_count,
            "anomaly_flags":  dict(self._anomaly_flags),
            "timestamp":      time.time(),
        }

    def subsystem_snapshot(self, name: str) -> Dict[str, Any]:
        """Snapshot for a single subsystem."""
        col = self._collectors.get(name)
        if not col:
            return {"error": f"unknown subsystem: {name}"}
        return col.snapshot()

    def last(self, subsystem: str, metric: str) -> Optional[float]:
        col = self._collectors.get(subsystem)
        return col.last_value(metric) if col else None

    # ── Raw Signal Stream ─────────────────────────────────────────────────────

    def raw_signals(self, subsystem: Optional[str] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._raw)
        if subsystem:
            items = [s for s in items if s.subsystem == subsystem]
        return [s.to_dict() for s in items[-limit:]]

    # ── Listeners ─────────────────────────────────────────────────────────────

    def subscribe(self, subsystem: str, callback: Callable) -> None:
        """Subscribe to push events for a subsystem (use '*' for all)."""
        self._listeners[subsystem].append(callback)

    def unsubscribe(self, subsystem: str, callback: Callable) -> None:
        try:
            self._listeners[subsystem].remove(callback)
        except ValueError:
            pass

    # ── Anomaly Detection ─────────────────────────────────────────────────────

    _ANOMALY_RULES: Dict[str, Dict[str, float]] = {
        "emma_mesh": {
            "latency_ms":   3000.0,  # p95 > 3s
            "block_rate":   0.25,    # > 25%
            "avg_confidence": None,  # min check — handled separately
        },
        "fivem": {
            "bridge_latency_ms": 5000.0,
            "error_rate":        0.20,
        },
        "swarm": {
            "agent_load":   0.95,
            "timeout_rate": 0.15,
        },
        "safety": {
            "block_rate":   0.30,
            "anomaly_count": 5.0,
        },
    }

    def _check_anomaly(self, sig: TelemetrySignal) -> None:
        rules = self._ANOMALY_RULES.get(sig.subsystem, {})
        threshold = rules.get(sig.metric)
        if threshold is None:
            return

        # Special case: metrics that should be > threshold are anomalous when above it
        if sig.value > threshold:
            flag = f"{sig.subsystem}.{sig.metric}>{threshold:.1f}"
            self._anomaly_flags[f"{sig.subsystem}:{sig.metric}"] = flag
        else:
            self._anomaly_flags.pop(f"{sig.subsystem}:{sig.metric}", None)

    def clear_anomaly(self, subsystem: str, metric: str) -> None:
        self._anomaly_flags.pop(f"{subsystem}:{metric}", None)

    def anomalies(self) -> Dict[str, str]:
        return dict(self._anomaly_flags)

    # ── Dashboard Summary ─────────────────────────────────────────────────────

    def dashboard_summary(self) -> Dict[str, Any]:
        """Compact summary for live dashboard tiles."""
        def _last(sub: str, met: str, default: float = 0.0) -> float:
            v = self.last(sub, met)
            return v if v is not None else default

        return {
            "emma": {
                "latency_ms":   _last("emma_mesh", "latency_ms"),
                "confidence":   _last("emma_mesh", "avg_confidence", 0.70),
                "block_rate":   _last("emma_mesh", "block_rate"),
                "consensus":    _last("emma_mesh", "strong_consensus_rate", 0.80),
            },
            "lucy_prime": {
                "lte_avg":      _last("lucy_prime", "lte_avg", 70.0),
                "synth_ms":     _last("lucy_prime", "synthesis_ms"),
                "state":        _last("lucy_prime", "state_code", 0),
            },
            "swarm": {
                "agent_load":   _last("swarm", "agent_load"),
                "queue_depth":  _last("swarm", "queue_depth"),
                "timeout_rate": _last("swarm", "timeout_rate"),
            },
            "fivem": {
                "latency_ms":   _last("fivem", "bridge_latency_ms"),
                "player_count": _last("fivem", "player_count"),
                "error_rate":   _last("fivem", "error_rate"),
            },
            "earth": {
                "query_rate":    _last("earth", "query_rate"),
                "freshness":     _last("earth", "freshness_score", 0.90),
            },
            "bioyth0n": {
                "exec_count":   _last("bioyth0n", "exec_count"),
                "gate_pass_rate": _last("bioyth0n", "gate_pass_rate", 1.0),
            },
            "safety": {
                "block_events": _last("safety", "block_events"),
                "override_active": _last("safety", "override_active"),
            },
            "system": {
                "uptime":   round(time.time() - self._boot_time, 2),
                "anomalies": len(self._anomaly_flags),
                "total_signals": self._push_count,
            },
        }

    # ── Async Stream Generator ─────────────────────────────────────────────────

    async def stream_dashboard(self, interval: float = 1.0):
        """Async generator yielding dashboard summaries at `interval` seconds."""
        while True:
            yield self.dashboard_summary()
            await asyncio.sleep(interval)

    # ── Export ────────────────────────────────────────────────────────────────

    def export_json(self, subsystem: Optional[str] = None) -> str:
        if subsystem:
            data = {subsystem: self.subsystem_snapshot(subsystem)}
        else:
            data = self.snapshot()
        return json.dumps(data, indent=2)

    # ── Populate from Emma result ─────────────────────────────────────────────

    def ingest_emma_result(self, result: Dict[str, Any]) -> None:
        """
        Ingest an EmmaPipelineResult dict and push relevant metrics automatically.
        Called automatically by the pipeline after each Emma run.
        """
        sub = "emma_mesh"
        if "latency_ms" in result:
            self.push(sub, "latency_ms", float(result["latency_ms"]), "ms")
        if "confidence" in result:
            self.push(sub, "avg_confidence", float(result["confidence"]))
        if "blocked" in result:
            self.push(sub, "block_rate", 1.0 if result["blocked"] else 0.0)
        if "consensus" in result:
            is_strong = 1.0 if result["consensus"] == "strong" else 0.0
            self.push(sub, "strong_consensus_rate", is_strong)
        if "lte_score" in result:
            self.push("lte", "lte_score", float(result["lte_score"]))

    def ingest_lucy_prime(self, data: Dict[str, Any]) -> None:
        sub = "lucy_prime"
        if "lte_avg" in data:
            self.push(sub, "lte_avg", float(data["lte_avg"]))
        if "synthesis_ms" in data:
            self.push(sub, "synthesis_ms", float(data["synthesis_ms"]), "ms")
        state_map = {"nominal": 0, "reflective": 1, "repair": 2, "elevated": 3, "standby": 4}
        if "state" in data:
            self.push(sub, "state_code", float(state_map.get(data["state"], 0)))

    def ingest_swarm(self, data: Dict[str, Any]) -> None:
        sub = "swarm"
        for key in ("agent_load", "queue_depth", "timeout_rate", "active_agents"):
            if key in data:
                self.push(sub, key, float(data[key]))

    def ingest_fivem(self, data: Dict[str, Any]) -> None:
        sub = "fivem"
        for key in ("bridge_latency_ms", "player_count", "error_rate"):
            if key in data:
                self.push(sub, key, float(data[key]))

    def ingest_bioyth0n(self, data: Dict[str, Any]) -> None:
        sub = "bioyth0n"
        for key in ("exec_count", "gate_pass_rate"):
            if key in data:
                self.push(sub, key, float(data[key]))

    def ingest_safety(self, data: Dict[str, Any]) -> None:
        sub = "safety"
        for key in ("block_events", "override_active", "anomaly_count"):
            if key in data:
                self.push(sub, key, float(data[key]))


# ── Singleton ──────────────────────────────────────────────────────────────────
telemetry = LTETelemetry()