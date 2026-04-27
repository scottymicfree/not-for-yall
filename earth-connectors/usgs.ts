import { API_REGISTRY } from '../apiRegistry';
import type { ConnectorSnapshot } from '../earthState';

async function fetchJson<T>(connector: keyof typeof API_REGISTRY, url: string): Promise<ConnectorSnapshot<T>> {
  try {
    const response = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = (await response.json()) as T;
    return { source: API_REGISTRY[connector].label, connector, timestamp: Date.now(), ok: true, payload, error: null };
  } catch (error: any) {
    return { source: API_REGISTRY[connector].label, connector, timestamp: Date.now(), ok: false, payload: null, error: error?.message || 'fetch_failed' };
  }
}

export function fetchUSGSQuakes() {
  return fetchJson<any>('usgs_quakes', API_REGISTRY.usgs_quakes.url);
}

export function fetchUSGSVolcano() {
  return fetchJson<any>('usgs_volcano', API_REGISTRY.usgs_volcano.url);
}
