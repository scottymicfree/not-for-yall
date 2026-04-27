type DeltaVaultEntryInput = {
  id: string;
  timestamp: number;
  actionType: string;
  decision: 'approved';
  payload: unknown;
  reason: string;
  previousHash: string | null;
  entryHash: string;
};

type EmmaReviewInput = {
  decision: 'approved' | 'rejected';
  level: 'low' | 'medium' | 'high';
  reason: string;
  approvedAt: number;
};

export type TrustLevel = 'low' | 'guarded' | 'stable' | 'strong';

export type TrustMetric = {
  key: string;
  value: number;
  summary: string;
};

export type TrustReport = {
  timestamp: number;
  score: number;
  level: TrustLevel;
  metrics: TrustMetric[];
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function round2(value: number): number {
  return Number(value.toFixed(2));
}

function scoreToLevel(score: number): TrustLevel {
  if (score >= 85) return 'strong';
  if (score >= 65) return 'stable';
  if (score >= 40) return 'guarded';
  return 'low';
}

export function deriveTrustState(
  ledgerEntries: DeltaVaultEntryInput[],
  emmaReviews: EmmaReviewInput[],
): TrustReport {
  const approvedCount = ledgerEntries.length;
  const rejectionCount = emmaReviews.filter((review) => review.decision === 'rejected').length;
  const highRiskApprovedCount = emmaReviews.filter(
    (review) => review.decision === 'approved' && review.level === 'high',
  ).length;

  const approvalScore = approvedCount * 6;
  const rejectionPenalty = rejectionCount * 12;
  const highRiskPenalty = highRiskApprovedCount * 3;

  const score = clamp(50 + approvalScore - rejectionPenalty - highRiskPenalty, 0, 100);

  return {
    timestamp: Date.now(),
    score: round2(score),
    level: scoreToLevel(score),
    metrics: [
      {
        key: 'approved-actions',
        value: approvedCount,
        summary: `${approvedCount} approved actions recorded in DeltaVault.`,
      },
      {
        key: 'rejections',
        value: rejectionCount,
        summary: `${rejectionCount} Emma rejections recorded in review memory.`,
      },
      {
        key: 'high-risk-approvals',
        value: highRiskApprovedCount,
        summary: `${highRiskApprovedCount} high-risk approvals observed.`,
      },
    ],
  };
}
