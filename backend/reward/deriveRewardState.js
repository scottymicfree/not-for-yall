function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
function round2(value) { return Number(value.toFixed(2)); }
function scoreToLevel(score) { if (score >= 85) return 'strong'; if (score >= 65) return 'stable'; if (score >= 40) return 'building'; return 'low'; }
export function deriveRewardState(ledgerEntries, emmaReviews, trust, eagleEye) {
  const approvedCount = ledgerEntries.length;
  const rejectedCount = emmaReviews.filter((review) => review.decision === 'rejected').length;
  const mediumHighApprovals = emmaReviews.filter((review) => review.decision === 'approved' && (review.level === 'medium' || review.level === 'high')).length;
  const baseScore = trust.score * 0.45 + approvedCount * 4 - rejectedCount * 8 - mediumHighApprovals * 2;
  const monitoringPenalty = eagleEye.trusted ? 0 : 15 + eagleEye.contradictionCount * 5;
  const confidenceAdjustment = eagleEye.confidence * 10;
  const score = clamp(baseScore + confidenceAdjustment - monitoringPenalty, 0, 100);
  const eligible = eagleEye.trusted && trust.score >= 50;
  return { timestamp: Date.now(), score: round2(score), level: scoreToLevel(score), eligible, metrics: [
    { key: 'approved-actions', value: approvedCount, summary: `${approvedCount} approved actions contribute to reward state.` },
    { key: 'rejections', value: rejectedCount, summary: `${rejectedCount} rejections reduce reward state.` },
    { key: 'monitoring-confidence', value: round2(eagleEye.confidence), summary: `Eagle Eye confidence is ${round2(eagleEye.confidence)}.` },
    { key: 'trust-score', value: round2(trust.score), summary: `Trust score is ${round2(trust.score)}.` },
  ] };
}
