import { validateInputs } from './validateInputs.ts';
import { detectContradictions } from './detectContradictions.ts';
import { scoreConfidence } from './scoreConfidence.ts';

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

export type EagleEyeLevel = 'stable' | 'watch' | 'warning';

export type EagleEyeMetric = {
  key: string;
  level: EagleEyeLevel;
  value: number | boolean;
  summary: string;
};

export type EagleEyeReport = {
  timestamp: number;
  overall: EagleEyeLevel;
  pressureIndex: number;
  confidence: number;
  trusted: boolean;
  contradictionCount: number;
  validationIssues: string[];
  contradictionIssues: string[];
  metrics: EagleEyeMetric[];
};

function round3(value: number): number {
  return Number(value.toFixed(3));
}

function toLevel(score: number): EagleEyeLevel {
  if (score >= 0.6) return 'warning';
  if (score >= 0.25) return 'watch';
  return 'stable';
}

export function deriveWatchState(
  sentinel: SentinelInput,
  integrity: DeltaVaultIntegrityInput,
): EagleEyeReport {
  const validation = validateInputs(sentinel, integrity);
  const contradictions = detectContradictions(sentinel, integrity);
  const confidenceResult = scoreConfidence(
    sentinel,
    integrity,
    validation,
    contradictions,
  );

  const warningSignals = sentinel.signals.filter((signal) => signal.level === 'warning').length;
  const watchSignals = sentinel.signals.filter((signal) => signal.level === 'watch').length;

  const integrityPressure = integrity.ok ? 0 : 1;
  const governancePressure =
    (sentinel.governance.reviewSpike ? 0.25 : 0) +
    (sentinel.governance.ledgerBurst ? 0.35 : 0) +
    Math.min(sentinel.governance.rejectionCount * 0.1, 0.4);

  const signalPressure = Math.min(
    warningSignals * 0.25 + watchSignals * 0.08 + sentinel.driftIndex,
    1,
  );

  const contradictionPressure = Math.min(contradictions.count * 0.18, 0.5);
  const validationPressure = validation.valid ? 0 : Math.min(validation.issues.length * 0.15, 0.5);
  const confidencePenalty = 1 - confidenceResult.confidence;

  const pressureIndex = round3(
    Math.min(
      signalPressure +
        governancePressure +
        integrityPressure +
        contradictionPressure +
        validationPressure +
        confidencePenalty * 0.5,
      1,
    ),
  );

  const metrics: EagleEyeMetric[] = [
    {
      key: 'sentinel-drift',
      level: toLevel(sentinel.driftIndex),
      value: sentinel.driftIndex,
      summary: `Sentinel composite drift is ${sentinel.driftIndex}.`,
    },
    {
      key: 'warning-signal-count',
      level: toLevel(Math.min(warningSignals * 0.25, 1)),
      value: warningSignals,
      summary: `${warningSignals} warning-level Sentinel signals detected.`,
    },
    {
      key: 'governance-rejections',
      level: toLevel(Math.min(sentinel.governance.rejectionCount * 0.12, 1)),
      value: sentinel.governance.rejectionCount,
      summary: `${sentinel.governance.rejectionCount} Emma rejections observed in memory.`,
    },
    {
      key: 'review-spike',
      level: sentinel.governance.reviewSpike ? 'watch' : 'stable',
      value: sentinel.governance.reviewSpike,
      summary: sentinel.governance.reviewSpike
        ? 'Governance review volume is elevated.'
        : 'Governance review volume is stable.',
    },
    {
      key: 'ledger-burst',
      level: sentinel.governance.ledgerBurst ? 'warning' : 'stable',
      value: sentinel.governance.ledgerBurst,
      summary: sentinel.governance.ledgerBurst
        ? 'DeltaVault write burst detected.'
        : 'DeltaVault write activity is stable.',
    },
    {
      key: 'ledger-integrity',
      level: integrity.ok ? 'stable' : 'warning',
      value: integrity.ok,
      summary: integrity.ok
        ? `DeltaVault integrity verified across ${integrity.checked} entries.`
        : `DeltaVault integrity failure detected at ${integrity.brokenAt}.`,
    },
    {
      key: 'confidence',
      level: confidenceResult.trusted ? 'stable' : confidenceResult.confidence >= 0.5 ? 'watch' : 'warning',
      value: confidenceResult.confidence,
      summary: confidenceResult.trusted
        ? `Eagle Eye confidence is ${confidenceResult.confidence} and trusted.`
        : `Eagle Eye confidence is ${confidenceResult.confidence} and not trusted.`,
    },
    {
      key: 'contradictions',
      level: contradictions.count === 0 ? 'stable' : contradictions.count < 3 ? 'watch' : 'warning',
      value: contradictions.count,
      summary:
        contradictions.count === 0
          ? 'No monitoring contradictions detected.'
          : `${contradictions.count} monitoring contradictions detected.`,
    },
  ];

  return {
    timestamp: Date.now(),
    overall: toLevel(pressureIndex),
    pressureIndex,
    confidence: confidenceResult.confidence,
    trusted: confidenceResult.trusted,
    contradictionCount: contradictions.count,
    validationIssues: validation.issues,
    contradictionIssues: contradictions.issues,
    metrics,
  };
}
