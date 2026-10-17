# Full-week ADSB.lol backfill

The August 3–9, 2026 SFO replay uses matched ADSB.lol airborne paths, with Museum
paths as fallback. The full DataSF roster remains authoritative for operations,
throughput, runway use, and spacing. A path match never adds a roster operation.

## Reproduce

Normal development needs no network or global archive download. The accepted
supplement is committed in `pipeline/adsb-backfill/`:

```sh
python3 pipeline/build_web_data.py
python3 pipeline/verify_web_data.py
```

To reproduce extraction and verify the original received observations, use Python 3.11 or newer:

```sh
python3 pipeline/download_adsb_week.py --workers 8
python3 pipeline/accept_adsb_backfill.py
python3 pipeline/build_web_data.py
python3 pipeline/verify_web_data.py
python3 pipeline/verify_adsb_backfill.py
```

The download needs about 30 GB of disk, plus retained traces. All global archives
stay in ignored `pipeline/.cache/adsb-lol/full-week/`. Downloads resume after
interruptions. Every part must match the GitHub release's byte size and SHA-256.
The tar scanner requires valid end markers and rejects nonzero trailing data.
Each complete day retains original compressed, identity-matched trace members.

The committed `provenance.json` identifies every release and asset digest. It
also hashes the accepted compressed supplement. Each accepted operation retains
its ICAO address, matching rule, airport evidence timestamp, original member
names and hashes, source flags, and the received point tuples. `audit.json`
records full-week source-lineage and exhaustive separation checks.

## Source dates and licensing

The [official archive](https://github.com/adsblol/globe_history_2026) publishes
split tar files containing gzip-compressed readsb traces. These are decoded
observations, not original radio messages. The
[readsb format](https://github.com/wiedehopf/readsb/blob/dev/README-json.md#trace-jsons)
defines the altitude reference, ground state, stale-position bit, and leg markers.

The local PDT week starts August 3 at 07:00 UTC and ends August 10 at 07:00 UTC.
It therefore requires eight UTC dates. The preferred releases selected on
October 17, 2026 total **29,918,603,776 bytes**. August 3–7 use prod-0;
August 8–10 use staging-0. The source's preferred-release list can change;
the saved manifest freezes this extraction's choices.

August 9 is smaller than other days (2.38 GB). Its prod replica is slightly
smaller still. A fully downloaded archive does not establish complete receiver
coverage. The output reports observed matches, without a near-100% assumption.

The derived ADS-B supplement is available under
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/), with attribution to
ADSB.lol and its contributing feeders. The app links both provenance and the
complete derived ADS-B database. This license does not replace the DataSF PDDL
or Museum CDLA-Permissive-1.0 notices for their separate source bundles.

## Matching and flight boundaries

We compared stitching ADS-B points into Museum paths with selecting one source
per operation. Stitching would mix altitude semantics and potentially duplicate
positions. The replay prefers one reviewed ADS-B leg, then falls back to the
existing Museum path when no such match exists.

The acceptance step combines original traces across UTC dates before matching.
It requires a matching registration or explicit source-roster ICAO identity.
Callsign alone cannot establish identity. Non-ICAO source addresses are excluded.
The match needs an airborne terminal point within 3 NM of SFO, at or below
1,000 barometric feet, and within 15 minutes of the roster time. Arrival evidence
belongs at the end of the leg; departure evidence belongs at its start. The leg
must also have an observed excursion beyond 3 NM at or above 1,000 ft. This
conservative rule can leave very low or incomplete flights unmatched.

Arrival windows extend up to 90 minutes before and 10 minutes after the roster
time. Departure windows extend 10 minutes before and 90 minutes after. Windows
stop at the midpoint to adjacent roster operations of the same aircraft.
Only positions within 80 NM are exported. The map still refuses to interpolate
observation gaps over 120 seconds.

Ground observations, source new-leg flags, and gaps over 20 minutes separate
flight legs. Stale observations never draw a path, but their boundary flags
still separate legs. This prevents a parked aircraft or later takeoff from
creating a go-around. Ground and geometric altitudes never become barometric
heights. Readsb bit 4 describes vertical-rate reference; bit 8 describes altitude
reference. Source times normalize to milliseconds, without adding samples.

The importer rejects multiple eligible legs, ambiguous aircraft identities,
conflicting observations, and overlapping operations for the same source
address. It screens coordinate jumps above 700 kt, and rejects a match if more
than 5% of its points fail or its terminal evidence is lost. These are matching
and quality heuristics, not certified landing or takeoff detection.

## Safety and coverage

The exporter rebuilds path coverage, measured-altitude coverage, separation
candidates, and go-around candidates from the selected paths. Safety counts are
limited to timestamps inside the local replay week. The paired 28L/28R final
corridor exclusion remains geometric; no visual clearance is inferred.

Go-arounds appear only after the sustained climb evidence is available. Another
candidate on the same arrival requires a new low approach after a descent of at
least 1,000 ft. A continuous climb cannot generate repeated candidates.

The source audit checks each exported ADS-B observation against the original
compressed traces, including altitude reference and flight boundaries. An
exhaustive pair scan checks the separation results without the production
spatial-cell optimization. Every go-around must have consecutive usable measured
observations supporting its low point and sustained climb.

## Earlier bounded sample

Before this full extraction, a deliberately partial 4 MiB August 3 sample found
four missing SkyWest N979SW / ICAO ada6b9 operations. The standalone
`adsb_lol.py` remains a candidate-only diagnostic tool. Its `--allow-partial`
flag labels incomplete samples; the acceptance step refuses incomplete archives.
A directory scan cannot establish archive completeness either.

The separate October dataset under `data/` has different dates and contracts.
This August backfill does not modify it.
