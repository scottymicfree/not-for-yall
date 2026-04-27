import fs from 'node:fs';
import path from 'node:path';

const STORE_PATH = path.join(process.cwd(), 'data', 'control', 'user-config.json');

const DEFAULT_CONFIG = {
  current: {
    ue5Path: '',
    unityPath: '',
    blenderPath: '',
    godotPath: '',
    projectPath: '',
    fivemRoot: '',
    handbookUrls: {
      fivemPrimary: '',
      fivemFirstScript: '',
      fivemFxmanifest: '',
      fivemNatives: '',
      fivemCommunity: '',
    },
  },
  updatedAt: null,
};

function ensureDir() {
  fs.mkdirSync(path.dirname(STORE_PATH), { recursive: true });
}

function loadStore() {
  ensureDir();
  if (!fs.existsSync(STORE_PATH)) {
    fs.writeFileSync(STORE_PATH, JSON.stringify(DEFAULT_CONFIG, null, 2));
    return structuredClone(DEFAULT_CONFIG);
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(STORE_PATH, 'utf8'));
    return {
      ...DEFAULT_CONFIG,
      ...parsed,
      current: {
        ...DEFAULT_CONFIG.current,
        ...(parsed.current || {}),
        handbookUrls: {
          ...DEFAULT_CONFIG.current.handbookUrls,
          ...((parsed.current && parsed.current.handbookUrls) || {}),
        },
      },
    };
  } catch {
    fs.writeFileSync(STORE_PATH, JSON.stringify(DEFAULT_CONFIG, null, 2));
    return structuredClone(DEFAULT_CONFIG);
  }
}

function saveStore(store) {
  ensureDir();
  fs.writeFileSync(STORE_PATH, JSON.stringify(store, null, 2));
}

let cache = loadStore();

export function getUserConfig() {
  return structuredClone(cache.current);
}

export function setUserConfig(updates) {
  cache = {
    ...cache,
    current: {
      ...cache.current,
      ...updates,
      handbookUrls: {
        ...cache.current.handbookUrls,
        ...(updates.handbookUrls || {}),
      },
    },
    updatedAt: new Date().toISOString(),
  };
  saveStore(cache);
  return getUserConfig();
}

export function setHandbookUrls(updates) {
  return setUserConfig({ handbookUrls: updates });
}

export function getUserConfigSnapshot() {
  return structuredClone(cache);
}
