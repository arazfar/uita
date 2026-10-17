# SFO replay verification

Verified locally on October 17, 2026. Scope: `web/`, replay export, and optional
ADSB.lol candidate extraction. The separate controller simulator and benchmark
work are outside this change.

## Delivered behavior

The replay preserves all 8,439 source operations: 4,220 arrivals and 4,219
departures. It displays 4,128 available paths, or 48.9% of operations. The feed,
throughput, runway split, and arrival gaps use the full roster. The feed shows
the latest 200 operations at the selected time.

The panel shows throughput against the 54/hour demo reference, arrival schedule
offsets, runway use, arrival spacing, path coverage, and limited safety
candidates. Assigned altitude is never treated as measured height. Only 300
paths have usable measured-height intervals. Go-around detection is unavailable
because no arrival has sufficient measured low-altitude observations.

Map paths split at gaps over 120 seconds. Untracked operations do not create
aircraft positions or runway pulses. Missing external basemap tiles produce a
status message while aircraft, range rings, controls, and KPIs remain available.

## Checks run

| Check | Result |
| --- | --- |
| `cd web && bun run build` | Passed TypeScript and production build; regenerated local JSON |
| `python3 pipeline/verify_web_data.py` | Passed roster identity, source-point lineage, coverage, chronology, heights, and schedule checks |
| `cd web && npx e2e run tests/replay.e2e.ts` | Seven browser tests passed in 195.54 seconds |
| Affected browser checks after the basemap readiness fix | Two tests passed in 39.88 seconds |
| Optional ADSB.lol importer, real 4 MiB August 3 sample | Four missing SkyWest operation candidates; explicitly partial |
| Incomplete ADS-B input without the partial flag | Refused; previous output remained unchanged |
| `git diff --check` | Passed |

The browser suite checks complete roster/KPI totals, moving traffic playback,
speed, all seven days, tracked and untracked selections, keyboard controls,
week limits, a 390-pixel viewport, missing replay data, and failed basemap
requests. It uses actual source bundles and browser actions, with no model
credentials. Missing-file and failed-basemap tests inject only those failures.

Visible Codex Browser inspection also confirmed the geographic basemap, flight
positions, replay controls, day changes, and KPI layout. Headless Chromium did
not consistently load external geographic tiles; it rendered aircraft and range
rings and exercised the explicit degraded-basemap state. No physical-phone or
operational ATC validation is claimed.

Runtime: Node 26.5.0, Bun 1.3.3, Python 3.14.6, e2e 0.21.2, and the web engine
0.15.2. The headless WebGL startup needed a 30-second assertion budget. The Vite
build reports a large main JavaScript chunk of about 2.04 MB before gzip.

## Data limits

The delivered data contains 93,095 retained points, including 2,671 explicit
beacon heights. It retains 2,164 arrival schedules. Recorded operation time and
scheduled arrival time do not establish equivalent gate/touchdown events; their
difference is an approximate schedule offset. Departure schedules are absent.
No complete safety result follows from sparse paths and heights.

The optional ADSB.lol importer writes review candidates. It does not add paths
to the replay. The small SkyWest sample proves feasibility; it does not estimate
coverage. A full local-week extraction also requires UTC August 10 and about
29.92 GB of archives. See [the backfill workflow](../pipeline/ADSB_LOL.md) and
[replay data methods](../pipeline/WEB_REPLAY.md).
