export function detectContradictions(sentinel, integrity) {
  const issues = [];
  const warningCount = sentinel.signals.filter((signal) => signal.level === 'warning').length;
  if (sentinel.driftIndex < 0.05 && warningCount >= 2) issues.push('Warning signal count is high while composite drift is low.');
  if (sentinel.governance.ledgerBurst && sentinel.governance.recentEntries === 0) issues.push('Ledger burst flag is true while recent entry count is zero.');
  if (sentinel.governance.reviewSpike && sentinel.governance.approvalCount + sentinel.governance.rejectionCount < 5) issues.push('Review spike flag is true while review count is below threshold.');
  if (!integrity.ok && sentinel.governance.totalEntries === 0) issues.push('Integrity failed while no DeltaVault entries exist.');
  if (sentinel.governance.rejectionCount > sentinel.governance.approvalCount * 3 && sentinel.driftIndex < 0.03) issues.push('Heavy rejection pattern is present while system drift remains unusually low.');
  return { count: issues.length, issues };
}
