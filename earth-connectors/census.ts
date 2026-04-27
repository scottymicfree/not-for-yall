import { API_REGISTRY } from '../apiRegistry';
import type { ConnectorSnapshot } from '../earthState';

export async function fetchCensusPlaceholder(): Promise<ConnectorSnapshot<null>> {
  return {
    source: API_REGISTRY.census.label,
    connector: 'census',
    timestamp: Date.now(),
    ok: false,
    payload: null,
    error: 'inactive_connector',
  };
}
