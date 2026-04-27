"""
LUCY OS — Plugin Manager for Earth Data Streams
================================================
Allows new data sources to be registered at runtime without modifying
core Lucy code. Each plugin is a Python callable that:
  1. Polls a URL or runs a function
  2. Returns a list of EarthEvent-compatible dicts
  3. Declares its metadata (name, poll_interval, schema)

Built-in plugins (registered by default):
  • usgs_quake  — USGS M2.5+ earthquake feed
  • noaa_wx     — NOAA active weather alerts
  • nasa_kp     — NASA/SWPC Kp index
  • volcano_si  — Smithsonian GVP volcano alerts (example third-party)
  • isc_seismic — ISC bulletin (alternate seismic source)

Plugin interface:
  class MyPlugin(BaseDataPlugin):
      name = "my_plugin"
      poll_interval_s = 60
      schema = {"lat": float, "lon": float, "magnitude": float, ...}

      def poll(self) -> list[dict]:
          ...

Or register a simple function:
  plugin_mgr.register_function(
      name="custom_feed",
      fn=my_poll_fn,
      poll_interval_s=120,
      description="My custom data feed"
  )
"""

import threading
import time
import json
import importlib
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Callable, Optional, Any
from pathlib import Path


# ── Base plugin interface ─────────────────────────────────────────────────────

class BaseDataPlugin(ABC):
    """Abstract base class for all Lucy data plugins."""

    name: str = "unnamed_plugin"
    poll_interval_s: float = 60.0
    description: str = ""
    version: str = "1.0"
    author: str = "system"
    enabled: bool = True

    # Schema: dict of field_name → type hint (for documentation)
    schema: dict = {}

    @abstractmethod
    def poll(self) -> list[dict]:
        """
        Fetch latest data from this plugin's source.
        Returns a list of event dicts compatible with EarthEvent.
        Each dict should have at minimum:
          event_id, timestamp, source, event_type, latitude, longitude, magnitude
        """
        ...

    def on_error(self, exc: Exception) -> None:
        """Called when poll() raises an exception. Override for custom handling."""
        print(f"[Plugin:{self.name}] Error: {exc}")

    def validate_event(self, event: dict) -> bool:
        """Minimal schema validation."""
        required = ["event_id", "source", "event_type"]
        return all(k in event for k in required)


# ── Plugin registry entry ─────────────────────────────────────────────────────

@dataclass
class PluginRecord:
    name: str
    plugin: Any                   # BaseDataPlugin instance or callable
    poll_interval_s: float
    description: str
    enabled: bool = True
    last_poll_utc: str = ""
    last_poll_epoch: float = 0.0
    last_event_count: int = 0
    total_events: int = 0
    error_count: int = 0
    last_error: str = ""
    _thread: Optional[threading.Thread] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "poll_interval_s": self.poll_interval_s,
            "enabled": self.enabled,
            "last_poll_utc": self.last_poll_utc,
            "last_event_count": self.last_event_count,
            "total_events": self.total_events,
            "error_count": self.error_count,
            "last_error": self.last_error,
        }


# ── Function adapter ──────────────────────────────────────────────────────────

class FunctionPlugin(BaseDataPlugin):
    """Wraps a plain function as a plugin."""

    def __init__(self, name: str, fn: Callable, poll_interval_s: float,
                 description: str, schema: dict = {}):
        self.name = name
        self._fn = fn
        self.poll_interval_s = poll_interval_s
        self.description = description
        self.schema = schema

    def poll(self) -> list[dict]:
        return self._fn()


# ── Built-in example plugins ──────────────────────────────────────────────────

class VolcanoSIPlugin(BaseDataPlugin):
    """
    Smithsonian Institution Global Volcanism Program — current eruptions.
    Real endpoint: https://volcano.si.edu/api/  (XML/JSON)
    This is a synthetic demo implementation showing the plugin pattern.
    """
    name = "volcano_si"
    poll_interval_s = 300.0  # 5 min
    description = "Smithsonian GVP volcano activity (synthetic demo)"
    schema = {
        "event_id": str,
        "source": str,
        "event_type": str,
        "latitude": float,
        "longitude": float,
        "magnitude": float,
        "location": str,
    }

    # Known active volcanoes (lat, lon, name)
    _VOLCANOES = [
        (19.421, -155.287, "Kilauea, Hawaii",       3.5),
        (63.630,  -19.605, "Katla, Iceland",         4.0),
        (37.734,  15.004,  "Etna, Italy",            3.8),
        (-8.342,  115.508, "Agung, Bali",            3.6),
        (52.076,  160.641, "Shiveluch, Russia",      4.2),
        (14.381, -90.601,  "Fuego, Guatemala",       3.7),
        (3.833,   102.366, "Merapi, Indonesia",      3.4),
    ]

    def poll(self) -> list[dict]:
        import random, hashlib
        now = time.time()
        # Deterministic "activity" based on current hour
        hour_seed = int(now / 3600) % len(self._VOLCANOES)
        vol = self._VOLCANOES[hour_seed]

        # Only "report" if in a simulated active window
        if int(now / 600) % 5 != 0:  # active ~20% of 10-min windows
            return []

        evt_id = hashlib.md5(f"vol_{hour_seed}_{int(now/3600)}".encode()).hexdigest()[:12]
        return [{
            "event_id": f"vol_{evt_id}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "volcano_si",
            "event_type": "volcanic_activity",
            "latitude": vol[0] + random.gauss(0, 0.01),
            "longitude": vol[1] + random.gauss(0, 0.01),
            "magnitude": vol[3] + random.gauss(0, 0.1),
            "depth_km": random.uniform(0, 5),
            "location": vol[2],
            "description": f"Volcanic activity detected at {vol[2]}",
        }]


class ISCSeismicPlugin(BaseDataPlugin):
    """
    ISC (International Seismological Centre) alternate seismic feed.
    Real endpoint: http://www.isc.ac.uk/cgi-bin/web-db-run
    This demo version generates ISC-style events synthetically.
    """
    name = "isc_seismic"
    poll_interval_s = 120.0
    description = "ISC alternate seismic bulletin (synthetic demo)"
    schema = {
        "event_id": str,
        "source": str,
        "event_type": str,
        "latitude": float,
        "longitude": float,
        "magnitude": float,
        "depth_km": float,
    }

    _REGIONS = [
        (35.6, 139.7,  "Japan"),
        (-33.9, 151.2, "Australia"),
        (28.6, 77.2,   "India"),
        (41.0, 29.0,   "Turkey"),
        (-12.0, -77.0, "Peru"),
        (60.0, -150.0, "Alaska"),
        (0.0, 100.0,   "Indonesia"),
    ]

    def poll(self) -> list[dict]:
        import random, hashlib
        now = time.time()
        if int(now / 120) % 4 != 0:  # active ~25% of 2-min windows
            return []

        region = self._REGIONS[int(now / 3600) % len(self._REGIONS)]
        evt_id = hashlib.md5(f"isc_{int(now/120)}".encode()).hexdigest()[:12]
        mag = round(random.uniform(2.0, 5.5), 1)
        return [{
            "event_id": f"isc_{evt_id}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "isc_seismic",
            "event_type": "earthquake",
            "latitude": region[0] + random.gauss(0, 0.5),
            "longitude": region[1] + random.gauss(0, 0.5),
            "magnitude": mag,
            "depth_km": round(random.uniform(5, 200), 1),
            "location": region[2],
            "description": f"M{mag} ISC bulletin event near {region[2]}",
        }]


# ── Plugin Manager ────────────────────────────────────────────────────────────

class PluginManager:
    """
    Central registry and runner for all Lucy data plugins.

    Usage:
        mgr = PluginManager(event_callback=my_fn)
        mgr.register(VolcanoSIPlugin())
        mgr.start()
        ...
        mgr.stop()
    """

    def __init__(self, event_callback: Optional[Callable[[dict], None]] = None):
        self._plugins: dict[str, PluginRecord] = {}
        self._lock = threading.Lock()
        self._event_cb = event_callback
        self._running = False
        self._threads: list[threading.Thread] = []

        # Register built-in plugins
        self._register_builtins()

    def _register_builtins(self) -> None:
        self.register(VolcanoSIPlugin(), enabled=False)   # off by default
        self.register(ISCSeismicPlugin(), enabled=False)  # off by default

    def register(self, plugin: BaseDataPlugin, enabled: bool = True) -> None:
        """Register a plugin instance."""
        with self._lock:
            rec = PluginRecord(
                name=plugin.name,
                plugin=plugin,
                poll_interval_s=plugin.poll_interval_s,
                description=plugin.description,
                enabled=enabled,
            )
            self._plugins[plugin.name] = rec
            if self._running and enabled:
                self._start_plugin_thread(rec)

    def register_function(
        self,
        name: str,
        fn: Callable[[], list[dict]],
        poll_interval_s: float = 60.0,
        description: str = "",
        enabled: bool = True,
        schema: dict = {},
    ) -> None:
        """Register a plain function as a plugin."""
        plugin = FunctionPlugin(name, fn, poll_interval_s, description, schema)
        self.register(plugin, enabled=enabled)

    def unregister(self, name: str) -> bool:
        """Remove a plugin by name."""
        with self._lock:
            if name in self._plugins:
                self._plugins[name].enabled = False
                del self._plugins[name]
                return True
        return False

    def enable(self, name: str) -> bool:
        with self._lock:
            if name in self._plugins:
                self._plugins[name].enabled = True
                if self._running:
                    rec = self._plugins[name]
                    if rec._thread is None or not rec._thread.is_alive():
                        self._start_plugin_thread(rec)
                return True
        return False

    def disable(self, name: str) -> bool:
        with self._lock:
            if name in self._plugins:
                self._plugins[name].enabled = False
                return True
        return False

    def start(self) -> None:
        """Start polling all enabled plugins in background threads."""
        self._running = True
        with self._lock:
            for rec in self._plugins.values():
                if rec.enabled:
                    self._start_plugin_thread(rec)

    def stop(self) -> None:
        """Stop all plugin threads."""
        self._running = False

    def _start_plugin_thread(self, rec: PluginRecord) -> None:
        t = threading.Thread(
            target=self._poll_loop,
            args=(rec,),
            name=f"plugin-{rec.name}",
            daemon=True,
        )
        rec._thread = t
        t.start()

    def _poll_loop(self, rec: PluginRecord) -> None:
        """Background polling loop for a single plugin."""
        while self._running and rec.enabled:
            try:
                t0 = time.time()
                events = rec.plugin.poll()
                elapsed = (time.time() - t0) * 1000

                now_iso = datetime.now(timezone.utc).isoformat()
                with self._lock:
                    rec.last_poll_utc = now_iso
                    rec.last_poll_epoch = time.time()
                    rec.last_event_count = len(events)
                    rec.total_events += len(events)

                for evt in events:
                    if self._event_cb:
                        try:
                            self._event_cb(evt)
                        except Exception as cb_err:
                            print(f"[PluginMgr] Callback error: {cb_err}")

            except Exception as exc:
                with self._lock:
                    rec.error_count += 1
                    rec.last_error = str(exc)[:200]
                rec.plugin.on_error(exc)

            # Wait for next poll (interruptible)
            deadline = time.time() + rec.poll_interval_s
            while self._running and rec.enabled and time.time() < deadline:
                time.sleep(0.5)

    def get_status(self) -> list[dict]:
        """Return status of all registered plugins."""
        with self._lock:
            return [rec.to_dict() for rec in self._plugins.values()]

    def list_plugins(self) -> list[str]:
        with self._lock:
            return list(self._plugins.keys())

    def get_plugin(self, name: str) -> Optional[PluginRecord]:
        with self._lock:
            return self._plugins.get(name)

    def poll_now(self, name: str) -> list[dict]:
        """Manually trigger a poll for a named plugin (for testing/debug)."""
        with self._lock:
            rec = self._plugins.get(name)
        if not rec:
            raise KeyError(f"Plugin '{name}' not found")
        try:
            events = rec.plugin.poll()
            with self._lock:
                rec.last_poll_utc = datetime.now(timezone.utc).isoformat()
                rec.last_event_count = len(events)
                rec.total_events += len(events)
            return events
        except Exception as exc:
            with self._lock:
                rec.error_count += 1
                rec.last_error = str(exc)[:200]
            raise


# ── Module-level singleton ────────────────────────────────────────────────────

_manager: Optional[PluginManager] = None

def get_plugin_manager(
    event_callback: Optional[Callable[[dict], None]] = None
) -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager(event_callback=event_callback)
    elif event_callback and not _manager._event_cb:
        _manager._event_cb = event_callback
    return _manager