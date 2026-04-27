export type EmmaDecision = 'approved' | 'rejected';

export type EmmaApprovalInput = {
  type: string;
  payload: unknown;
};

export type EmmaApprovalLevel = 'low' | 'medium' | 'high';

export type EmmaApprovalResult = {
  decision: EmmaDecision;
  level: EmmaApprovalLevel;
  reason: string;
  approvedAt: number;
};

function hasType(input: EmmaApprovalInput): boolean {
  return typeof input.type === 'string' && input.type.trim().length > 0;
}

function isObjectLike(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function classifyLevel(input: EmmaApprovalInput): EmmaApprovalLevel {
  const type = input.type.trim().toLowerCase();

  if (type.includes('twinearth') || type.includes('projection') || type.includes('analysis')) {
    return 'low';
  }

  if (type.includes('config') || type.includes('settings') || type.includes('review')) {
    return 'medium';
  }

  return 'high';
}

function validateByLevel(
  level: EmmaApprovalLevel,
  input: EmmaApprovalInput,
): { ok: boolean; reason: string } {
  if (level === 'low') {
    return {
      ok: true,
      reason: `Emma approved low-risk action type "${input.type}".`,
    };
  }

  if (!isObjectLike(input.payload)) {
    return {
      ok: false,
      reason: `Emma rejected ${level}-risk action "${input.type}" because payload must be an object.`,
    };
  }

  const operatorVisible = input.payload.operatorVisible === true;
  const requestedBy = typeof input.payload.requestedBy === 'string' && input.payload.requestedBy.length > 0;

  if (level === 'medium') {
    if (!operatorVisible) {
      return {
        ok: false,
        reason: `Emma rejected medium-risk action "${input.type}" because operatorVisible=true is required.`,
      };
    }

    return {
      ok: true,
      reason: `Emma approved medium-risk action "${input.type}" with operator-visible handling.`,
    };
  }

  if (!operatorVisible || !requestedBy) {
    return {
      ok: false,
      reason:
        `Emma rejected high-risk action "${input.type}" because operatorVisible=true and requestedBy are required.`,
    };
  }

  return {
    ok: true,
    reason: `Emma approved high-risk action "${input.type}" with explicit operator trace.`,
  };
}

export function reviewAction(input: EmmaApprovalInput): EmmaApprovalResult {
  if (!hasType(input)) {
    return {
      decision: 'rejected',
      level: 'high',
      reason: 'Action type is required.',
      approvedAt: Date.now(),
    };
  }

  const level = classifyLevel(input);
  const validation = validateByLevel(level, input);

  return {
    decision: validation.ok ? 'approved' : 'rejected',
    level,
    reason: validation.reason,
    approvedAt: Date.now(),
  };
}
