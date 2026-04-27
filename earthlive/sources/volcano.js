import { getCache, setCache } from '../cache.js';
const URL = 'https://volcanoes.usgs.gov/hans-public/api/volcano/getMonitoredVolcanoes';
export async function getVolcano() {
  const cached = getCache('volcano', 300000);
  if (cached) return { source: 'volcano', ok: true, data: cached, cached: true };
  try {
    const res = await fetch(URL, { headers: { 'User-Agent': 'LucyEarth/1.0' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const items = Array.isArray(json) ? json : Array.isArray(json?.features) ? json.features : Array.isArray(json?.monitoredVolcanoes) ? json.monitoredVolcanoes : [];
    const normalized = items.slice(0, 20).map((item) => ({
      type: 'volcano',
      name: item?.volcanoName ?? item?.name ?? item?.properties?.name ?? 'Unknown',
      status: item?.activityStatus ?? item?.status ?? item?.properties?.status ?? 'Unknown',
      alert: item?.alertLevel ?? item?.alertlevel ?? item?.properties?.alertLevel ?? 'Unknown',
      lat: item?.latitude ?? item?.lat ?? item?.properties?.latitude ?? null,
      lon: item?.longitude ?? item?.lon ?? item?.properties?.longitude ?? null,
    }));
    setCache('volcano', normalized);
    return { source: 'volcano', ok: true, data: normalized };
  } catch (error) {
    return { source: 'volcano', ok: false, error: error instanceof Error ? error.message : 'fetch_failed', data: [] };
  }
}
