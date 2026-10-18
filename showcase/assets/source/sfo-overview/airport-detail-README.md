# SFO airport detail

`airport-detail.py` generates the adjacent `airport-detail.blend` and the browser asset `showcase/candidates/assets/overview/airport-detail.glb` using Blender 5.2.1. Run from the repository root:

```sh
blender -b -t 2 --python showcase/assets/source/sfo-overview/airport-detail.py
```

The model reuses the ten existing OpenStreetMap terminal footprints in `showcase/candidates/sfo-pack/sfo-aeroway.geojson`. It adds schematic glazing, roof parapets, roof equipment, apron service masts, and a control tower at the recorded centroid and 67.36 m height. It also fills the two relation-based terminal footprints omitted by the existing building GLB. These details are illustrative and do not represent a surveyed airport model. Building heights retain the existing pack's OSM values or fallback heights.

The airport module also reuses the existing compressed `sfo-buildings.glb` and the SFO apron, runway, and taxiway data from `showcase/candidates/data/airports.geojson`. The four runways retain their geographic endpoints and designations. Runway striping and material texture are procedural visual detail.

Coordinates use metres relative to SFO ATCT `[-122.3826, 37.6164]`, with exact constants from `sfo-pack/bounds.json`. Blender uses x=east, y=north, z=up; the glTF exporter converts this to Three.js x=east, y=up, z=south. Runtime surfaces sit 3 m above local water level, above the flattened airport terrain at 2 m. This vertical placement is schematic.

The generated GLB contains six merged material meshes and uses Draco compression. Background Blender execution does not alter the user's open Blender session. Source geometry: © OpenStreetMap contributors (ODbL), retained from the repository's existing map pack.
