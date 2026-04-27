import { getCache, setCache } from '../cache.js';
const URL = 'https://services.swpc.noaa.gov/json/rtsw.json';
export async function getSolar() {
  const cached = getCache('solar', 300000);
  if (cached) return { source: 'solar', ok: true, data: cached, cached: true };
  try {
    const res = await fetch(URL, { headers: { 'User-Agent': 'LucyEarth/1.0' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const latest = Array.isArray(json) && json.length > 0 ? json[json.length - 1] : null;
    const normalized = latest ? [{ type: 'solar', speed: Number(latest.speed ?? 0), density: Number(latest.density ?? 0), temperature: Number(latest.temperature ?? 0), time_tag: latest.time_tag ?? null }] : [];
    setCache('solar', normalized);
    return { source: 'solar', ok: true, data: normalized };
  } catch (error) {
    return { source: 'solar', ok: false, error: error instanceof Error ? error.message : 'fetch_failed', data: [] };
  }
}
