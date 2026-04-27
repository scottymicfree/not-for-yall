import { getCache, setCache } from '../cache.js';
const URL = 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson';
export async function getEarthquakes() {
  const cached = getCache('earthquakes', 300000);
  if (cached) return { source: 'earthquakes', ok: true, data: cached, cached: true };
  try {
    const res = await fetch(URL, { headers: { 'User-Agent': 'LucyEarth/1.0' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const normalized = Array.isArray(json?.features) ? json.features.map((f) => ({ type: 'earthquake', mag: f?.properties?.mag ?? null, place: f?.properties?.place ?? 'Unknown', lat: f?.geometry?.coordinates?.[1] ?? null, lon: f?.geometry?.coordinates?.[0] ?? null, depth: f?.geometry?.coordinates?.[2] ?? null, time: f?.properties?.time ?? null })) : [];
    setCache('earthquakes', normalized);
    return { source: 'earthquakes', ok: true, data: normalized };
  } catch (error) {
    return { source: 'earthquakes', ok: false, error: error instanceof Error ? error.message : 'fetch_failed', data: [] };
  }
}
