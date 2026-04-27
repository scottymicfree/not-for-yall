import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT = path.join(__dirname, 'lastForecast.json');

export function getEarth2Status() {
  const configured = Boolean(process.env.LUCY_EARTH2_ENABLED === '1' || process.env.LUCY_EARTH2_BRIDGE);
  const bridge = process.env.LUCY_EARTH2_BRIDGE || 'earth2studio';
  let latestRun = null;
  if (fs.existsSync(OUTPUT)) {
    try { latestRun = JSON.parse(fs.readFileSync(OUTPUT, 'utf8')); } catch {}
  }
  return {
    configured,
    enabled: configured,
    bridge,
    localOnly: true,
    lastRun: latestRun?.timestamp ?? null,
    hasForecast: Boolean(latestRun),
    summary: latestRun?.summary ?? (configured
      ? 'Earth-2 bridge configured but no cached forecast found.'
      : 'Earth-2 slot available. Set LUCY_EARTH2_ENABLED=1 and connect a local Earth2Studio bridge.'),
    forecast: latestRun?.forecast ?? null,
  };
}

export function saveEarth2Forecast(payload) {
  fs.writeFileSync(OUTPUT, JSON.stringify(payload, null, 2));
}