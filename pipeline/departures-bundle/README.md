# SFO departures: August 3-9, 2026

Companion to `../bundle` (arrivals), same method adapted for departures. Counts are in `coverage.json`; they describe this extraction, not every SFO movement. Flight identities are matched heuristically.

## Files
`departures.json` (one object per DataSF departure operation), `tracks.json` (matched Museum `swim-path` observations; join on `operation_id`), `coverage.json`, `quality-notes.json`, `provenance.json`, `datasf-source-metadata.json`, `SFO-Museum-LICENSE.txt`.

## Method
1. DataSF `operation_type='D'`, grouped exactly as in `provenance.json` (`datasf_query`), Aug 1-13. The naive `flight_date_time` is read as America/Los_Angeles (UTC-07:00); keep [2026-08-03 00:00, 2026-08-10 00:00) and runway pattern `(?:0?1|10|19|28)[LR]`. Helicopter pads and rows without a runway are dropped (see `provenance.json`). One row per `operation_no` (asserted).
2. Museum monthly Parquet: metadata rows with `flysfo:event='D'` are joined on `wof:id` to `swim-path` geometry rows (geometry rows have null metadata; do not filter on event before the join). Paths must be LineStrings with aligned, strictly increasing arrays and a FIRST point within 5 NM of (37.6213, -122.379); first timestamp within the week +/- 20 min. Points within 80 NM are kept (>= 2), coordinates rounded to 7 dp.
3. Match operation to path within 20 min of the path's FIRST timestamp via callsign aliases and/or registration; differing registrations are rejected. Priority: callsign+registration+time, callsign+time, registration+time; greedy by priority then smallest |dt|; one-to-one.
4. `operation_minus_track_start_seconds` is operation time minus first path timestamp. It is almost always negative (median about -70 s): the recorded DataSF departure-operation time precedes the first observed track point. Treat it as an operation time, not wheels-up.

## Limits
Altitude (FAA `simpleAltitude`, hundreds of ft, optional letter suffix) and speed are raw. Raw paths contain speed outliers (see `quality-notes.json`); `swim-takeoff`/`swim-approach` alternates are excluded; paths may start after the roll and are clipped at 80 NM. No synthetic records were added.

## Attribution
Source observations are from SFO / DataSF (PDDL) and SFO Museum (CDLA-Permissive-1.0, license included). This bundle is a derived subset (selection, grouping, heuristic joins, clipping/rounding, timestamp conversion, restructuring); those transformations are ours, not the publishers'. Preserve attribution and the license when sharing.
