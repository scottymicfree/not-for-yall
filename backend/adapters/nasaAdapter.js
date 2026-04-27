import { loadLocalData } from './baseAdapter.js';

export function fetchNasaData() {
  return loadLocalData('nasa.json');
}
