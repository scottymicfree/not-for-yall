import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { DEFAULT_TOOLBELT_PACKS } from './seedPacks.js';

const STORE_PATH = path.join(process.cwd(), 'data', 'toolbelt', 'registry.json');

function ensureDir() {
  fs.mkdirSync(path.dirname(STORE_PATH), { recursive: true });
}

function normalizePack(id, input = {}) {
  return {
    id,
    label: input.label || id,
    type: input.type || 'engine_docs',
    primary: input.primary || '',
    refs: Array.isArray(input.refs) ? input.refs.filter(Boolean) : [],
    tags: Array.isArray(input.tags) ? input.tags.filter(Boolean) : [],
    active: input.active !== false,
    sourceMode: input.sourceMode || 'human_curated',
    planningOnly: input.planningOnly !== false,
    version: input.version || null,
    createdAt: input.createdAt || Date.now(),
    updatedAt: Date.now(),
  };
}

function defaultStore() {
  const packs = Object.fromEntries(
    Object.entries(DEFAULT_TOOLBELT_PACKS).map(([id, pack]) => [id, normalizePack(id, pack)])
  );
  return { packs, updatedAt: new Date().toISOString() };
}

function loadStore() {
  ensureDir();
  if (!fs.existsSync(STORE_PATH)) {
    const seed = defaultStore();
    fs.writeFileSync(STORE_PATH, JSON.stringify(seed, null, 2));
    return seed;
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(STORE_PATH, 'utf8'));
    const merged = defaultStore();
    if (parsed && parsed.packs && typeof parsed.packs === 'object') {
      for (const [id, pack] of Object.entries(parsed.packs)) {
        merged.packs[id] = normalizePack(id, pack);
      }
    }
    return merged;
  } catch {
    const seed = defaultStore();
    fs.writeFileSync(STORE_PATH, JSON.stringify(seed, null, 2));
    return seed;
  }
}

function saveStore(store) {
  ensureDir();
  store.updatedAt = new Date().toISOString();
  fs.writeFileSync(STORE_PATH, JSON.stringify(store, null, 2));
}

let cache = loadStore();

export function listToolbeltPacks() {
  return Object.values(cache.packs).sort((a, b) => a.label.localeCompare(b.label)).map((pack) => structuredClone(pack));
}

export function getToolbeltPack(packId) {
  const found = cache.packs[packId];
  return found ? structuredClone(found) : null;
}

export function upsertToolbeltPack(packInput) {
  const id = (packInput.id || packInput.label || crypto.randomUUID()).toString().trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_');
  const current = cache.packs[id] || { createdAt: Date.now() };
  const next = normalizePack(id, { ...current, ...packInput, createdAt: current.createdAt || Date.now() });
  cache.packs[id] = next;
  saveStore(cache);
  return structuredClone(next);
}
