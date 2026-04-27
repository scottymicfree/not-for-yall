"""
Lucy OS — Quantum Music Engine: State Engine
=============================================
Represents the system as a tensor field of oscillators.

Metaphor → Math mapping:
  "All notes at once"  → superposition of 200 oscillators
  "Stable note"        → attractor state (low energy variance)
  "Dissonance"         → high phase incoherence / energy drift

Each oscillator has:
  - frequency (ω)   : how fast it evolves
  - phase (φ)       : current position in its cycle
  - energy (E)      : amplitude squared
  - damping (γ)     : natural decay rate
  - coupling (k)    : strength of neighbor interaction
"""

import numpy as np
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import threading
import logging

log = logging.getLogger("lucy.qme.state")


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class Oscillator:
    """Single quantum oscillator node."""
    id:        int
    frequency: float        # Hz  (0.1 – 10.0)
    phase:     float        # radians [0, 2π)
    energy:    float        # normalized [0, 1]
    damping:   float        # decay per step (0.001 – 0.05)
    coupling:  float        # neighbor coupling strength
    group:     str          # 'earth', 'plasma', 'free'
    x:         float = 0.0  # spatial position
    y:         float = 0.0
    history:   List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":        self.id,
            "frequency": round(self.frequency, 4),
            "phase":     round(self.phase % (2 * np.pi), 4),
            "energy":    round(self.energy, 4),
            "damping":   round(self.damping, 4),
            "coupling":  round(self.coupling, 4),
            "group":     self.group,
            "x":         round(self.x, 3),
            "y":         round(self.y, 3),
        }


@dataclass
class FieldState:
    """Snapshot of the full oscillator field at time t."""
    t:              float               # simulation time
    oscillators:    List[Dict]          # serialized oscillator dicts
    mean_energy:    float
    energy_variance: float
    mean_phase_coherence: float         # 0=chaos, 1=perfect sync
    entropy:        float
    stability_score: float
    attractor_count: int                # # of stable attractors detected
    n_oscillators:  int
    timestamp:      str                 # UTC wall-clock

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t":                    round(self.t, 4),
            "oscillators":          self.oscillators,
            "mean_energy":          round(self.mean_energy, 4),
            "energy_variance":      round(self.energy_variance, 6),
            "mean_phase_coherence": round(self.mean_phase_coherence, 4),
            "entropy":              round(self.entropy, 4),
            "stability_score":      round(self.stability_score, 4),
            "attractor_count":      self.attractor_count,
            "n_oscillators":        self.n_oscillators,
            "timestamp":            self.timestamp,
        }


# ─── Oscillator Field ─────────────────────────────────────────────────────────

class OscillatorField:
    """
    200-oscillator tensor field.

    Groups:
      - 'earth'  (80):  low-frequency (0.1–1.0 Hz) — geophysical rhythms
      - 'plasma' (80):  mid-frequency (1.0–5.0 Hz) — plasma-like dynamics
      - 'free'   (40):  high-frequency (5.0–10.0 Hz) — free resonators

    Layout: 20×10 spatial grid
    """

    N_TOTAL  = 200
    N_EARTH  = 80
    N_PLASMA = 80
    N_FREE   = 40
    GRID_W   = 20
    GRID_H   = 10
    DT       = 0.05         # simulation timestep (50ms real → 1s sim)

    def __init__(self, seed: int = 42):
        self._rng  = np.random.default_rng(seed)
        self._t    = 0.0
        self._step = 0
        self._lock = threading.Lock()
        self._oscillators: List[Oscillator] = []
        self._noise_level  = 0.02   # external disturbance amplitude
        self._external_disturbances: List[Dict] = []  # from Earth bridge
        self._init_oscillators()
        log.info(f"OscillatorField ready | N={self.N_TOTAL} | groups=earth/plasma/free")

    # ── Init ──────────────────────────────────────────────────────────────────

    def _init_oscillators(self):
        """Seed 200 oscillators across the spatial grid."""
        positions = [(i % self.GRID_W, i // self.GRID_W)
                     for i in range(self.N_TOTAL)]

        groups = (
            ["earth"]  * self.N_EARTH +
            ["plasma"] * self.N_PLASMA +
            ["free"]   * self.N_FREE
        )
        freq_ranges = {
            "earth":  (0.1, 1.0),
            "plasma": (1.0, 5.0),
            "free":   (5.0, 10.0),
        }

        for i in range(self.N_TOTAL):
            g  = groups[i]
            fl, fh = freq_ranges[g]
            gx, gy = positions[i]
            osc = Oscillator(
                id        = i,
                frequency = float(self._rng.uniform(fl, fh)),
                phase     = float(self._rng.uniform(0, 2 * np.pi)),
                energy    = float(self._rng.uniform(0.3, 0.9)),
                damping   = float(self._rng.uniform(0.005, 0.02)),
                coupling  = float(self._rng.uniform(0.01, 0.08)),
                group     = g,
                x         = gx / self.GRID_W,
                y         = gy / self.GRID_H,
            )
            self._oscillators.append(osc)

    # ── Step ──────────────────────────────────────────────────────────────────

    def step(self, action: Optional[np.ndarray] = None) -> "FieldState":
        """
        Advance the field by one timestep DT.

        action: shape (N_TOTAL, 3) — [dω, dφ, dE] nudges per oscillator
                or None (free evolution)
        """
        with self._lock:
            oscs = self._oscillators
            N    = len(oscs)
            dt   = self.DT

            # Extract arrays
            omega = np.array([o.frequency for o in oscs])
            phi   = np.array([o.phase     for o in oscs])
            E     = np.array([o.energy    for o in oscs])
            damp  = np.array([o.damping   for o in oscs])
            coup  = np.array([o.coupling  for o in oscs])

            # ── Coupling: Kuramoto-style phase sync ───────────────────────
            # Each oscillator is pulled toward neighbors' phases
            # (nearest 4 on the grid)
            coupling_force = np.zeros(N)
            for i, o in enumerate(oscs):
                neighbors = self._get_neighbor_indices(i)
                if neighbors:
                    phase_diffs = np.sin(phi[neighbors] - phi[i])
                    coupling_force[i] = coup[i] * np.mean(phase_diffs)

            # ── External disturbances (from Earth bridge / HAL alerts) ────
            disturbance = np.zeros(N)
            for d in self._external_disturbances:
                # Apply to oscillators in spatial region
                cx, cy = d.get("x", 0.5), d.get("y", 0.5)
                radius  = d.get("radius", 0.3)
                amp     = d.get("amplitude", 0.1)
                for i, o in enumerate(oscs):
                    dist = np.sqrt((o.x - cx)**2 + (o.y - cy)**2)
                    if dist < radius:
                        disturbance[i] += amp * (1 - dist / radius)
            self._external_disturbances.clear()

            # ── Noise injection ───────────────────────────────────────────
            noise = self._rng.normal(0, self._noise_level, N)

            # ── Action nudges ────────────────────────────────────────────
            d_omega = np.zeros(N)
            d_phi   = np.zeros(N)
            d_E     = np.zeros(N)
            if action is not None and action.shape == (N, 3):
                d_omega = np.clip(action[:, 0], -0.5, 0.5)
                d_phi   = np.clip(action[:, 1], -0.3, 0.3)
                d_E     = np.clip(action[:, 2], -0.1, 0.1)

            # ── Equations of motion ───────────────────────────────────────
            # Phase: φ(t+dt) = φ(t) + ω·dt + coupling + noise + disturbance
            new_phi = phi + (omega + d_omega) * dt + coupling_force * dt \
                      + noise + disturbance + d_phi

            # Energy: E decays + coupling exchange + external energy input
            energy_exchange = np.zeros(N)
            for i, o in enumerate(oscs):
                neighbors = self._get_neighbor_indices(i)
                if neighbors:
                    energy_exchange[i] = coup[i] * 0.1 * \
                                         (np.mean(E[neighbors]) - E[i])

            new_E = E * (1 - damp * dt) + energy_exchange * dt + \
                    np.abs(disturbance) * 0.5 + d_E
            new_E = np.clip(new_E, 0.0, 1.0)

            # Frequency drift (slow)
            new_omega = omega + d_omega * 0.1 + \
                        self._rng.normal(0, 0.001, N)
            new_omega = np.clip(new_omega, 0.01, 12.0)

            # ── Update oscillators ────────────────────────────────────────
            for i, o in enumerate(oscs):
                o.phase     = float(new_phi[i] % (2 * np.pi))
                o.energy    = float(new_E[i])
                o.frequency = float(new_omega[i])
                o.history.append(float(new_E[i]))
                if len(o.history) > 200:
                    o.history.pop(0)

            self._t    += dt
            self._step += 1

            return self._compute_state()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_neighbor_indices(self, i: int) -> List[int]:
        """Return indices of 4-connected grid neighbors."""
        gx = i % self.GRID_W
        gy = i // self.GRID_W
        neighbors = []
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = gx + dx, gy + dy
            if 0 <= nx < self.GRID_W and 0 <= ny < self.GRID_H:
                neighbors.append(ny * self.GRID_W + nx)
        return neighbors

    def _compute_state(self) -> FieldState:
        """Compute full field state metrics."""
        oscs  = self._oscillators
        E     = np.array([o.energy for o in oscs])
        phi   = np.array([o.phase  for o in oscs])

        mean_E   = float(np.mean(E))
        var_E    = float(np.var(E))

        # Phase coherence (order parameter |⟨e^{iφ}⟩|)
        coherence = float(np.abs(np.mean(np.exp(1j * phi))))

        # Shannon entropy of energy distribution
        E_norm = E / (E.sum() + 1e-10)
        entropy = float(-np.sum(E_norm * np.log(E_norm + 1e-10)))

        # Attractor detection: oscillators with low variance over last 20 steps
        attractor_count = 0
        for o in oscs:
            if len(o.history) >= 20:
                if np.std(o.history[-20:]) < 0.02:
                    attractor_count += 1

        # Stability score (higher = better)
        from .stability import StabilityFunction
        stab = StabilityFunction.compute(
            energy_variance  = var_E,
            entropy_change   = entropy,
            particle_loss    = float(np.mean(E < 0.05)),  # % near-dead
            phase_coherence  = coherence,
        )

        return FieldState(
            t                    = self._t,
            oscillators          = [o.to_dict() for o in oscs],
            mean_energy          = mean_E,
            energy_variance      = var_E,
            mean_phase_coherence = coherence,
            entropy              = entropy,
            stability_score      = stab,
            attractor_count      = attractor_count,
            n_oscillators        = len(oscs),
            timestamp            = _utc_now(),
        )

    def inject_disturbance(self, x: float, y: float,
                           amplitude: float, radius: float = 0.2,
                           source: str = "unknown"):
        """Inject an external disturbance (e.g. from seismic event)."""
        with self._lock:
            self._external_disturbances.append({
                "x": x, "y": y,
                "amplitude": amplitude,
                "radius": radius,
                "source": source,
            })
        log.debug(f"Disturbance injected | source={source} "
                  f"amp={amplitude:.3f} @({x:.2f},{y:.2f})")

    def set_noise_level(self, level: float):
        """Set external noise amplitude (0.0 – 0.5)."""
        self._noise_level = float(np.clip(level, 0.0, 0.5))

    def get_current_state(self) -> FieldState:
        with self._lock:
            return self._compute_state()

    def get_oscillator(self, idx: int) -> Oscillator:
        return self._oscillators[idx]

    @property
    def t(self) -> float:
        return self._t

    @property
    def step_count(self) -> int:
        return self._step


def _utc_now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"