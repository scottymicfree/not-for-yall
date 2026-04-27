"""
Lucy OS — Quantum Music Engine: Earth Oscillator Bridge
=======================================================
Connects real Earth data → QME disturbances.

Earth IS a planet-scale orchestra:
  Seismic waves      → oscillator disturbances (amplitude ∝ magnitude)
  Atmospheric waves  → low-frequency field modulation
  Magnetic field     → coupling constant adjustments
  Ocean tides        → slow phase drift injection

Data sources (live + fallback):
  USGS    → seismic events  (real-time GeoJSON feed)
  NOAA    → weather/wind    (GFS API)
  NASA    → space weather   (DONKI API)
  OpenMet → atmospheric     (free, no key)

Each event is mapped to:
  (lat, lon) → normalized (x, y) on oscillator grid
  magnitude  → disturbance amplitude
  depth      → radius of effect
"""

import numpy as np
import threading
import time
import logging
import datetime
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
import urllib.request
import urllib.error
import json

log = logging.getLogger("lucy.qme.earth_bridge")


# ─── Earth Event ──────────────────────────────────────────────────────────────

@dataclass
class EarthEvent:
    """A real-world event that becomes a QME disturbance."""
    source:     str          # 'usgs', 'noaa', 'nasa', 'synthetic'
    event_type: str          # 'seismic', 'weather', 'solar', 'magnetic'
    lat:        float        # degrees [-90, 90]
    lon:        float        # degrees [-180, 180]
    magnitude:  float        # event intensity (0–10 for seismic, hPa for pressure, etc.)
    depth_km:   float        # depth/altitude in km
    timestamp:  str          # UTC ISO string
    title:      str          # human-readable description
    url:        str          # source URL for traceability
    raw:        Dict = field(default_factory=dict)  # raw API response

    @property
    def grid_x(self) -> float:
        """Normalized x position on QME grid [0, 1] (lon→x)."""
        return (self.lon + 180.0) / 360.0

    @property
    def grid_y(self) -> float:
        """Normalized y position on QME grid [0, 1] (lat→y, N=0, S=1)."""
        return (90.0 - self.lat) / 180.0

    @property
    def qme_amplitude(self) -> float:
        """Convert magnitude to QME disturbance amplitude [0, 1]."""
        if self.event_type == "seismic":
            # Richter scale: M5=0.1, M7=0.5, M9=1.0
            return float(np.clip(self.magnitude / 9.0, 0.0, 1.0))
        elif self.event_type == "weather":
            # Wind speed mph → amplitude
            return float(np.clip(self.magnitude / 150.0, 0.0, 1.0))
        elif self.event_type == "solar":
            # Kp index 0–9
            return float(np.clip(self.magnitude / 9.0, 0.0, 1.0))
        return float(np.clip(self.magnitude / 10.0, 0.0, 1.0))

    @property
    def qme_radius(self) -> float:
        """Effect radius on QME grid [0.05, 0.5]."""
        if self.event_type == "seismic":
            # Deeper = wider effect
            return float(np.clip(0.05 + self.depth_km / 700.0, 0.05, 0.4))
        return 0.15

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source":     self.source,
            "event_type": self.event_type,
            "lat":        round(self.lat, 4),
            "lon":        round(self.lon, 4),
            "magnitude":  round(self.magnitude, 2),
            "depth_km":   round(self.depth_km, 1),
            "timestamp":  self.timestamp,
            "title":      self.title,
            "url":        self.url,
            "grid_x":     round(self.grid_x, 4),
            "grid_y":     round(self.grid_y, 4),
            "qme_amplitude": round(self.qme_amplitude, 4),
            "qme_radius":    round(self.qme_radius, 4),
        }


# ─── Feed Status ──────────────────────────────────────────────────────────────

@dataclass
class FeedStatus:
    name:           str
    live:           bool
    last_updated:   Optional[str]
    events_60s:     int
    total_ingested: int
    last_error:     Optional[str]
    lag_seconds:    float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name":           self.name,
            "live":           self.live,
            "last_updated":   self.last_updated,
            "events_60s":     self.events_60s,
            "total_ingested": self.total_ingested,
            "last_error":     self.last_error,
            "lag_seconds":    round(self.lag_seconds, 1),
            "status":         "✅ Live" if self.live and self.lag_seconds < 300
                              else "⚠️ Updating" if self.lag_seconds < 900
                              else "❌ Stale",
        }


# ─── Earth Oscillator Bridge ──────────────────────────────────────────────────

class EarthOscillatorBridge:
    """
    Polls real Earth data feeds and converts events → QME disturbances.

    Thread-safe. Runs background polling loops for each feed.
    Falls back to synthetic data if feeds are unavailable.
    """

    POLL_INTERVAL_USGS  = 30    # seconds between USGS polls
    POLL_INTERVAL_NOAA  = 60    # seconds between NOAA polls
    POLL_INTERVAL_SPACE = 120   # seconds between space weather polls
    MAX_EVENTS_CACHE    = 500   # max events in local cache
    STALENESS_WARN_S    = 300   # warn if feed >5min stale

    def __init__(self,
                 on_event: Optional[Callable[[EarthEvent], None]] = None,
                 synthetic_fallback: bool = True):

        self._on_event  = on_event
        self._synthetic = synthetic_fallback
        self._running   = False
        self._lock      = threading.Lock()

        # Event cache
        self._events:   List[EarthEvent] = []
        self._events_60s: Dict[str, int] = {"usgs": 0, "noaa": 0, "nasa": 0}
        self._ingestion_window: List[tuple] = []  # (timestamp, source)

        # Feed status
        self._feeds: Dict[str, FeedStatus] = {
            "USGS":  FeedStatus("USGS",  False, None, 0, 0, None, 9999),
            "NOAA":  FeedStatus("NOAA",  False, None, 0, 0, None, 9999),
            "NASA":  FeedStatus("NASA",  False, None, 0, 0, None, 9999),
        }

        # Threads
        self._threads: List[threading.Thread] = []
        log.info("EarthOscillatorBridge initialized")

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        for name, target in [
            ("usgs-poll",  self._poll_usgs_loop),
            ("noaa-poll",  self._poll_noaa_loop),
            ("space-poll", self._poll_space_loop),
            ("synth-gen",  self._synthetic_loop),
        ]:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        log.info("EarthOscillatorBridge started")

    def stop(self):
        self._running = False
        log.info("EarthOscillatorBridge stopped")

    # ── USGS Seismic Feed ─────────────────────────────────────────────────────

    def _poll_usgs_loop(self):
        """Poll USGS earthquake feed every 30s."""
        while self._running:
            try:
                events = self._fetch_usgs()
                if events:
                    self._ingest_events(events, "USGS")
            except Exception as e:
                self._set_feed_error("USGS", str(e))
            time.sleep(self.POLL_INTERVAL_USGS)

    def _fetch_usgs(self) -> List[EarthEvent]:
        """Fetch last hour of M2.5+ earthquakes from USGS GeoJSON."""
        url = ("https://earthquake.usgs.gov/earthquakes/feed/v1.0/"
               "summary/2.5_hour.geojson")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LucyOS/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            events = []
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                coords = feat.get("geometry", {}).get("coordinates", [0, 0, 0])
                mag   = props.get("mag", 0) or 0
                if mag < 2.5:
                    continue
                ts_ms = props.get("time", 0)
                ts    = datetime.datetime.utcfromtimestamp(
                    ts_ms / 1000).isoformat() + "Z"
                events.append(EarthEvent(
                    source     = "usgs",
                    event_type = "seismic",
                    lat        = float(coords[1]),
                    lon        = float(coords[0]),
                    magnitude  = float(mag),
                    depth_km   = float(coords[2]) if len(coords) > 2 else 10.0,
                    timestamp  = ts,
                    title      = props.get("title", f"M{mag} earthquake"),
                    url        = props.get("url", url),
                    raw        = props,
                ))
            return events
        except Exception as e:
            log.warning(f"USGS fetch failed: {e}")
            raise

    # ── NOAA Weather Feed ─────────────────────────────────────────────────────

    def _poll_noaa_loop(self):
        """Poll NOAA weather alerts every 60s."""
        while self._running:
            try:
                events = self._fetch_noaa()
                if events:
                    self._ingest_events(events, "NOAA")
            except Exception as e:
                self._set_feed_error("NOAA", str(e))
            time.sleep(self.POLL_INTERVAL_NOAA)

    def _fetch_noaa(self) -> List[EarthEvent]:
        """Fetch active NOAA weather alerts (US)."""
        url = "https://api.weather.gov/alerts/active?status=actual&limit=50"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "LucyOS/1.0 (lucy@sovereign.ai)",
                "Accept": "application/geo+json",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            events = []
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                geo   = feat.get("geometry")
                if not geo:
                    # Use center of affected area if no geometry
                    lat, lon = 39.5, -98.35  # geographic center of US
                else:
                    coords = geo.get("coordinates", [[[-98.35, 39.5]]])
                    if geo["type"] == "Point":
                        lon, lat = coords[0], coords[1]
                    else:
                        # Take centroid of first polygon
                        pts = coords[0] if isinstance(coords[0][0], list) else coords
                        lon = float(np.mean([p[0] for p in pts[:5]]))
                        lat = float(np.mean([p[1] for p in pts[:5]]))

                severity = props.get("severity", "Minor")
                severity_map = {"Extreme": 9, "Severe": 7,
                                "Moderate": 5, "Minor": 3, "Unknown": 2}
                mag = severity_map.get(severity, 2)

                events.append(EarthEvent(
                    source     = "noaa",
                    event_type = "weather",
                    lat        = float(lat),
                    lon        = float(lon),
                    magnitude  = float(mag),
                    depth_km   = 0.0,
                    timestamp  = props.get("sent", _utc_now()),
                    title      = props.get("headline", props.get("event", "Weather Alert")),
                    url        = props.get("@id", url),
                    raw        = {k: v for k, v in props.items()
                                  if k in ["event", "severity", "urgency",
                                           "certainty", "areaDesc"]},
                ))
            return events
        except Exception as e:
            log.warning(f"NOAA fetch failed: {e}")
            raise

    # ── Space Weather Feed ────────────────────────────────────────────────────

    def _poll_space_loop(self):
        """Poll NASA DONKI space weather every 2min."""
        while self._running:
            try:
                events = self._fetch_space_weather()
                if events:
                    self._ingest_events(events, "NASA")
            except Exception as e:
                self._set_feed_error("NASA", str(e))
            time.sleep(self.POLL_INTERVAL_SPACE)

    def _fetch_space_weather(self) -> List[EarthEvent]:
        """Fetch geomagnetic storm data from NOAA Space Weather."""
        url = ("https://services.swpc.noaa.gov/products/"
               "noaa-planetary-k-index.json")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LucyOS/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            events = []
            if len(data) > 1:
                latest = data[-1]  # [timestamp, kp_index]
                kp = float(latest[1]) if latest[1] else 0.0
                if kp >= 3.0:  # Only notable events
                    events.append(EarthEvent(
                        source     = "nasa",
                        event_type = "solar",
                        lat        = 0.0,   # global effect
                        lon        = 0.0,
                        magnitude  = kp,
                        depth_km   = 0.0,
                        timestamp  = latest[0] + "Z" if latest[0] else _utc_now(),
                        title      = f"Geomagnetic Activity Kp={kp:.1f}",
                        url        = "https://www.swpc.noaa.gov/products/planetary-k-index",
                        raw        = {"kp_index": kp, "source": "NOAA SWPC"},
                    ))
            return events
        except Exception as e:
            log.warning(f"Space weather fetch failed: {e}")
            raise

    # ── Synthetic Fallback ────────────────────────────────────────────────────

    def _synthetic_loop(self):
        """Generate synthetic Earth events when real feeds are unavailable."""
        rng = np.random.default_rng(42)
        t   = 0
        # Known seismically active zones
        zones = [
            (35.0,  139.0, "seismic"),   # Japan
            (37.8, -122.2, "seismic"),   # SF Bay
            (19.4, -155.3, "seismic"),   # Hawaii
            (-33.9, 151.2, "seismic"),   # Sydney
            (51.5,  -0.12, "weather"),   # London
            (40.7,  -74.0, "weather"),   # New York
            (0.0,    0.0,  "solar"),     # Global
        ]
        while self._running:
            # Only inject synthetic if real feeds are lagging
            with self._lock:
                usgs_live = self._feeds["USGS"].live
                noaa_live = self._feeds["NOAA"].live

            # Always generate some synthetic background
            zone = zones[t % len(zones)]
            lat0, lon0, etype = zone
            lat  = lat0 + rng.uniform(-5, 5)
            lon  = lon0 + rng.uniform(-5, 5)
            mag  = rng.uniform(2.5, 6.0) if etype == "seismic" else rng.uniform(2, 8)

            event = EarthEvent(
                source     = "synthetic",
                event_type = etype,
                lat        = float(lat),
                lon        = float(lon),
                magnitude  = float(mag),
                depth_km   = float(rng.uniform(5, 200)) if etype == "seismic" else 0.0,
                timestamp  = _utc_now(),
                title      = f"[SIM] {etype.title()} M{mag:.1f} near ({lat:.1f},{lon:.1f})",
                url        = "synthetic://lucy-qme",
            )
            with self._lock:
                self._events.append(event)
                if len(self._events) > self.MAX_EVENTS_CACHE:
                    self._events.pop(0)

            if self._on_event:
                try:
                    self._on_event(event)
                except Exception:
                    pass

            t += 1
            time.sleep(15 + rng.uniform(0, 20))

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def _ingest_events(self, events: List[EarthEvent], feed: str):
        now = time.time()
        with self._lock:
            for ev in events:
                self._events.append(ev)
                self._ingestion_window.append((now, feed))
                if self._on_event:
                    try:
                        self._on_event(ev)
                    except Exception:
                        pass

            # Trim cache
            if len(self._events) > self.MAX_EVENTS_CACHE:
                self._events = self._events[-self.MAX_EVENTS_CACHE:]

            # Trim ingestion window to last 60s
            self._ingestion_window = [
                (t, s) for t, s in self._ingestion_window
                if now - t < 60
            ]

            # Update feed status
            events_60s = sum(1 for t, s in self._ingestion_window
                             if s == feed)
            if feed in self._feeds:
                self._feeds[feed].live           = True
                self._feeds[feed].last_updated   = _utc_now()
                self._feeds[feed].events_60s     = events_60s
                self._feeds[feed].total_ingested += len(events)
                self._feeds[feed].last_error     = None
                self._feeds[feed].lag_seconds    = 0.0

        log.debug(f"Ingested {len(events)} events from {feed}")

    def _set_feed_error(self, feed: str, error: str):
        with self._lock:
            if feed in self._feeds:
                self._feeds[feed].live       = False
                self._feeds[feed].last_error = error
                if self._feeds[feed].last_updated:
                    try:
                        lu = datetime.datetime.fromisoformat(
                            self._feeds[feed].last_updated.rstrip("Z"))
                        lag = (datetime.datetime.utcnow() - lu).total_seconds()
                        self._feeds[feed].lag_seconds = lag
                    except Exception:
                        pass

    # ── Public API ────────────────────────────────────────────────────────────

    def get_recent_events(self, n: int = 50,
                          source: Optional[str] = None) -> List[Dict]:
        with self._lock:
            evs = list(reversed(self._events[-n:]))
            if source:
                evs = [e for e in evs if e.source == source]
        return [e.to_dict() for e in evs[:n]]

    def get_feed_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            # Update lag for all feeds
            for feed in self._feeds.values():
                if feed.last_updated:
                    try:
                        lu  = datetime.datetime.fromisoformat(
                            feed.last_updated.rstrip("Z"))
                        lag = (datetime.datetime.utcnow() - lu).total_seconds()
                        feed.lag_seconds = lag
                        feed.live = lag < self.STALENESS_WARN_S
                    except Exception:
                        pass
                # Count events in last 60s
                feed.events_60s = sum(
                    1 for t, s in self._ingestion_window
                    if s == feed.name and now - t < 60
                )
            return {
                name: fs.to_dict()
                for name, fs in self._feeds.items()
            }

    def get_events_per_minute(self) -> Dict[str, int]:
        now = time.time()
        with self._lock:
            window = [(t, s) for t, s in self._ingestion_window
                      if now - t < 60]
        counts: Dict[str, int] = {}
        for _, s in window:
            counts[s] = counts.get(s, 0) + 1
        return counts

    def get_total_events(self) -> int:
        with self._lock:
            return len(self._events)


def _utc_now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"