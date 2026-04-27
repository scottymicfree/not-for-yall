import { fetchNasaData } from '../adapters/nasaAdapter.js';
import { fetchUsgsData } from '../adapters/usgsAdapter.js';
import { fetchWeatherData } from '../adapters/weatherAdapter.js';
import { fetchOceanData } from '../adapters/oceanAdapter.js';
import { fetchEconomicsData } from '../adapters/economicsAdapter.js';
import { normalizeEarthBaseline } from './normalizeEarthBaseline.js';

export async function fetchEarthBaseline() {
  const datasets = {
    nasa: fetchNasaData(),
    usgs: fetchUsgsData(),
    weather: fetchWeatherData(),
    ocean: fetchOceanData(),
    economics: fetchEconomicsData(),
  };
  return normalizeEarthBaseline(datasets);
}
