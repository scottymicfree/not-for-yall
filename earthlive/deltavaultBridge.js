import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOG_PATH = path.join(__dirname, 'deltavault.json');

export function logToDeltaVault(payload) {
  let logs = [];
  if (fs.existsSync(LOG_PATH)) {
    try { logs = JSON.parse(fs.readFileSync(LOG_PATH, 'utf8')); } catch { logs = []; }
  }
  logs.push({
    timestamp: payload.timestamp,
    count: payload.totalEvents,
    sources: payload.sources,
    sourceCounts: payload.sourceCounts,
    sourceHealth: payload.sourceHealth,
    missingCount: payload.missingCount,
  });
  fs.writeFileSync(LOG_PATH, JSON.stringify(logs.slice(-500), null, 2));
}