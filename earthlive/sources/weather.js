import { getCache, setCache } from '../cache.js';
const URL = 'https://api.weather.gov/gridpoints/LOT/74,75/forecast';
export async function getWeather() {
  const cached = getCache('weather', 300000);
  if (cached) return { source: 'weather', ok: true, data: cached, cached: true };
  try {
    const res = await fetch(URL, { headers: { 'User-Agent': 'LucyEarth/1.0', 'Accept': 'application/geo+json, application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const periods = Array.isArray(json?.properties?.periods) ? json.properties.periods.slice(0, 4) : [];
    const normalized = periods.map((p) => ({ type: 'weather', name: p?.name ?? 'Period', temp: p?.temperature ?? null, tempUnit: p?.temperatureUnit ?? 'F', windSpeed: p?.windSpeed ?? null, forecast: p?.shortForecast ?? 'Unavailable', isDaytime: !!p?.isDaytime }));
    setCache('weather', normalized);
    return { source: 'weather', ok: true, data: normalized };
  } catch (error) {
    return { source: 'weather', ok: false, error: error instanceof Error ? error.message : 'fetch_failed', data: [] };
  }
}
