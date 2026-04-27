import fs from 'node:fs';
import path from 'node:path';

function classifyFreshness(timestamp) {
  const parsed = new Date(timestamp || 0).getTime();
  if (!Number.isFinite(parsed) || parsed <= 0) return 'missing';
  const ageMs = Date.now() - parsed;
  const oneDayMs = 24 * 60 * 60 * 1000;
  return ageMs > oneDayMs ? 'stale' : 'fresh';
}

export function loadLocalData(filename) {
  const filePath = path.join(process.cwd(), 'data', 'earth', filename);
  try {
    if (!fs.existsSync(filePath)) {
      return { source: filename.replace('.json', ''), timestamp: new Date().toISOString(), freshness: 'missing', data: null, error: 'File not found' };
    }
    const raw = fs.readFileSync(filePath, 'utf-8');
    const parsed = JSON.parse(raw);
    return {
      source: filename.replace('.json', ''),
      timestamp: parsed.timestamp || new Date().toISOString(),
      freshness: classifyFreshness(parsed.timestamp),
      data: parsed.data || null,
      error: undefined,
    };
  } catch (error) {
    return {
      source: filename.replace('.json', ''),
      timestamp: new Date().toISOString(),
      freshness: 'missing',
      data: null,
      error: error instanceof Error ? error.message : 'Unknown adapter error',
    };
  }
}
