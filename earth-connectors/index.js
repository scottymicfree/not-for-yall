/**
 * Lucy Earth Connectors — Zero-API-Key Sources
 * ==============================================
 * All sources here are FREE and require no API key.
 * Lucy can use these immediately after install.
 *
 * Each connector returns a normalized object:
 * { source, timestamp, data, error }
 */

const TIMEOUT_MS = 8000;

async function safeFetch(url, opts = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) return { error: `HTTP ${res.status}` };
    return await res.json();
  } catch (err) {
    clearTimeout(timer);
    return { error: err.name === 'AbortError' ? 'timeout' : err.message };
  }
}

// ════════════════════════════════════════════════════════════════════════════
// 1. USGS EARTHQUAKES (real-time, updates every 1-5 min)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchEarthquakes(timeRange = 'hour', minMag = 'all') {
  // timeRange: hour | day | week | month
  // minMag: all | 1.0 | 2.5 | 4.5 | significant
  const url = `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/${minMag}_${timeRange}.geojson`;
  const data = await safeFetch(url);
  if (data.error) return { source: 'USGS', timestamp: Date.now(), data: null, error: data.error };

  const quakes = (data.features || []).map(f => ({
    id:        f.id,
    magnitude: f.properties.mag,
    place:     f.properties.place,
    time:      f.properties.time,
    depth:     f.geometry?.coordinates?.[2] ?? null,
    lat:       f.geometry?.coordinates?.[1] ?? null,
    lon:       f.geometry?.coordinates?.[0] ?? null,
    status:    f.properties.status,
    tsunami:   f.properties.tsunami === 1,
    url:       f.properties.url,
  }));

  return {
    source: 'USGS',
    timestamp: Date.now(),
    data: { count: quakes.length, quakes },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// 2. NOAA WEATHER ALERTS (real-time US)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchWeatherAlerts(area = null) {
  const url = area
    ? `https://api.weather.gov/alerts/active?area=${area}`
    : 'https://api.weather.gov/alerts/active?status=actual&message_type=alert';
  const data = await safeFetch(url, { headers: { 'User-Agent': 'LucyOS/5.0 (contact@lucyos.ai)' } });
  if (data.error) return { source: 'NOAA_ALERTS', timestamp: Date.now(), data: null, error: data.error };

  const alerts = (data.features || []).map(f => ({
    id:       f.id,
    event:    f.properties.event,
    severity: f.properties.severity,
    urgency:  f.properties.urgency,
    areas:    f.properties.areaDesc,
    headline: f.properties.headline,
    onset:    f.properties.onset,
    expires:  f.properties.expires,
  }));

  return {
    source: 'NOAA_ALERTS',
    timestamp: Date.now(),
    data: { count: alerts.length, alerts },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// 3. OPEN-METEO WEATHER (real-time + forecast, global)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchWeather(lat = 40.7128, lon = -74.0060, location = 'New York') {
  const params = [
    'temperature_2m', 'relative_humidity_2m', 'wind_speed_10m',
    'wind_direction_10m', 'precipitation', 'weather_code',
    'surface_pressure', 'cloud_cover', 'visibility',
  ].join(',');

  const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=${params}&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=auto`;
  const data = await safeFetch(url);
  if (data.error) return { source: 'OPEN_METEO', timestamp: Date.now(), data: null, error: data.error };

  const c = data.current || {};
  return {
    source: 'OPEN_METEO',
    timestamp: Date.now(),
    data: {
      location,
      lat, lon,
      temperature_f:  c.temperature_2m,
      humidity_pct:   c.relative_humidity_2m,
      wind_speed_mph: c.wind_speed_10m,
      wind_dir_deg:   c.wind_direction_10m,
      precipitation:  c.precipitation,
      cloud_cover:    c.cloud_cover,
      pressure_hpa:   c.surface_pressure,
      visibility_m:   c.visibility,
      weather_code:   c.weather_code,
      time:           c.time,
    },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// 4. NOAA SPACE WEATHER (real-time solar/geomagnetic)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchSpaceWeather() {
  const [solarWind, kIndex, xRay, alerts] = await Promise.allSettled([
    safeFetch('https://services.swpc.noaa.gov/json/solar-wind/plasma-7-day.json'),
    safeFetch('https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json'),
    safeFetch('https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json'),
    safeFetch('https://services.swpc.noaa.gov/products/alerts.json'),
  ]);

  const wind = solarWind.status === 'fulfilled' && !solarWind.value.error
    ? solarWind.value.slice(-1)[0]  // most recent reading
    : null;

  const kCurrent = kIndex.status === 'fulfilled' && !kIndex.value.error
    ? kIndex.value.slice(-1)[0]
    : null;

  const xrayCurrent = xRay.status === 'fulfilled' && !xRay.value.error
    ? xRay.value.slice(-1)[0]
    : null;

  const activeAlerts = alerts.status === 'fulfilled' && Array.isArray(alerts.value)
    ? alerts.value.filter(a => a.issue_datetime && !a.message?.includes('CANCEL'))
    : [];

  return {
    source: 'NOAA_SWPC',
    timestamp: Date.now(),
    data: {
      solar_wind: wind ? {
        density:      wind[1],  // protons/cm3
        speed:        wind[2],  // km/s
        temperature:  wind[3],
        time:         wind[0],
      } : null,
      k_index: kCurrent ? {
        value: kCurrent[1],
        time:  kCurrent[0],
      } : null,
      xray_flux: xrayCurrent ? {
        short: xrayCurrent[1],
        long:  xrayCurrent[2],
        time:  xrayCurrent[0],
      } : null,
      active_alerts: activeAlerts.length,
      geomagnetic_storm: kCurrent ? Number(kCurrent[1]) >= 5 : false,
    },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// 5. OPENSKY NETWORK — LIVE AIRCRAFT (real-time, ~10s delay)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchAircraft(bounds = null) {
  // bounds: { lamin, lomin, lamax, lomax } or null for all
  let url = 'https://opensky-network.org/api/states/all';
  if (bounds) {
    url += `?lamin=${bounds.lamin}&lomin=${bounds.lomin}&lamax=${bounds.lamax}&lomax=${bounds.lomax}`;
  }
  const data = await safeFetch(url);
  if (data.error || !data.states) {
    return { source: 'OPENSKY', timestamp: Date.now(), data: null, error: data.error || 'no data' };
  }

  const aircraft = data.states.map(s => ({
    icao24:     s[0],
    callsign:   s[1]?.trim() || null,
    origin:     s[2],
    lon:        s[5],
    lat:        s[6],
    altitude_m: s[7],
    velocity:   s[9],   // m/s
    heading:    s[10],
    on_ground:  s[8],
  })).filter(a => a.lat && a.lon);

  return {
    source: 'OPENSKY',
    timestamp: Date.now(),
    data: {
      count:    aircraft.length,
      aircraft: aircraft.slice(0, 500),  // cap for performance
    },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// 6. USGS STREAM FLOW (real-time, 15-min intervals)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchStreamFlow(stateCd = 'US') {
  const url = `https://waterservices.usgs.gov/nwis/iv/?format=json&stateCd=${stateCd}&parameterCd=00060&siteStatus=active&siteType=ST`;
  const data = await safeFetch(url);
  if (data.error || !data.value) {
    return { source: 'USGS_WATER', timestamp: Date.now(), data: null, error: data.error || 'no data' };
  }

  const sites = (data.value.timeSeries || []).slice(0, 100).map(ts => ({
    site_name:  ts.sourceInfo?.siteName,
    site_code:  ts.sourceInfo?.siteCode?.[0]?.value,
    lat:        ts.sourceInfo?.geoLocation?.geogLocation?.latitude,
    lon:        ts.sourceInfo?.geoLocation?.geogLocation?.longitude,
    flow_cfs:   ts.values?.[0]?.value?.[0]?.value,
    time:       ts.values?.[0]?.value?.[0]?.dateTime,
  }));

  return {
    source: 'USGS_WATER',
    timestamp: Date.now(),
    data: { count: sites.length, sites },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// 7. NOAA TIDES (real-time + predictions)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchTides(stationId = '8518750', days = 1) {
  // Default: The Battery, New York
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const url = `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=lucy_os&begin_date=${today}&range=${days * 24}&station=${stationId}&datum=MLLW&time_zone=gmt&units=english&format=json`;
  const data = await safeFetch(url);
  if (data.error || data.error) {
    return { source: 'NOAA_TIDES', timestamp: Date.now(), data: null, error: data.error || data.message };
  }

  return {
    source: 'NOAA_TIDES',
    timestamp: Date.now(),
    data: {
      station_id: stationId,
      readings: (data.data || []).slice(-24).map(r => ({
        time: r.t,
        level_ft: parseFloat(r.v),
        quality: r.q,
      })),
    },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// 8. AVIATION METARs (real-time airport weather)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchMETARs(airports = 'KJFK,KLAX,KORD,KATL,KDFW') {
  const url = `https://aviationweather.gov/api/data/metar?ids=${airports}&format=json&taf=false&hours=2`;
  const data = await safeFetch(url);
  if (data.error || !Array.isArray(data)) {
    return { source: 'AVWX_METAR', timestamp: Date.now(), data: null, error: data.error || 'invalid response' };
  }

  return {
    source: 'AVWX_METAR',
    timestamp: Date.now(),
    data: {
      count: data.length,
      metars: data.map(m => ({
        station:      m.stationId,
        time:         m.reportTime,
        temp_c:       m.temp,
        dewpoint_c:   m.dewp,
        wind_dir:     m.wdir,
        wind_speed:   m.wspd,
        visibility:   m.visib,
        sky:          m.skyCondition,
        raw:          m.rawOb,
      })),
    },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// 9. NASA NEAR-EARTH OBJECTS (requires free API key but DEMO_KEY works)
// ════════════════════════════════════════════════════════════════════════════
export async function fetchNearEarthObjects(apiKey = 'DEMO_KEY') {
  const today = new Date().toISOString().slice(0, 10);
  const url = `https://api.nasa.gov/neo/rest/v1/feed?start_date=${today}&end_date=${today}&api_key=${apiKey}`;
  const data = await safeFetch(url);
  if (data.error || !data.element_count) {
    return { source: 'NASA_NEO', timestamp: Date.now(), data: null, error: data.error || 'no data' };
  }

  const allNeos = Object.values(data.near_earth_objects || {}).flat();
  const hazardous = allNeos.filter(n => n.is_potentially_hazardous_asteroid);

  return {
    source: 'NASA_NEO',
    timestamp: Date.now(),
    data: {
      total_count:      data.element_count,
      hazardous_count:  hazardous.length,
      neos: allNeos.slice(0, 20).map(n => ({
        name:          n.name,
        hazardous:     n.is_potentially_hazardous_asteroid,
        diameter_m:    n.estimated_diameter?.meters?.estimated_diameter_max,
        approach_date: n.close_approach_data?.[0]?.close_approach_date,
        miss_dist_km:  n.close_approach_data?.[0]?.miss_distance?.kilometers,
        speed_kph:     n.close_approach_data?.[0]?.relative_velocity?.kilometers_per_hour,
      })),
    },
    error: null,
  };
}

// ════════════════════════════════════════════════════════════════════════════
// COMBINED SNAPSHOT — fetch all sources at once
// ════════════════════════════════════════════════════════════════════════════
export async function fetchEarthSnapshot() {
  const [quakes, alerts, weather, space, aircraft, neos] = await Promise.allSettled([
    fetchEarthquakes('day', '2.5'),
    fetchWeatherAlerts(),
    fetchWeather(),
    fetchSpaceWeather(),
    fetchAircraft({ lamin: 24, lomin: -125, lamax: 50, lomax: -65 }),  // CONUS
    fetchNearEarthObjects(),
  ]);

  return {
    timestamp: Date.now(),
    earthquakes: quakes.status === 'fulfilled'  ? quakes.value  : { error: 'failed' },
    weather_alerts: alerts.status === 'fulfilled' ? alerts.value  : { error: 'failed' },
    weather:        weather.status === 'fulfilled' ? weather.value : { error: 'failed' },
    space_weather:  space.status === 'fulfilled'   ? space.value  : { error: 'failed' },
    aircraft:       aircraft.status === 'fulfilled' ? aircraft.value : { error: 'failed' },
    near_earth:     neos.status === 'fulfilled'    ? neos.value   : { error: 'failed' },
  };
}