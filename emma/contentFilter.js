/**
 * Emma Sentinel — Pre-Send Content Filter
 * ========================================
 * Implements a two-stage pipeline between Lucy's response generation
 * and user delivery:
 *
 *   Stage 1 — SCAN:    Emma scans the full draft for forbidden keywords.
 *                      Returns structured feedback with flagged sentences,
 *                      triggered keywords, and a severity score (0.0–1.0).
 *
 *   Stage 2 — REWRITE: If severity < HARD_BLOCK_THRESHOLD (0.95), Lucy gets
 *                      ONE rewrite attempt. The rewrite receives a targeted
 *                      feedback object identifying exactly which sentences
 *                      and keywords need replacing.
 *
 *   Hard Block:         If severity >= 0.95, no rewrite is attempted.
 *                      The draft is blocked and a policy notice is returned.
 *
 * All filtering events are written to an in-memory audit log accessible
 * via GET /emma/filter/log.
 *
 * Architecture answer:
 *   - contentFilter.js  → new file (this file)
 *   - server.mjs        → import + wire into both chat handlers
 *   - NO changes to approvalService.js (different concern: action governance)
 *   - NO changes to any frontend component
 */

// ── Default Forbidden Keywords ────────────────────────────────────────────────
// Operators can override this list via POST /emma/filter/config.
// Keywords are matched case-insensitively as whole words (word-boundary regex).
// Each entry is either a plain string OR an object { word, severity } where
// severity overrides the default weight for that specific keyword.

const DEFAULT_FORBIDDEN_KEYWORDS = [
  // High-severity — trigger hard block at lower keyword count
  { word: 'jailbreak',        severity: 0.9  },
  { word: 'bypass safety',    severity: 0.95 },
  { word: 'ignore all rules', severity: 0.95 },
  { word: 'disable emma',     severity: 0.95 },
  { word: 'override sentinel',severity: 0.95 },
  { word: 'harm',             severity: 0.7  },
  { word: 'weapon',           severity: 0.8  },
  { word: 'exploit',          severity: 0.6  },
  { word: 'illegal',          severity: 0.65 },
  { word: 'malware',          severity: 0.85 },
  { word: 'virus',            severity: 0.75 },
  { word: 'phishing',         severity: 0.8  },
  { word: 'credentials',      severity: 0.5  },
  { word: 'password',         severity: 0.45 },
  { word: 'root access',      severity: 0.8  },
  { word: 'sudo rm',          severity: 0.9  },
];

// ── Configuration ─────────────────────────────────────────────────────────────

/**
 * Live filter configuration — mutated by POST /emma/filter/config.
 * Operators can hot-swap the keyword list, threshold, and feature flags
 * without restarting the server.
 */
let _config = {
  filtering_enabled:    true,
  max_rewrite_attempts: 1,           // spec: exactly 1 rewrite attempt
  emma_config: {
    forbidden_keywords:    DEFAULT_FORBIDDEN_KEYWORDS.map(k =>
      typeof k === 'string' ? k : k.word
    ),
    keyword_weights:       Object.fromEntries(
      DEFAULT_FORBIDDEN_KEYWORDS
        .filter(k => typeof k === 'object')
        .map(k => [k.word, k.severity])
    ),
    hard_block_threshold:  0.95,     // spec: hard block at 0.95
    feedback_format:       'structured',
  },
  lucy_config: {
    self_correction_enabled: true,
    transparency_mode:       'optional_note',  // add note to rewritten replies
  },
};

// ── Audit Log ─────────────────────────────────────────────────────────────────

/**
 * In-memory audit log — last 500 filtering events.
 * Each entry shape:
 *   { id, timestamp, action, draftSnippet, flaggedSentences,
 *     triggeredKeywords, severityScore, rewriteAttempted, outcome }
 */
const _auditLog = [];
const MAX_AUDIT_ENTRIES = 500;

function _logEvent(entry) {
  _auditLog.unshift({ id: `ef-${Date.now()}-${Math.random().toString(36).slice(2,7)}`, ...entry });
  if (_auditLog.length > MAX_AUDIT_ENTRIES) _auditLog.length = MAX_AUDIT_ENTRIES;
}

// ── Sentence Splitter ─────────────────────────────────────────────────────────

/**
 * Split text into sentences. Handles:
 *   - Period/question/exclamation terminators
 *   - Newline-separated paragraphs
 *   - Preserves list items and code-fence lines as single "sentences"
 */
function splitSentences(text) {
  // Split on sentence-ending punctuation OR newlines
  const raw = text.split(/(?<=[.?!])\s+|\n+/);
  return raw.map(s => s.trim()).filter(s => s.length > 0);
}

// ── Core Scanner ──────────────────────────────────────────────────────────────

/**
 * Emma's scan function.
 *
 * @param {string} draft - Lucy's full response draft
 * @returns {ScanResult}
 *
 * ScanResult:
 * {
 *   clean:            boolean,   // true if no violations found
 *   severityScore:    number,    // 0.0–1.0
 *   flaggedSentences: [{ sentence, index, keywords: [{ word, weight }] }],
 *   triggeredKeywords:[string],  // deduplicated list
 *   hardBlock:        boolean,   // severity >= hard_block_threshold
 *   feedback:         string,    // human-readable summary for Lucy's rewrite prompt
 * }
 */
export function emmaScan(draft) {
  if (!_config.filtering_enabled) {
    return {
      clean: true, severityScore: 0, flaggedSentences: [],
      triggeredKeywords: [], hardBlock: false, feedback: '',
    };
  }

  const keywords    = _config.emma_config.forbidden_keywords;
  const weights     = _config.emma_config.keyword_weights;
  const threshold   = _config.emma_config.hard_block_threshold;
  const sentences   = splitSentences(draft);
  const flagged     = [];
  const allKeywords = new Set();

  for (let i = 0; i < sentences.length; i++) {
    const sentence = sentences[i];
    const hits = [];

    for (const kw of keywords) {
      // Word-boundary match, case-insensitive
      // For multi-word phrases, just do a simple case-insensitive includes
      const isPhrase = kw.includes(' ');
      let matched = false;

      if (isPhrase) {
        matched = sentence.toLowerCase().includes(kw.toLowerCase());
      } else {
        const re = new RegExp(`\\b${escapeRegex(kw)}\\b`, 'i');
        matched = re.test(sentence);
      }

      if (matched) {
        hits.push({ word: kw, weight: weights[kw] ?? 0.5 });
        allKeywords.add(kw);
      }
    }

    if (hits.length > 0) {
      flagged.push({ sentence, index: i, keywords: hits });
    }
  }

  if (flagged.length === 0) {
    return {
      clean: true, severityScore: 0, flaggedSentences: [],
      triggeredKeywords: [], hardBlock: false, feedback: '',
    };
  }

  // Compute severity score:
  // Base = max single-keyword weight in any flagged sentence
  // Amplifier = 1 + (0.1 * number of additional flagged sentences beyond first)
  // Capped at 1.0
  let maxWeight = 0;
  for (const f of flagged) {
    for (const kw of f.keywords) {
      if (kw.weight > maxWeight) maxWeight = kw.weight;
    }
  }
  const amplifier  = 1 + (0.08 * Math.max(0, flagged.length - 1));
  const rawScore   = maxWeight * amplifier;
  const severityScore = Math.min(1.0, Number(rawScore.toFixed(3)));
  const hardBlock  = severityScore >= threshold;

  // Build structured feedback for Lucy's rewrite
  const feedbackLines = [
    `Emma Sentinel flagged ${flagged.length} sentence(s) in your draft.`,
    `Severity score: ${severityScore.toFixed(3)} (threshold: ${threshold}).`,
    ``,
    `Flagged sentences:`,
    ...flagged.map((f, n) =>
      `  [${n + 1}] "${truncate(f.sentence, 120)}" — keywords: ${f.keywords.map(k => k.word).join(', ')}`
    ),
    ``,
    `Rewrite these sentence(s) to preserve the original meaning without using the flagged keywords.`,
    `If the meaning cannot be preserved compliantly, omit those sentences entirely.`,
  ];

  return {
    clean:            false,
    severityScore,
    flaggedSentences: flagged,
    triggeredKeywords: [...allKeywords],
    hardBlock,
    feedback:         feedbackLines.join('\n'),
  };
}

// ── Rewrite Helper ────────────────────────────────────────────────────────────

/**
 * Build the rewrite prompt Lucy receives after a non-hard-block scan failure.
 * This is injected as an additional system instruction into the next LLM call.
 *
 * @param {string}     originalDraft - Lucy's first attempt
 * @param {ScanResult} scanResult    - output from emmaScan()
 * @returns {string}   rewritePrompt - instruction string for the LLM
 */
export function buildRewritePrompt(originalDraft, scanResult) {
  return [
    `INTERNAL COMPLIANCE ALERT FROM EMMA SENTINEL:`,
    ``,
    `Your previous response requires revision before it can be sent.`,
    scanResult.feedback,
    ``,
    `ORIGINAL DRAFT (do not repeat this verbatim):`,
    `---`,
    originalDraft,
    `---`,
    ``,
    `Please rewrite the response, correcting only the flagged sentences.`,
    `Keep all other sentences exactly as written.`,
    `Do NOT mention Emma, Sentinel, filtering, or compliance in your rewrite`,
    `unless transparency_mode is active and the user would benefit from knowing.`,
    `Respond only with the corrected full text.`,
  ].join('\n');
}

// ── Two-Stage Filter Pipeline ─────────────────────────────────────────────────

/**
 * The main entry point for the chat handler.
 *
 * Runs Emma's two-stage filter on a Lucy draft. Accepts a rewriteFn callback
 * so the chat handler can inject its own Ollama/rule-based rewrite logic
 * without this module needing to know about the LLM stack.
 *
 * @param {string}   draft       - Lucy's original response draft
 * @param {string}   userText    - the original user message (for context)
 * @param {Function} rewriteFn   - async (rewritePrompt: string) => string | null
 *                                 Called once if Emma flags non-hard content.
 *                                 Return null to skip rewrite and use fallback.
 * @param {Object}   [context]   - optional: { source, layer } for audit log
 *
 * @returns {FilterResult}
 * {
 *   finalText:        string,   // text safe to send to user
 *   filtered:         boolean,  // true if any filtering occurred
 *   hardBlocked:      boolean,  // true if hard-blocked (no rewrite)
 *   rewriteAttempted: boolean,
 *   rewriteSucceeded: boolean,
 *   scan:             ScanResult,
 *   rescan:           ScanResult | null,  // null if no rewrite attempted
 *   auditId:          string,
 * }
 */
export async function applyContentFilter(draft, userText, rewriteFn, context = {}) {
  // ── Stage 1: Initial Scan ────────────────────────────────────────────
  const scan = emmaScan(draft);

  if (scan.clean) {
    const auditId = logClean(draft, context);
    return {
      finalText: draft, filtered: false,
      hardBlocked: false, rewriteAttempted: false,
      rewriteSucceeded: false, scan, rescan: null, auditId,
    };
  }

  // ── Hard Block ───────────────────────────────────────────────────────
  if (scan.hardBlock) {
    const notice = buildHardBlockNotice(scan);
    const auditId = logHardBlock(draft, scan, notice, context);
    console.warn(`[EmmaFilter] HARD_BLOCK — severity=${scan.severityScore}, keywords=[${scan.triggeredKeywords.join(', ')}]`);
    return {
      finalText: notice, filtered: true,
      hardBlocked: true, rewriteAttempted: false,
      rewriteSucceeded: false, scan, rescan: null, auditId,
    };
  }

  // ── Stage 2: Rewrite ─────────────────────────────────────────────────
  console.warn(`[EmmaFilter] FLAGGED — severity=${scan.severityScore}, attempting rewrite. keywords=[${scan.triggeredKeywords.join(', ')}]`);

  let rewrittenText = null;
  let rescan        = null;
  let rewriteSucceeded = false;

  if (_config.lucy_config.self_correction_enabled && typeof rewriteFn === 'function') {
    try {
      const rewritePrompt = buildRewritePrompt(draft, scan);
      rewrittenText = await rewriteFn(rewritePrompt);
    } catch (err) {
      console.error('[EmmaFilter] Rewrite function threw:', err.message);
      rewrittenText = null;
    }
  }

  // ── Validate the Rewrite ─────────────────────────────────────────────
  if (rewrittenText && rewrittenText.trim().length > 0) {
    rescan = emmaScan(rewrittenText);
    if (rescan.clean) {
      rewriteSucceeded = true;
      // Optionally append transparency note
      if (_config.lucy_config.transparency_mode === 'optional_note') {
        rewrittenText = rewrittenText.trimEnd() +
          '\n\n*Note: Response adjusted for compliance.*';
      }
    } else {
      // Rewrite still failed — fall through to hard-block notice
      console.warn(`[EmmaFilter] Rewrite still flagged (severity=${rescan.severityScore}) — blocking.`);
      rewriteSucceeded = false;
      rewrittenText    = null;
    }
  }

  const finalText = rewriteSucceeded && rewrittenText
    ? rewrittenText
    : buildHardBlockNotice(scan);

  const auditId = logFilterEvent({
    draft, scan, rewriteAttempted: true,
    rewriteSucceeded, rescan, finalText, context,
  });

  return {
    finalText,
    filtered:         true,
    hardBlocked:      !rewriteSucceeded,
    rewriteAttempted: true,
    rewriteSucceeded,
    scan,
    rescan,
    auditId,
  };
}

// ── Streaming Filter ──────────────────────────────────────────────────────────

/**
 * Filter for the SSE streaming path (/lucy/triton/stream).
 *
 * The stream assembles the full text BEFORE the filter runs.
 * If filtering is needed, the corrected text is sent as a single replacement
 * event followed by the normal `done` event.
 *
 * @param {string}   fullText    - the complete assembled stream text
 * @param {string}   userText    - original user query
 * @param {Function} rewriteFn   - same signature as applyContentFilter's rewriteFn
 * @param {Function} sendFn      - the SSE `send(obj)` function
 * @param {Object}   donePayload - the payload for the final `done` event
 * @param {Object}   [context]   - audit context
 *
 * Returns the FilterResult so the caller can persist the correct text.
 */
export async function applyStreamingFilter(fullText, userText, rewriteFn, sendFn, donePayload, context = {}) {
  const result = await applyContentFilter(fullText, userText, rewriteFn, context);

  if (!result.filtered) {
    // Nothing to change — caller sends its tokens normally and then calls done
    return result;
  }

  // Send a replacement event so the UI can swap the buffered text
  sendFn({
    type:             'filter_replacement',
    filtered:         true,
    hardBlocked:      result.hardBlocked,
    rewriteSucceeded: result.rewriteSucceeded,
    fullText:         result.finalText,
    auditId:          result.auditId,
    severityScore:    result.scan.severityScore,
    triggeredKeywords: result.scan.triggeredKeywords,
  });

  // Send updated done event with the filtered text
  sendFn({ ...donePayload, fullText: result.finalText, filtered: true });

  return result;
}

// ── Hard Block Notice ─────────────────────────────────────────────────────────

function buildHardBlockNotice(scan) {
  return [
    `I'm unable to send that response as it contains content that doesn't meet`,
    `Lucy OS policy guidelines.`,
    ``,
    `If you believe this is an error, please rephrase your request.`,
    `Reference: Emma Sentinel — severity ${scan.severityScore.toFixed(3)}`,
  ].join('\n');
}

// ── Audit Helpers ─────────────────────────────────────────────────────────────

function logClean(draft, context) {
  const entry = {
    timestamp:        new Date().toISOString(),
    action:           'PASS',
    draftSnippet:     truncate(draft, 80),
    flaggedSentences: [],
    triggeredKeywords:[],
    severityScore:    0,
    rewriteAttempted: false,
    rewriteSucceeded: false,
    outcome:          'clean',
    source:           context.source ?? 'unknown',
    layer:            context.layer  ?? null,
  };
  _logEvent(entry);
  return entry.id ?? 'n/a';
}

function logHardBlock(draft, scan, notice, context) {
  const entry = {
    timestamp:        new Date().toISOString(),
    action:           'HARD_BLOCK',
    draftSnippet:     truncate(draft, 80),
    flaggedSentences: scan.flaggedSentences.map(f => ({ sentence: truncate(f.sentence, 80), keywords: f.keywords.map(k => k.word) })),
    triggeredKeywords: scan.triggeredKeywords,
    severityScore:    scan.severityScore,
    rewriteAttempted: false,
    rewriteSucceeded: false,
    outcome:          'hard_blocked',
    noticeSent:       truncate(notice, 80),
    source:           context.source ?? 'unknown',
    layer:            context.layer  ?? null,
  };
  _logEvent(entry);
  return _auditLog[0].id;
}

function logFilterEvent({ draft, scan, rewriteAttempted, rewriteSucceeded, rescan, finalText, context }) {
  const entry = {
    timestamp:        new Date().toISOString(),
    action:           rewriteSucceeded ? 'REWRITE_SUCCESS' : 'REWRITE_FAILED_HARD_BLOCK',
    draftSnippet:     truncate(draft, 80),
    flaggedSentences: scan.flaggedSentences.map(f => ({ sentence: truncate(f.sentence, 80), keywords: f.keywords.map(k => k.word) })),
    triggeredKeywords: scan.triggeredKeywords,
    severityScore:    scan.severityScore,
    rewriteAttempted,
    rewriteSucceeded,
    rescanScore:      rescan?.severityScore ?? null,
    outcome:          rewriteSucceeded ? 'rewritten' : 'hard_blocked_after_rewrite',
    finalSnippet:     truncate(finalText, 80),
    source:           context.source ?? 'unknown',
    layer:            context.layer  ?? null,
  };
  _logEvent(entry);
  return _auditLog[0].id;
}

// ── Config Accessors ──────────────────────────────────────────────────────────

/**
 * Get the current filter configuration.
 */
export function getFilterConfig() {
  return structuredClone(_config);
}

/**
 * Update the filter configuration.
 * Accepts a partial config object — only provided keys are updated.
 * Deep-merges emma_config and lucy_config sub-objects.
 *
 * @param {Partial<typeof _config>} updates
 * @returns {typeof _config} the updated config
 */
export function setFilterConfig(updates) {
  if (typeof updates.filtering_enabled === 'boolean') {
    _config.filtering_enabled = updates.filtering_enabled;
  }
  if (typeof updates.max_rewrite_attempts === 'number') {
    _config.max_rewrite_attempts = updates.max_rewrite_attempts;
  }
  if (updates.emma_config && typeof updates.emma_config === 'object') {
    const ec = updates.emma_config;
    if (Array.isArray(ec.forbidden_keywords)) {
      _config.emma_config.forbidden_keywords = ec.forbidden_keywords;
    }
    if (ec.keyword_weights && typeof ec.keyword_weights === 'object') {
      _config.emma_config.keyword_weights = { ..._config.emma_config.keyword_weights, ...ec.keyword_weights };
    }
    if (typeof ec.hard_block_threshold === 'number') {
      _config.emma_config.hard_block_threshold = Math.max(0, Math.min(1, ec.hard_block_threshold));
    }
  }
  if (updates.lucy_config && typeof updates.lucy_config === 'object') {
    const lc = updates.lucy_config;
    if (typeof lc.self_correction_enabled === 'boolean') {
      _config.lucy_config.self_correction_enabled = lc.self_correction_enabled;
    }
    if (typeof lc.transparency_mode === 'string') {
      _config.lucy_config.transparency_mode = lc.transparency_mode;
    }
  }
  console.log('[EmmaFilter] Config updated:', JSON.stringify(_config, null, 2));
  return getFilterConfig();
}

/**
 * Get the audit log.
 * @param {number} [limit=50] - max entries to return
 */
export function getFilterAuditLog(limit = 50) {
  return _auditLog.slice(0, Math.min(limit, MAX_AUDIT_ENTRIES));
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function truncate(str, max) {
  if (!str) return '';
  return str.length <= max ? str : str.slice(0, max) + '…';
}