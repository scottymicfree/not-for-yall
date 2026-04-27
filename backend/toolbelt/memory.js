import fs from 'node:fs';
import path from 'node:path';

const STORE_PATH = path.join(process.cwd(), 'data', 'toolbelt', 'context.json');

const DEFAULT_STORE = {
  active: {
    userId: 'local-operator',
    activePackIds: [],
    mode: 'planning',
    timestamp: null,
    lastResolvedFrom: null,
  },
  history: [],
};

function ensureDir() {
  fs.mkdirSync(path.dirname(STORE_PATH), { recursive: true });
}

function loadStore() {
  ensureDir();
  if (!fs.existsSync(STORE_PATH)) {
    fs.writeFileSync(STORE_PATH, JSON.stringify(DEFAULT_STORE, null, 2));
    return structuredClone(DEFAULT_STORE);
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(STORE_PATH, 'utf8'));
    return {
      active: { ...DEFAULT_STORE.active, ...(parsed.active || {}) },
      history: Array.isArray(parsed.history) ? parsed.history : [],
    };
  } catch {
    fs.writeFileSync(STORE_PATH, JSON.stringify(DEFAULT_STORE, null, 2));
    return structuredClone(DEFAULT_STORE);
  }
}

function saveStore(store) {
  ensureDir();
  fs.writeFileSync(STORE_PATH, JSON.stringify(store, null, 2));
}

let cache = loadStore();

export function getActiveToolbeltContext() {
  return structuredClone(cache.active);
}

export function setActiveToolbeltContext({ userId = 'local-operator', activePackIds = [], mode = 'planning', lastResolvedFrom = null }) {
  cache.active = {
    userId,
    activePackIds: [...new Set(activePackIds.filter(Boolean))],
    mode,
    lastResolvedFrom,
    timestamp: Date.now(),
  };
  cache.history.unshift(structuredClone(cache.active));
  cache.history = cache.history.slice(0, 50);
  saveStore(cache);
  return getActiveToolbeltContext();
}
