"""
AME Plugin Manager — Lucy OS v5
Dynamic plugin system for extending Lucy's capabilities at runtime.

Plugin types:
  - perception  : Input preprocessors (text cleaning, intent detection, translation)
  - swarm       : Custom swarm agents injected into the L1-L48 pool
  - memory      : Memory adapters (vector DBs, external stores)
  - output      : Output formatters / post-processors
  - bridge      : External system connectors (APIs, databases, IoT)
  - tool        : Callable tools exposed to Lucy's reasoning
  - monitor     : Background monitors publishing to EventBus

Plugin lifecycle:
  REGISTERED → LOADING → ACTIVE → (PAUSED | ERROR) → UNLOADED
"""

from __future__ import annotations
import asyncio
import importlib
import importlib.util
import time
import uuid
import logging
import hashlib
import inspect
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Set, Type
from enum import Enum
from pathlib import Path

from ame.event_bus import AMEEventBus, BusEvent, Priority, event_bus

log = logging.getLogger("ame.plugins")

# ── Plugin State ───────────────────────────────────────────────────────────────

class PluginState(str, Enum):
    REGISTERED = "registered"
    LOADING    = "loading"
    ACTIVE     = "active"
    PAUSED     = "paused"
    ERROR      = "error"
    UNLOADED   = "unloaded"

# ── Plugin Types ───────────────────────────────────────────────────────────────

class PluginType(str, Enum):
    PERCEPTION = "perception"
    SWARM      = "swarm"
    MEMORY     = "memory"
    OUTPUT     = "output"
    BRIDGE     = "bridge"
    TOOL       = "tool"
    MONITOR    = "monitor"

# ── Plugin Manifest ────────────────────────────────────────────────────────────

@dataclass
class PluginManifest:
    """Declarative description of a plugin — filled in by the plugin author."""
    name:        str
    version:     str
    plugin_type: PluginType
    description: str = ""
    author:      str = "unknown"
    requires:    List[str] = field(default_factory=list)   # other plugin names
    topics_sub:  List[str] = field(default_factory=list)   # bus topics to subscribe
    topics_pub:  List[str] = field(default_factory=list)   # bus topics this publishes to
    config:      Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["plugin_type"] = self.plugin_type.value
        return d

# ── Base Plugin ────────────────────────────────────────────────────────────────

class LucyPlugin:
    """
    Base class for all Lucy OS plugins.
    Subclass this and implement `on_load`, `on_event`, and `on_unload`.
    """

    # Subclasses must set this
    MANIFEST: PluginManifest = None

    def __init__(self, bus: AMEEventBus = None) -> None:
        self._bus     = bus or event_bus
        self._sub_ids: List[str] = []
        self._active  = False
        self._load_ts = 0.0
        self._event_count = 0
        self._error_count = 0

    # ── Lifecycle (override in subclass) ──────────────────────────────────────

    async def on_load(self) -> None:
        """Called once when the plugin is activated. Perform setup here."""
        pass

    async def on_event(self, event: BusEvent) -> None:
        """Called for every subscribed bus event."""
        pass

    async def on_unload(self) -> None:
        """Called once when the plugin is deactivated. Clean up here."""
        pass

    async def health_check(self) -> Dict[str, Any]:
        """Return plugin health status. Override for custom checks."""
        return {"status": "ok", "active": self._active}

    # ── Event Bus ─────────────────────────────────────────────────────────────

    def _subscribe(self, topic: str) -> None:
        async def _dispatch(event: BusEvent) -> None:
            self._event_count += 1
            try:
                await self.on_event(event)
            except Exception as e:
                self._error_count += 1
                log.error("Plugin %s event error: %s", self.MANIFEST.name, e)
        sid = self._bus.subscribe(topic, _dispatch)
        self._sub_ids.append(sid)

    def _unsubscribe_all(self) -> None:
        for sid in self._sub_ids:
            self._bus.unsubscribe(sid)
        self._sub_ids.clear()

    async def publish(
        self,
        topic:    str,
        payload:  Any,
        priority: Priority = Priority.NORMAL,
    ) -> str:
        return await self._bus.publish(
            topic=topic,
            payload=payload,
            priority=priority,
            source=f"plugin:{self.MANIFEST.name}",
        )

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        return {
            "name":         self.MANIFEST.name,
            "type":         self.MANIFEST.plugin_type.value,
            "active":       self._active,
            "event_count":  self._event_count,
            "error_count":  self._error_count,
            "uptime":       round(time.time() - self._load_ts, 2) if self._load_ts else 0,
        }

# ── Plugin Entry ──────────────────────────────────────────────────────────────

@dataclass
class PluginEntry:
    plugin_id: str
    manifest:  PluginManifest
    instance:  Optional[LucyPlugin]
    state:     PluginState = PluginState.REGISTERED
    error:     Optional[str] = None
    loaded_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id":  self.plugin_id,
            "manifest":   self.manifest.to_dict(),
            "state":      self.state.value,
            "error":      self.error,
            "loaded_at":  self.loaded_at,
            "stats":      self.instance.stats() if self.instance else None,
        }

# ── Plugin Manager ─────────────────────────────────────────────────────────────

class AMEPluginManager:
    """
    Manages the full lifecycle of all Lucy OS plugins.
    Plugins can be registered programmatically or loaded from a directory.
    """

    def __init__(self, bus: AMEEventBus = None) -> None:
        self._bus     = bus or event_bus
        self._plugins: Dict[str, PluginEntry] = {}   # plugin_id → entry
        self._by_name: Dict[str, str] = {}            # name → plugin_id
        self._by_type: Dict[PluginType, Set[str]] = {t: set() for t in PluginType}

    # ── Register ──────────────────────────────────────────────────────────────

    def register(
        self,
        plugin_class: Type[LucyPlugin],
        config:       Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a plugin class. Returns plugin_id."""
        if not issubclass(plugin_class, LucyPlugin):
            raise TypeError(f"{plugin_class} must subclass LucyPlugin")
        if plugin_class.MANIFEST is None:
            raise ValueError(f"{plugin_class} must define MANIFEST")

        manifest = plugin_class.MANIFEST
        if config:
            manifest.config.update(config)

        plugin_id = str(uuid.uuid4())[:8]
        instance  = plugin_class(bus=self._bus)

        entry = PluginEntry(
            plugin_id=plugin_id,
            manifest=manifest,
            instance=instance,
            state=PluginState.REGISTERED,
        )
        self._plugins[plugin_id] = entry
        self._by_name[manifest.name] = plugin_id
        self._by_type[manifest.plugin_type].add(plugin_id)

        log.info("Plugin registered: %s [%s]", manifest.name, plugin_id)
        return plugin_id

    # ── Load / Activate ───────────────────────────────────────────────────────

    async def load(self, plugin_id: str) -> bool:
        """Load (activate) a registered plugin."""
        entry = self._plugins.get(plugin_id)
        if not entry:
            raise KeyError(f"Plugin not found: {plugin_id}")
        if entry.state == PluginState.ACTIVE:
            return True

        entry.state = PluginState.LOADING

        # Check requirements
        for req_name in entry.manifest.requires:
            if req_name not in self._by_name:
                entry.state = PluginState.ERROR
                entry.error = f"Required plugin not found: {req_name}"
                return False
            req_id = self._by_name[req_name]
            if self._plugins[req_id].state != PluginState.ACTIVE:
                ok = await self.load(req_id)
                if not ok:
                    entry.state = PluginState.ERROR
                    entry.error = f"Required plugin failed to load: {req_name}"
                    return False

        # Wire subscriptions
        inst = entry.instance
        for topic in entry.manifest.topics_sub:
            inst._subscribe(topic)

        # Call on_load
        try:
            await inst.on_load()
            inst._active  = True
            inst._load_ts = time.time()
            entry.state    = PluginState.ACTIVE
            entry.loaded_at = time.time()
            log.info("Plugin loaded: %s", entry.manifest.name)

            await self._bus.publish(
                topic="system.plugin_loaded",
                payload={"name": entry.manifest.name, "type": entry.manifest.plugin_type.value},
                source="plugin_manager",
            )
            return True
        except Exception as e:
            entry.state = PluginState.ERROR
            entry.error = str(e)
            inst._unsubscribe_all()
            log.error("Plugin load error (%s): %s", entry.manifest.name, e)
            return False

    async def load_all(self) -> Dict[str, bool]:
        """Load all registered plugins. Returns {plugin_id: success}."""
        results = {}
        for pid in list(self._plugins.keys()):
            results[pid] = await self.load(pid)
        return results

    async def load_by_name(self, name: str) -> bool:
        pid = self._by_name.get(name)
        if not pid:
            raise KeyError(f"Plugin not found by name: {name}")
        return await self.load(pid)

    # ── Unload / Pause ────────────────────────────────────────────────────────

    async def unload(self, plugin_id: str) -> bool:
        entry = self._plugins.get(plugin_id)
        if not entry or entry.state not in (PluginState.ACTIVE, PluginState.PAUSED):
            return False
        inst = entry.instance
        try:
            await inst.on_unload()
        except Exception as e:
            log.warning("Plugin unload error (%s): %s", entry.manifest.name, e)
        inst._unsubscribe_all()
        inst._active = False
        entry.state  = PluginState.UNLOADED
        log.info("Plugin unloaded: %s", entry.manifest.name)
        return True

    async def pause(self, plugin_id: str) -> bool:
        entry = self._plugins.get(plugin_id)
        if not entry or entry.state != PluginState.ACTIVE:
            return False
        entry.instance._unsubscribe_all()
        entry.state = PluginState.PAUSED
        return True

    async def resume(self, plugin_id: str) -> bool:
        entry = self._plugins.get(plugin_id)
        if not entry or entry.state != PluginState.PAUSED:
            return False
        for topic in entry.manifest.topics_sub:
            entry.instance._subscribe(topic)
        entry.state = PluginState.ACTIVE
        return True

    # ── Load from File ────────────────────────────────────────────────────────

    async def load_from_file(self, file_path: str) -> Optional[str]:
        """
        Dynamically load a plugin from a Python file.
        The file must contain a class with MANIFEST and subclass LucyPlugin.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Plugin file not found: {file_path}")

        # Compute checksum for integrity
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        module_name = f"lucy_plugin_{checksum}"

        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find LucyPlugin subclass
        plugin_class = None
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (inspect.isclass(obj) and issubclass(obj, LucyPlugin)
                    and obj is not LucyPlugin and obj.MANIFEST):
                plugin_class = obj
                break

        if not plugin_class:
            raise ValueError(f"No valid LucyPlugin subclass found in {file_path}")

        plugin_id = self.register(plugin_class)
        await self.load(plugin_id)
        return plugin_id

    async def load_from_directory(self, directory: str) -> Dict[str, str]:
        """Load all *.py plugin files from a directory. Returns {filename: plugin_id}."""
        results = {}
        for p in Path(directory).glob("*.py"):
            if p.name.startswith("_"):
                continue
            try:
                pid = await self.load_from_file(str(p))
                results[p.name] = pid
            except Exception as e:
                log.warning("Failed to load plugin from %s: %s", p.name, e)
                results[p.name] = f"ERROR:{e}"
        return results

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_by_id(self, plugin_id: str) -> Optional[PluginEntry]:
        return self._plugins.get(plugin_id)

    def get_by_name(self, name: str) -> Optional[PluginEntry]:
        pid = self._by_name.get(name)
        return self._plugins.get(pid) if pid else None

    def get_by_type(self, plugin_type: PluginType) -> List[PluginEntry]:
        ids = self._by_type.get(plugin_type, set())
        return [self._plugins[pid] for pid in ids if pid in self._plugins]

    def active_plugins(self) -> List[PluginEntry]:
        return [e for e in self._plugins.values() if e.state == PluginState.ACTIVE]

    def all_plugins(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._plugins.values()]

    def stats(self) -> Dict[str, Any]:
        states = {}
        for entry in self._plugins.values():
            states[entry.state.value] = states.get(entry.state.value, 0) + 1
        return {
            "total":       len(self._plugins),
            "by_state":    states,
            "by_type":     {t.value: len(ids) for t, ids in self._by_type.items()},
            "active":      sum(1 for e in self._plugins.values() if e.state == PluginState.ACTIVE),
        }

    # ── Tool Plugin Invocation ────────────────────────────────────────────────

    async def invoke_tool(self, name: str, payload: Dict[str, Any]) -> Any:
        """Invoke a TOOL-type plugin by name."""
        entry = self.get_by_name(name)
        if not entry or entry.state != PluginState.ACTIVE:
            raise RuntimeError(f"Tool plugin '{name}' not active")
        if entry.manifest.plugin_type != PluginType.TOOL:
            raise TypeError(f"Plugin '{name}' is not a TOOL plugin")
        event = BusEvent(topic="tool.invoke", payload=payload, source="plugin_manager")
        await entry.instance.on_event(event)

    # ── Health Check ──────────────────────────────────────────────────────────

    async def health_check_all(self) -> Dict[str, Any]:
        results = {}
        for entry in self._plugins.values():
            if entry.state == PluginState.ACTIVE:
                try:
                    h = await entry.instance.health_check()
                    results[entry.manifest.name] = h
                except Exception as e:
                    results[entry.manifest.name] = {"status": "error", "error": str(e)}
        return results


# ── Built-in Plugins ───────────────────────────────────────────────────────────

class TelemetryPlugin(LucyPlugin):
    """
    Built-in monitor plugin — auto-ingests Emma results and pushes telemetry.
    """
    MANIFEST = PluginManifest(
        name="telemetry_monitor",
        version="1.0.0",
        plugin_type=PluginType.MONITOR,
        description="Auto-ingests Emma results into the LTE telemetry engine.",
        topics_sub=[
            AMEEventBus.TOPIC_EMMA_RESULT,
            AMEEventBus.TOPIC_LTE_SCORE,
            AMEEventBus.TOPIC_SAFETY_BLOCK,
        ],
        topics_pub=[AMEEventBus.TOPIC_TELEMETRY_PUSH],
    )

    async def on_load(self) -> None:
        try:
            from lte.telemetry import telemetry
            self._telemetry = telemetry
        except ImportError:
            self._telemetry = None

    async def on_event(self, event: BusEvent) -> None:
        if not self._telemetry:
            return
        if event.topic == AMEEventBus.TOPIC_EMMA_RESULT:
            self._telemetry.ingest_emma_result(event.payload or {})
        elif event.topic == AMEEventBus.TOPIC_LTE_SCORE:
            score = (event.payload or {}).get("score", 0)
            self._telemetry.push("lte", "lte_score", float(score))
        elif event.topic == AMEEventBus.TOPIC_SAFETY_BLOCK:
            self._telemetry.push("safety", "block_events", 1.0)


class EarthMonitorPlugin(LucyPlugin):
    """
    Built-in monitor plugin — subscribes to earth events and tracks freshness.
    """
    MANIFEST = PluginManifest(
        name="earth_monitor",
        version="1.0.0",
        plugin_type=PluginType.MONITOR,
        description="Tracks Earth data freshness and query rate.",
        topics_sub=[
            AMEEventBus.TOPIC_EARTH_QUERY,
            AMEEventBus.TOPIC_EARTH_RESULT,
        ],
    )

    def __init__(self, bus=None):
        super().__init__(bus)
        self._query_count = 0

    async def on_event(self, event: BusEvent) -> None:
        self._query_count += 1
        try:
            from lte.telemetry import telemetry
            telemetry.push("earth", "query_rate", float(self._query_count))
        except ImportError:
            pass


class SentinelPlugin(LucyPlugin):
    """
    Built-in monitor — listens for sentinel alerts and re-publishes with high priority.
    """
    MANIFEST = PluginManifest(
        name="sentinel_relay",
        version="1.0.0",
        plugin_type=PluginType.MONITOR,
        description="Relays sentinel alerts to safety layer at high priority.",
        topics_sub=[AMEEventBus.TOPIC_SENTINEL_ALERT],
        topics_pub=[AMEEventBus.TOPIC_SAFETY_BLOCK],
    )

    async def on_event(self, event: BusEvent) -> None:
        payload = event.payload or {}
        severity = payload.get("severity", "low")
        if severity in ("high", "critical"):
            await self.publish(
                topic=AMEEventBus.TOPIC_SAFETY_BLOCK,
                payload={**payload, "source": "sentinel_relay"},
                priority=Priority.CRITICAL,
            )


# ── Singleton ──────────────────────────────────────────────────────────────────
plugin_manager = AMEPluginManager(bus=event_bus)


async def _register_builtins() -> None:
    """Register and load all built-in plugins."""
    for cls in (TelemetryPlugin, EarthMonitorPlugin, SentinelPlugin):
        pid = plugin_manager.register(cls)
        await plugin_manager.load(pid)

# Call at startup: asyncio.get_event_loop().run_until_complete(_register_builtins())