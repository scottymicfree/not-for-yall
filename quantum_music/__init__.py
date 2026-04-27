"""
Lucy OS — Quantum Music Engine
================================
Translates physics simulation into musical metaphor:
  All notes at once   → Monte Carlo / wavefunction superposition
  Tuning notes        → Gradient descent / RL policy
  Harmony             → Phase synchronization
  Stable note         → Attractor state
  Dissonance          → Instability / divergence
  Composer            → Lucy control system
"""

from .state_engine      import OscillatorField, FieldState
from .stability         import StabilityFunction
from .control_layer     import ControlPolicy, ActionType
from .learning_loop     import QuantumMusicLearner
from .field_simulation  import WaveFieldSimulator
from .earth_bridge      import EarthOscillatorBridge

__all__ = [
    "OscillatorField", "FieldState",
    "StabilityFunction",
    "ControlPolicy", "ActionType",
    "QuantumMusicLearner",
    "WaveFieldSimulator",
    "EarthOscillatorBridge",
]