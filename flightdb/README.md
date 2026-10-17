# SFO flight data in PostGIS

Loads `sfomuseum-data-flights-2026-08` (SFO flights for August 2026) into a PostGIS database running in Docker.

## Setup

You need Docker Desktop, and the `uita` repo sitting next to the data folder:

```
RecursiveHackathon/
  uita/
    flightdb/                        <- this folder
  sfomuseum-data-flights-2026-08/    <- the data
```

If the data is somewhere else, set `DATA_DIR=/path/to/sfomuseum-data-flights-2026-08/data` before running.

## Load

```sh
cd flightdb
./load.sh
```

The script starts the container, then drops and reloads all the data. It takes about a minute, and you can run it again whenever you like.

## Connect

```
postgresql://postgres:postgres@localhost:5432/flights
```

```sh
docker compose exec db psql -U postgres -d flights
```

## Tables

| Name | What it is |
|---|---|
| `features` | One row per GeoJSON file: `id`, `alt` (NULL for the flight, or `swim-path` / `swim-approach` / `swim-takeoff`), `props` (jsonb), `geom` |
| `flights` (view) | One row per flight: `flight_number`, `airline`, `event` (A = arrival, D = departure), `journey`, `gate`, `date`, `scheduled_at`, `estimated_at`, `actual_at`, `geom` |
| `flight_tracks` (view) | Time-stamped tracks for simulation: `times[i]`, `altitudes[i]` and `speeds[i]` match point `i` of `geom` |

## Example: replay one flight point by point

```sql
SELECT p.path[1] AS i, t.times[p.path[1]] AS at,
       ST_X(p.geom) AS lon, ST_Y(p.geom) AS lat,
       t.altitudes[p.path[1]] AS alt, t.speeds[p.path[1]] AS speed
FROM flight_tracks t, ST_DumpPoints(t.geom) p
WHERE t.kind = 'swim-path'
  AND t.id = (SELECT id FROM flights WHERE flight_number = 'UA1722' AND date = '2026-08-10')
ORDER BY at;
```

## Things to know

- **Only some flights have tracks.** There are 120,655 flights but only about 31,000 tracks (9,594 full paths, 11,408 approaches and 9,927 takeoffs). Fewer than 10% of flights have a full path, so the simulation can only animate those. Code-share flights never have tracks.
- **Tracks are cut off at the edges.** Paths and routes stop at airport boundaries and at the US border.
- **Altitudes are raw SWIM values.** They're stored as text, in hundreds of feet, and aren't converted. A trailing `C` means beacon-reported and `T` means interim. For example, `050C` is 5,000 ft.
- **Approach and takeoff tracks have no speeds.** For those, `speeds` is empty and the altitude values come from `swim:elevations`.
- **The login is for local use only.** It's `postgres`/`postgres`. Change it before putting this anywhere shared.
- **Port 5432 may already be taken.** If you already run Postgres locally, change `"5432:5432"` in `docker-compose.yml` to something like `"5433:5432"` and connect on 5433.
- **The Docker image is `imresamu/postgis`.** The official `postgis/postgis` image doesn't run on Apple Silicon Macs. This one is the same build and runs on both Apple Silicon and Intel.

## Stop / reset

```sh
docker compose down       # stop the container (the data is kept)
docker compose down -v    # stop the container and delete the database
```
