export type LocalOperator = {
  id: string;
  role: 'human-operator';
  approved: true;
  source: 'local-bypass';
};

export function getLocalOperator(): LocalOperator {
  return {
    id: 'local-operator',
    role: 'human-operator',
    approved: true,
    source: 'local-bypass',
  };
}

export function isLocalBypassEnabled(): boolean {
  return process.env.LOCAL_DEV_BYPASS === 'true';
}
