# pipeline

Reproduce departures bundle + web data (needs `.cache/sfomuseum-data-flights-2026-08.parquet`, 66,135,198 bytes, from https://static.sfomuseum.org/parquet/sfomuseum-data-flights-2026-08.parquet; the server is slow per connection, so use parallel `curl -r` ranges):

```
cd pipeline && uv run extract_departures.py && uv run build_web_data.py
```

- `extract_departures.py` -> `departures-bundle/` (DataSF departures cached in `.cache/`, fetched on first run).
- `build_web_data.py` -> `../web/public/data/{flights,tracks}.json` + `runways.geojson` (arrivals from `bundle/` + departures).
- `load_supabase.py [--dry-run]` -> Supabase (`../supabase/migrations/*_flight_week.sql` first). Needs `SUPABASE_DB_URL` or `SUPABASE_SECRET_KEY` + `NEXT_PUBLIC_SUPABASE_URL` in env or `../.env.local`; exits with an error if missing.

Web track cleaning: drop points implying more than 700 kt from the previous kept point; lon/lat 5 dp; altitude = FAA `simpleAltitude` digits x 100 ft (trailing letter such as `C` ignored); speed = raw integer, assumed knots.
