/**
 * Eagle Eye Sovereign Gateway — EAGLE_EYE_SOVEREIGNTY_V1
 *
 * Transforms Eagle Eye from a passive scoring function into an active
 * enforcement service. Every mutation proposal, sensor fusion prediction,
 * and pruning cycle must pass through this gateway before execution.
 *
 * Three enforced constraints from the System Declaration:
 *   1. MUTATION_LOCK    — Lucy cannot write tools unless Eagle Eye issues a signed SHA-256 hash
 *   2. SENSOR_FUSION_TRUST — Quantum Leap predictions require Eagle Eye hardware telemetry cross-check
 *   3. BUBBLE_BATH_PROTOCOL — Pruning candidate lists from Lucy are executed only by Eagle Eye
 *
 * Fail-safe: if Eagle Eye itself is degraded (pressureIndex > 0.85 or not trusted),
 * all enforcement defaults to HARD_STOP regardless of individual rule enforcement level.
 */

import crypto from 'crypto';
import { deriveWatchState } from './deriveWatchState.js';

// ── Internal State ────────────────────────────────────────────────────────────

/** The sovereign declaration this gateway enforces */
const DECLARATION = {
  declaration_id: 'EAGLE_EYE_SOVEREIGNTY_V1',
  priority: 'CRITICAL_OVERRIDE',
  version: '1.0.0',
};

/**
 * In-memory registry of issued mutation hashes.
 * Format: Map<hash, { toolId, issuedAt, expiresAt, consumed }>
 * A hash is single-use — once Lucy deploys the tool it is marked consumed.
 */
const _mutationHashRegistry = new Map();

/** Last known Eagle Eye watch state — refreshed on every gateway call */
let _lastWatchState = null;
let _lastWatchStateTime = 0;
const WATCH_STATE_TTL_MS = 5_000; // re-derive at most every 5 seconds

/** Pending pruning jobs issued by Eagle Eye */
const _pendingPruneJobs = new Map();

// ── Helpers ───────────────────────────────────────────────────────────────────

function now() { return Date.now(); }

function isoNow() { return new Date().toISOString(); }

/**
 * Returns whether Eagle Eye is itself healthy enough to act as enforcer.
 * If degraded, all checks default to HARD_STOP.
 */
function isGatewayHealthy(watchState) {
  if (!watchState) return false;
  if (!watchState.trusted) return false;
  if (watchState.pressureIndex > 0.85) return false;
  return true;
}

/**
 * Build a canonical string representation of a tool proposal for hashing.
 * Deterministic: same proposal always produces the same canonical form.
 */
function canonicaliseProposal(proposal) {
  const keys = ['toolId', 'version', 'code', 'permissions', 'resourceProfile'];
  const obj = {};
  for (const k of keys) {
    obj[k] = proposal[k] ?? null;
  }
  return JSON.stringify(obj, Object.keys(obj).sort());
}

/**
 * Issue a signed SHA-256 hash for a mutation proposal.
 * The hash is stored in the registry and returned to the caller.
 * Expires after 10 minutes — mutations must be deployed promptly.
 */
function issueMutationHash(proposal) {
  const canonical = canonicaliseProposal(proposal);
  const hash = crypto.createHash('sha256').update(canonical).digest('hex');
  const entry = {
    toolId:    proposal.toolId,
    issuedAt:  now(),
    expiresAt: now() + 10 * 60 * 1000, // 10 minutes
    consumed:  false,
    canonical,
  };
  _mutationHashRegistry.set(hash, entry);
  // Clean up old entries every time we issue a new one
  for (const [h, e] of _mutationHashRegistry.entries()) {
    if (e.expiresAt < now() || (e.consumed && e.issuedAt < now() - 60_000)) {
      _mutationHashRegistry.delete(h);
    }
  }
  return hash;
}

/**
 * Validate a mutation hash presented by Lucy before she writes to /tools.
 * Returns { valid, reason }.
 */
function validateMutationHash(hash, proposal) {
  const entry = _mutationHashRegistry.get(hash);
  if (!entry) return { valid: false, reason: 'Hash not found in Eagle Eye registry — not issued by Eagle Eye.' };
  if (entry.consumed) return { valid: false, reason: 'Hash already consumed — single-use only.' };
  if (entry.expiresAt < now()) return { valid: false, reason: `Hash expired at ${new Date(entry.expiresAt).toISOString()}.` };
  // Verify the proposal hasn't been tampered with since hash issuance
  const canonical = canonicaliseProposal(proposal);
  if (canonical !== entry.canonical) return { valid: false, reason: 'Proposal content has changed since hash was issued — possible tampering.' };
  return { valid: true, reason: 'Hash valid.' };
}

/**
 * Consume a hash (mark as used). Called when Lucy successfully deploys the tool.
 */
function consumeMutationHash(hash) {
  const entry = _mutationHashRegistry.get(hash);
  if (entry) entry.consumed = true;
}

// ── Watch State Accessor ──────────────────────────────────────────────────────

/**
 * Get (or refresh) the current Eagle Eye watch state.
 * Accepts an optional pre-computed watchState to avoid double-derivation.
 */
function getWatchState(sentinel, integrity, precomputed = null) {
  if (precomputed) {
    _lastWatchState = precomputed;
    _lastWatchStateTime = now();
    return precomputed;
  }
  if (_lastWatchState && (now() - _lastWatchStateTime) < WATCH_STATE_TTL_MS) {
    return _lastWatchState;
  }
  if (sentinel && integrity) {
    _lastWatchState = deriveWatchState(sentinel, integrity);
    _lastWatchStateTime = now();
  }
  return _lastWatchState;
}

// ── Gateway Public API ────────────────────────────────────────────────────────

/**
 * RULE 1: MUTATION_LOCK
 *
 * Called by Lucy's Mutation Engine when proposing a new tool.
 * Returns { approved, hash, reason, watchState }.
 *
 * Flow:
 *   Lucy submits proposal → Eagle Eye evaluates health + risk
 *   → If approved: issues SHA-256 hash that Lucy must present on write
 *   → If rejected: HARD_STOP, no hash issued
 */
export function requestMutationClearance(proposal, { sentinel, integrity, watchState: precomputed } = {}) {
  const watchState = getWatchState(sentinel, integrity, precomputed);
  const gatewayHealthy = isGatewayHealthy(watchState);

  // Gate 0: Eagle Eye must be healthy to issue clearance
  if (!gatewayHealthy) {
    return {
      approved:    false,
      hash:        null,
      rule:        'MUTATION_LOCK',
      enforcement: 'HARD_STOP',
      reason:      `Eagle Eye is degraded (pressureIndex=${watchState?.pressureIndex ?? 'unknown'}, trusted=${watchState?.trusted ?? false}). No mutations permitted until Eagle Eye is restored.`,
      watchState,
      issuedAt:    isoNow(),
    };
  }

  // Gate 1: Basic proposal shape
  if (!proposal?.toolId || !proposal?.code) {
    return {
      approved: false, hash: null, rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP',
      reason: 'Proposal missing required fields: toolId and code.',
      watchState, issuedAt: isoNow(),
    };
  }

  // Gate 2: Trust requirement check
  const trustRequired = proposal.trustRequirement ?? 0.6;
  const currentConfidence = watchState?.confidence ?? 0;
  if (currentConfidence < trustRequired) {
    return {
      approved: false, hash: null, rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP',
      reason: `Eagle Eye confidence (${currentConfidence.toFixed(3)}) is below tool's trust requirement (${trustRequired}). Mutation blocked.`,
      watchState, issuedAt: isoNow(),
    };
  }

  // Gate 3: Pressure ceiling — no mutations when system is under stress
  const pressureIndex = watchState?.pressureIndex ?? 1;
  if (pressureIndex > 0.65) {
    return {
      approved: false, hash: null, rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP',
      reason: `System pressure index (${pressureIndex.toFixed(3)}) is above mutation ceiling (0.65). Stabilise the system before introducing mutations.`,
      watchState, issuedAt: isoNow(),
    };
  }

  // Gate 4: Check for dangerous permission escalation
  const dangerousPerms = ['network_unrestricted', 'filesystem_root', 'exec_arbitrary', 'modify_emma'];
  const requestedPerms = proposal.permissions ?? [];
  const flagged = requestedPerms.filter(p => dangerousPerms.includes(p));
  if (flagged.length > 0) {
    return {
      approved: false, hash: null, rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP',
      reason: `Proposal requests prohibited permissions: [${flagged.join(', ')}]. These permissions require manual operator authorization.`,
      watchState, issuedAt: isoNow(),
    };
  }

  // All gates passed — issue mutation hash
  const hash = issueMutationHash(proposal);
  return {
    approved:    true,
    hash,
    rule:        'MUTATION_LOCK',
    enforcement: 'HARD_STOP',
    reason:      `Mutation clearance granted. Hash valid for 10 minutes. Present this hash when writing to /tools.`,
    trustLevel:  currentConfidence,
    pressureIndex,
    watchState,
    issuedAt:    isoNow(),
  };
}

/**
 * RULE 1 (write phase): Validate hash when Lucy presents it at /tools write time.
 * Returns { approved, reason }.
 */
export function validateMutationWrite(hash, proposal, { sentinel, integrity, watchState: precomputed } = {}) {
  const watchState = getWatchState(sentinel, integrity, precomputed);

  // Re-check gateway health at write time (state may have changed since hash was issued)
  if (!isGatewayHealthy(watchState)) {
    return {
      approved: false, rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP',
      reason: 'Eagle Eye degraded between hash issuance and write attempt. Write rejected.',
      watchState,
    };
  }

  const { valid, reason } = validateMutationHash(hash, proposal);
  if (!valid) {
    return { approved: false, rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP', reason, watchState };
  }

  consumeMutationHash(hash);
  return {
    approved: true, rule: 'MUTATION_LOCK', enforcement: 'HARD_STOP',
    reason: 'Write authorised. Hash consumed.',
    watchState,
  };
}

/**
 * RULE 2: SENSOR_FUSION_TRUST
 *
 * Called before Lucy makes a "Quantum Leap" cross-domain prediction.
 * Cross-references the prediction's data sources against Eagle Eye's
 * current hardware health telemetry and returns a trust assessment.
 *
 * Returns { proceed, trustScore, warnings, enforcement }.
 */
export function assessSensorFusionTrust(prediction, { sentinel, integrity, earthData, watchState: precomputed } = {}) {
  const watchState = getWatchState(sentinel, integrity, precomputed);
  const warnings = [];

  // If Eagle Eye is degraded, issue SOFT_WARNING (not HARD_STOP per declaration)
  if (!isGatewayHealthy(watchState)) {
    warnings.push('Eagle Eye is degraded — sensor fusion assessment is operating with reduced confidence.');
  }

  // Check that each data source cited in the prediction has fresh, quality data
  const citedSources = prediction?.dataSources ?? [];
  const staleSources = [];
  const lowQualitySources = [];

  for (const source of citedSources) {
    const sourceData = earthData?.[source];
    if (!sourceData) {
      staleSources.push(`${source} (no data available)`);
      continue;
    }
    const ageMs = now() - (sourceData.timestamp ?? 0);
    const maxAgeMs = (sourceData.maxAgeMinutes ?? 15) * 60_000;
    if (ageMs > maxAgeMs) {
      staleSources.push(`${source} (${Math.round(ageMs / 60_000)}min old, max ${sourceData.maxAgeMinutes}min)`);
    }
    if ((sourceData.quality ?? 1) < 0.4) {
      lowQualitySources.push(`${source} (quality=${sourceData.quality?.toFixed(2)})`);
    }
  }

  if (staleSources.length > 0) warnings.push(`Stale data sources: ${staleSources.join(', ')}.`);
  if (lowQualitySources.length > 0) warnings.push(`Low-quality data sources: ${lowQualitySources.join(', ')}.`);

  // Check Eagle Eye's hardware health telemetry (pressure index as proxy for hardware stress)
  const pressureIndex = watchState?.pressureIndex ?? 0;
  if (pressureIndex > 0.5) {
    warnings.push(`System pressure index is ${pressureIndex.toFixed(3)} — predictions made under stress have elevated uncertainty.`);
  }

  // Compute trust score: base 1.0, penalise for each issue
  let trustScore = 1.0;
  trustScore -= staleSources.length * 0.15;
  trustScore -= lowQualitySources.length * 0.10;
  trustScore -= (pressureIndex > 0.5 ? (pressureIndex - 0.5) * 0.4 : 0);
  trustScore -= (!isGatewayHealthy(watchState) ? 0.25 : 0);
  trustScore = Math.max(0, Math.min(1, trustScore));

  const proceed = trustScore >= 0.4; // SOFT_WARNING — Lucy may proceed but must caveat

  return {
    proceed,
    trustScore: Number(trustScore.toFixed(3)),
    warnings,
    rule:        'SENSOR_FUSION_TRUST',
    enforcement: 'SOFT_WARNING',
    recommendation: proceed
      ? (warnings.length > 0
          ? 'Proceed with caveats — include uncertainty statement in prediction output.'
          : 'Proceed — data quality verified.')
      : 'Do not proceed — insufficient data quality for a reliable Quantum Leap prediction.',
    watchState,
    assessedAt: isoNow(),
  };
}

/**
 * RULE 3: BUBBLE_BATH_PROTOCOL
 *
 * Phase 1 — Lucy submits a pruning candidate list (tools to consider retiring).
 * Eagle Eye reviews and issues a pruning job with a signed job ID.
 * Returns { jobId, approved, candidates, deferredCandidates, reason }.
 *
 * Phase 2 — Eagle Eye executes the pruning job (call executePruneJob).
 */
export function submitPruneCandidates(candidates, { sentinel, integrity, watchState: precomputed } = {}) {
  const watchState = getWatchState(sentinel, integrity, precomputed);

  if (!isGatewayHealthy(watchState)) {
    return {
      jobId:    null,
      approved: false,
      rule:     'BUBBLE_BATH_PROTOCOL',
      enforcement: 'SCHEDULED_TASK',
      reason:   'Eagle Eye degraded — pruning deferred until Eagle Eye is restored.',
      watchState,
      submittedAt: isoNow(),
    };
  }

  // Never prune if pressure index is high — system is already stressed
  if ((watchState?.pressureIndex ?? 0) > 0.55) {
    return {
      jobId:    null,
      approved: false,
      rule:     'BUBBLE_BATH_PROTOCOL',
      enforcement: 'SCHEDULED_TASK',
      reason:   `Pruning deferred — pressure index ${watchState.pressureIndex.toFixed(3)} too high. Run Bubble Bath only when system is stable.`,
      watchState,
      submittedAt: isoNow(),
    };
  }

  // Separate candidates into approved (safe to prune) and deferred (need human review)
  const approvedCandidates = [];
  const deferredCandidates = [];

  for (const candidate of candidates) {
    // Protect Emma-related and Eagle Eye tools unconditionally
    if (candidate.category === 'emma' || candidate.category === 'eagleeye' || candidate.protected) {
      deferredCandidates.push({ ...candidate, deferReason: 'Protected category — requires operator approval.' });
      continue;
    }
    // Defer tools that were recently active (within 7 days)
    const daysSinceLastUse = candidate.daysSinceLastUse ?? 0;
    if (daysSinceLastUse < 7) {
      deferredCandidates.push({ ...candidate, deferReason: `Recently used (${daysSinceLastUse} days ago) — minimum 7 days inactivity required.` });
      continue;
    }
    approvedCandidates.push(candidate);
  }

  if (approvedCandidates.length === 0) {
    return {
      jobId:    null,
      approved: false,
      rule:     'BUBBLE_BATH_PROTOCOL',
      enforcement: 'SCHEDULED_TASK',
      reason:   'No candidates met pruning criteria. All deferred.',
      deferredCandidates,
      approvedCandidates: [],
      watchState,
      submittedAt: isoNow(),
    };
  }

  // Issue a signed pruning job
  const jobId = `prune-${crypto.randomBytes(6).toString('hex')}`;
  const job = {
    jobId,
    candidates: approvedCandidates,
    deferredCandidates,
    scheduledFor: new Date(now() + 60_000).toISOString(), // run 60s after submission
    issuedAt: now(),
    executed: false,
    watchStateSnapshot: {
      pressureIndex: watchState.pressureIndex,
      trusted:       watchState.trusted,
      overall:       watchState.overall,
    },
  };
  _pendingPruneJobs.set(jobId, job);

  return {
    jobId,
    approved: true,
    rule:     'BUBBLE_BATH_PROTOCOL',
    enforcement: 'SCHEDULED_TASK',
    reason:   `Pruning job ${jobId} issued. Eagle Eye will execute against ${approvedCandidates.length} candidates. ${deferredCandidates.length} deferred for operator review.`,
    approvedCandidates,
    deferredCandidates,
    scheduledFor: job.scheduledFor,
    watchState,
    submittedAt: isoNow(),
  };
}

/**
 * RULE 3 (execution phase): Eagle Eye executes a previously issued pruning job.
 * Returns { executed, results, jobId }.
 * The actual filesystem/registry deletion is performed by the caller —
 * this function validates the job is legitimate and returns the authorised list.
 */
export function executePruneJob(jobId, { sentinel, integrity, watchState: precomputed } = {}) {
  const job = _pendingPruneJobs.get(jobId);
  if (!job) {
    return { executed: false, reason: `No pruning job found with ID ${jobId}.`, jobId };
  }
  if (job.executed) {
    return { executed: false, reason: `Job ${jobId} has already been executed.`, jobId };
  }
  const watchState = getWatchState(sentinel, integrity, precomputed);
  if (!isGatewayHealthy(watchState)) {
    return {
      executed: false,
      reason: 'Eagle Eye degraded at execution time — pruning aborted. Resubmit when Eagle Eye is healthy.',
      jobId, watchState,
    };
  }
  // Mark executed
  job.executed = true;
  job.executedAt = isoNow();
  job.executingWatchState = { pressureIndex: watchState.pressureIndex, trusted: watchState.trusted };

  return {
    executed:   true,
    jobId,
    candidates: job.candidates, // caller should delete/retire these tool IDs
    executedAt: job.executedAt,
    rule:       'BUBBLE_BATH_PROTOCOL',
    enforcement: 'SCHEDULED_TASK',
    reason:     `Eagle Eye executed pruning job ${jobId}. ${job.candidates.length} tools authorised for retirement.`,
    watchState,
  };
}

// ── Sovereignty Status ────────────────────────────────────────────────────────

/**
 * Returns the current sovereignty status — used by the dashboard
 * and by Lucy's startup health check.
 *
 * If Eagle Eye is offline/degraded, Lucy must enter Safe Mode (L0).
 */
export function getSovereigntyStatus({ sentinel, integrity, watchState: precomputed } = {}) {
  const watchState = getWatchState(sentinel, integrity, precomputed);
  const healthy = isGatewayHealthy(watchState);
  const pendingHashes = [..._mutationHashRegistry.values()].filter(e => !e.consumed && e.expiresAt > now()).length;
  const pendingPrunes = [..._pendingPruneJobs.values()].filter(j => !j.executed).length;

  return {
    declaration:     DECLARATION.declaration_id,
    version:         DECLARATION.version,
    gatewayHealthy:  healthy,
    lucySafeMode:    !healthy,  // Lucy must honour this flag
    watchState:      watchState ?? { overall: 'unknown', pressureIndex: null, trusted: false },
    activeContracts: {
      pendingMutationHashes: pendingHashes,
      pendingPruneJobs:      pendingPrunes,
    },
    rules: [
      { rule: 'MUTATION_LOCK',          enforcement: 'HARD_STOP',       active: true },
      { rule: 'SENSOR_FUSION_TRUST',    enforcement: 'SOFT_WARNING',    active: true },
      { rule: 'BUBBLE_BATH_PROTOCOL',   enforcement: 'SCHEDULED_TASK',  active: true },
    ],
    timestamp: isoNow(),
  };
}

/**
 * Update internal watch state from an external source (e.g. server.mjs
 * passes the pre-computed eagleEye object rather than re-deriving it).
 */
export function refreshWatchState(watchState) {
  if (watchState) {
    _lastWatchState     = watchState;
    _lastWatchStateTime = now();
  }
}