export function buildSimulationPacket({ executionGate, humanApprovalDecisions, ledgerEntries }) {
  const reasons = executionGate?.reasons ?? [];
  const approvedDecision = (humanApprovalDecisions ?? [])
    .filter((entry) => entry.decision === 'approved')
    .sort((a, b) => b.decidedAt - a.decidedAt)[0];

  const latestLedgerEntry = (ledgerEntries ?? []).slice().sort((a, b) => b.timestamp - a.timestamp)[0] ?? null;

  const readyForSimulation = Boolean(executionGate?.ready) && Boolean(approvedDecision);

  return {
    timestamp: Date.now(),
    simulationOnly: true,
    readyForSimulation,
    blocked: !readyForSimulation,
    reasons: readyForSimulation
      ? []
      : reasons.length > 0
        ? reasons
        : ['Simulation gate is not satisfied.'],
    packetPreview: readyForSimulation
      ? {
          sourceHumanDecisionId: approvedDecision.id,
          sourceItemId: approvedDecision.itemId,
          decidedBy: approvedDecision.decidedBy,
          decidedAt: approvedDecision.decidedAt,
          latestLedgerEntryId: latestLedgerEntry?.id ?? null,
          latestLedgerActionType: latestLedgerEntry?.actionType ?? null,
          mode: 'dry-run',
        }
      : null,
  };
}
