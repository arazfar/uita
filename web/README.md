# SFO week replay (web)

```sh
bun install --frozen-lockfile
bun run dev
```

Open [the replay](http://localhost:5174). `predev` and `prebuild` regenerate
`public/data/` from the tracked arrivals/departures bundles using Python 3.
Those generated JSON files stay ignored. `bun run data` regenerates them manually.

Select a day, scrub the week, change speed, then play. Select aircraft or feed rows
for details. Space controls playback when focus is outside another control. Cyan
marks arrivals; amber marks departures. Operations without a path remain in the
feed and throughput. Long observation gaps stay empty.

The KPI panel uses complete roster counts for throughput, runway split, and
same-runway arrival gaps. Arrival schedule offsets use tracked, scheduled arrivals
only. The offset is approximate: the timestamps do not establish equivalent
gate/touchdown events. Safety checks use sparse reported heights; go-arounds are
unavailable with the current evidence. The 54 arrivals/hour figure is a demo
reference. Read [data methods](../pipeline/WEB_REPLAY.md) for thresholds and sources.

## Verify

```sh
bun run build
python3 ../pipeline/verify_web_data.py
npx @e2e-dev/web install chromium
npx e2e run
```

The browser suite drives the actual app and source bundles. It checks playback,
all seven days, selection, timeline limits, KPI totals, narrow-screen layout, and
missing-data recovery. It needs no model credentials. Reports and screenshots
are written under `.e2e/` and stay ignored.

Basemap tiles need internet access. A status message identifies slow or missing
tiles; aircraft paths, range rings, controls, and KPIs continue to work.

The optional [ADSB.lol candidate importer](../pipeline/ADSB_LOL.md) supports a later
backfill. It does not change the replay or claim complete coverage.

Reusable data layer: `src/data/` (types, loaders, dataset, interpolate, clock, time, geo).
