"""
Lucy OS — Quantum Music Engine: Learning Loop
=============================================
The core RL loop:

for t in range(sim_time):
    action = model(state)
    new_state = simulate(state, action)
    reward = stability_score(new_state)
    model.learn(state, action, reward)
    state = new_state

Features:
  - Runs in background thread (non-blocking)
  - Emits events to Lucy HAL EventBus
  - Tracks reward history, regime transitions
  - Supports pause/resume/reset
  - Checkpoints policy weights to MemorySpine
"""

import numpy as np
import threading
import time
import logging
import collections
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

from .state_engine   import OscillatorField, FieldState
from .stability      import StabilityTracker
from .control_layer  import ControlPolicy, NeuralPolicy, make_policy

log = logging.getLogger("lucy.qme.learner")


# ─── Episode Record ───────────────────────────────────────────────────────────

@dataclass
class EpisodeRecord:
    episode:        int
    steps:          int
    total_reward:   float
    mean_stability: float
    final_regime:   str
    duration_s:     float
    best_stability: float
    worst_stability: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode":         self.episode,
            "steps":           self.steps,
            "total_reward":    round(self.total_reward, 4),
            "mean_stability":  round(self.mean_stability, 4),
            "final_regime":    self.final_regime,
            "duration_s":      round(self.duration_s, 3),
            "best_stability":  round(self.best_stability, 4),
            "worst_stability": round(self.worst_stability, 4),
        }


# ─── Quantum Music Learner ────────────────────────────────────────────────────

class QuantumMusicLearner:
    """
    Background RL learner for the Quantum Music Engine.

    Lifecycle:
      start()  → spawns background thread
      pause()  → freezes simulation
      resume() → continues
      stop()   → graceful shutdown

    API:
      get_state()    → latest FieldState
      get_metrics()  → learning metrics dict
      inject_event() → add external disturbance
    """

    STEP_INTERVAL_S  = 0.05    # 50ms per step (20 steps/sec real-time)
    EPISODE_STEPS    = 500     # steps per episode before policy update
    CHECKPOINT_EVERY = 10      # episodes between weight saves
    MAX_EPISODES     = 10_000

    def __init__(self,
                 policy_kind:   str = "neural",
                 noise_level:   float = 0.02,
                 checkpoint_dir: Optional[str] = None,
                 event_callback: Optional[Callable] = None):

        self._field     = OscillatorField(seed=42)
        self._tracker   = StabilityTracker()
        self._policy    = make_policy(policy_kind)
        self._noise     = noise_level
        self._ckpt_dir  = checkpoint_dir
        self._on_event  = event_callback   # Lucy HAL EventBus callback

        self._field.set_noise_level(noise_level)

        # State
        self._running    = False
        self._paused     = False
        self._thread:    Optional[threading.Thread] = None
        self._lock       = threading.Lock()
        self._latest_state: Optional[FieldState] = None

        # Metrics
        self._episode       = 0
        self._total_steps   = 0
        self._episode_steps = 0
        self._episode_rewards: List[float] = []
        self._episode_history: collections.deque = collections.deque(maxlen=100)
        self._reward_history:  collections.deque = collections.deque(maxlen=1000)
        self._last_action_dict: Dict = {}

        log.info(f"QuantumMusicLearner ready | policy={policy_kind} "
                 f"noise={noise_level}")

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._run_loop,
            name="qme-learner",
            daemon=True,
        )
        self._thread.start()
        log.info("QuantumMusicLearner started")

    def pause(self):
        self._paused = True
        log.info("QuantumMusicLearner paused")

    def resume(self):
        self._paused = False
        log.info("QuantumMusicLearner resumed")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        log.info("QuantumMusicLearner stopped")

    # ── Main Loop ──────────────────────────────────────────────────────────────

    def _run_loop(self):
        """Background simulation + learning loop."""
        episode_start = time.time()
        episode_stabilities: List[float] = []

        while self._running and self._episode < self.MAX_EPISODES:
            if self._paused:
                time.sleep(0.1)
                continue

            t0 = time.time()

            # ── 1. Get current state ──────────────────────────────────────
            with self._lock:
                regime = self._tracker.get_regime()
                stab   = (self._tracker.get_rolling_mean()
                          if self._total_steps > 0 else 0.5)

            # ── 2. Select action ──────────────────────────────────────────
            state  = self._field.get_current_state()
            action = self._policy.select_action(
                oscillators = state.oscillators,
                stability   = state.stability_score,
                regime      = regime,
            )
            self._last_action_dict = action.to_dict()

            # ── 3. Step simulation ────────────────────────────────────────
            new_state = self._field.step(action.to_array())

            # ── 4. Compute reward ─────────────────────────────────────────
            reward = new_state.stability_score

            # Bonus for regime improvement
            if regime == "chaos" and new_state.stability_score > -0.2:
                reward += 0.2
            if regime in ("instability", "transition") and \
               new_state.stability_score > 0.3:
                reward += 0.1

            # ── 5. Learn ──────────────────────────────────────────────────
            if isinstance(self._policy, NeuralPolicy):
                self._policy.update_weights(reward, lr=0.0005)

            # ── 6. Track ──────────────────────────────────────────────────
            self._tracker.record(new_state.stability_score, new_state.t)
            episode_stabilities.append(new_state.stability_score)
            self._episode_rewards.append(reward)
            self._reward_history.append(reward)

            with self._lock:
                self._latest_state = new_state
                self._total_steps   += 1
                self._episode_steps += 1

            # ── 7. Emit events to HAL ────────────────────────────────────
            self._emit_events(new_state)

            # ── 8. Episode boundary ───────────────────────────────────────
            if self._episode_steps >= self.EPISODE_STEPS:
                dur = time.time() - episode_start
                rec = EpisodeRecord(
                    episode        = self._episode,
                    steps          = self._episode_steps,
                    total_reward   = float(sum(self._episode_rewards)),
                    mean_stability = float(np.mean(episode_stabilities)),
                    final_regime   = self._tracker.get_regime(),
                    duration_s     = dur,
                    best_stability = float(max(episode_stabilities)),
                    worst_stability= float(min(episode_stabilities)),
                )
                self._episode_history.append(rec.to_dict())
                log.info(f"[QME] Episode {self._episode} | "
                         f"mean_stab={rec.mean_stability:.3f} | "
                         f"regime={rec.final_regime} | "
                         f"reward={rec.total_reward:.2f}")

                # Checkpoint
                if (self._episode % self.CHECKPOINT_EVERY == 0 and
                        self._ckpt_dir and
                        isinstance(self._policy, NeuralPolicy)):
                    path = f"{self._ckpt_dir}/qme_policy_ep{self._episode}"
                    try:
                        self._policy.save(path)
                    except Exception as e:
                        log.warning(f"Checkpoint save failed: {e}")

                self._episode       += 1
                self._episode_steps  = 0
                self._episode_rewards.clear()
                episode_stabilities.clear()
                episode_start = time.time()

            # ── 9. Rate limiting ──────────────────────────────────────────
            elapsed = time.time() - t0
            sleep   = max(0, self.STEP_INTERVAL_S - elapsed)
            if sleep > 0:
                time.sleep(sleep)

    # ── Event Emission ────────────────────────────────────────────────────────

    def _emit_events(self, state: FieldState):
        """Fire events to Lucy HAL EventBus when notable things happen."""
        if not self._on_event:
            return

        # Regime change alert
        regime = self._tracker.get_regime()
        if regime == "chaos":
            self._on_event({
                "topic":   "QME_ALERT",
                "payload": {
                    "type":      "chaos_detected",
                    "stability": state.stability_score,
                    "t":         state.t,
                    "timestamp": state.timestamp,
                },
            })

        # Attractor formation
        if state.attractor_count > 50:
            self._on_event({
                "topic":   "QME_HARMONY",
                "payload": {
                    "type":          "attractor_formation",
                    "attractor_count": state.attractor_count,
                    "coherence":     state.mean_phase_coherence,
                    "stability":     state.stability_score,
                    "timestamp":     state.timestamp,
                },
            })

        # Stability alerts
        alerts = self._tracker.pop_alerts()
        for alert in alerts:
            self._on_event({
                "topic":   "QME_ALERT",
                "payload": alert,
            })

    # ── External API ──────────────────────────────────────────────────────────

    def inject_disturbance(self, x: float, y: float,
                           amplitude: float, radius: float = 0.2,
                           source: str = "external"):
        """Inject external disturbance (e.g. seismic event from Earth bridge)."""
        self._field.inject_disturbance(x, y, amplitude, radius, source)

    def set_noise_level(self, level: float):
        self._field.set_noise_level(level)

    def get_state(self) -> Optional[FieldState]:
        with self._lock:
            return self._latest_state

    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running":          self._running,
                "paused":           self._paused,
                "episode":          self._episode,
                "total_steps":      self._total_steps,
                "episode_steps":    self._episode_steps,
                "reward_mean":      round(float(np.mean(self._reward_history))
                                         if self._reward_history else 0.0, 4),
                "reward_std":       round(float(np.std(self._reward_history))
                                         if len(self._reward_history) > 1 else 0.0, 4),
                "stability_summary": self._tracker.get_summary(),
                "last_action":      self._last_action_dict,
                "episode_history":  list(self._episode_history)[-10:],
                "policy_type":      type(self._policy).__name__,
            }

    def get_field_snapshot(self) -> Dict[str, Any]:
        """Compact snapshot for dashboard rendering."""
        state = self.get_state()
        if not state:
            return {"ready": False}
        metrics = self._tracker.get_summary()
        return {
            "ready":            True,
            "t":                state.t,
            "timestamp":        state.timestamp,
            "stability_score":  state.stability_score,
            "regime":           metrics["regime"],
            "trend":            metrics["trend"],
            "phase_coherence":  state.mean_phase_coherence,
            "energy_variance":  state.energy_variance,
            "entropy":          state.entropy,
            "attractor_count":  state.attractor_count,
            "n_oscillators":    state.n_oscillators,
            "oscillators":      state.oscillators,   # full field for viz
            "stability_history": metrics["history"],
            "episode":          self._episode,
            "total_steps":      self._total_steps,
        }

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused