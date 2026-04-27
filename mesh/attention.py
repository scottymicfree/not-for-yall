"""
N6 — Attention Weight Engine
Computes dynamic attention weights for nodes based on:
- Domain relevance
- Node performance history
- Confidence scores from previous outputs
- Urgency of the request
- Emma's routing decisions

Weights influence which outputs Lucy Prime prioritizes in synthesis.
"""

import time
import math
from typing import Dict, List, Optional
from collections import defaultdict
import threading


class AttentionWeightEngine:
    """
    N6 — Dynamic attention weights for Lucy's cognitive mesh.

    Weights are updated continuously based on:
    - Past performance (success rate, confidence, speed)
    - Domain affinity (how well a node performs in specific domains)
    - Current load and availability
    - Emma's evaluation scores

    final_score = (confidence * 0.4) + (relevance * 0.3) + (consistency * 0.2) + (novelty * 0.1)
    """

    DECAY_FACTOR = 0.95        # Weight decay per tick (prevents overfitting)
    BOOST_ON_SUCCESS = 0.05    # Boost on successful high-confidence output
    PENALTY_ON_FAILURE = 0.10  # Penalty on failure or low confidence
    MIN_WEIGHT = 0.1
    MAX_WEIGHT = 2.0

    def __init__(self):
        self._weights: Dict[str, float] = {}          # node_id -> weight
        self._domain_affinity: Dict[str, Dict[str, float]] = defaultdict(dict)  # node_id -> domain -> score
        self._performance_history: Dict[str, List[dict]] = defaultdict(list)    # node_id -> recent results
        self._lock = threading.RLock()
        self._tick_count = 0

        # Initialize all 137 nodes with default weight 1.0
        self._init_weights()

    def _init_weights(self):
        """Initialize all nodes with 1.0 weight."""
        all_node_ids = (
            [f"P{i}" for i in range(1, 13)] +
            [f"M{i}" for i in range(1, 19)] +
            [f"L{i}" for i in range(1, 49)] +
            [f"E{i}" for i in range(1, 25)] +
            [f"LP{i}" for i in range(1, 13)] +
            [f"N{i}" for i in range(1, 11)] +
            [f"O{i}" for i in range(1, 8)] +
            [f"S{i}" for i in range(1, 7)]
        )
        for nid in all_node_ids:
            self._weights[nid] = 1.0

    def get_weight(self, node_id: str) -> float:
        with self._lock:
            return self._weights.get(node_id, 1.0)

    def get_weights_for_layer(self, layer_nodes: List[str]) -> Dict[str, float]:
        with self._lock:
            return {nid: self._weights.get(nid, 1.0) for nid in layer_nodes}

    def record_output(self, node_id: str, domain: str, confidence: float,
                      relevance: float, novelty: float, consistency: float,
                      success: bool, duration_ms: int = 0):
        """Record a node's output and update its weight."""
        with self._lock:
            # Emma composite score formula
            composite = (
                confidence   * 0.4 +
                relevance    * 0.3 +
                consistency  * 0.2 +
                novelty      * 0.1
            )

            # Store in performance history (max 50 per node)
            hist = self._performance_history[node_id]
            hist.append({
                "ts": int(time.time() * 1000),
                "domain": domain,
                "composite": composite,
                "success": success,
                "durationMs": duration_ms,
            })
            if len(hist) > 50:
                hist.pop(0)

            # Update domain affinity
            current_affinity = self._domain_affinity[node_id].get(domain, 0.5)
            self._domain_affinity[node_id][domain] = (
                current_affinity * 0.7 + composite * 0.3
            )

            # Update weight
            current = self._weights.get(node_id, 1.0)
            if success and composite >= 0.7:
                new_weight = min(current + self.BOOST_ON_SUCCESS * composite, self.MAX_WEIGHT)
            elif not success or composite < 0.3:
                new_weight = max(current - self.PENALTY_ON_FAILURE, self.MIN_WEIGHT)
            else:
                # Neutral — slight pull toward 1.0
                new_weight = current * 0.99 + 1.0 * 0.01

            self._weights[node_id] = round(new_weight, 4)

    def get_domain_affinity(self, node_id: str, domain: str) -> float:
        with self._lock:
            return self._domain_affinity[node_id].get(domain, 0.5)

    def rank_swarm_outputs(self, outputs: List[dict], domain: str) -> List[dict]:
        """
        Rank swarm candidate outputs using Emma's composite scoring formula.
        Each output must have: node_id, confidence, relevance, novelty, consistency (optional).
        """
        scored = []
        for output in outputs:
            node_id     = output.get("nodeId", "unknown")
            confidence  = output.get("confidence", 0.5)
            relevance   = output.get("relevance", 0.5)
            novelty     = output.get("novelty", 0.3)
            consistency = output.get("consistency", 0.7)

            # Domain affinity bonus
            affinity = self.get_domain_affinity(node_id, domain)
            node_weight = self.get_weight(node_id)

            emma_score = (
                confidence  * 0.4 +
                relevance   * 0.3 +
                consistency * 0.2 +
                novelty     * 0.1
            )

            # Apply node weight and domain affinity
            final_score = emma_score * node_weight * (0.8 + affinity * 0.4)

            scored.append({
                **output,
                "emmaScore": round(emma_score, 4),
                "nodeWeight": round(node_weight, 4),
                "domainAffinity": round(affinity, 4),
                "finalScore": round(final_score, 4),
            })

        return sorted(scored, key=lambda x: x["finalScore"], reverse=True)

    def decay_tick(self):
        """Apply weight decay — prevents any node from permanently dominating."""
        with self._lock:
            self._tick_count += 1
            for node_id in self._weights:
                current = self._weights[node_id]
                # Pull toward 1.0 with decay
                self._weights[node_id] = round(
                    current * self.DECAY_FACTOR + 1.0 * (1 - self.DECAY_FACTOR),
                    4
                )

    def get_top_nodes(self, n: int = 10) -> List[dict]:
        with self._lock:
            sorted_weights = sorted(self._weights.items(), key=lambda x: x[1], reverse=True)
            return [{"nodeId": nid, "weight": w} for nid, w in sorted_weights[:n]]

    def get_all_weights(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._weights)

    def get_node_performance(self, node_id: str) -> dict:
        with self._lock:
            hist = self._performance_history.get(node_id, [])
            if not hist:
                return {"nodeId": node_id, "samples": 0, "avgComposite": 0.5, "weight": self.get_weight(node_id)}

            avg_composite = sum(h["composite"] for h in hist) / len(hist)
            success_rate  = sum(1 for h in hist if h["success"]) / len(hist)
            avg_duration  = sum(h["durationMs"] for h in hist) / len(hist)

            return {
                "nodeId": node_id,
                "samples": len(hist),
                "avgComposite": round(avg_composite, 4),
                "successRate": round(success_rate, 4),
                "avgDurationMs": round(avg_duration, 1),
                "weight": self.get_weight(node_id),
                "domainAffinities": dict(self._domain_affinity.get(node_id, {})),
            }

    def full_report(self) -> dict:
        with self._lock:
            weights = dict(self._weights)
            top = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:10]
            bottom = sorted(weights.items(), key=lambda x: x[1])[:5]
            return {
                "tickCount": self._tick_count,
                "totalNodes": len(weights),
                "avgWeight": round(sum(weights.values()) / len(weights), 4) if weights else 1.0,
                "maxWeight": max(weights.values()) if weights else 1.0,
                "minWeight": min(weights.values()) if weights else 1.0,
                "topNodes": [{"nodeId": k, "weight": v} for k, v in top],
                "bottomNodes": [{"nodeId": k, "weight": v} for k, v in bottom],
            }


# Singleton
attention_engine = AttentionWeightEngine()