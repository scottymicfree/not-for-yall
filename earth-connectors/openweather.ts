import { API_REGISTRY } from '../apiRegistry';
import type { ConnectorSnapshot } from '../earthState';

export async function fetchOpenWeather(apiKey?: string): Promise<ConnectorSnapshot<any>> {
  if (!apiKey) {
    return {
      source: API_REGISTRY.openweather.label,
      connector: 'openweather',
      timestamp: Date.now(),
      ok: false,
      payload: null,
      error: 'api_key_missing',
    };
  }

  try {
    const response = await fetch(`${API_REGISTRY.openweather.url}?q=Chicago&appid=${encodeURIComponent(apiKey)}&units=imperial`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    return { source: API_REGISTRY.openweather.label, connector: 'openweather', timestamp: Date.now(), ok: true, payload, error: null };
  } catch (error: any) {
    return { source: API_REGISTRY.openweather.label, connector: 'openweather', timestamp: Date.now(), ok: false, payload: null, error: error?.message || 'fetch_failed' };
  }
}
