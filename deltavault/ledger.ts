import crypto from 'node:crypto';

export type DeltaVaultDecision = 'approved';

export type DeltaVaultEntry = {
  id: string;
  timestamp: number;
  actionType: string;
  decision: DeltaVaultDecision;
  payload: unknown;
  reason: string;
  previousHash: string | null;
  entryHash: string;
};

const ledger: DeltaVaultEntry[] = [];

function buildEntryId(): string {
  return `dv_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function canonicalize(value: unknown): string {
  return JSON.stringify(value, (_key, currentValue) => {
    if (
      currentValue &&
      typeof currentValue === 'object' &&
      !Array.isArray(currentValue)
    ) {
      return Object.keys(currentValue)
        .sort()
        .reduce<Record<string, unknown>>((acc, key) => {
          acc[key] = (currentValue as Record<string, unknown>)[key];
          return acc;
        }, {});
    }
    return currentValue;
  });
}

function computeEntryHash(params: {
  id: string;
  timestamp: number;
  actionType: string;
  decision: DeltaVaultDecision;
  payload: unknown;
  reason: string;
  previousHash: string | null;
}): string {
  const hashInput = [
    params.id,
    String(params.timestamp),
    params.actionType,
    params.decision,
    canonicalize(params.payload),
    params.reason,
    params.previousHash ?? 'GENESIS',
  ].join('|');

  return crypto.createHash('sha256').update(hashInput).digest('hex');
}

export function appendApprovedEntry(params: {
  actionType: string;
  payload: unknown;
  reason: string;
}): DeltaVaultEntry {
  const id = buildEntryId();
  const timestamp = Date.now();
  const previousHash = ledger.length > 0 ? ledger[ledger.length - 1].entryHash : null;

  const entryHash = computeEntryHash({
    id,
    timestamp,
    actionType: params.actionType,
    decision: 'approved',
    payload: params.payload,
    reason: params.reason,
    previousHash,
  });

  const entry: DeltaVaultEntry = {
    id,
    timestamp,
    actionType: params.actionType,
    decision: 'approved',
    payload: params.payload,
    reason: params.reason,
    previousHash,
    entryHash,
  };

  ledger.push(entry);
  return entry;
}

export function getLedgerEntries(): DeltaVaultEntry[] {
  return ledger.map((entry) => ({ ...entry }));
}

export function verifyLedgerIntegrity(): {
  ok: boolean;
  checked: number;
  brokenAt: string | null;
} {
  for (let i = 0; i < ledger.length; i += 1) {
    const entry = ledger[i];
    const expectedPreviousHash = i === 0 ? null : ledger[i - 1].entryHash;

    if (entry.previousHash !== expectedPreviousHash) {
      return {
        ok: false,
        checked: i + 1,
        brokenAt: entry.id,
      };
    }

    const recomputedHash = computeEntryHash({
      id: entry.id,
      timestamp: entry.timestamp,
      actionType: entry.actionType,
      decision: entry.decision,
      payload: entry.payload,
      reason: entry.reason,
      previousHash: entry.previousHash,
    });

    if (entry.entryHash !== recomputedHash) {
      return {
        ok: false,
        checked: i + 1,
        brokenAt: entry.id,
      };
    }
  }

  return {
    ok: true,
    checked: ledger.length,
    brokenAt: null,
  };
}
