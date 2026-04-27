import { API_REGISTRY } from '../apiRegistry';
import type { ConnectorSnapshot } from '../earthState';

const GIBS_LAYERS = [
  { label: 'True Color', url: 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/{date}/250m/{z}/{y}/{x}.jpg' },
  { label: 'Night Lights', url: 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/VIIRS_CityLights_2012/default/{date}/500m/{z}/{y}/{x}.jpg' },
  { label: 'Sea Surface Temp', url: 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/GHRSST_L4_MUR_Sea_Surface_Temperature/default/{date}/2km/{z}/{y}/{x}.png' },
];

export async function fetchNASAGibsCatalog(): Promise<ConnectorSnapshot<Array<{ label: string; url: string }>>> {
  return {
    source: API_REGISTRY.nasa_gibs.label,
    connector: 'nasa_gibs',
    timestamp: Date.now(),
    ok: true,
    payload: GIBS_LAYERS,
    error: null,
  };
}
