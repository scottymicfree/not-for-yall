"""
Lucy OS — Quantum Music Engine: Stability Function
====================================================
This is Lucy's "ear" for harmony.

def stability_score(state):
    return (
        -energy_variance(state)
        -entropy_change(state)
        -particle_loss_rate(state)
    )

Lucy maximizes this score.

Extended with:
  - Phase coherence bonus  (sync = harmony)
  - Attractor density      (more attractors = more stable)
  - Trend analysis         (is the field improving or degrading?)
"""

import numpy as np
import collections
import logging
from typing import List, Optional

log = logging.getLogger("lucy.qme.stability")


class StabilityFunction:
    """
    Computes the stability score for the oscillator field.

    Score range: [-1.0, 1.0]
      1.0 = perfect harmony (all oscillators in sync, stable energy)
      0.0 = neutral
     -1.0 = complete chaos / collapse

    Weights (tunable):
      w_variance   = 0.30  — penalize energy variance
      w_entropy    = 0.20  — penalize high entropy
      w_loss       = 0.25  — penalize particle (oscillator) death
      w_coherence  = 0.25  — reward phase synchronization
    """

    W_VARIANCE  = 0.30
    W_ENTROPY   = 0.20
    W_LOSS      = 0.25
    W_COHERENCE = 0.25

    # Normalization bounds (empirically set for 200-oscillator system)
    MAX_VARIANCE  = 0.25   # max expected energy variance
    MAX_ENTROPY   = 5.30   # log(200) ≈ 5.30 — max entropy for 200 nodes
    MAX_LOSS      = 1.0    # 100% particle loss

    @classmethod
    def compute(cls,
                energy_variance:  float,
                entropy_change:   float,
                particle_loss:    float,
                phase_coherence:  float = 0.5) -> float:
        """
        Core stability score.

        Parameters
        ----------
        energy_variance : float  — variance of oscillator energies [0, ∞)
        entropy_change  : float  — Shannon entropy of energy distribution
        particle_loss   : float  — fraction of near-dead oscillators [0, 1]
        phase_coherence : float  — Kuramoto order parameter [0, 1]

        Returns
        -------
        float — stability score in [-1.0, 1.0]
        """
        # Normalize to [0, 1] (penalty terms)
        norm_var  = min(energy_variance / cls.MAX_VARIANCE,  1.0)
        norm_ent  = min(entropy_change  / cls.MAX_ENTROPY,   1.0)
        norm_loss = min(particle_loss   / cls.MAX_LOSS,      1.0)

        # Coherence is already [0, 1] — reward (not penalty)
        coherence_reward = phase_coherence  # 1.0 = perfect sync

        # Weighted sum: penalties subtract, coherence adds
        raw = (
            - cls.W_VARIANCE  * norm_var
            - cls.W_ENTROPY   * norm_ent
            - cls.W_LOSS      * norm_loss
            + cls.W_COHERENCE * coherence_reward
        )

        # Rescale from [-0.75, 0.25] to [-1.0, 1.0]
        score = (raw + 0.75) / 1.0 - 0.75
        return float(np.clip(score, -1.0, 1.0))

    @classmethod
    def energy_variance(cls, energies: np.ndarray) -> float:
        """Variance of oscillator energy distribution."""
        return float(np.var(energies))

    @classmethod
    def entropy_change(cls, energies: np.ndarray) -> float:
        """Shannon entropy of normalized energy distribution."""
        e_norm = energies / (energies.sum() + 1e-10)
        return float(-np.sum(e_norm * np.log(e_norm + 1e-10)))

    @classmethod
    def particle_loss_rate(cls, energies: np.ndarray,
                           threshold: float = 0.05) -> float:
        """Fraction of oscillators below energy threshold (near-dead)."""
        return float(np.mean(energies < threshold))

    @classmethod
    def phase_coherence(cls, phases: np.ndarray) -> float:
        """
        Kuramoto order parameter: |⟨e^{iφ}⟩|
        0 = complete incoherence, 1 = perfect synchrony
        """
        return float(np.abs(np.mean(np.exp(1j * phases))))

    @classmethod
    def from_arrays(cls,
                    energies: np.ndarray,
                    phases:   np.ndarray) -> float:
        """Compute full stability score from raw arrays."""
        return cls.compute(
            energy_variance = cls.energy_variance(energies),
            entropy_change  = cls.entropy_change(energies),
            particle_loss   = cls.particle_loss_rate(energies),
            phase_coherence = cls.phase_coherence(phases),
        )


class StabilityTracker:
    """
    Tracks stability score history and detects trends.

    Features:
      - Rolling window of last N scores
      - Trend detection (improving / degrading / stable)
      - Anomaly detection (sudden drops)
      - Regime classification (chaos / transition / harmony)
    """

    WINDOW = 100  # rolling window size

    REGIMES = {
        "harmony":    (0.4,  1.0),
        "transition": (0.0,  0.4),
        "instability":(-0.4, 0.0),
        "chaos":      (-1.0,-0.4),
    }

    def __init__(self):
        self._history:    collections.deque = collections.deque(maxlen=self.WINDOW)
        self._timestamps: collections.deque = collections.deque(maxlen=self.WINDOW)
        self._best_score  = -1.0
        self._worst_score =  1.0
        self._alerts:     List[dict]        = []

    def record(self, score: float, t: float):
        """Record a new stability score."""
        self._history.append(score)
        self._timestamps.append(t)

        if score > self._best_score:
            self._best_score = score
        if score < self._worst_score:
            self._worst_score = score

        # Anomaly: sudden drop > 0.3 in one step
        if len(self._history) >= 2:
            delta = score - list(self._history)[-2]
            if delta < -0.3:
                self._alerts.append({
                    "t": t, "type": "sudden_drop",
                    "delta": round(delta, 4),
                    "score": round(score, 4),
                })
                log.warning(f"[QME] Stability sudden drop: {delta:.3f} → {score:.3f}")

    def get_trend(self) -> str:
        """
        Returns 'improving', 'degrading', or 'stable'
        based on linear regression over last 20 scores.
        """
        if len(self._history) < 10:
            return "unknown"
        recent = list(self._history)[-20:]
        x = np.arange(len(recent))
        slope = np.polyfit(x, recent, 1)[0]
        if slope > 0.002:
            return "improving"
        elif slope < -0.002:
            return "degrading"
        return "stable"

    def get_regime(self) -> str:
        """Classify current regime based on latest score."""
        if not self._history:
            return "unknown"
        score = self._history[-1]
        for regime, (lo, hi) in self.REGIMES.items():
            if lo <= score <= hi:
                return regime
        return "unknown"

    def get_rolling_mean(self) -> float:
        if not self._history:
            return 0.0
        return float(np.mean(self._history))

    def get_rolling_std(self) -> float:
        if len(self._history) < 2:
            return 0.0
        return float(np.std(self._history))

    def get_summary(self) -> dict:
        return {
            "current":      round(self._history[-1], 4) if self._history else 0.0,
            "rolling_mean": round(self.get_rolling_mean(), 4),
            "rolling_std":  round(self.get_rolling_std(), 4),
            "trend":        self.get_trend(),
            "regime":       self.get_regime(),
            "best_ever":    round(self._best_score, 4),
            "worst_ever":   round(self._worst_score, 4),
            "n_alerts":     len(self._alerts),
            "recent_alerts": self._alerts[-5:],
            "history":      list(self._history)[-50:],
        }

    def pop_alerts(self) -> List[dict]:
        alerts = list(self._alerts)
        self._alerts.clear()
        return alerts