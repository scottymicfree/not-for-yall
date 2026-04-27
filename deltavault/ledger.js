import crypto from 'node:crypto';

const ledger = [];
let counter = 0;

function buildEntryId() {
  counter += 1;
  return `dv_${Date.now()}_${String(counter).padStart(6, '0')}`;
}

function canonicalize(value) {
  return JSON.stringify(value, (_key, currentValue) => {
    if (currentValue && typeof currentValue === 'object' && !Array.isArray(currentValue)) {
      return Object.keys(currentValue).sort().reduce((acc, key) => {
        acc[key] = currentValue[key];
        return acc;
      }, {});
    }
    return currentValue;
  });
}

function computeEntryHash(params) {
  const hashInput = [params.id, String(params.timestamp), params.actionType, params.decision, canonicalize(params.payload), params.reason, params.previousHash ?? 'GENESIS'].join('|');
  return crypto.createHash('sha256').update(hashInput).digest('hex');
}

export function appendApprovedEntry(params) {
  const id = buildEntryId();
  const timestamp = Date.now();
  const previousHash = ledger.length > 0 ? ledger[ledger.length - 1].entryHash : null;
  const entryHash = computeEntryHash({ id, timestamp, actionType: params.actionType, decision: 'approved', payload: params.payload, reason: params.reason, previousHash });
  const entry = { id, timestamp, actionType: params.actionType, decision: 'approved', payload: params.payload, reason: params.reason, previousHash, entryHash };
  ledger.push(entry);
  return entry;
}

export function getLedgerEntries() {
  return ledger.map((entry) => ({ ...entry }));
}

export function verifyLedgerIntegrity() {
  for (let i = 0; i < ledger.length; i += 1) {
    const entry = ledger[i];
    const expectedPreviousHash = i === 0 ? null : ledger[i - 1].entryHash;
    if (entry.previousHash !== expectedPreviousHash) return { ok: false, checked: i + 1, brokenAt: entry.id };
    const recomputedHash = computeEntryHash({ id: entry.id, timestamp: entry.timestamp, actionType: entry.actionType, decision: entry.decision, payload: entry.payload, reason: entry.reason, previousHash: entry.previousHash });
    if (entry.entryHash !== recomputedHash) return { ok: false, checked: i + 1, brokenAt: entry.id };
  }
  return { ok: true, checked: ledger.length, brokenAt: null };
}
