import { API_REGISTRY } from './apiRegistry';
import { createEmptyEarthState, type ConnectorSnapshot, type EarthStateModel, type SourceHealthRecord } from './earthState';

function healthState(snapshot: ConnectorSnapshot, active: boolean): SourceHealthRecord['state'] {
  if (!active) return 'inactive';
  return snapshot.ok ? 'live' : 'failed';
}

export function normalizeEarthState(snapshots: ConnectorSnapshot[]): EarthStateModel {
  const state = createEmptyEarthState();
  const now = Date.now();
  state.timestamp = now;

  for (const snapshot of snapshots) {
    const meta = API_REGISTRY[snapshot.connector];
    state.sourceHealth[snapshot.connector] = {
      connector: snapshot.connector,
      label: meta?.label || snapshot.source,
      category: meta?.category || 'signals',
      state: healthState(snapshot, Boolean(meta?.active)),
      authRequired: Boolean(meta?.authRequired),
      active: Boolean(meta?.active),
      lastOkAt: snapshot.ok ? snapshot.timestamp : undefined,
      lastAttemptAt: snapshot.timestamp,
      error: snapshot.error,
    };

    if (!snapshot.ok || !snapshot.payload) continue;

    if (snapshot.connector === 'usgs_quakes') {
      const features = Array.isArray((snapshot.payload as any)?.features) ? (snapshot.payload as any).features : [];
      state.seismic.events = features.map((f: any, index: number) => ({
        id: f.id || `quake-${index}`,
        magnitude: Number(f?.properties?.mag ?? 0),
        place: f?.properties?.place || 'Unknown location',
        depth: Number(f?.geometry?.coordinates?.[2] ?? 0),
        longitude: Number(f?.geometry?.coordinates?.[0] ?? 0),
        latitude: Number(f?.geometry?.coordinates?.[1] ?? 0),
        time: Number(f?.properties?.time ?? now),
        url: f?.properties?.url,
      })).sort((a, b) => b.magnitude - a.magnitude);
    }

    if (snapshot.connector === 'usgs_volcano') {
      const rawItems = Array.isArray(snapshot.payload)
        ? (snapshot.payload as any[])
        : Array.isArray((snapshot.payload as any)?.features)
          ? (snapshot.payload as any).features.map((f: any) => f.properties || {})
          : [];
      state.volcano.events = rawItems.map((item: any, index: number) => ({
        id: item.id || item.volcanoId || `volcano-${index}`,
        name: item.name || item.volcanoName || 'Unknown volcano',
        status: item.status || item.activity || 'unknown',
        alertLevel: item.alertLevel || item.alertlevel || item.alert_level,
        volcanoType: item.type || item.volcanoType,
        latitude: item.latitude,
        longitude: item.longitude,
      }));
    }

    if (snapshot.connector === 'noaa_weather') {
      const periods = Array.isArray((snapshot.payload as any)?.properties?.periods) ? (snapshot.payload as any).properties.periods : [];
      const first = periods[0] || {};
      state.weather = {
        source: 'NOAA Weather.gov',
        temperature: first?.temperature != null ? Number(first.temperature) : undefined,
        shortForecast: first?.shortForecast,
        windSpeed: first?.windSpeed,
      };
    }

    if (snapshot.connector === 'noaa_swpc') {
      const entries = Array.isArray(snapshot.payload) ? (snapshot.payload as any[]) : [];
      const latest = entries[entries.length - 1] || {};
      state.signals.solar = {
        speed: latest?.speed != null ? Number(latest.speed) : undefined,
        density: latest?.density != null ? Number(latest.density) : undefined,
        temperature: latest?.temperature != null ? Number(latest.temperature) : undefined,
        sourceTime: latest?.time_tag,
      };
    }

    if (snapshot.connector === 'opensky') {
      const states = Array.isArray((snapshot.payload as any)?.states) ? (snapshot.payload as any).states : [];
      state.aircraft = {
        count: states.length,
        sample: states.slice(0, 12).map((entry: any[]) => ({
          callsign: entry?.[1]?.trim?.(),
          country: entry?.[2],
          longitude: entry?.[5],
          latitude: entry?.[6],
          velocity: entry?.[9],
        })),
      };
    }

    if (snapshot.connector === 'nasa_gibs') {
      state.satellites.imageryLayers = Array.isArray(snapshot.payload) ? snapshot.payload as any : [];
    }
  }

  return state;
}
