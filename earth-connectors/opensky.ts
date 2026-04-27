import { API_REGISTRY } from '../apiRegistry';
import type { ConnectorSnapshot } from '../earthState';

export async function fetchOpenSky(): Promise<ConnectorSnapshot<any>> {
  try {
    const response = await fetch(API_REGISTRY.opensky.url, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    return { source: API_REGISTRY.opensky.label, connector: 'opensky', timestamp: Date.now(), ok: true, payload, error: null };
  } catch (error: any) {
    return { source: API_REGISTRY.opensky.label, connector: 'opensky', timestamp: Date.now(), ok: false, payload: null, error: error?.message || 'fetch_failed' };
  }
}
