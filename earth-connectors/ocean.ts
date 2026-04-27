import { API_REGISTRY } from '../apiRegistry';
import type { ConnectorSnapshot } from '../earthState';

export async function fetchOceanPlaceholder(): Promise<ConnectorSnapshot<null>> {
  return {
    source: API_REGISTRY.ocean_noaa.label,
    connector: 'ocean_noaa',
    timestamp: Date.now(),
    ok: false,
    payload: null,
    error: 'inactive_connector',
  };
}
