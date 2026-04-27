import { loadLocalData } from './baseAdapter.js';

export function fetchWeatherData() {
  return loadLocalData('weather.json');
}
