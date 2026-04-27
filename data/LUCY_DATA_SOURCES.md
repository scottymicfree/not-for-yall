# Lucy OS v5 — Data Source Master List
## Earth Intelligence & Prediction Systems

---

## 1. WEATHER & CLIMATE DATA

### Real-Time Weather Feeds

**OpenWeatherMap**
- API: `https://api.openweathermap.org/data/2.5/weather`
- Forecast: `https://api.openweathermap.org/data/2.5/forecast`
- One Call (current+forecast+historical): `https://api.openweathermap.org/data/3.0/onecall`
- Type: Real-time + 5-day forecast
- Access: Free tier (1,000 calls/day) — API key required → https://openweathermap.org/api
- Best for: Global current conditions, hourly/daily forecasts

**NOAA National Weather Service (FREE, no key)**
- Current observations: `https://api.weather.gov/stations/{stationId}/observations/latest`
- Forecast by point: `https://api.weather.gov/points/{lat},{lon}`
- Active alerts: `https://api.weather.gov/alerts/active`
- Hourly forecast: `https://api.weather.gov/gridpoints/{office}/{x},{y}/forecast/hourly`
- Type: Real-time + forecasts
- Access: FREE, no API key — US coverage
- Docs: https://www.weather.gov/documentation/services-web-api

**Open-Meteo (FREE, no key)**
- Current + forecast: `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true`
- Historical: `https://archive-api.open-meteo.com/v1/era5`
- Marine: `https://marine-api.open-meteo.com/v1/marine`
- Air quality: `https://air-quality-api.open-meteo.com/v1/air-quality`
- Type: Real-time, forecast, historical
- Access: FREE, no key (rate limit applies)
- Best for: Hourly temperature, wind, precipitation, pressure

**WeatherAPI.com**
- Current: `https://api.weatherapi.com/v1/current.json?key={KEY}&q={location}`
- Forecast: `https://api.weatherapi.com/v1/forecast.json`
- Historical: `https://api.weatherapi.com/v1/history.json`
- Astronomy: `https://api.weatherapi.com/v1/astronomy.json`
- Type: Real-time + historical + forecast
- Access: Free tier (1M calls/month) — API key required → https://www.weatherapi.com

**Visual Crossing Weather**
- Historical + forecast: `https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{location}/{date1}/{date2}`
- Type: Real-time, historical (decades), forecast
- Access: Free tier (1,000 records/day) — API key required → https://www.visualcrossing.com

### Atmospheric & Climate Science Data

**NASA POWER (Prediction of Worldwide Energy Resources) — FREE**
- API: `https://power.larc.nasa.gov/api/temporal/daily/point?parameters={params}&community=AG&longitude={lon}&latitude={lat}&start={YYYYMMDD}&end={YYYYMMDD}&format=JSON`
- Parameters: temperature, humidity, solar radiation, wind, precipitation
- Type: Historical (1981–present) + near-real-time
- Access: FREE, no key
- Best for: Long-range climate modeling, energy/agriculture predictions

**NOAA Climate Data Online (CDO)**
- Search: `https://www.ncdc.noaa.gov/cdo-web/api/v2/data`
- Datasets: GHCND (daily), GSOD, PRECIP_15, NEXRAD
- Type: Historical (decades to centuries)
- Access: FREE — API key required → https://www.ncdc.noaa.gov/cdo-web/token

**Copernicus Climate Change Service (C3S) — EU**
- ERA5 Reanalysis: `https://cds.climate.copernicus.eu/api/v2`
- Type: Historical (1940–present), hourly global
- Access: FREE registration → https://cds.climate.copernicus.eu
- Best for: High-resolution global atmospheric reanalysis

**ECMWF Open Data**
- Forecast: `https://data.ecmwf.int/forecasts/{date}/{time}/ifs/{resolution}/`
- Type: Real-time global NWP forecasts (0.25° resolution)
- Access: FREE for open data tier

---

## 2. SEISMIC & GEOLOGICAL DATA

### Real-Time Earthquake Data

**USGS Earthquake Hazards Program — FREE, no key**
- Real-time feed (GeoJSON): `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson`
- Past day M2.5+: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson`
- Past 7 days M4.5+: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson`
- All month: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.geojson`
- Event detail: `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime={date}&minmagnitude={mag}`
- Type: Real-time (updates every 1–5 min)
- Access: FREE, no key

**EMSC (European Mediterranean Seismological Centre) — FREE**
- Latest earthquakes: `https://www.seismicportal.eu/fdsnws/event/1/query?limit=100&format=json`
- WebSocket real-time: `wss://www.seismicportal.eu/standing_order/websocket`
- Type: Real-time global
- Access: FREE, no key

**IRIS (Incorporated Research Institutions for Seismology)**
- Event service: `https://service.iris.edu/fdsnws/event/1/query`
- Station data: `https://service.iris.edu/fdsnws/station/1/query`
- Waveforms: `https://service.iris.edu/fdsnws/dataselect/1/query`
- Type: Historical + real-time
- Access: FREE

### Volcanic Activity

**Smithsonian Global Volcanism Program — FREE**
- Weekly activity: `https://volcano.si.edu/news/WeeklyVolcanoNews`
- Database: `https://volcano.si.edu/gvp_currenteruptions.cfm`
- Type: Weekly updates
- Access: FREE (no formal API — scrape or RSS)

**VAAC (Volcanic Ash Advisory Centers) — Aviation Safety**
- Darwin VAAC: `https://www.bom.gov.au/aviation/volcanic-ash/`
- Anchorage VAAC: `https://www.weather.gov/aawu/vaac`
- Type: Real-time volcanic ash advisories
- Access: FREE

**USGS Volcano Hazards Program**
- Current alerts: `https://volcanoes.usgs.gov/vhp/updates.html`
- JSON alerts: `https://volcanoes.usgs.gov/feeds/vhp_update_feed.json`
- Type: Real-time alert levels
- Access: FREE

### Geological / Geospatial

**USGS National Map — FREE**
- API: `https://tnmaccess.nationalmap.gov/api/v1/products`
- Elevation data: `https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&wkid=4326&includeDate=True`
- Type: Historical/static + updated datasets
- Access: FREE

**OpenTopography (DEM/LiDAR) — FREE**
- REST API: `https://portal.opentopography.org/API/globaldem?demtype=SRTMGL3&south={lat}&north={lat}&west={lon}&east={lon}&outputFormat=GTiff`
- Type: Static elevation models
- Access: FREE — API key required → https://opentopography.org

---

## 3. AIR TRAFFIC DATA

### Live Flight Tracking

**OpenSky Network — FREE for research**
- All aircraft states: `https://opensky-network.org/api/states/all`
- Flights in bounding box: `https://opensky-network.org/api/states/all?lamin={lat1}&lomin={lon1}&lamax={lat2}&lomax={lon2}`
- Arrivals at airport: `https://opensky-network.org/api/flights/arrival?airport={ICAO}&begin={unix}&end={unix}`
- Departures: `https://opensky-network.org/api/flights/departure?airport={ICAO}&begin={unix}&end={unix}`
- WebSocket: Available for anonymous (limited) and registered users
- Type: Real-time (~10s delay anonymous, ~5s registered)
- Access: FREE for non-commercial — registration recommended for higher limits

**ADS-B Exchange — FREE (community-sourced)**
- API v2: `https://adsbexchange.com/api/aircraft/v2/lat/{lat}/lon/{lon}/dist/{nm}/`
- Global all aircraft: `https://globe.adsbexchange.com/`
- Type: Real-time (near zero delay — unfiltered)
- Access: Free tier available; premium for high-volume

**FlightAware AeroAPI**
- Flights: `https://aeroapi.flightaware.com/aeroapi/flights/{ident}`
- Airports: `https://aeroapi.flightaware.com/aeroapi/airports/{id}/flights`
- Type: Real-time + historical
- Access: API key required → https://flightaware.com/aeroapi/ (free tier: 500 requests/month)

**Aviation Weather Center (NOAA) — FREE, no key**
- METARs: `https://aviationweather.gov/api/data/metar?ids={ICAO}&format=json`
- TAFs: `https://aviationweather.gov/api/data/taf?ids={ICAO}&format=json`
- SIGMETs: `https://aviationweather.gov/api/data/sigmet`
- PIREPs: `https://aviationweather.gov/api/data/pirep?format=json`
- Type: Real-time aviation weather
- Access: FREE, no key

**FAA SWIM (System Wide Information Management)**
- TFMS Data: `https://tfms.fly.faa.gov/` (registration required)
- NOTAM search: `https://notams.aim.faa.gov/notamSearch/`
- Type: Real-time US air traffic management
- Access: FREE — registration required for SWIM feeds

---

## 4. GOVERNMENT & LEGAL DATA

### Federal Open Data

**data.gov — US Federal Open Data Catalog — FREE**
- API: `https://catalog.data.gov/api/3/action/package_search?q={query}`
- Datasets: 250,000+ government datasets across all agencies
- Type: Static + updated
- Access: FREE

**USAspending.gov — Federal Spending — FREE**
- Awards: `https://api.usaspending.gov/api/v2/awards/`
- Contracts: `https://api.usaspending.gov/api/v2/search/spending_by_award/`
- Type: Historical + near-real-time
- Access: FREE, no key

**US Census Bureau — Demographics — FREE**
- Data API: `https://api.census.gov/data/{year}/acs/acs5?get={vars}&for={geography}&key={KEY}`
- Population estimates: `https://api.census.gov/data/2023/pep/population`
- Type: Annual + decennial
- Access: FREE — API key required → https://api.census.gov/data/key_signup.html

**FEC (Federal Election Commission) — FREE**
- Candidates: `https://api.open.fec.gov/v1/candidates/`
- Filings: `https://api.open.fec.gov/v1/filings/`
- Type: Historical + real-time (filings as they occur)
- Access: FREE — API key required → https://api.open.fec.gov/developers/

**EPA Environmental Data — FREE**
- Air quality (AQS): `https://aqs.epa.gov/data/api/`
- ECHO (facility compliance): `https://echo.epa.gov/tools/web-services`
- Type: Real-time + historical
- Access: FREE — registration for AQS

**FEMA National Flood Hazard Layer — FREE**
- API: `https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer`
- Type: Updated periodically
- Access: FREE

### Legal Data

**Congress.gov API — FREE**
- Bills: `https://api.congress.gov/v3/bill?api_key={KEY}`
- Members: `https://api.congress.gov/v3/member`
- Amendments: `https://api.congress.gov/v3/amendment`
- Type: Real-time (as legislation moves)
- Access: FREE — API key required → https://api.congress.gov/sign-up/

**CourtListener (PACER/Federal Courts) — FREE**
- Opinions: `https://www.courtlistener.com/api/rest/v3/opinions/`
- Dockets: `https://www.courtlistener.com/api/rest/v3/dockets/`
- Type: Historical + near-real-time
- Access: FREE with registration → https://www.courtlistener.com/register/

**Regulations.gov (Federal Rulemaking) — FREE**
- Documents: `https://api.regulations.gov/v4/documents?api_key={KEY}`
- Comments: `https://api.regulations.gov/v4/comments`
- Type: Real-time (open comment periods)
- Access: FREE — API key required → https://open.gsa.gov/api/regulationsgov/

**OpenStates (State Legislature Data) — FREE**
- Bills: `https://v3.openstates.org/bills?jurisdiction={state}`
- Legislators: `https://v3.openstates.org/people`
- Type: Real-time (as sessions progress)
- Access: FREE — API key required → https://openstates.org/api/register/

**World Bank Open Data — FREE**
- Indicators: `https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json`
- Type: Annual + quarterly
- Access: FREE, no key

---

## 5. SPACE & SOLAR WEATHER

### NASA & Space Weather

**NASA APIs — FREE**
- APOD: `https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY`
- Earth imagery: `https://api.nasa.gov/planetary/earth/imagery`
- Near-Earth objects: `https://api.nasa.gov/neo/rest/v1/feed?start_date={date}&api_key={KEY}`
- DONKI (space weather): `https://api.nasa.gov/DONKI/`
- Type: Real-time + historical
- Access: FREE — API key → https://api.nasa.gov/ (DEMO_KEY works for testing)

**NOAA Space Weather Prediction Center — FREE, no key**
- Solar wind: `https://services.swpc.noaa.gov/json/solar-wind/plasma-7-day.json`
- Geomagnetic storms: `https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json`
- Solar flares: `https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json`
- CME alerts: `https://services.swpc.noaa.gov/products/alerts.json`
- Aurora forecast: `https://services.swpc.noaa.gov/json/ovation_aurora_latest.json`
- Type: Real-time (updates every 1–5 minutes)
- Access: FREE, no key

**ESA Space Weather Service — FREE**
- Space weather portal: `https://swe.ssa.esa.int/`
- Type: Real-time
- Access: FREE registration

---

## 6. OCEAN & HYDROLOGICAL DATA

**NOAA Tides and Currents — FREE, no key**
- Water levels: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&station={id}&datum=MLLW&time_zone=gmt&format=json`
- Currents: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=currents`
- Type: Real-time + historical
- Access: FREE

**Copernicus Marine Service (CMEMS) — FREE**
- Ocean forecast: `https://marine.copernicus.eu/services/use-cases/accessing-marine-data`
- SST, salinity, currents: Multiple products
- Type: Real-time + forecast + historical
- Access: FREE registration → https://marine.copernicus.eu

**USGS Water Resources — FREE, no key**
- Current conditions: `https://waterservices.usgs.gov/nwis/iv/?format=json&stateCd={state}&parameterCd=00060`
- Stream flow: `https://waterservices.usgs.gov/nwis/iv/?sites={siteNo}&parameterCd=00060&format=json`
- Type: Real-time (15-minute intervals)
- Access: FREE

**Global Flood Monitoring System — FREE**
- Current floods: `https://global-flood-monitor.org/`
- Type: Near-real-time
- Access: FREE

---

## 7. HUMAN ACTIVITY & SOCIAL DATA

**GeoNames — FREE**
- Search: `http://api.geonames.org/searchJSON?q={query}&username={USER}`
- Nearby places: `http://api.geonames.org/findNearbyJSON?lat={lat}&lng={lon}&username={USER}`
- Type: Static geographic names database
- Access: FREE registration → https://www.geonames.org/login

**World Population — FREE**
- REST Countries: `https://restcountries.com/v3.1/all`
- Population clock: `https://www.census.gov/popclock/data/population.php/us`
- Type: Annual + estimated real-time
- Access: FREE, no key

**CDC Public Health Data — FREE**
- Wonder API: `https://wonder.cdc.gov/`
- Open Data: `https://data.cdc.gov/resource/{dataset}.json`
- Type: Weekly + monthly updates
- Access: FREE

**WHO Global Health Observatory — FREE**
- Indicators: `https://ghoapi.azureedge.net/api/{indicator}`
- Type: Annual
- Access: FREE, no key

---

## 8. ENERGY & INFRASTRUCTURE

**EIA (US Energy Information Administration) — FREE**
- Electricity: `https://api.eia.gov/v2/electricity/rto/region-data/data/?api_key={KEY}`
- Natural gas: `https://api.eia.gov/v2/natural-gas/`
- Petroleum: `https://api.eia.gov/v2/petroleum/`
- Type: Hourly + daily + historical
- Access: FREE — API key → https://www.eia.gov/opendata/register.php

**PJM Interconnection (Eastern US Grid) — FREE**
- Load forecast: `https://dataminer2.pjm.com/feed/`
- Type: Real-time
- Access: FREE registration

---

## 9. QUICK REFERENCE — NO-KEY FREE APIS (BEST FOR LUCY)

| Source | Endpoint | Data | Update Rate |
|--------|----------|------|------------|
| USGS Earthquakes | `earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson` | Seismic | 1-5 min |
| NOAA Weather API | `api.weather.gov/alerts/active` | Weather alerts | Real-time |
| Open-Meteo | `api.open-meteo.com/v1/forecast` | Weather/climate | Hourly |
| NOAA Space Weather | `services.swpc.noaa.gov/json/solar-wind/plasma-7-day.json` | Solar wind | 1 min |
| OpenSky Network | `opensky-network.org/api/states/all` | Aircraft | 10s |
| USGS Water | `waterservices.usgs.gov/nwis/iv/?format=json` | Stream flow | 15 min |
| NOAA Tides | `api.tidesandcurrents.noaa.gov/api/prod/datagetter` | Ocean levels | 6 min |
| NASA POWER | `power.larc.nasa.gov/api/temporal/daily/point` | Climate history | Daily |
| EMSC Seismic | `seismicportal.eu/fdsnws/event/1/query?format=json` | Earthquakes | Real-time |
| Aviation Weather | `aviationweather.gov/api/data/metar?format=json` | METARs | 20-60 min |

---

## 10. LUCY INTEGRATION PRIORITY ORDER

### Phase 1 — Zero Setup (no keys needed)
1. USGS Earthquakes (already wired in lucy-server ✓)
2. NOAA Weather API + Alerts
3. Open-Meteo weather + historical
4. NOAA Space Weather (solar wind, K-index, aurora)
5. OpenSky Network (aircraft)
6. USGS Water Resources (stream flow)
7. NOAA Tides and Currents

### Phase 2 — Free Keys (register once)
1. OpenWeatherMap (global weather)
2. NASA APIs (APOD, NEO, DONKI)
3. NOAA CDO (historical climate)
4. Congress.gov (legislation)
5. EIA (energy grid data)
6. OpenTopography (terrain/elevation)

### Phase 3 — Premium/Subscription
1. FlightAware AeroAPI (detailed aviation)
2. Copernicus Marine (ocean forecasts)
3. Visual Crossing (long historical weather)

---

*Generated for Lucy OS v5 — Earth Intelligence Module*
*Last updated: 2025*