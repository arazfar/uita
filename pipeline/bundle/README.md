# SFO arrivals: August 3–9, 2026

A starter dataset for **Up in the Air**, a custom AI ATC simulation built with coding agents.

## What is included

- **4,220 unique recorded runway-arrival operations** from DataSF.
- **2,164 matched observed flight paths** from SFO Museum (51.3% of the roster).
- **60,535 observed points** within approximately 80 nautical miles of SFO.
- **2,056 arrivals without a matched path** in this extraction.
- No synthetic aircraft, generated flight paths, ATC dialogue, weather observations or runway geometry have been added.

The period is **2026-08-03 00:00:00 inclusive through 2026-08-10 00:00:00 exclusive**, interpreted in America/Los_Angeles (UTC−07:00). Membership in the week is determined from the DataSF operation timestamp, not the Museum's scheduled-flight date. An overnight arrival can therefore retain a Museum date from the previous day.

These counts describe this extraction. They are not a guarantee of every actual SFO movement or a complete trajectory for every arriving aircraft. Flight identities are matched heuristically, not independently certified.

## Files

| File | Contents |
| --- | --- |
| `arrivals.json` | One object per recorded runway-arrival operation, with identifiers, source/local/UTC timestamps, origin, aircraft type, runway and path-match status. |
| `tracks.json` | Matched observed paths, source identifiers, matching method, source timestamps and point arrays. Join to arrivals by `operation_id`. |
| `coverage.json` | Overall and daily counts, runway counts, matching methods and path-screening counts. |
| `quality-notes.json` | Raw-point diagnostics, short-track counts and match-timing distribution. |
| `provenance.json` | Source URLs, retrieval date, exact source query, input hashes and processing notes. |
| `datasf-source-metadata.json` | Source metadata and its public-domain dedication/license link. |
| `SFO-Museum-LICENSE.txt` | Source data's Community Data License Agreement – Permissive – Version 1.0. |

## Sources

### DataSF SFO Flight Operations

- Dataset: https://data.sf.gov/d/43zc-xw3x
- API: https://data.sfgov.org/resource/43zc-xw3x.json
- Official catalog description: https://catalog.data.gov/dataset/sfo-flight-operations

The source includes repeated analysis-gate rows for an operation. We grouped on the selected operation/identity fields, restricted to SFO arrivals, and retained named runway arrivals in the target week. The resulting extraction has one row per `operation_no`; uniqueness was checked. Helicopter-pad codes and records without a named runway are excluded. All retained records name runway 28L or 28R.

The naive source `flight_date_time` is interpreted as SFO local time. This interpretation is consistent with matches against the Museum's UTC tracks, but its timezone was not explicitly established in the source documentation reviewed. We retain the original value alongside the conversion. Treat it as the recorded **arrival-operation time**, not an exact touchdown or gate-in timestamp.

### SFO Museum August GeoParquet

- Direct monthly file: https://static.sfomuseum.org/parquet/sfomuseum-data-flights-2026-08.parquet
- Index: https://static.sfomuseum.org/parquet/index.html
- Repository and field notes: https://github.com/sfomuseum-data/sfomuseum-data-flights-2026-08
- Publisher's schema/query examples: https://aaronland.info/weblog/2025/01/07/things/

The monthly Parquet contains base flight metadata and alternate geometry rows. We joined arrival metadata to `swim-path` rows on `wof:id`. Filtering all rows on `flysfo:event` before that join would discard geometry rows whose metadata fields are null.

Paths are observed flight paths, distinct from the source's planned `swim-route` geometries. The publisher documents incomplete path availability, missing codeshare geometries and clipping at airport/US boundaries. Base flight metadata can contain codeshares; it should not be counted directly as physical aircraft movements.

## Matching and screening

1. Retrieve grouped DataSF SFO arrival records for August 1–13 to provide boundary context, then select the target local week and runway-name pattern `(?:0?1|10|19|28)[LR]`.
2. Join Museum arrival metadata to `swim-path` geometry on `wof:id`. Consider paths whose final timestamp falls within the target week plus a 20-minute margin on each end.
3. Require a LineString; equal counts of coordinates, timestamps, altitudes and speeds; strictly increasing timestamps; and a final point within 5 NM of the approximate SFO center (37.6213, −122.3790).
4. Retain observed points within 80 NM of that center, requiring at least two. Coordinates are rounded to seven decimal places.
5. Match a DataSF operation to Museum aliases and/or registration within 20 minutes of the observed path's final timestamp. Reject pairs with differing registrations when both are available.
6. Prefer callsign + registration + time, then callsign + time, then registration + time. Resolve candidates greedily by that priority and smallest absolute time difference, with at most one operation per Museum ID and one Museum ID per operation.
7. The retained set has 1,825 callsign/registration/time matches and 339 callsign/time matches; it has no registration-only matches.

A missing match does not imply a flight did not arrive. The matching window, identifiers, missing source paths and screening rules all affect coverage. The screening counts in `coverage.json` describe the considered path records, not every missing roster arrival.

## Data fields and limits

Each `tracks.json` point follows its `point_columns` list:

`[timestamp_unix_utc, longitude, latitude, altitude_raw, speed_raw]`

- **Altitude is deliberately raw.** Museum `swim:altitudes` uses FAA `simpleAltitude` strings, which can encode assigned, beacon-reported or interim altitude, including suffixes. Validate the semantics and units before converting or using them as actual aircraft height.
- **Speed is deliberately raw.** Units and interpretation must be confirmed before using it in a physics model.
- Source scheduled and estimated timestamps are preserved with those labels. They are not renamed actual arrival times; missing values may be represented by the source's sentinel values.
- Arrays are aligned and time-ordered, but the paths are **raw, not physically cleaned**. A diagnostic found **385 adjacent point pairs across 231 tracks** implying speeds above 700 knots, and **56 tracks** have fewer than five retained points. Outlier filtering, smoothing and short-track handling are required before deriving velocity, initializing aircraft or scoring separation. See `quality-notes.json`; its threshold is a diagnostic, not an operational rule. Clipping points to a radius is not a promise of uninterrupted coverage or an exact boundary-crossing sample.
- Detailed `swim-approach` alternates are excluded. A spot check found about a seven-hour disagreement between one approach trace and its associated longer path/operation. This has not been established for every approach trace; do not correct all records by a presumed offset without further source validation.
- The paths may stop before touchdown. Final runway occupancy, runway vacation, missing terminal segments and responses to new controller instructions require simulation.

## Recommended use in the demo

Use the full roster for real arrival demand. For matched flights, normalize point fields, filter position outliers and assess short tracks before deriving initial motion and seeding the simulation at the first usable terminal observation. For unmatched flights, generate an explicitly labeled entry state and approach pattern from development-day examples, or investigate supplementary ADS-B traces. Inferring entry time from an observed arrival time is a scenario-construction assumption, not an observed boundary crossing.

Once the agent issues a clearance, advance the custom simulator under that action; do not continue treating the recorded future path as its result. Keep future observations and observed arrival times out of the controller's current-state prompt. Use the historical demand to construct fixed scenarios, not as proof that the simulated controller would outperform the real one.

Use August 3–7 for development/validation and August 8–9 for the final frozen comparison. Fit gap-filling patterns only on development days, and freeze the simulator, checker, scorer and reconstruction rules before final evaluation.

Historical weather and airport geometry can be added from IEM KSFO METAR observations and date-matched FAA data. Authentic ATC commands, radio transcripts and complete pilot intent are not provided by this bundle; pilot dialogue will be simulated.

## Attribution and modifications

Source observations are from **SFO / DataSF** and **SFO Museum**. DataSF identifies its dataset license as the Open Data Commons Public Domain Dedication and License (PDDL); see the included metadata. SFO Museum publishes its data under CDLA-Permissive-1.0; the complete source license is included.

This bundle is a derived subset: selected dates and arrivals, grouped source operation rows, heuristic joins, coordinate clipping/rounding, timestamp conversions, JSON restructuring and added coverage/match metadata. These transformations and the recommendations above are our work, not statements or endorsements by the data publishers. Preserve attribution and the included license when sharing the source-derived data.
