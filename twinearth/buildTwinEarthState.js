import { getEarth2Status } from '../earth2/earth2Adapter.js';

export function buildTwinEarthState(baseline, liveEarth = null) {
  const { earth } = baseline;
  const quakePressure = Math.min(0.25, ((liveEarth?.sourceCounts?.earthquakes ?? 0) / 40) * 0.1);
  const volcanoPressure = Math.min(0.18, ((liveEarth?.sourceCounts?.volcano ?? 0) / 12) * 0.08);
  const solarPressure = Math.min(0.12, ((liveEarth?.sourceCounts?.solar ?? 0) / 4) * 0.03);
  const weatherPressure = Math.min(0.16, ((liveEarth?.sourceCounts?.weather ?? 0) / 8) * 0.05);
  const livePressure = Number((quakePressure + volcanoPressure + solarPressure + weatherPressure).toFixed(3));
  const earth2 = getEarth2Status();
  const simBStability = Math.max(0, earth.stability - 0.04 - livePressure);
  return {
    timestamp: Date.now(),
    simA: { mode: 'current-baseline', earth, livePressure },
    simB: {
      mode: 'accelerated-projection',
      earth: {
        stability: Number(simBStability.toFixed(3)),
        climatePressure: Number(Math.min(1, earth.climatePressure + 0.06 + weatherPressure).toFixed(3)),
        seismicPressure: Number(Math.min(1, earth.seismicPressure + 0.03 + quakePressure + volcanoPressure).toFixed(3)),
        resourceStrain: Number(Math.min(1, earth.resourceStrain + 0.05 + solarPressure).toFixed(3)),
      },
      sources: {
        livePressure,
        weatherPressure,
        quakePressure,
        volcanoPressure,
        solarPressure,
      },
    },
    earth2: {
      enabled: earth2.enabled,
      configured: earth2.configured,
      summary: earth2.summary,
      forecast: earth2.forecast,
      lastRun: earth2.lastRun,
    },
  };
}
