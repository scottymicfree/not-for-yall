export function deriveHumanApprovalState(
  emmaReviews,
  eagleEye,
  humanDecisions = [],
) {
  const items = [];

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

    const itemId = `ha_${review.approvedAt}_${review.level}_${index}`;
    const priorDecision = humanDecisions.find((entry) => entry.itemId === itemId);

    if (priorDecision) return;

    items.push({
      id: itemId,
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
