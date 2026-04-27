import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const STORE_PATH = path.join(process.cwd(), 'data', 'persona', 'lucy-session.json');

function ensureDir() {
  fs.mkdirSync(path.dirname(STORE_PATH), { recursive: true });
}

function defaultMessages() {
  return [{
    id: crypto.randomUUID(),
    role: 'assistant',
    text: 'Hello. I am Lucy, the persona interface inside Emma. I can review system state, save your build paths, propose governed build pipelines, and execute approved steps.',
    createdAt: Date.now(),
  }];
}

function loadStore() {
  ensureDir();
  if (!fs.existsSync(STORE_PATH)) {
    const seed = { messages: defaultMessages() };
    fs.writeFileSync(STORE_PATH, JSON.stringify(seed, null, 2));
    return seed;
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(STORE_PATH, 'utf8'));
    if (!Array.isArray(parsed.messages)) throw new Error('invalid');
    return parsed;
  } catch {
    const seed = { messages: defaultMessages() };
    fs.writeFileSync(STORE_PATH, JSON.stringify(seed, null, 2));
    return seed;
  }
}

let store = loadStore();

function persist() {
  ensureDir();
  fs.writeFileSync(STORE_PATH, JSON.stringify(store, null, 2));
}

function createEntry(role, text) {
  return { id: crypto.randomUUID(), role, text, createdAt: Date.now() };
}

export function getLucySessionMessages() {
  return store.messages.map((entry) => ({ ...entry }));
}

export function appendLucyUserMessage(text) {
  const entry = createEntry('user', text);
  store.messages.push(entry);
  persist();
  return { ...entry };
}

export function appendLucyAssistantMessage(text) {
  const entry = createEntry('assistant', text);
  store.messages.push(entry);
  persist();
  return { ...entry };
}
