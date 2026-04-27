import { getEarthquakes } from './sources/earthquakes.js';
import { getSolar } from './sources/solar.js';
import { getWeather } from './sources/weather.js';
import { getVolcano } from './sources/volcano.js';
import { getAircraft } from './sources/aircraft.js';
import { getGibs } from './sources/gibs.js';
import { normalizeLiveEarth } from './normalizeLiveEarth.js';
import { logToDeltaVault } from './deltavaultBridge.js';

let lastPayload = null;
let lastRunAt = 0;
const TTL = 120000;

export async function runIngestCycle(force = false) {
  if (!force && lastPayload && Date.now() - lastRunAt < TTL) return lastPayload;
  const results = await Promise.all([getEarthquakes(), getSolar(), getWeather(), getVolcano(), getAircraft(), getGibs()]);
  const payload = normalizeLiveEarth(results);
  logToDeltaVault(payload);
  lastPayload = payload;
  lastRunAt = Date.now();
  return payload;
}
