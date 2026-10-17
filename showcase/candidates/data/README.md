# UITA demo data (SF Bay Area)

Retrieved 2026-10-17 between 19:15 and 19:22 UTC (12:15 to 12:22 PDT). All files are compact JSON. Coordinates are WGS84 `[lon, lat]`. Load them with `fetch('data/<file>')`.

| File | Source | License |
|---|---|---|
| `bay-coastline.geojson` | US Census Bureau cartographic boundary counties, `cb_2023_us_county_500k` (https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip). The polygons are clipped to the shoreline. | Public domain (US Government work) |
| `airports.geojson` | OpenStreetMap through the Overpass API (https://overpass-api.de/api/interpreter), OSM base 2026-10-17T19:15:50Z | ODbL. Credit: "© OpenStreetMap contributors" |
| `buildings-sf.geojson` | OpenStreetMap through the Overpass API, `way[building]` in bbox [-122.425, 37.775, -122.385, 37.81] | ODbL. Credit: "© OpenStreetMap contributors" |
| `adsb-tracks.json` | OpenSky Network REST API, anonymous `GET https://opensky-network.org/api/states/all?lamin=37.2&lomin=-123.0&lamax=38.2&lomax=-121.6`, polled every 10 s | OpenSky terms: non-commercial and research use. Credit: "The OpenSky Network, https://opensky-network.org" |
| `metar.json` | aviationweather.gov Data API: `https://aviationweather.gov/api/data/metar?ids=KSFO,KOAK,KSJC&format=json&hours=3` and `.../taf?ids=KSFO,KOAK,KSJC&format=json` | Public domain (NOAA/NWS) |

## Schemas

### `bay-coastline.geojson`
A FeatureCollection of land `Polygon` features with `properties.kind = "land"`. The land is the union of the Bay Area counties, clipped to bbox [-122.65, 37.45, -122.0, 38.05] and simplified at 0.0001° (about 10 m). Water is everything not covered by a polygon. `properties.counties` at the top level lists the counties included.

### `airports.geojson`
A FeatureCollection. Each feature's `properties` has:
- `kind`: `runway`, `taxiway`, `apron`, `terminal` or `tower`
- `airport`: `SFO` or `OAK`
- `ref`, for runways and taxiways. Runways use the OSM style `10L/28R`, so a single feature covers both ends.
- `width` in metres, `name`, `surface`, `osm_id`
- `centroid` `[lon, lat]`, for towers

Geometry by kind:
- Runways and taxiways are centerline `LineString`s. Draw runways with a buffer of `width` (61 m at SFO, 46 m at OAK). Some runways are split into two or three segments.
- Aprons and terminals are `Polygon`s.
- Towers are building `Polygon`s. Their `centroid` values are SFO [-122.3838, 37.6158] and OAK [-122.2219, 37.7194].

### `buildings-sf.geojson`
Downtown SF and SoMa building footprints as `Polygon`s. The file holds only buildings that have a height tagged in OSM, tallest first, cut off at about 1.45 MB. `properties.h` is the height in metres; it comes from `height`, or `building:levels × 3.5` when only levels are tagged. `properties.name` is included when OSM has one.

### `adsb-tracks.json`
The file is a top-level array:
```
[{ "icao": "a1b2c3", "callsign": "UAL852", "type": null, "squawk": "7411",
   "points": [[t_s, lon, lat, alt_ft, gs_kt, track_deg, on_ground], ...] }]
```
- `t_s` is seconds since the earliest position in the file. Points are sorted by time. Elements 0 to 3 follow the requested `[t, lon, lat, alt_ft]` contract, and elements 4 to 6 are extra fields.
- `alt_ft` is barometric altitude in feet. It falls back to geometric altitude when baro is missing, and it is 0 when the aircraft is on the ground. `gs_kt` and `track_deg` can be `null`.
- `type` is always `null`, because the OpenSky state vectors carry no aircraft type.
- The aircraft are those nearest SFO and OAK, ranked by distance and altitude, capped at 150. Each has at least 2 points.

**Caveat:** this is a **live capture of about 5 minutes**, not one historical hour. ADSB.lol (`api.adsb.lol`) could not be reached from this network, the historical archives are multi-GB, and OpenSky historical access needs an account. OpenSky's anonymous resolution is about 10 s, so tracks are short (a few kilometres per aircraft). Interpolate between points, or loop the clip, to animate it.

### `metar.json`
`{source, metar: [...], taf: [...]}`. These are the raw aviationweather.gov JSON objects. METAR entries cover the last 3 hours for each station and include `rawOb`, `wdir`, `wspd`, `visib`, `clouds`, `temp`, `altim` and `reportTime`. TAF entries include `rawTAF` and `fcsts`. On retrieval day the weather was VFR with light northerly winds (KSFO 03006KT 10SM CLR).
