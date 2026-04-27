import { loadLocalData } from './baseAdapter.js';

export function fetchUsgsData() {
  return loadLocalData('usgs.json');
}
