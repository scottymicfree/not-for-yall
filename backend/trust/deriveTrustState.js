function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
function round2(value) { return Number(value.toFixed(2)); }
function scoreToLevel(score) { if (score >= 85) return 'strong'; if (score >= 65) return 'stable'; if (score >= 40) return 'guarded'; return 'low'; }
export function deriveTrustState(ledgerEntries, emmaReviews) {
  const approvedCount = ledgerEntries.length;
  const rejectionCount = emmaReviews.filter((review) => review.decision === 'rejected').length;
  const highRiskApprovedCount = emmaReviews.filter((review) => review.decision === 'approved' && review.level === 'high').length;
  const score = clamp(50 + approvedCount * 6 - rejectionCount * 12 - highRiskApprovedCount * 3, 0, 100);
  return { timestamp: Date.now(), score: round2(score), level: scoreToLevel(score), metrics: [
    { key: 'approved-actions', value: approvedCount, summary: `${approvedCount} approved actions recorded in DeltaVault.` },
    { key: 'rejections', value: rejectionCount, summary: `${rejectionCount} Emma rejections recorded in review memory.` },
    { key: 'high-risk-approvals', value: highRiskApprovedCount, summary: `${highRiskApprovedCount} high-risk approvals observed.` },
  ] };
}
