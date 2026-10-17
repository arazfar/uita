# SFO week replay (web)

`bun install && bun run dev` (port 5174). Build: `bun run build`.

Data in `public/data/` is gitignored. Regenerate it (flights.json, tracks.json, runways.geojson) with `cd pipeline && uv run build_web_data.py`.

Reusable data layer: `src/data/` (types, loaders, dataset, interpolate, clock, time, geo).
