const trendMemory = [];
const MAX_TREND_POINTS = 20;

function round3(value) { return Number(value.toFixed(3)); }
function getLevel(value) {
  if (value >= 0.12) return 'warning';
  if (value >= 0.05) return 'watch';
  return 'normal';
}
function updateTrendMemory(point) {
  trendMemory.push(point);
  if (trendMemory.length > MAX_TREND_POINTS) trendMemory.shift();
  const latestDrift = point.driftIndex;
  const averageDrift = trendMemory.length === 0 ? 0 : round3(trendMemory.reduce((sum, entry) => sum + entry.driftIndex, 0) / trendMemory.length);
  let direction = 'stable';
  if (trendMemory.length >= 2) {
    const previous = trendMemory[trendMemory.length - 2].driftIndex;
    if (latestDrift > previous) direction = 'rising';
    if (latestDrift < previous) direction = 'falling';
  }
  return { points: trendMemory.map((entry) => ({ ...entry })), direction, averageDrift, latestDrift };
}
function buildGovernanceTrend(ledgerEntries, emmaReviews) {
  const now = Date.now();
  const recentWindowMs = 5 * 60 * 1000;
  const recentEntries = ledgerEntries.filter((entry) => now - entry.timestamp <= recentWindowMs).length;
  const approvalCount = emmaReviews.filter((review) => review.decision === 'approved').length;
  const rejectionCount = emmaReviews.filter((review) => review.decision === 'rejected').length;
  return { totalEntries: ledgerEntries.length, recentEntries, approvalCount, rejectionCount, reviewSpike: emmaReviews.length >= 5, ledgerBurst: recentEntries >= 3 };
}
export function detectSignals(earthBaseline, twinEarth, ledgerEntries = [], emmaReviews = []) {
  const simA = twinEarth.simA.earth;
  const simB = twinEarth.simB.earth;
  const stabilityDelta = round3(Math.abs(simB.stability - simA.stability));
  const climateDelta = round3(Math.abs(simB.climatePressure - simA.climatePressure));
  const seismicDelta = round3(Math.abs(simB.seismicPressure - simA.seismicPressure));
  const resourceDelta = round3(Math.abs(simB.resourceStrain - simA.resourceStrain));
  const driftIndex = round3((stabilityDelta + climateDelta + seismicDelta + resourceDelta) / 4);
  const trend = updateTrendMemory({ timestamp: earthBaseline.timestamp, driftIndex, stabilityDelta, climateDelta, seismicDelta, resourceDelta });
  const governance = buildGovernanceTrend(ledgerEntries, emmaReviews);
  const staleCount = earthBaseline.sourceHealth?.staleCount ?? 0;
  const missingCount = earthBaseline.sourceHealth?.missingCount ?? 0;
  const signals = [
    { key: 'stability-drift', level: getLevel(stabilityDelta), value: stabilityDelta, summary: `Stability drift is ${stabilityDelta}.` },
    { key: 'climate-drift', level: getLevel(climateDelta), value: climateDelta, summary: `Climate pressure drift is ${climateDelta}.` },
    { key: 'seismic-drift', level: getLevel(seismicDelta), value: seismicDelta, summary: `Seismic pressure drift is ${seismicDelta}.` },
    { key: 'resource-drift', level: getLevel(resourceDelta), value: resourceDelta, summary: `Resource strain drift is ${resourceDelta}.` },
    { key: 'composite-drift', level: getLevel(driftIndex), value: driftIndex, summary: `Composite Earth/Twin Earth drift is ${driftIndex}.` },
    { key: 'dataset-stale-count', level: staleCount >= 2 ? 'warning' : staleCount >= 1 ? 'watch' : 'normal', value: staleCount, summary: staleCount > 0 ? `${staleCount} Earth datasets are stale.` : 'Earth datasets freshness is normal.' },
    { key: 'dataset-missing-count', level: missingCount >= 1 ? 'warning' : 'normal', value: missingCount, summary: missingCount > 0 ? `${missingCount} Earth datasets are missing.` : 'No Earth datasets are missing.' },
    { key: 'governance-review-spike', level: governance.reviewSpike ? 'watch' : 'normal', value: governance.approvalCount + governance.rejectionCount, summary: governance.reviewSpike ? 'Governance review volume is elevated.' : 'Governance review volume is normal.' },
    { key: 'deltavault-write-burst', level: governance.ledgerBurst ? 'warning' : 'normal', value: governance.recentEntries, summary: governance.ledgerBurst ? 'DeltaVault write burst detected.' : 'DeltaVault write activity is normal.' },
    { key: 'emma-rejection-pattern', level: governance.rejectionCount >= 3 ? 'warning' : governance.rejectionCount >= 1 ? 'watch' : 'normal', value: governance.rejectionCount, summary: governance.rejectionCount >= 3 ? 'Emma rejection count is unusually high.' : governance.rejectionCount >= 1 ? 'Emma has recent rejections to review.' : 'Emma rejection pattern is normal.' },
  ];
  return {
    timestamp: Date.now(), driftIndex, stabilityDelta, climateDelta, seismicDelta, resourceDelta,
    signals, trend, governance,
    dataQuality: { freshCount: earthBaseline.sourceHealth?.freshCount ?? 0, staleCount, missingCount, isStale: earthBaseline.sourceHealth?.isStale ?? false, isMissing: earthBaseline.sourceHealth?.isMissing ?? false },
  };
}
