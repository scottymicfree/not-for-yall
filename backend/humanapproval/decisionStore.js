const decisionMemory = [];

function buildDecisionId(itemId) {
  return `had_${itemId}_${Date.now()}`;
}

export function getHumanApprovalDecisions() {
  return decisionMemory.map((entry) => ({ ...entry }));
}

export function recordHumanApprovalDecision({
  itemId,
  decision,
  decidedBy,
  reason,
}) {
  const entry = {
    id: buildDecisionId(itemId),
    itemId,
    decision,
    decidedBy,
    reason: reason ?? '',
    decidedAt: Date.now(),
  };

  decisionMemory.push(entry);
  return entry;
}
