"""
Lucy OS — Quantum Music Engine: Control Layer
=============================================
The "mixing console" — Lucy nudges the field instead of switching things OFF.

Instead of:  kill oscillator X
Lucy does:   nudge frequency / phase / energy of oscillators

Action space per oscillator: [dω, dφ, dE]
  dω = frequency nudge  (-0.5 to +0.5 Hz)
  dφ = phase nudge      (-0.3 to +0.3 rad)
  dE = energy nudge     (-0.1 to +0.1)

Policy types:
  1. RulePolicy      — hand-crafted rules (fast, interpretable)
  2. GradientPolicy  — gradient ascent on stability score
  3. NeuralPolicy    — small PyTorch MLP (learnable)
"""

import numpy as np
import logging
from enum import Enum, auto
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass

log = logging.getLogger("lucy.qme.control")


# ─── Action Types ─────────────────────────────────────────────────────────────

class ActionType(Enum):
    NUDGE_FREQUENCY = auto()   # shift ω toward group mean
    NUDGE_PHASE     = auto()   # shift φ toward neighbors
    BOOST_ENERGY    = auto()   # inject energy into weak oscillators
    DAMP_ENERGY     = auto()   # drain energy from overactive ones
    SYNC_GROUP      = auto()   # lock group to common frequency
    FULL_NUDGE      = auto()   # all three dimensions simultaneously


@dataclass
class Action:
    """A single control action applied to the field."""
    action_type:    ActionType
    target_indices: List[int]       # which oscillators to affect
    delta_omega:    np.ndarray      # shape (N,)
    delta_phi:      np.ndarray      # shape (N,)
    delta_energy:   np.ndarray      # shape (N,)
    reason:         str = ""

    def to_array(self) -> np.ndarray:
        """Stack into (N, 3) array for OscillatorField.step()."""
        return np.stack([self.delta_omega,
                         self.delta_phi,
                         self.delta_energy], axis=1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type":    self.action_type.name,
            "targets": len(self.target_indices),
            "reason":  self.reason,
            "d_omega_mean": round(float(np.mean(np.abs(self.delta_omega))), 5),
            "d_phi_mean":   round(float(np.mean(np.abs(self.delta_phi))),   5),
            "d_energy_mean":round(float(np.mean(np.abs(self.delta_energy))),5),
        }


# ─── Base Policy ──────────────────────────────────────────────────────────────

class ControlPolicy:
    """Abstract base class for all control policies."""

    N = 200  # number of oscillators

    def select_action(self,
                      oscillators: List[Dict],
                      stability:   float,
                      regime:      str) -> Action:
        raise NotImplementedError

    def _zero_action(self, reason: str = "no_action") -> Action:
        N = self.N
        return Action(
            action_type    = ActionType.FULL_NUDGE,
            target_indices = [],
            delta_omega    = np.zeros(N),
            delta_phi      = np.zeros(N),
            delta_energy   = np.zeros(N),
            reason         = reason,
        )


# ─── Rule-Based Policy ────────────────────────────────────────────────────────

class RulePolicy(ControlPolicy):
    """
    Hand-crafted rules — fast, interpretable, always-on.

    Rules:
      R1: If regime=chaos      → boost low-energy osc + sync phases
      R2: If regime=instability → damp high-energy + nudge toward mean freq
      R3: If regime=transition  → gentle phase nudge toward neighbors
      R4: If regime=harmony     → minimal nudge (preserve attractor)
      R5: Always boost near-dead oscillators (E < 0.05)
    """

    BOOST_THRESHOLD  = 0.05   # oscillators below this get boosted
    DAMP_THRESHOLD   = 0.90   # oscillators above this get damped
    PHASE_SYNC_RATE  = 0.10   # how hard to push phases together
    FREQ_PULL_RATE   = 0.05   # how hard to pull frequencies toward mean
    ENERGY_BOOST     = 0.08
    ENERGY_DAMP      = 0.06

    def select_action(self,
                      oscillators: List[Dict],
                      stability:   float,
                      regime:      str) -> Action:
        N = len(oscillators)
        if N == 0:
            return self._zero_action("empty_field")

        omega = np.array([o["frequency"] for o in oscillators])
        phi   = np.array([o["phase"]     for o in oscillators])
        E     = np.array([o["energy"]    for o in oscillators])

        d_omega = np.zeros(N)
        d_phi   = np.zeros(N)
        d_E     = np.zeros(N)

        mean_omega = np.mean(omega)
        mean_phi   = float(np.angle(np.mean(np.exp(1j * phi))))  # circular mean

        if regime == "chaos":
            # R1: Aggressive re-sync + energy equalization
            d_phi   = self.PHASE_SYNC_RATE * np.sin(mean_phi - phi)
            d_omega = self.FREQ_PULL_RATE  * (mean_omega - omega)
            low_E   = E < 0.3
            d_E[low_E] = self.ENERGY_BOOST
            action_type = ActionType.SYNC_GROUP
            reason = "chaos_resync"

        elif regime == "instability":
            # R2: Damp over-energized, pull frequencies to mean
            d_omega = self.FREQ_PULL_RATE * (mean_omega - omega) * 0.5
            high_E  = E > self.DAMP_THRESHOLD
            d_E[high_E] = -self.ENERGY_DAMP
            low_E   = E < 0.15
            d_E[low_E] = self.ENERGY_BOOST * 0.5
            action_type = ActionType.DAMP_ENERGY
            reason = "instability_damp"

        elif regime == "transition":
            # R3: Gentle phase nudge
            d_phi   = self.PHASE_SYNC_RATE * 0.4 * np.sin(mean_phi - phi)
            action_type = ActionType.NUDGE_PHASE
            reason = "transition_gentle"

        else:  # harmony
            # R4: Preserve — only rescue near-dead
            action_type = ActionType.BOOST_ENERGY
            reason = "harmony_preserve"

        # R5: Always rescue near-dead oscillators
        near_dead = E < self.BOOST_THRESHOLD
        d_E[near_dead] = self.ENERGY_BOOST

        targets = list(np.where(near_dead)[0]) + \
                  list(np.where(E > self.DAMP_THRESHOLD)[0])

        return Action(
            action_type    = action_type,
            target_indices = targets,
            delta_omega    = d_omega,
            delta_phi      = d_phi,
            delta_energy   = d_E,
            reason         = reason,
        )


# ─── Gradient Policy ──────────────────────────────────────────────────────────

class GradientPolicy(ControlPolicy):
    """
    Gradient ascent on stability score.
    Numerically estimates ∂stability/∂action and steps uphill.

    Uses finite differences — no autograd needed.
    """

    STEP_SIZE    = 0.02
    EPSILON      = 0.001   # finite difference step
    MAX_STEPS    = 3       # gradient steps per call

    def __init__(self):
        self._prev_stability = 0.0
        self._prev_action:   Optional[np.ndarray] = None

    def select_action(self,
                      oscillators: List[Dict],
                      stability:   float,
                      regime:      str) -> Action:
        N = len(oscillators)
        E = np.array([o["energy"]    for o in oscillators])
        p = np.array([o["phase"]     for o in oscillators])

        # Gradient estimate: which direction improved stability last time?
        if self._prev_action is not None:
            delta = stability - self._prev_stability
            if delta > 0:
                # Last action helped — amplify slightly
                scale = min(1.0 + delta * 2, 2.0)
                grad_action = self._prev_action * scale
            else:
                # Last action hurt — reverse
                grad_action = -self._prev_action * 0.5
        else:
            # Initial: small random perturbation
            grad_action = np.random.normal(0, self.STEP_SIZE, (N, 3))

        grad_action = np.clip(grad_action * self.STEP_SIZE,
                              [-0.5, -0.3, -0.1],
                              [ 0.5,  0.3,  0.1])

        self._prev_stability = stability
        self._prev_action    = grad_action

        return Action(
            action_type    = ActionType.FULL_NUDGE,
            target_indices = list(range(N)),
            delta_omega    = grad_action[:, 0],
            delta_phi      = grad_action[:, 1],
            delta_energy   = grad_action[:, 2],
            reason         = f"gradient_ascent|stab={stability:.3f}",
        )


# ─── Neural Policy (lightweight MLP) ─────────────────────────────────────────

class NeuralPolicy(ControlPolicy):
    """
    Small MLP policy network.
    Input:  state vector (5 features: mean_E, var_E, coherence, entropy, stability)
    Output: global scale factors for [dω, dφ, dE]

    Trained online via the QuantumMusicLearner.
    No heavy deps — pure numpy forward pass.
    """

    INPUT_DIM  = 7
    HIDDEN_DIM = 32
    OUTPUT_DIM = 3   # [omega_scale, phi_scale, energy_scale]

    def __init__(self, seed: int = 0):
        rng = np.random.default_rng(seed)
        # Xavier init
        s1 = np.sqrt(2.0 / (self.INPUT_DIM + self.HIDDEN_DIM))
        s2 = np.sqrt(2.0 / (self.HIDDEN_DIM + self.OUTPUT_DIM))
        self.W1 = rng.normal(0, s1, (self.INPUT_DIM, self.HIDDEN_DIM))
        self.b1 = np.zeros(self.HIDDEN_DIM)
        self.W2 = rng.normal(0, s2, (self.HIDDEN_DIM, self.OUTPUT_DIM))
        self.b2 = np.zeros(self.OUTPUT_DIM)
        self._rule_policy = RulePolicy()
        self._episode_reward = 0.0
        self._steps = 0

    def _forward(self, x: np.ndarray) -> np.ndarray:
        h = np.tanh(x @ self.W1 + self.b1)
        out = np.tanh(h @ self.W2 + self.b2)  # [-1, 1]
        return out

    def _state_vector(self, oscillators: List[Dict],
                      stability: float) -> np.ndarray:
        E   = np.array([o["energy"]    for o in oscillators])
        phi = np.array([o["phase"]     for o in oscillators])
        return np.array([
            float(np.mean(E)),
            float(np.var(E)),
            float(np.abs(np.mean(np.exp(1j * phi)))),  # coherence
            float(-np.sum((E / (E.sum() + 1e-10)) *
                          np.log(E / (E.sum() + 1e-10) + 1e-10))),  # entropy
            float(stability),
            float(np.mean(E < 0.05)),   # particle loss
            float(np.mean(E > 0.9)),    # saturation
        ], dtype=np.float32)

    def select_action(self,
                      oscillators: List[Dict],
                      stability:   float,
                      regime:      str) -> Action:
        N = len(oscillators)
        sv = self._state_vector(oscillators, stability)
        scales = self._forward(sv)   # [omega_scale, phi_scale, energy_scale]

        # Use rule policy as base, scale by neural output
        base = self._rule_policy.select_action(oscillators, stability, regime)
        omega_s, phi_s, energy_s = scales

        d_omega = base.delta_omega * (0.5 + abs(omega_s))
        d_phi   = base.delta_phi   * (0.5 + abs(phi_s))
        d_E     = base.delta_energy * (0.5 + abs(energy_s))

        self._steps += 1
        return Action(
            action_type    = ActionType.FULL_NUDGE,
            target_indices = base.target_indices,
            delta_omega    = d_omega,
            delta_phi      = d_phi,
            delta_energy   = d_E,
            reason         = f"neural|regime={regime}|scales={scales.round(2)}",
        )

    def update_weights(self, reward: float, lr: float = 0.001):
        """
        Simple policy gradient weight update.
        reward > 0 → reinforce last action
        reward < 0 → penalize last action
        """
        # REINFORCE-style: nudge weights in gradient direction
        noise_scale = lr * reward
        self.W1 += noise_scale * np.random.normal(0, 0.01, self.W1.shape)
        self.W2 += noise_scale * np.random.normal(0, 0.01, self.W2.shape)
        self._episode_reward += reward

    def save(self, path: str):
        np.savez(path, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2)
        log.info(f"NeuralPolicy saved → {path}")

    def load(self, path: str):
        data = np.load(path + ".npz")
        self.W1, self.b1 = data["W1"], data["b1"]
        self.W2, self.b2 = data["W2"], data["b2"]
        log.info(f"NeuralPolicy loaded ← {path}")


# ─── Policy Factory ───────────────────────────────────────────────────────────

def make_policy(kind: str = "neural", **kwargs) -> ControlPolicy:
    """
    Factory: 'rule' | 'gradient' | 'neural'
    """
    if kind == "rule":
        return RulePolicy()
    elif kind == "gradient":
        return GradientPolicy()
    elif kind == "neural":
        return NeuralPolicy(**kwargs)
    raise ValueError(f"Unknown policy kind: {kind!r}")