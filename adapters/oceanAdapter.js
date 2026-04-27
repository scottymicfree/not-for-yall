import { loadLocalData } from './baseAdapter.js';

export function fetchOceanData() {
  return loadLocalData('ocean.json');
}
