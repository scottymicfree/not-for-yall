type EmmaReviewInput = {
  decision: 'approved' | 'rejected';
  level: 'low' | 'medium' | 'high';
  reason: string;
  approvedAt: number;
};

type EagleEyeInput = {
  trusted: boolean;
  confidence: number;
};

export type HumanApprovalItem = {
  id: string;
  level: 'medium' | 'high';
  reason: string;
  createdAt: number;
  status: 'pending-human-visibility';
};

export type HumanApprovalReport = {
  timestamp: number;
  pendingCount: number;
  visible: boolean;
  items: HumanApprovalItem[];
};

function buildId(review: EmmaReviewInput, index: number): string {
  return `ha_${review.approvedAt}_${review.level}_${index}`;
}

export function deriveHumanApprovalState(
  emmaReviews: EmmaReviewInput[],
  eagleEye: EagleEyeInput,
): HumanApprovalReport {
  const items: HumanApprovalItem[] = [];

  if (!eagleEye.trusted) {
    return {
      timestamp: Date.now(),
      pendingCount: 0,
      visible: false,
      items,
    };
  }

  emmaReviews.forEach((review, index) => {
    if (review.decision !== 'approved') return;
    if (review.level === 'low') return;

    items.push({
      id: buildId(review, index),
      level: review.level,
      reason: review.reason,
      createdAt: review.approvedAt,
      status: 'pending-human-visibility',
    });
  });

  return {
    timestamp: Date.now(),
    pendingCount: items.length,
    visible: items.length > 0,
    items,
  };
}
