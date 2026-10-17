# SFO offline map pack

Fully offline replacement for streamed Google Photorealistic 3D Tiles in the SkyFlow demo. No Google data is used, cached or derived here.

| File | What | Size |
|---|---|---|
| `sfo-ortho.jpg` | USGS NAIP orthoimagery, SFO detail, 4000x3673 px, ~1.2 m/px ground (1.53 m Mercator) | ~2.6 MB |
| `bay-ortho.jpg` | USGS NAIP orthoimagery, Bay overview, 3420x4000 px, ~10.4 m/px ground | ~2.7 MB |
| `bounds.json` | Lon/lat bounds, EPSG:3857 extents (exact server-returned) and local ENU extents of each image; ENU formula | |
| `sfo-buildings.glb` | OSM buildings in the SFO bbox (2,394 footprints incl. terminals, control tower 67.4 m, Superbay hangar) + 766 SF downtown buildings >= 25 m, Draco-compressed | ~0.4 MB |
| `sfo-aeroway.geojson` | OSM runways/terminals/aprons/tower for SFO (alignment overlay) | |
| `demo.html` | three.js 0.170.0 viewer (vendored, no network): drapes both images, loads the GLB, overlays OSM runway edges. `?view=tower|sfo|bay` | |
| `vendor/three@0.170.0/` | Pinned three.js module, GLTF/Draco loaders, OrbitControls, Draco decoder (MIT) | 2.2 MB |

## Coordinates
- Images are EPSG:3857, north-up; pixel rows are linear in Mercator Y, not latitude. `demo.html` resamples UVs per row so they drape exactly on ENU.
- Local ENU metres, origin SFO ATCT `[-122.3826, 37.6164]`: `east = (lon-lon0)*m_per_deg_lon`, `north = (lat-lat0)*m_per_deg_lat` (constants in `bounds.json`).
- GLB axes: three.js `x = east`, `y = up`, `z = -north`. Units: metres, no vertical exaggeration.

## Sources and licenses
- Imagery: USGS NAIP (public domain). Fetched from `imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage` (server cap is 4000 px per side, so 4000 rather than 4096).
- © OpenStreetMap contributors (ODbL). Buildings via the Overpass API (`building=*`, bbox 37.600,-122.405,37.640,-122.350) on 2026-10-17; aeroways and SF skyline from `../data/airports.geojson` and `../data/buildings-sf.geojson`.
- Heights: OSM `height`, else `building:levels` x 3.4 m, else defaults by type (terminal 20 m, hangar 22 m, garage 18 m, residential 7 m, other 9 m).
- three.js: MIT (`vendor/three@0.170.0/LICENSE`).

Build scripts live outside the repo in the session scratchpad (`sfo-pack-build/`: `fetch.py`, `build_glb.py`, `enu.py`).
