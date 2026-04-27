import { getCache, setCache } from '../cache.js';
const URL = 'https://opensky-network.org/api/states/all';
export async function getAircraft() {
  const cached = getCache('aircraft', 180000);
  if (cached) return { source: 'aircraft', ok: true, data: cached, cached: true };
  try {
    const res = await fetch(URL, { headers: { 'User-Agent': 'LucyEarth/1.0' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const states = Array.isArray(json?.states) ? json.states.slice(0, 25) : [];
    const normalized = states.map((state) => ({
      type: 'aircraft',
      callsign: state?.[1]?.trim?.() || 'UNKNOWN',
      originCountry: state?.[2] ?? 'Unknown',
      lon: state?.[5] ?? null,
      lat: state?.[6] ?? null,
      altitude: state?.[7] ?? null,
      velocity: state?.[9] ?? null,
    }));
    setCache('aircraft', normalized);
    return { source: 'aircraft', ok: true, data: normalized };
  } catch (error) {
    return { source: 'aircraft', ok: false, error: error instanceof Error ? error.message : 'fetch_failed', data: [] };
  }
}
