# SFO overview models

These local browser assets are part of the showcase package. Runtime loading does not depend on another app or an external model provider.

- `airport-detail.glb`: Blender-generated terminal glazing, roof details, service masts, tower, and two terminal bases. Reuses the existing OpenStreetMap footprints. Six material meshes; Draco compressed. Schematic details, not a surveyed airport model.
- `uita-airliner.glb`: existing project aircraft, reused from the frontend assets.

Airport model coordinates use metres relative to SFO ATCT `[-122.3826, 37.6164]`, with Three.js axes x=east, y=up, z=south. The tower retains its recorded centroid and 67.36 m height. Source geometry: © OpenStreetMap contributors (ODbL). Existing maps and their complete credits remain in `../../sfo-pack/README.md` and `../../data/README.md`.

The Blender source and deterministic generation script are retained in `showcase/assets/source/sfo-overview/`; they are development inputs only, not runtime dependencies.
