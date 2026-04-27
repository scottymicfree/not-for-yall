type SentinelSignalLevel = 'normal' | 'watch' | 'warning';

type SentinelSignal = {
  key: string;
  level: SentinelSignalLevel;
  value: number;
  summary: string;
};

type SentinelInput = {
  timestamp: number;
  driftIndex: number;
  signals: SentinelSignal[];
  governance: {
    totalEntries: number;
    recentEntries: number;
    approvalCount: number;
    rejectionCount: number;
    reviewSpike: boolean;
    ledgerBurst: boolean;
  };
};

type DeltaVaultIntegrityInput = {
  ok: boolean;
  checked: number;
  brokenAt: string | null;
};

export type EagleEyeValidationResult = {
  valid: boolean;
  issues: string[];
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function validateInputs(
  sentinel: SentinelInput,
  integrity: DeltaVaultIntegrityInput,
): EagleEyeValidationResult {
  const issues: string[] = [];

  if (!isFiniteNumber(sentinel.timestamp) || sentinel.timestamp <= 0) {
    issues.push('Sentinel timestamp is invalid.');
  }

  if (!isFiniteNumber(sentinel.driftIndex) || sentinel.driftIndex < 0 || sentinel.driftIndex > 1) {
    issues.push('Sentinel driftIndex is out of range.');
  }

  if (!Array.isArray(sentinel.signals)) {
    issues.push('Sentinel signals must be an array.');
  }

  if (
    !isFiniteNumber(sentinel.governance.totalEntries) ||
    !isFiniteNumber(sentinel.governance.recentEntries) ||
    !isFiniteNumber(sentinel.governance.approvalCount) ||
    !isFiniteNumber(sentinel.governance.rejectionCount)
  ) {
    issues.push('Sentinel governance counters are invalid.');
  }

  if (sentinel.governance.recentEntries > sentinel.governance.totalEntries) {
    issues.push('Recent DeltaVault entries exceed total entries.');
  }

  if (typeof integrity.ok !== 'boolean') {
    issues.push('DeltaVault integrity flag is invalid.');
  }

  if (!isFiniteNumber(integrity.checked) || integrity.checked < 0) {
    issues.push('DeltaVault integrity checked count is invalid.');
  }

  if (integrity.ok && integrity.brokenAt !== null) {
    issues.push('DeltaVault integrity reports brokenAt while ok=true.');
  }

  return {
    valid: issues.length === 0,
    issues,
  };
}
