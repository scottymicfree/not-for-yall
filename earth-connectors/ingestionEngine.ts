import { listActiveApis } from './apiRegistry';
import { saveNormalizedEarthState, savePatternSummary, saveRawEarthSnapshots } from './cacheLayer';
import { type ConnectorSnapshot } from './earthState';
import { normalizeEarthState } from './normalizer';
import { detectPatterns } from './patternEngine';
import { fetchNASAGibsCatalog } from './connectors/nasa';
import { fetchNOAAWeather } from './connectors/noaa';
import { fetchOpenSky } from './connectors/opensky';
import { fetchOpenWeather } from './connectors/openweather';
import { fetchOceanPlaceholder } from './connectors/ocean';
import { fetchNOAASolar } from './connectors/swpc';
import { fetchCensusPlaceholder } from './connectors/census';
import { fetchEconomicsPlaceholder } from './connectors/economics';
import { fetchUSGSQuakes, fetchUSGSVolcano } from './connectors/usgs';

export interface EarthIngestionResult {
  snapshots: ConnectorSnapshot[];
  earthState: ReturnType<typeof normalizeEarthState>;
  patterns: ReturnType<typeof detectPatterns>;
}

export async function runEarthIngestion(openWeatherApiKey?: string): Promise<EarthIngestionResult> {
  const active = listActiveApis();
  const connectors: Array<Promise<ConnectorSnapshot>> = [
    fetchNOAAWeather(),
    fetchUSGSQuakes(),
    fetchUSGSVolcano(),
    fetchNOAASolar(),
    fetchOpenSky(),
    fetchNASAGibsCatalog(),
  ];

  // Register inactive/future connectors as snapshots so source health is still visible.
  if (active.find(item => item.id === 'openweather')) connectors.push(fetchOpenWeather(openWeatherApiKey));
  connectors.push(fetchOceanPlaceholder(), fetchCensusPlaceholder(), fetchEconomicsPlaceholder());

  const snapshots = await Promise.all(connectors);
  const earthState = normalizeEarthState(snapshots);
  const patterns = detectPatterns(earthState);
  earthState.patternSummary = patterns;

  saveRawEarthSnapshots(snapshots);
  saveNormalizedEarthState(earthState);
  savePatternSummary(patterns);

  return { snapshots, earthState, patterns };
}
