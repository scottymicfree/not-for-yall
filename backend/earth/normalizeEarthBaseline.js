function numberOr(value, fallback) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}
function buildSourceSummary(dataset) {
  if (dataset.freshness === 'missing') return `${dataset.source} dataset missing.`;
  if (dataset.freshness === 'stale') return `${dataset.source} dataset is stale.`;
  return `${dataset.source} dataset is fresh.`;
}
export function normalizeEarthBaseline(datasets) {
  const list = Object.values(datasets);
  const freshCount = list.filter((dataset) => dataset.freshness === 'fresh').length;
  const staleCount = list.filter((dataset) => dataset.freshness === 'stale').length;
  const missingCount = list.filter((dataset) => dataset.freshness === 'missing').length;

  const nasa = datasets.nasa?.data || {};
  const usgs = datasets.usgs?.data || {};
  const weather = datasets.weather?.data || {};
  const ocean = datasets.ocean?.data || {};
  const economics = datasets.economics?.data || {};

  const climatePressure = Number(Math.min(1,
    numberOr(weather.globalTempAnomaly, 0) / 2 +
    numberOr(ocean.seaSurfaceTempAnomaly, 0) / 3 +
    numberOr(ocean.acidityDelta, 0) / 2
  ).toFixed(3));

  const seismicPressure = Number(Math.min(1,
    numberOr(usgs.seismicEvents, 0) / 50 +
    numberOr(usgs.maxMagnitude, 0) / 10
  ).toFixed(3));

  const resourceStrain = Number(Math.min(1,
    numberOr(economics.currentEmissions, 0) / 200 +
    numberOr(economics.inflation, 0) / 10 +
    Math.max(0, numberOr(economics.gdpGrowth, 0) < 0 ? 0.2 : 0)
  ).toFixed(3));

  const anomalyPenalty = numberOr(nasa.anomalies, 0) > 0 ? Math.min(0.2, numberOr(nasa.anomalies, 0) * 0.05) : 0;
  const sourcePenalty = staleCount * 0.08 + missingCount * 0.16;

  const stability = Number(Math.max(0, 1 - (climatePressure * 0.35 + seismicPressure * 0.25 + resourceStrain * 0.25 + anomalyPenalty + sourcePenalty)).toFixed(3));

  return {
    timestamp: Date.now(),
    normalizedAt: new Date().toISOString(),
    datasets,
    sourceHealth: { freshCount, staleCount, missingCount, isStale: staleCount > 0, isMissing: missingCount > 0 },
    sources: {
      nasa: { status: datasets.nasa.freshness, summary: buildSourceSummary(datasets.nasa) },
      usgs: { status: datasets.usgs.freshness, summary: buildSourceSummary(datasets.usgs) },
      weather: { status: datasets.weather.freshness, summary: buildSourceSummary(datasets.weather) },
      ocean: { status: datasets.ocean.freshness, summary: buildSourceSummary(datasets.ocean) },
      economics: { status: datasets.economics.freshness, summary: buildSourceSummary(datasets.economics) },
    },
    earth: { stability, climatePressure, seismicPressure, resourceStrain },
  };
}
