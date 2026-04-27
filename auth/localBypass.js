export function getLocalOperator() {
  return {
    id: 'local-operator',
    role: 'human-operator',
    approved: true,
    source: 'local-bypass',
  };
}

export function isLocalBypassEnabled() {
  return process.env.LOCAL_DEV_BYPASS === 'true';
}
