import { loadLocalData } from './baseAdapter.js';

export function fetchEconomicsData() {
  return loadLocalData('economics.json');
}
