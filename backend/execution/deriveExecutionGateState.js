export function deriveExecutionGateState({ eagleEye, deltaVaultIntegrity, humanApprovalDecisions }) {
  const reasons = [];

  if (!deltaVaultIntegrity?.ok) reasons.push('DeltaVault integrity is not verified.');
  if (!eagleEye?.trusted) reasons.push('Eagle Eye is not trusted.');

  const approvedHumanDecisions = (humanApprovalDecisions || []).filter(
    (entry) => entry.decision === 'approved',
  );

  if (approvedHumanDecisions.length === 0) reasons.push('No human-approved decisions exist.');

  return {
    timestamp: Date.now(),
    ready: reasons.length === 0,
    blocked: reasons.length > 0,
    reasons,
    approvedDecisionCount: approvedHumanDecisions.length,
  };
}
