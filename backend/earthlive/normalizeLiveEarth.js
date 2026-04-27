function summarize(data) {
  const first = Array.isArray(data) && data.length ? data[0] : null;
  if (!first) return 'Unavailable';
  if (first.type === 'earthquake') return `Top quake M${first.mag ?? '—'} · ${first.place ?? 'Unknown'}`;
  if (first.type === 'solar') return `Solar wind ${Math.round(first.speed ?? 0)} km/s`; 
  if (first.type === 'weather') return `${first.name ?? 'Now'} ${first.temp ?? '—'}°${first.tempUnit ?? 'F'} · ${first.forecast ?? 'Unavailable'}`;
  if (first.type === 'volcano') return `${first.name ?? 'Unknown'} · ${first.alert ?? first.status ?? 'Unknown'}`;
  if (first.type === 'aircraft') return `${data.length} aircraft sampled`; 
  if (first.type === 'imagery') return `${first.provider ?? 'imagery'} layers ready`; 
  return first.type;
}

export function normalizeLiveEarth(sourceResults) {
  const data = sourceResults.flatMap((result) => Array.isArray(result.data) ? result.data : []);
  const sources = sourceResults.map((result) => result.source);
  const sourceHealth = Object.fromEntries(sourceResults.map((result) => [result.source, result.ok ? 'ok' : 'fail']));
  const sourceCounts = Object.fromEntries(sourceResults.map((result) => [result.source, Array.isArray(result.data) ? result.data.length : 0]));
  const sourceSummaries = Object.fromEntries(sourceResults.map((result) => [result.source, summarize(result.data)]));
  const sourceErrors = Object.fromEntries(sourceResults.filter((result) => !result.ok).map((result) => [result.source, result.error || 'fetch_failed']));
  const missingCount = sourceResults.filter((result) => !result.ok).length;
  const staleCount = 0;
  const hazardSummary = {
    earthquakes: sourceCounts.earthquakes ?? 0,
    volcano: sourceCounts.volcano ?? 0,
    weather: sourceCounts.weather ?? 0,
    solar: sourceCounts.solar ?? 0,
    aircraft: sourceCounts.aircraft ?? 0,
    imagery: sourceCounts.gibs ?? 0,
  };
  return { timestamp: new Date().toISOString(), totalEvents: data.length, sources, sourceHealth, sourceCounts, sourceSummaries, sourceErrors, staleCount, missingCount, hazardSummary, data };
}
