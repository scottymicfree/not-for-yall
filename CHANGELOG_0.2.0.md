# Alpha Delta Vualt 0.2.0

## Added
- Earth Intelligence Layer modules: API registry, connectors, ingestion engine, cache layer, normalizer, pattern engine
- Earth error boundary and source health panel
- Event bus emissions for earth_state_updated, earth_source_failed, earth_pattern_detected, earth_alert
- Workspace earth_cache snapshot writing to LucyFileManager/Imports/earth_cache

## Changed
- Earth module now reads normalized Earth state instead of direct ad hoc fetch logic
- Chat supports show source health, show seismic, show solar, show weather
- Automatic Earth refresh interval every 5 minutes while the app is open

## Notes
- Earth-2 remains an adapter slot only
- Feed failures degrade honestly; no fake values are shown
