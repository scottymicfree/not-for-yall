"""
Lucy OS v5 — Master FastAPI Backend
Wires ALL routers into a single application with CORS, lifespan, and health.
"""

from __future__ import annotations
import asyncio
import logging
import time
import sys
import os
from contextlib import asynccontextmanager

# Ensure lucy-os root is on sys.path so all submodules (ame, lte, etc.) resolve
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("lucy_os.backend")

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot sequence on startup; graceful shutdown on exit."""
    log.info("═" * 60)
    log.info("  Lucy OS v5 — Initialising…")
    log.info("═" * 60)

    # ── Boot AME Lucy Core
    try:
        from ame.lucy_core import lucy_core
        await lucy_core.boot()
        log.info("✓ AME Lucy Core online")
    except Exception as e:
        log.warning("✗ AME Lucy Core boot error: %s", e)

    # ── Register built-in plugins
    try:
        from ame.plugins import _register_builtins
        await _register_builtins()
        log.info("✓ Built-in plugins registered")
    except Exception as e:
        log.warning("✗ Plugin registration error: %s", e)

    # ── Inject synthetic telemetry seed for dashboard demo
    try:
        from lte.telemetry import telemetry
        _seed_telemetry(telemetry)
        log.info("✓ Telemetry seeded")
    except Exception as e:
        log.warning("✗ Telemetry seed error: %s", e)

    log.info("═" * 60)
    log.info("  Lucy OS v5 — ONLINE")
    log.info("═" * 60)

    yield

    # ── Shutdown
    log.info("Lucy OS v5 shutting down…")
    try:
        from ame.lucy_core import lucy_core
        await lucy_core.shutdown()
    except Exception:
        pass


def _seed_telemetry(tel) -> None:
    """Push initial telemetry readings so dashboard tiles show non-zero values."""
    import random
    rng = random.Random(42)
    seeds = {
        ("emma_mesh",  "latency_ms"):           lambda: rng.uniform(80, 200),
        ("emma_mesh",  "avg_confidence"):        lambda: rng.uniform(0.72, 0.90),
        ("emma_mesh",  "block_rate"):            lambda: rng.uniform(0.01, 0.05),
        ("emma_mesh",  "strong_consensus_rate"): lambda: rng.uniform(0.70, 0.95),
        ("lucy_prime", "lte_avg"):               lambda: rng.uniform(65, 88),
        ("lucy_prime", "synthesis_ms"):          lambda: rng.uniform(30, 120),
        ("swarm",      "agent_load"):            lambda: rng.uniform(0.20, 0.60),
        ("swarm",      "queue_depth"):           lambda: rng.uniform(0, 10),
        ("swarm",      "timeout_rate"):          lambda: rng.uniform(0.0, 0.03),
        ("fivem",      "bridge_latency_ms"):     lambda: rng.uniform(40, 180),
        ("fivem",      "player_count"):          lambda: rng.randint(5, 48),
        ("fivem",      "error_rate"):            lambda: rng.uniform(0.0, 0.02),
        ("earth",      "query_rate"):            lambda: rng.uniform(1, 10),
        ("earth",      "freshness_score"):       lambda: rng.uniform(0.85, 0.99),
        ("bioyth0n",   "exec_count"):            lambda: rng.randint(0, 20),
        ("bioyth0n",   "gate_pass_rate"):        lambda: rng.uniform(0.90, 1.0),
        ("safety",     "block_events"):          lambda: rng.randint(0, 3),
        ("lte",        "lte_score"):             lambda: rng.uniform(60, 92),
    }
    for (sub, met), fn in seeds.items():
        for _ in range(5):
            tel.push(sub, met, fn())


# ── App Factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Lucy OS v5",
        description="Autonomous AGI/OS — 137-node cognitive mesh",
        version="5.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers
    _mount_routers(app)

    # ── Static files — serve dashboard
    import os
    dashboard_dir = os.path.join(os.path.dirname(__file__), "mesh")
    if os.path.isdir(dashboard_dir):
        app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True),
                  name="dashboard")

    # ── Root
    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": "Lucy OS v5", "status": "online",
                "version": "5.0.0", "timestamp": time.time()}

    # ── Global health
    @app.get("/health", tags=["system"])
    async def health():
        return {
            "status":    "online",
            "version":   "5.0.0",
            "timestamp": time.time(),
        }

    return app


def _mount_routers(app: FastAPI) -> None:
    """Mount each sub-router with graceful fallback on import error."""

    def _try_mount(module_path: str, attr: str) -> None:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            router = getattr(mod, attr)
            app.include_router(router)
            log.info("  ✓ Router mounted: %s", module_path)
        except Exception as e:
            log.warning("  ✗ Router skipped (%s): %s", module_path, e)

    routers = [
        ("chat.api",          "router"),
        ("unr5.api",          "router"),
        ("bridges.fivem_api", "router"),
        ("lucidity.api",      "router"),
        ("lte.api",           "router"),
        ("ame.api",           "router"),
        ("dashboard.earth_api", "router"),
    ]
    for mod_path, attr in routers:
        _try_mount(mod_path, attr)


# ── Entry Point ────────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )