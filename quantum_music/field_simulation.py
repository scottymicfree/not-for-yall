"""
Lucy OS — Quantum Music Engine: Wave Field Simulator
====================================================
Step 3 in the roadmap: Convert oscillators → spatial grid
→ Wave interference patterns → Real "music" field

Uses a 2D wave equation on a discrete grid:
  ∂²u/∂t² = c² ∇²u - γ ∂u/∂t + f(x,y,t)

where:
  u(x,y,t) = wave amplitude
  c         = wave speed (tuned by stability)
  γ         = damping coefficient
  f(x,y,t)  = forcing from oscillators

PhysicsNeMo-inspired: uses FNO-style spatial convolution for
wave propagation (pure numpy, no GPU required in SIM mode).
"""

import numpy as np
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

log = logging.getLogger("lucy.qme.field")


@dataclass
class WaveSnapshot:
    """Snapshot of the 2D wave field."""
    t:           float
    u:           np.ndarray    # (H, W) amplitude
    u_dot:       np.ndarray    # (H, W) velocity
    energy_map:  np.ndarray    # (H, W) local energy density
    interference_map: np.ndarray  # (H, W) constructive/destructive
    timestamp:   str

    def to_dict(self, downsample: int = 2) -> Dict[str, Any]:
        """Serialize for JSON (downsampled for bandwidth)."""
        u_ds = self.u[::downsample, ::downsample]
        e_ds = self.energy_map[::downsample, ::downsample]
        return {
            "t":         round(self.t, 4),
            "timestamp": self.timestamp,
            "shape":     list(u_ds.shape),
            "u":         u_ds.round(4).tolist(),
            "energy":    e_ds.round(4).tolist(),
            "max_amplitude":   round(float(np.max(np.abs(self.u))), 4),
            "total_energy":    round(float(np.sum(self.energy_map)), 4),
            "interference_pct": round(float(
                np.mean(self.interference_map > 0.1)), 4),
        }


class WaveFieldSimulator:
    """
    2D wave field driven by oscillators.

    Grid: 64×32 (matches GRID_W×GRID_H × 3.2 upscale)
    Each oscillator acts as a point source at its (x,y) grid position.

    The wave field shows:
      - Constructive interference → bright spots (harmony)
      - Destructive interference  → nodes (cancellation)
      - Standing waves            → stable patterns (attractors)
      - Traveling waves           → active propagation
    """

    GRID_H = 32
    GRID_W = 64
    DT     = 0.02      # wave timestep
    C      = 2.0       # base wave speed
    GAMMA  = 0.05      # damping
    MAX_AMP = 5.0      # clip amplitude

    def __init__(self):
        self._t    = 0.0
        self._u    = np.zeros((self.GRID_H, self.GRID_W))   # amplitude
        self._u_prev = np.zeros_like(self._u)               # previous step
        self._u_dot  = np.zeros_like(self._u)               # velocity
        self._sources: List[Dict] = []   # active point sources

        # Precompute Laplacian kernel
        self._lap_kernel = np.array([
            [0,  1, 0],
            [1, -4, 1],
            [0,  1, 0],
        ], dtype=float)

        log.info(f"WaveFieldSimulator ready | grid={self.GRID_W}×{self.GRID_H}")

    def update_sources(self, oscillators: List[Dict]):
        """
        Sync oscillators → point sources on the wave grid.
        Each oscillator's energy × sin(phase) drives its grid cell.
        """
        self._sources.clear()
        for o in oscillators:
            gx = int(o["x"] * (self.GRID_W - 1))
            gy = int(o["y"] * (self.GRID_H - 1))
            gx = np.clip(gx, 0, self.GRID_W - 1)
            gy = np.clip(gy, 0, self.GRID_H - 1)
            self._sources.append({
                "gx":       gx,
                "gy":       gy,
                "amplitude": o["energy"] * 0.5,
                "phase":    o["phase"],
                "frequency": o["frequency"] * 0.1,  # scale down for grid
            })

    def step(self, dt: Optional[float] = None) -> WaveSnapshot:
        """Advance wave equation by one timestep."""
        dt  = dt or self.DT
        u   = self._u
        u_p = self._u_prev
        H, W = self.GRID_H, self.GRID_W

        # ── Laplacian (finite difference) ────────────────────────────────
        lap = np.zeros_like(u)
        lap[1:-1, 1:-1] = (
            u[:-2, 1:-1] + u[2:, 1:-1] +
            u[1:-1, :-2] + u[1:-1, 2:] -
            4 * u[1:-1, 1:-1]
        )

        # ── Wave equation: u_new = 2u - u_prev + c²dt²·lap - γ·dt·(u-u_prev) ──
        c2  = self.C ** 2
        u_new = (2 * u - u_p +
                 c2 * dt**2 * lap -
                 self.GAMMA * dt * (u - u_p))

        # ── Apply point sources ───────────────────────────────────────────
        forcing = np.zeros_like(u)
        for src in self._sources:
            gx, gy = src["gx"], src["gy"]
            amp    = src["amplitude"]
            phase  = src["phase"]
            freq   = src["frequency"]
            # Gaussian spread around source point
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    nx, ny = gx + dx, gy + dy
                    if 0 <= nx < W and 0 <= ny < H:
                        w = np.exp(-(dx**2 + dy**2) / 2.0)
                        forcing[ny, nx] += amp * w * \
                                           np.sin(phase + freq * self._t * 2 * np.pi)

        u_new += forcing * dt**2

        # ── Absorbing boundary (PML-lite) ─────────────────────────────────
        damp = np.ones((H, W))
        for i in range(4):
            f = 1.0 - (4 - i) * 0.08
            damp[i,   :] *= f
            damp[H-1-i, :] *= f
            damp[:, i]   *= f
            damp[:, W-1-i] *= f
        u_new *= damp

        # ── Clip ──────────────────────────────────────────────────────────
        u_new = np.clip(u_new, -self.MAX_AMP, self.MAX_AMP)

        # ── Update state ──────────────────────────────────────────────────
        self._u_dot  = (u_new - u) / dt
        self._u_prev = u.copy()
        self._u      = u_new
        self._t     += dt

        # ── Compute derived fields ────────────────────────────────────────
        energy_map       = 0.5 * (self._u_dot**2 + c2 * lap**2)
        interference_map = np.abs(u_new) - np.abs(u_new - forcing * dt**2)

        return WaveSnapshot(
            t                = self._t,
            u                = u_new.copy(),
            u_dot            = self._u_dot.copy(),
            energy_map       = energy_map,
            interference_map = interference_map,
            timestamp        = _utc_now(),
        )

    def get_standing_wave_score(self) -> float:
        """
        Detect standing waves (time-averaged amplitude pattern).
        High score = stable patterns (musical harmony).
        """
        if np.max(np.abs(self._u)) < 1e-6:
            return 0.0
        # Standing wave: u·u_prev correlation (high when phase-locked)
        corr = np.corrcoef(self._u.ravel(), self._u_prev.ravel())[0, 1]
        return float(max(0, corr))

    def get_interference_fraction(self) -> Tuple[float, float]:
        """Returns (constructive_fraction, destructive_fraction)."""
        if np.max(np.abs(self._u)) < 1e-6:
            return 0.0, 0.0
        norm = self._u / (np.max(np.abs(self._u)) + 1e-10)
        constructive = float(np.mean(norm > 0.3))
        destructive  = float(np.mean(norm < -0.3))
        return constructive, destructive

    def inject_pulse(self, x: float, y: float, amplitude: float = 1.0):
        """Inject a Gaussian pulse at normalized (x,y) — simulates disturbance."""
        gx = int(x * (self.GRID_W - 1))
        gy = int(y * (self.GRID_H - 1))
        H, W = self.GRID_H, self.GRID_W
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                nx, ny = np.clip(gx + dx, 0, W-1), np.clip(gy + dy, 0, H-1)
                w = np.exp(-(dx**2 + dy**2) / 8.0)
                self._u[ny, nx] += amplitude * w

    def reset(self):
        self._u      = np.zeros((self.GRID_H, self.GRID_W))
        self._u_prev = np.zeros_like(self._u)
        self._u_dot  = np.zeros_like(self._u)
        self._t      = 0.0

    def to_dict(self) -> Dict[str, Any]:
        snap = WaveSnapshot(
            t=self._t,
            u=self._u,
            u_dot=self._u_dot,
            energy_map=0.5 * self._u_dot**2,
            interference_map=np.zeros_like(self._u),
            timestamp=_utc_now(),
        )
        constructive, destructive = self.get_interference_fraction()
        d = snap.to_dict(downsample=1)
        d.update({
            "standing_wave_score": round(self.get_standing_wave_score(), 4),
            "constructive_pct":    round(constructive, 4),
            "destructive_pct":     round(destructive, 4),
        })
        return d


def _utc_now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"