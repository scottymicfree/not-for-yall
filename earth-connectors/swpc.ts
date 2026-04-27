import { API_REGISTRY } from '../apiRegistry';
import type { ConnectorSnapshot } from '../earthState';

export async function fetchNOAASolar(): Promise<ConnectorSnapshot<any>> {
  try {
    const response = await fetch(API_REGISTRY.noaa_swpc.url, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    return { source: API_REGISTRY.noaa_swpc.label, connector: 'noaa_swpc', timestamp: Date.now(), ok: true, payload, error: null };
  } catch (error: any) {
    return { source: API_REGISTRY.noaa_swpc.label, connector: 'noaa_swpc', timestamp: Date.now(), ok: false, payload: null, error: error?.message || 'fetch_failed' };
  }
}
