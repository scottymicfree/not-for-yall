import { API_REGISTRY } from '../apiRegistry';
import type { ConnectorSnapshot } from '../earthState';

export async function fetchEconomicsPlaceholder(): Promise<ConnectorSnapshot<null>> {
  return {
    source: API_REGISTRY.fred.label,
    connector: 'fred',
    timestamp: Date.now(),
    ok: false,
    payload: null,
    error: 'inactive_connector',
  };
}
