import type { EarthBaseline } from '../earth/fetchEarthBaseline.js';

export type TwinEarthState = {
  timestamp: number;
  simA: {
    mode: 'current-baseline';
    earth: EarthBaseline['earth'];
  };
  simB: {
    mode: 'accelerated-projection';
    earth: EarthBaseline['earth'];
  };
};

export function buildTwinEarthState(baseline: EarthBaseline): TwinEarthState {
  const { earth } = baseline;

  return {
    timestamp: Date.now(),
    simA: {
      mode: 'current-baseline',
      earth,
    },
    simB: {
      mode: 'accelerated-projection',
      earth: {
        stability: Number((earth.stability - 0.06).toFixed(3)),
        climatePressure: Number((earth.climatePressure + 0.09).toFixed(3)),
        seismicPressure: Number((earth.seismicPressure + 0.03).toFixed(3)),
        resourceStrain: Number((earth.resourceStrain + 0.08).toFixed(3)),
      },
    },
  };
}
