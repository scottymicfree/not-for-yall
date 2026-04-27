import { getCache, setCache } from '../cache.js';
const BASE = 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best';
export async function getGibs() {
  const cached = getCache('gibs', 900000);
  if (cached) return { source: 'gibs', ok: true, data: cached, cached: true };
  try {
    const today = new Date().toISOString().slice(0,10);
    const layers = [
      { name: 'True Color', layer: 'MODIS_Terra_CorrectedReflectance_TrueColor' },
      { name: 'Thermal', layer: 'MODIS_Terra_Land_Surface_Temp_Day' },
      { name: 'Night Lights', layer: 'VIIRS_Black_Marble' },
      { name: 'Sea Surface Temp', layer: 'GHRSST_L4_MUR_Sea_Surface_Temperature' },
    ];
    const normalized = layers.map((entry) => ({
      type: 'imagery',
      provider: 'nasa-gibs',
      name: entry.name,
      layer: entry.layer,
      tileUrl: `${BASE}/${entry.layer}/default/${today}/250m/0/0/0.jpg`,
      date: today,
    }));
    setCache('gibs', normalized);
    return { source: 'gibs', ok: true, data: normalized };
  } catch (error) {
    return { source: 'gibs', ok: false, error: error instanceof Error ? error.message : 'build_failed', data: [] };
  }
}
