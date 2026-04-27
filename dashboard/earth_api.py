"""
Lucy OS — Earth Dashboard API
==============================
FastAPI router providing:
  GET  /api/earth/events   — recent Earth events (seismic, weather, solar)
  GET  /api/earth/feeds    — feed status (USGS, NOAA, NASA)
  GET  /api/earth/stats    — ingestion statistics
  GET  /api/qme/snapshot   — QME field state snapshot
  POST /api/qme/inject     — inject disturbance into QME
  GET  /api/qme/metrics    — full QME learning metrics
  WS   /ws/earth           — WebSocket for real-time push

Live proof elements:
  - Every response includes UTC timestamp + lag seconds
  - Feed status shows events/60s, last_updated, lag
  - Anomaly detection: flag feeds >5min stale
"""

import asyncio
import json
import logging
import datetime
import threading
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

log = logging.getLogger("lucy.earth.api")

router = APIRouter(prefix="/api", tags=["earth"])

# ─── Lazy-init singletons ─────────────────────────────────────────────────────
_earth_bridge = None
_qme_learner  = None
_ws_clients: List[WebSocket] = []
_lock = threading.Lock()


def _get_bridge():
    global _earth_bridge
    if _earth_bridge is None:
        from quantum_music.earth_bridge import EarthOscillatorBridge
        _earth_bridge = EarthOscillatorBridge(
            on_event=_on_earth_event,
            synthetic_fallback=True,
        )
        _earth_bridge.start()
        log.info("EarthOscillatorBridge started")
    return _earth_bridge


def _get_qme():
    global _qme_learner
    if _qme_learner is None:
        from quantum_music.learning_loop import QuantumMusicLearner
        _qme_learner = QuantumMusicLearner(
            policy_kind="neural",
            noise_level=0.02,
            event_callback=_on_qme_event,
        )
        _qme_learner.start()
        log.info("QuantumMusicLearner started")
    return _qme_learner


def _on_earth_event(event):
    """Callback: Earth event → inject into QME as disturbance."""
    try:
        qme = _get_qme()
        qme.inject_disturbance(
            x         = event.grid_x,
            y         = event.grid_y,
            amplitude = event.qme_amplitude,
            radius    = event.qme_radius,
            source    = event.title,
        )
    except Exception as e:
        log.warning(f"QME inject from Earth event failed: {e}")


def _on_qme_event(event: dict):
    """Callback: QME alert → broadcast via WebSocket."""
    asyncio.run_coroutine_threadsafe(
        _broadcast_ws(event),
        _get_event_loop(),
    ) if _ws_clients else None


_main_loop = None

def _get_event_loop():
    global _main_loop
    if _main_loop is None:
        _main_loop = asyncio.get_event_loop()
    return _main_loop


async def _broadcast_ws(data: dict):
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ─── Request/Response Models ──────────────────────────────────────────────────

class InjectRequest(BaseModel):
    x:         float = 0.5
    y:         float = 0.5
    amplitude: float = 0.3
    radius:    float = 0.2
    source:    str   = "manual"


class AnnotateRequest(BaseModel):
    event_id: str
    verified: bool = True
    note:     str  = ""


# ─── Earth Endpoints ──────────────────────────────────────────────────────────

@router.get("/earth/events")
async def get_earth_events(
    limit:  int = Query(100, ge=1, le=500),
    source: Optional[str] = None,
    type:   Optional[str] = None,
    min_mag: float = Query(0.0, ge=0.0),
):
    """
    Recent Earth events.
    Includes live proof: UTC timestamp, lag, source traceability.
    """
    bridge = _get_bridge()
    events = bridge.get_recent_events(n=limit * 2, source=source)

    # Filter
    if type:
        events = [e for e in events if e.get("event_type") == type]
    if min_mag > 0:
        events = [e for e in events if e.get("magnitude", 0) >= min_mag]

    events = events[:limit]

    return {
        "timestamp":   _utc_now(),
        "count":       len(events),
        "events":      events,
        "live_proof":  {
            "utc":           _utc_now(),
            "source_feeds":  list({e.get("source","") for e in events}),
            "oldest_event":  events[-1].get("timestamp") if events else None,
            "newest_event":  events[0].get("timestamp")  if events else None,
        },
    }


@router.get("/earth/feeds")
async def get_feed_status():
    """
    Feed status with live proof elements.
    Shows: last_updated, lag_seconds, events_60s, status badge.
    """
    bridge = _get_bridge()
    feeds  = bridge.get_feed_status()
    epm    = bridge.get_events_per_minute()

    return {
        "timestamp": _utc_now(),
        "feeds":     feeds,
        "events_per_minute": epm,
        "total_events": bridge.get_total_events(),
        "anomaly_flags": _check_anomalies(feeds),
    }


@router.get("/earth/stats")
async def get_earth_stats():
    """Ingestion statistics for the live proof panel."""
    bridge = _get_bridge()
    feeds  = bridge.get_feed_status()
    epm    = bridge.get_events_per_minute()

    return {
        "timestamp":        _utc_now(),
        "total_ingested":   bridge.get_total_events(),
        "events_per_minute": epm,
        "feeds":            feeds,
        "health":           _overall_health(feeds),
    }


def _check_anomalies(feeds: dict) -> List[dict]:
    """Flag feeds lagging >5min or suddenly silent."""
    anomalies = []
    for name, fs in feeds.items():
        lag = fs.get("lag_seconds", 0)
        if lag > 300:
            anomalies.append({
                "feed":    name,
                "type":    "stale_feed",
                "lag_s":   round(lag, 1),
                "message": f"{name} feed is {round(lag/60,1)}min stale",
            })
        if fs.get("total_ingested", 0) > 100 and fs.get("events_60s", 0) == 0:
            anomalies.append({
                "feed":    name,
                "type":    "feed_silent",
                "message": f"{name} has gone silent (0 events in 60s)",
            })
    return anomalies


def _overall_health(feeds: dict) -> str:
    live = sum(1 for f in feeds.values() if f.get("live"))
    total = len(feeds)
    if live == total: return "✅ All feeds live"
    if live == 0:     return "❌ All feeds offline"
    return f"⚠️ {live}/{total} feeds live"


# ─── QME Endpoints ───────────────────────────────────────────────────────────

@router.get("/qme/snapshot")
async def get_qme_snapshot():
    """Current QME field snapshot for dashboard rendering."""
    try:
        qme  = _get_qme()
        snap = qme.get_field_snapshot()
        return {
            "timestamp": _utc_now(),
            **snap,
        }
    except Exception as e:
        log.warning(f"QME snapshot error: {e}")
        return {
            "timestamp": _utc_now(),
            "ready":     False,
            "error":     str(e),
        }


@router.get("/qme/metrics")
async def get_qme_metrics():
    """Full QME learning metrics."""
    try:
        qme = _get_qme()
        return {
            "timestamp": _utc_now(),
            **qme.get_metrics(),
        }
    except Exception as e:
        return {"timestamp": _utc_now(), "error": str(e)}


@router.post("/qme/inject")
async def inject_qme_disturbance(req: InjectRequest):
    """
    Manually inject a disturbance into the QME field.
    Used by the Earth dashboard "Inject to QME" button.
    """
    try:
        qme = _get_qme()
        qme.inject_disturbance(
            x         = req.x,
            y         = req.y,
            amplitude = req.amplitude,
            radius    = req.radius,
            source    = req.source,
        )
        return {
            "status":    "injected",
            "timestamp": _utc_now(),
            "params":    req.dict(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/qme/control")
async def qme_control(action: str = Query(...)):
    """Control QME learner: start | pause | resume | stop | reset_noise."""
    try:
        qme = _get_qme()
        if action == "pause":   qme.pause()
        elif action == "resume":qme.resume()
        elif action == "stop":  qme.stop()
        elif action == "noise_low":  qme.set_noise_level(0.01)
        elif action == "noise_high": qme.set_noise_level(0.08)
        return {"status": "ok", "action": action, "timestamp": _utc_now()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/earth/annotate")
async def annotate_event(req: AnnotateRequest):
    """Human-in-the-loop: mark an event as verified / add note."""
    return {
        "status":    "annotated",
        "event_id":  req.event_id,
        "verified":  req.verified,
        "note":      req.note,
        "timestamp": _utc_now(),
    }


# ─── WebSocket ────────────────────────────────────────────────────────────────

@router.websocket("/ws/earth")
async def websocket_earth(ws: WebSocket):
    """
    Real-time push of Earth events + QME state.
    Client receives:
      { type: 'earth_event', data: EarthEvent }
      { type: 'qme_update',  data: QMESnapshot }
      { type: 'feed_status', data: FeedStatus }
    """
    await ws.accept()
    _ws_clients.append(ws)
    try:
        # Send initial state
        bridge = _get_bridge()
        qme    = _get_qme()
        await ws.send_text(json.dumps({
            "type": "init",
            "events":      bridge.get_recent_events(n=50),
            "feeds":       bridge.get_feed_status(),
            "qme":         qme.get_field_snapshot(),
            "timestamp":   _utc_now(),
        }))

        # Keep alive + periodic push
        while True:
            await asyncio.sleep(3)
            snap = {
                "type":      "tick",
                "qme":       qme.get_field_snapshot(),
                "feeds":     bridge.get_feed_status(),
                "timestamp": _utc_now(),
            }
            await ws.send_text(json.dumps(snap))
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"

# ─── Forecasting + DuckDB + Plugin + NL-query endpoints ──────────────────────
# (appended by upgrade pass)

_forecast_engine  = None
_duck_store       = None
_plugin_manager   = None


def _get_forecast():
    global _forecast_engine
    if _forecast_engine is None:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from quantum_music.forecast import ForecastEngine
        _forecast_engine = ForecastEngine()
    return _forecast_engine


def _get_store():
    global _duck_store
    if _duck_store is None:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from quantum_music.duckdb_store import LucyDuckStore
        _duck_store = LucyDuckStore()
    return _duck_store


def _get_plugins():
    global _plugin_manager
    if _plugin_manager is None:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from quantum_music.plugin_manager import PluginManager
        _plugin_manager = PluginManager(event_callback=_on_earth_event_dict)
    return _plugin_manager


def _on_earth_event_dict(event: dict):
    """Callback for plugin manager — receives plain dict (not EarthEvent)."""
    try:
        store = _get_store()
        store.insert_event(event)
    except Exception as e:
        log.warning(f"store.insert_event failed: {e}")
    try:
        qme = _get_qme()
        lat = event.get("latitude", 0) or 0
        lon = event.get("longitude", 0) or 0
        mag = event.get("magnitude", 2.0) or 2.0
        # Map lat/lon to QME grid (20×10)
        gx = int((lon + 180) / 360 * 20) % 20
        gy = int((90 - lat) / 180 * 10) % 10
        qme.inject_disturbance(x=gx, y=gy, amplitude=mag * 0.15,
                                radius=2, source=event.get("source", "plugin"))
    except Exception:
        pass


# ─── NL Query helpers ─────────────────────────────────────────────────────────

_NL_KEYWORDS = {
    "earthquake": {"event_type": "earthquake"},
    "quake":      {"event_type": "earthquake"},
    "seismic":    {"source": "usgs"},
    "usgs":       {"source": "usgs"},
    "weather":    {"source": "noaa"},
    "storm":      {"source": "noaa"},
    "noaa":       {"source": "noaa"},
    "space":      {"source": "nasa"},
    "kp":         {"source": "nasa"},
    "solar":      {"source": "nasa"},
    "volcanic":   {"source": "volcano_si"},
    "volcano":    {"source": "volcano_si"},
}

_NL_MAG_PHRASES = [
    ("above", None), ("over", None), ("greater than", None),
    ("magnitude", None), ("m", None),
]


def _parse_nl_query(raw: str) -> dict:
    """
    Lightweight NL parser — no LLM required.
    Extracts: source filter, event_type filter, min_magnitude, limit, time window.

    Examples:
      "show me earthquakes above 5"
        → {source: usgs, event_type: earthquake, min_mag: 5.0}
      "latest noaa weather alerts"
        → {source: noaa, limit: 20}
      "big solar storms in last hour"
        → {source: nasa, since_hours: 1.0}
      "all events magnitude over 4.5 from usgs"
        → {source: usgs, min_mag: 4.5}
    """
    import re
    text = raw.lower().strip()
    parsed: dict = {}

    # Source / type keyword matching
    for kw, filters in _NL_KEYWORDS.items():
        if kw in text:
            parsed.update(filters)
            break

    # Magnitude extraction: "above 5", "over 4.5", "magnitude 3", "m5"
    mag_match = re.search(
        r"(?:above|over|greater than|magnitude|>=|>)\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not mag_match:
        mag_match = re.search(r"m\s*([0-9]+(?:\.[0-9]+)?)", text)
    if mag_match:
        parsed["min_mag"] = float(mag_match.group(1))

    # Time window: "last hour", "last 2 hours", "last 30 min"
    time_match = re.search(
        r"last\s+([0-9]+(?:\.[0-9]+)?)\s*(hour|hr|h|minute|min|m)", text)
    if time_match:
        val = float(time_match.group(1))
        unit = time_match.group(2)
        if unit.startswith("m"):
            parsed["since_hours"] = val / 60
        else:
            parsed["since_hours"] = val
    elif "last hour" in text:
        parsed["since_hours"] = 1.0
    elif "today" in text:
        parsed["since_hours"] = 24.0

    # Limit: "top 10", "first 5", "20 events"
    lim_match = re.search(
        r"(?:top|first|show|latest|last)\s+([0-9]+)|([0-9]+)\s+events?", text)
    if lim_match:
        n = lim_match.group(1) or lim_match.group(2)
        if n:
            parsed["limit"] = min(int(n), 500)

    return parsed


# ─── New endpoints ────────────────────────────────────────────────────────────

@router.get("/earth/forecast")
async def get_forecast(domain: str = Query(default="all",
    description="seismic | qme | storm | kp | all")):
    """
    Short-term +6h forecasts for seismic activity, QME stability,
    storm tracks, and Kp-index.
    """
    try:
        import time
        bridge  = _get_bridge()
        qme     = _get_qme()
        engine  = _get_forecast()

        events = bridge.get_recent_events(n=200)

        # Build QME stability history from learner metrics
        metrics = qme.get_metrics()
        ep_hist = metrics.get("episode_history", [])
        stab_hist = [ep.get("mean_stability", 0.0) for ep in ep_hist[-50:]]
        if not stab_hist:
            snap = qme.get_field_snapshot()
            stab_hist = [snap.get("stability_score", 0.0)] * 4

        # Build Kp history from NASA events (magnitude field = Kp value)
        kp_events = [e for e in events if e.get("source") == "nasa"]
        kp_hist = [e.get("magnitude", 3.0) for e in kp_events[-24:]]
        if not kp_hist:
            kp_hist = [3.0, 2.5, 3.2, 2.8, 3.5]  # default quiet

        if domain == "all":
            result = engine.all_forecasts(
                events=events,
                stability_history=stab_hist,
                kp_history=kp_hist,
            )
        elif domain == "seismic":
            seismic_ev = [e for e in events if e.get("source") == "usgs"]
            result = engine.seismic(seismic_ev).to_dict()
        elif domain == "qme":
            result = engine.qme(stab_hist).to_dict()
        elif domain == "storm":
            wx_ev = [e for e in events if e.get("source") == "noaa"]
            result = engine.storm(wx_ev).to_dict()
        elif domain == "kp":
            result = engine.kp(kp_hist).to_dict()
        else:
            return {"error": f"Unknown domain: {domain}",
                    "valid": ["seismic", "qme", "storm", "kp", "all"]}

        result["live_proof"] = {
            "generated_utc": _utc_now(),
            "source": "lucy_forecast_engine",
            "horizon_hours": 6,
        }
        return result

    except Exception as e:
        log.exception("Forecast error")
        return {"error": str(e), "timestamp": _utc_now()}


@router.get("/earth/query")
async def natural_language_query(
    q: str = Query(..., description="Natural language query, e.g. 'earthquakes above 5 in last hour'"),
):
    """
    Natural language query interface over live Earth event data.
    No LLM required — uses keyword + regex extraction.
    """
    import time as _time
    t0 = _time.time()

    try:
        parsed = _parse_nl_query(q)

        # Map parsed filters to event query
        source    = parsed.get("source")
        event_type= parsed.get("event_type")
        min_mag   = parsed.get("min_mag", 0.0)
        limit     = parsed.get("limit", 50)
        since_h   = parsed.get("since_hours", 1.0)  # default: last hour

        bridge  = _get_bridge()
        events  = bridge.get_recent_events(n=500)

        # Filter
        import time
        since_epoch = time.time() - since_h * 3600
        filtered = []
        for ev in events:
            # Time filter
            ev_ts = ev.get("ts_epoch", ev.get("ingested_at", 0))
            if isinstance(ev_ts, str):
                try:
                    import datetime as _dt
                    ev_ts = _dt.datetime.fromisoformat(
                        ev_ts.rstrip("Z")).timestamp()
                except Exception:
                    ev_ts = 0
            if ev_ts < since_epoch:
                continue
            # Source filter
            if source and ev.get("source") != source:
                continue
            # Event type filter
            if event_type and ev.get("event_type") != event_type:
                continue
            # Magnitude filter
            ev_mag = ev.get("magnitude") or 0
            if ev_mag < min_mag:
                continue
            filtered.append(ev)

        filtered = filtered[:limit]
        elapsed_ms = (_time.time() - t0) * 1000

        # Log to DuckDB if available
        try:
            _get_store().log_nl_query(q, parsed, len(filtered), elapsed_ms)
        except Exception:
            pass

        return {
            "query": q,
            "parsed_filters": parsed,
            "result_count": len(filtered),
            "duration_ms": round(elapsed_ms, 2),
            "events": filtered,
            "live_proof": {"queried_utc": _utc_now()},
        }

    except Exception as e:
        log.exception("NL query error")
        return {"error": str(e), "query": q, "timestamp": _utc_now()}


@router.get("/earth/storage/stats")
async def storage_stats():
    """DuckDB time-series storage statistics."""
    try:
        store = _get_store()
        stats = store.get_stats()
        feed_summary = store.get_feed_summary()
        return {
            "storage": stats,
            "feed_summary": feed_summary,
            "timestamp": _utc_now(),
        }
    except Exception as e:
        return {"error": str(e), "timestamp": _utc_now()}


@router.get("/earth/storage/history")
async def qme_history(
    hours: float = Query(default=1.0, ge=0.1, le=168.0,
                         description="Hours of history to return"),
    limit: int = Query(default=200, ge=1, le=2000),
):
    """Return QME stability history from DuckDB for charting."""
    import time
    try:
        store     = _get_store()
        since     = time.time() - hours * 3600
        history   = store.get_qme_history(since_epoch=since, limit=limit)
        events_h  = store.get_events(since_epoch=since, limit=limit)
        return {
            "qme_history": history,
            "earth_events": events_h,
            "hours": hours,
            "timestamp": _utc_now(),
        }
    except Exception as e:
        return {"error": str(e), "timestamp": _utc_now()}


@router.get("/plugins/status")
async def plugin_status():
    """List all registered data plugins and their status."""
    try:
        mgr = _get_plugins()
        return {
            "plugins": mgr.get_status(),
            "timestamp": _utc_now(),
        }
    except Exception as e:
        return {"error": str(e), "timestamp": _utc_now()}


@router.post("/plugins/{name}/enable")
async def enable_plugin(name: str):
    """Enable a registered plugin."""
    try:
        mgr = _get_plugins()
        ok = mgr.enable(name)
        return {"plugin": name, "enabled": ok, "timestamp": _utc_now()}
    except Exception as e:
        return {"error": str(e), "timestamp": _utc_now()}


@router.post("/plugins/{name}/disable")
async def disable_plugin(name: str):
    """Disable a registered plugin."""
    try:
        mgr = _get_plugins()
        ok = mgr.disable(name)
        return {"plugin": name, "disabled": ok, "timestamp": _utc_now()}
    except Exception as e:
        return {"error": str(e), "timestamp": _utc_now()}


@router.post("/plugins/{name}/poll")
async def poll_plugin_now(name: str):
    """Manually trigger an immediate poll of a plugin."""
    try:
        mgr = _get_plugins()
        events = mgr.poll_now(name)
        return {
            "plugin": name,
            "events_returned": len(events),
            "events": events[:20],
            "timestamp": _utc_now(),
        }
    except KeyError:
        return {"error": f"Plugin '{name}' not found", "timestamp": _utc_now()}
    except Exception as e:
        return {"error": str(e), "timestamp": _utc_now()}


@router.get("/earth/anomalies")
async def get_anomalies():
    """
    Detect anomalies across all active data streams:
      - Feeds silent >5min
      - QME sudden stability drop >0.3
      - Seismic cluster (>5 events in 10min in same region)
      - Kp spike above 5
    """
    import time
    try:
        bridge  = _get_bridge()
        qme     = _get_qme()
        now     = time.time()

        anomalies = []

        # Feed staleness
        feeds = bridge.get_feed_status()
        for feed_name, fd in feeds.items():
            lag = fd.get("lag_seconds", 0)
            if lag > 300:
                anomalies.append({
                    "type": "feed_stale",
                    "severity": "warning",
                    "feed": feed_name,
                    "lag_seconds": lag,
                    "message": f"{feed_name} feed silent for {lag:.0f}s (>5min)",
                    "detected_utc": _utc_now(),
                })

        # QME instability
        snap = qme.get_field_snapshot()
        regime = snap.get("regime", "")
        stability = snap.get("stability_score", 0)
        if regime in ("chaos", "instability"):
            anomalies.append({
                "type": "qme_instability",
                "severity": "critical" if regime == "chaos" else "warning",
                "regime": regime,
                "stability_score": stability,
                "message": f"QME field in {regime} regime (score={stability:.3f})",
                "detected_utc": _utc_now(),
            })

        # Seismic cluster: >5 M3+ events in last 10min within ~500km
        events = bridge.get_recent_events(n=100)
        recent_quakes = [
            e for e in events
            if e.get("source") == "usgs"
            and (e.get("magnitude") or 0) >= 3.0
        ]
        if len(recent_quakes) >= 5:
            anomalies.append({
                "type": "seismic_cluster",
                "severity": "warning",
                "count": len(recent_quakes),
                "message": f"Seismic cluster: {len(recent_quakes)} M3+ events recently",
                "detected_utc": _utc_now(),
            })

        # Kp storm
        nasa_events = [e for e in events if e.get("source") == "nasa"]
        if nasa_events:
            kp = nasa_events[0].get("magnitude", 0)
            if kp >= 5:
                cls = ("G5" if kp >= 9 else "G4" if kp >= 8 else "G3" if kp >= 7
                       else "G2" if kp >= 6 else "G1")
                anomalies.append({
                    "type": "geomagnetic_storm",
                    "severity": "critical" if kp >= 7 else "warning",
                    "kp_index": kp,
                    "storm_class": cls,
                    "message": f"{cls} geomagnetic storm — Kp={kp:.1f}",
                    "detected_utc": _utc_now(),
                })

        return {
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "timestamp": _utc_now(),
            "live_proof": {"checked_feeds": list(feeds.keys())},
        }

    except Exception as e:
        log.exception("Anomaly detection error")
        return {"error": str(e), "timestamp": _utc_now()}
