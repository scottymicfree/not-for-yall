"""
LUCY OS — DuckDB Time-Series Storage
=====================================
Persistent storage for all Earth events, QME snapshots, and feed metrics.

Tables:
  earth_events    — USGS / NOAA / NASA / synthetic events
  qme_snapshots   — stability score, regime, coherence, attractor_count per step
  feed_metrics    — per-feed poll results: latency, event_count, status
  annotations     — human-in-the-loop event verifications / overrides
  nl_queries      — natural language query log + parsed result

All times stored as UTC ISO-8601 strings + epoch floats for fast range queries.
"""

import threading
import time
import json
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Optional, Any
from pathlib import Path

try:
    import duckdb
    _DUCKDB_OK = True
except ImportError:
    _DUCKDB_OK = False

# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS earth_events (
    event_id        VARCHAR PRIMARY KEY,
    ts_utc          VARCHAR NOT NULL,
    ts_epoch        DOUBLE  NOT NULL,
    source          VARCHAR NOT NULL,   -- usgs | noaa | nasa | synthetic
    event_type      VARCHAR NOT NULL,   -- earthquake | weather_alert | kp_storm | synthetic
    latitude        DOUBLE,
    longitude       DOUBLE,
    magnitude       DOUBLE,
    depth_km        DOUBLE,
    location_name   VARCHAR,
    description     VARCHAR,
    raw_json        VARCHAR,
    ingested_at     DOUBLE  NOT NULL,
    qme_injected    BOOLEAN DEFAULT FALSE,
    verified        BOOLEAN DEFAULT FALSE,
    annotation      VARCHAR
);

CREATE TABLE IF NOT EXISTS qme_snapshots (
    snap_id         INTEGER PRIMARY KEY,
    ts_utc          VARCHAR NOT NULL,
    ts_epoch        DOUBLE  NOT NULL,
    stability_score DOUBLE,
    regime          VARCHAR,
    phase_coherence DOUBLE,
    mean_energy     DOUBLE,
    energy_variance DOUBLE,
    entropy         DOUBLE,
    attractor_count INTEGER,
    episode         INTEGER,
    wave_max        DOUBLE,
    wave_standing   DOUBLE
);

CREATE SEQUENCE IF NOT EXISTS qme_snap_seq START 1;

CREATE TABLE IF NOT EXISTS feed_metrics (
    metric_id       INTEGER PRIMARY KEY,
    ts_epoch        DOUBLE  NOT NULL,
    feed_name       VARCHAR NOT NULL,   -- usgs | noaa | nasa | synthetic
    poll_latency_ms DOUBLE,
    events_returned INTEGER,
    status          VARCHAR,            -- ok | error | timeout | stale
    error_msg       VARCHAR
);

CREATE SEQUENCE IF NOT EXISTS feed_metric_seq START 1;

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id   VARCHAR PRIMARY KEY,
    event_id        VARCHAR NOT NULL,
    ts_utc          VARCHAR NOT NULL,
    annotator       VARCHAR DEFAULT 'human',
    action          VARCHAR NOT NULL,   -- verify | override | dismiss | flag
    note            VARCHAR,
    override_mag    DOUBLE,
    override_type   VARCHAR
);

CREATE TABLE IF NOT EXISTS nl_queries (
    query_id        INTEGER PRIMARY KEY,
    ts_utc          VARCHAR NOT NULL,
    raw_query       VARCHAR NOT NULL,
    parsed_filter   VARCHAR,            -- JSON string of extracted filters
    result_count    INTEGER,
    duration_ms     DOUBLE
);

CREATE SEQUENCE IF NOT EXISTS nl_query_seq START 1;
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_earth_ts    ON earth_events(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_earth_src   ON earth_events(source);
CREATE INDEX IF NOT EXISTS idx_earth_mag   ON earth_events(magnitude);
CREATE INDEX IF NOT EXISTS idx_qme_ts      ON qme_snapshots(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_feed_ts     ON feed_metrics(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_feed_name   ON feed_metrics(feed_name);
"""

# ── LucyDuckStore ─────────────────────────────────────────────────────────────

class LucyDuckStore:
    """
    Thread-safe DuckDB wrapper for Lucy OS time-series data.
    Falls back to in-memory lists if duckdb is unavailable.
    """

    def __init__(self, db_path: str = "data/duckdb/lucy_timeseries.db"):
        self._lock = threading.Lock()
        self._path = db_path
        self._available = _DUCKDB_OK

        # In-memory fallback buffers
        self._events_buf: list[dict] = []
        self._qme_buf: list[dict] = []
        self._metrics_buf: list[dict] = []
        self._annotations: dict[str, dict] = {}

        if self._available:
            try:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                self._con = duckdb.connect(db_path)
                self._con.execute(SCHEMA_SQL)
                self._con.execute(INDEXES_SQL)
                self._con.commit()
            except Exception as e:
                print(f"[DuckStore] Init failed, using memory fallback: {e}")
                self._available = False
        else:
            print("[DuckStore] duckdb not installed — using in-memory fallback")

    # ── Earth Events ──────────────────────────────────────────────────────────

    def insert_event(self, event: dict) -> bool:
        """Insert a single Earth event. event must have event_id, source, etc."""
        now = time.time()
        row = {
            "event_id":      event.get("event_id", f"ev_{now:.3f}"),
            "ts_utc":        event.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "ts_epoch":      event.get("ts_epoch", now),
            "source":        event.get("source", "unknown"),
            "event_type":    event.get("event_type", "unknown"),
            "latitude":      event.get("latitude"),
            "longitude":     event.get("longitude"),
            "magnitude":     event.get("magnitude"),
            "depth_km":      event.get("depth_km"),
            "location_name": event.get("location", ""),
            "description":   event.get("description", ""),
            "raw_json":      json.dumps(event.get("raw", {})),
            "ingested_at":   now,
            "qme_injected":  event.get("qme_injected", False),
            "verified":      False,
            "annotation":    None,
        }

        if not self._available:
            with self._lock:
                self._events_buf.append(row)
                # Keep last 10k in memory
                if len(self._events_buf) > 10000:
                    self._events_buf = self._events_buf[-10000:]
            return True

        try:
            with self._lock:
                self._con.execute("""
                    INSERT OR REPLACE INTO earth_events
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, [
                    row["event_id"], row["ts_utc"], row["ts_epoch"],
                    row["source"], row["event_type"],
                    row["latitude"], row["longitude"],
                    row["magnitude"], row["depth_km"],
                    row["location_name"], row["description"],
                    row["raw_json"], row["ingested_at"],
                    row["qme_injected"], row["verified"], row["annotation"],
                ])
                self._con.commit()
            return True
        except Exception as e:
            print(f"[DuckStore] insert_event error: {e}")
            with self._lock:
                self._events_buf.append(row)
            return False

    def get_events(
        self,
        since_epoch: float = 0.0,
        source: Optional[str] = None,
        min_mag: float = 0.0,
        limit: int = 200,
    ) -> list[dict]:
        """Query recent Earth events with optional filters."""
        if not self._available:
            with self._lock:
                rows = [r for r in self._events_buf
                        if r["ts_epoch"] >= since_epoch
                        and (source is None or r["source"] == source)
                        and (r["magnitude"] or 0) >= min_mag]
            return sorted(rows, key=lambda r: r["ts_epoch"], reverse=True)[:limit]

        try:
            conditions = ["ts_epoch >= ?"]
            params: list[Any] = [since_epoch]
            if source:
                conditions.append("source = ?")
                params.append(source)
            if min_mag > 0:
                conditions.append("(magnitude IS NULL OR magnitude >= ?)")
                params.append(min_mag)
            params.append(limit)

            sql = f"""
                SELECT event_id, ts_utc, ts_epoch, source, event_type,
                       latitude, longitude, magnitude, depth_km,
                       location_name, description, ingested_at,
                       qme_injected, verified, annotation
                FROM earth_events
                WHERE {' AND '.join(conditions)}
                ORDER BY ts_epoch DESC
                LIMIT ?
            """
            with self._lock:
                result = self._con.execute(sql, params).fetchall()
            cols = ["event_id","ts_utc","ts_epoch","source","event_type",
                    "latitude","longitude","magnitude","depth_km",
                    "location_name","description","ingested_at",
                    "qme_injected","verified","annotation"]
            return [dict(zip(cols, row)) for row in result]
        except Exception as e:
            print(f"[DuckStore] get_events error: {e}")
            return []

    def count_events_since(self, since_epoch: float, source: Optional[str] = None) -> int:
        """Count events since a given epoch — used for events/60s counter."""
        if not self._available:
            with self._lock:
                return sum(1 for r in self._events_buf
                           if r["ts_epoch"] >= since_epoch
                           and (source is None or r["source"] == source))
        try:
            sql = "SELECT COUNT(*) FROM earth_events WHERE ts_epoch >= ?"
            params: list[Any] = [since_epoch]
            if source:
                sql += " AND source = ?"
                params.append(source)
            with self._lock:
                return self._con.execute(sql, params).fetchone()[0]
        except Exception as e:
            print(f"[DuckStore] count error: {e}")
            return 0

    # ── QME Snapshots ─────────────────────────────────────────────────────────

    def insert_qme_snapshot(self, snap: dict) -> bool:
        """Store QME field snapshot."""
        now = time.time()
        row = {
            "ts_utc":          datetime.now(timezone.utc).isoformat(),
            "ts_epoch":        now,
            "stability_score": snap.get("stability_score", 0.0),
            "regime":          snap.get("regime", "unknown"),
            "phase_coherence": snap.get("mean_phase_coherence", 0.0),
            "mean_energy":     snap.get("mean_energy", 0.0),
            "energy_variance": snap.get("energy_variance", 0.0),
            "entropy":         snap.get("entropy", 0.0),
            "attractor_count": snap.get("attractor_count", 0),
            "episode":         snap.get("episode", 0),
            "wave_max":        snap.get("wave_max", 0.0),
            "wave_standing":   snap.get("wave_standing_score", 0.0),
        }

        if not self._available:
            with self._lock:
                self._qme_buf.append(row)
                if len(self._qme_buf) > 5000:
                    self._qme_buf = self._qme_buf[-5000:]
            return True

        try:
            with self._lock:
                self._con.execute("""
                    INSERT INTO qme_snapshots
                    (snap_id, ts_utc, ts_epoch, stability_score, regime,
                     phase_coherence, mean_energy, energy_variance, entropy,
                     attractor_count, episode, wave_max, wave_standing)
                    VALUES (nextval('qme_snap_seq'),?,?,?,?,?,?,?,?,?,?,?,?)
                """, [
                    row["ts_utc"], row["ts_epoch"],
                    row["stability_score"], row["regime"],
                    row["phase_coherence"], row["mean_energy"],
                    row["energy_variance"], row["entropy"],
                    row["attractor_count"], row["episode"],
                    row["wave_max"], row["wave_standing"],
                ])
                self._con.commit()
            return True
        except Exception as e:
            print(f"[DuckStore] insert_qme_snapshot error: {e}")
            with self._lock:
                self._qme_buf.append(row)
            return False

    def get_qme_history(self, since_epoch: float = 0.0, limit: int = 500) -> list[dict]:
        """Return QME stability history for charting."""
        if not self._available:
            with self._lock:
                rows = [r for r in self._qme_buf if r["ts_epoch"] >= since_epoch]
            return sorted(rows, key=lambda r: r["ts_epoch"], reverse=True)[:limit]

        try:
            with self._lock:
                result = self._con.execute("""
                    SELECT ts_utc, ts_epoch, stability_score, regime,
                           phase_coherence, attractor_count, episode
                    FROM qme_snapshots
                    WHERE ts_epoch >= ?
                    ORDER BY ts_epoch DESC LIMIT ?
                """, [since_epoch, limit]).fetchall()
            cols = ["ts_utc","ts_epoch","stability_score","regime",
                    "phase_coherence","attractor_count","episode"]
            return [dict(zip(cols, r)) for r in result]
        except Exception as e:
            print(f"[DuckStore] get_qme_history error: {e}")
            return []

    # ── Feed Metrics ──────────────────────────────────────────────────────────

    def record_feed_metric(self, feed: str, latency_ms: float,
                           count: int, status: str, error: str = "") -> None:
        """Record a feed poll result."""
        now = time.time()
        row = {
            "ts_epoch": now,
            "feed_name": feed,
            "poll_latency_ms": latency_ms,
            "events_returned": count,
            "status": status,
            "error_msg": error,
        }

        if not self._available:
            with self._lock:
                self._metrics_buf.append(row)
                if len(self._metrics_buf) > 2000:
                    self._metrics_buf = self._metrics_buf[-2000:]
            return

        try:
            with self._lock:
                self._con.execute("""
                    INSERT INTO feed_metrics
                    (metric_id, ts_epoch, feed_name, poll_latency_ms,
                     events_returned, status, error_msg)
                    VALUES (nextval('feed_metric_seq'),?,?,?,?,?,?)
                """, [now, feed, latency_ms, count, status, error])
                self._con.commit()
        except Exception as e:
            print(f"[DuckStore] record_feed_metric error: {e}")

    def get_feed_summary(self) -> dict[str, dict]:
        """Return per-feed summary: last_poll_utc, avg_latency, total_events, last_status."""
        if not self._available:
            with self._lock:
                feeds: dict[str, dict] = {}
                for r in self._metrics_buf:
                    fn = r["feed_name"]
                    if fn not in feeds:
                        feeds[fn] = {"count": 0, "total_lat": 0.0,
                                     "total_events": 0, "last_status": "", "last_ts": 0.0}
                    f = feeds[fn]
                    f["count"] += 1
                    f["total_lat"] += r["poll_latency_ms"]
                    f["total_events"] += r["events_returned"]
                    f["last_status"] = r["status"]
                    if r["ts_epoch"] > f["last_ts"]:
                        f["last_ts"] = r["ts_epoch"]
            summary = {}
            for fn, f in feeds.items():
                summary[fn] = {
                    "avg_latency_ms": round(f["total_lat"] / f["count"], 1) if f["count"] else 0,
                    "total_events": f["total_events"],
                    "last_status": f["last_status"],
                    "last_poll_epoch": f["last_ts"],
                }
            return summary

        try:
            with self._lock:
                result = self._con.execute("""
                    SELECT feed_name,
                           AVG(poll_latency_ms) AS avg_lat,
                           SUM(events_returned) AS total_ev,
                           LAST(status ORDER BY ts_epoch) AS last_status,
                           MAX(ts_epoch) AS last_poll
                    FROM feed_metrics
                    GROUP BY feed_name
                """).fetchall()
            return {r[0]: {
                "avg_latency_ms": round(r[1], 1) if r[1] else 0,
                "total_events": r[2] or 0,
                "last_status": r[3] or "unknown",
                "last_poll_epoch": r[4] or 0.0,
            } for r in result}
        except Exception as e:
            print(f"[DuckStore] get_feed_summary error: {e}")
            return {}

    # ── Annotations ───────────────────────────────────────────────────────────

    def annotate_event(self, event_id: str, action: str,
                       note: str = "", annotator: str = "human",
                       override_mag: Optional[float] = None,
                       override_type: Optional[str] = None) -> str:
        """Record a human annotation for an event. Returns annotation_id."""
        import uuid
        ann_id = str(uuid.uuid4())[:12]
        now_iso = datetime.now(timezone.utc).isoformat()

        row = {
            "annotation_id": ann_id,
            "event_id": event_id,
            "ts_utc": now_iso,
            "annotator": annotator,
            "action": action,
            "note": note,
            "override_mag": override_mag,
            "override_type": override_type,
        }
        with self._lock:
            self._annotations[ann_id] = row

        if self._available:
            try:
                with self._lock:
                    self._con.execute("""
                        INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?)
                    """, [ann_id, event_id, now_iso, annotator,
                           action, note, override_mag, override_type])
                    self._con.commit()
            except Exception as e:
                print(f"[DuckStore] annotate error: {e}")

        return ann_id

    # ── NL Query Log ──────────────────────────────────────────────────────────

    def log_nl_query(self, raw: str, parsed: dict,
                     result_count: int, duration_ms: float) -> None:
        """Log a natural language query execution."""
        now = datetime.now(timezone.utc).isoformat()
        if not self._available:
            return
        try:
            with self._lock:
                self._con.execute("""
                    INSERT INTO nl_queries
                    (query_id, ts_utc, raw_query, parsed_filter, result_count, duration_ms)
                    VALUES (nextval('nl_query_seq'),?,?,?,?,?)
                """, [now, raw, json.dumps(parsed), result_count, duration_ms])
                self._con.commit()
        except Exception as e:
            print(f"[DuckStore] log_nl_query error: {e}")

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return overall storage statistics."""
        if not self._available:
            with self._lock:
                return {
                    "backend": "memory",
                    "earth_events": len(self._events_buf),
                    "qme_snapshots": len(self._qme_buf),
                    "feed_metrics": len(self._metrics_buf),
                    "annotations": len(self._annotations),
                }
        try:
            with self._lock:
                ev = self._con.execute("SELECT COUNT(*) FROM earth_events").fetchone()[0]
                qs = self._con.execute("SELECT COUNT(*) FROM qme_snapshots").fetchone()[0]
                fm = self._con.execute("SELECT COUNT(*) FROM feed_metrics").fetchone()[0]
                an = self._con.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
            return {
                "backend": "duckdb",
                "db_path": self._path,
                "earth_events": ev,
                "qme_snapshots": qs,
                "feed_metrics": fm,
                "annotations": an,
            }
        except Exception as e:
            return {"backend": "duckdb", "error": str(e)}

    def close(self) -> None:
        if self._available:
            try:
                self._con.close()
            except Exception:
                pass


# ── Module-level singleton ────────────────────────────────────────────────────

_store: Optional["LucyDuckStore"] = None

def get_store() -> "LucyDuckStore":
    global _store
    if _store is None:
        _store = LucyDuckStore()
    return _store