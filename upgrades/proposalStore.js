const proposalMemory = [];

function buildProposalId() {
  return `up_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function getUpgradeProposals() {
  return proposalMemory.map((entry) => ({ ...entry }));
}

export function createUpgradeProposal({ title, summary, proposedBy, category }) {
  const entry = {
    id: buildProposalId(),
    title,
    summary,
    proposedBy,
    category,
    status: 'pending',
    createdAt: Date.now(),
    decidedAt: null,
    decidedBy: null,
    decisionReason: '',
  };

  proposalMemory.push(entry);
  return { ...entry };
}

export function decideUpgradeProposal({ proposalId, decision, decidedBy, reason }) {
  const target = proposalMemory.find((entry) => entry.id === proposalId);
  if (!target) return null;
  if (target.status !== 'pending') return { ...target };

  target.status = decision;
  target.decidedAt = Date.now();
  target.decidedBy = decidedBy;
  target.decisionReason = reason ?? '';

  return { ...target };
}
