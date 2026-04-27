function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
function round3(value) { return Number(value.toFixed(3)); }
export function scoreConfidence(sentinel, integrity, validation, contradictions) {
  let score = 1;
  if (!validation.valid) score -= validation.issues.length * 0.2;
  if (!integrity.ok) score -= 0.35;
  score -= contradictions.count * 0.15;
  score -= Math.min(sentinel.governance.rejectionCount * 0.03, 0.2);
  if (sentinel.governance.reviewSpike) score -= 0.05;
  if (sentinel.governance.ledgerBurst) score -= 0.08;
  score -= Math.min(sentinel.driftIndex * 0.2, 0.12);
  const confidence = round3(clamp(score, 0, 1));
  return { confidence, trusted: confidence >= 0.65 && validation.valid && integrity.ok && contradictions.count === 0 };
}
