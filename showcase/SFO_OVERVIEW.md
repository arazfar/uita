# Separate SFO overview

The public frontend serves the combined landscape and recorded replay at
`/sfo-overview/`. The existing root and research pages keep their current behavior.
The new shell can also open the existing tower simulation. Each frame uses its
own pause/resume protocol; only the visible frame renders. The reserved footer
keeps a touch-accessible return to the recorded overview.

## Build and run

```sh
cd showcase
npm ci
UITA_SERVER_URL=http://127.0.0.1:8001 npm run dev -- --port 5193 --strictPort
npm run build
```

The standalone `build:overview` command compiles only the two new HTML entries.
Generated JavaScript, CSS, and fonts live under `/candidates/overview-assets/`,
which the production gateway already serves locally. The frontend Docker build
copies this output over the two new source pages. It leaves existing entry pages
byte-for-byte unchanged. Private deployments retain their existing upstream
authorization behavior; this route is verified on the public frontend gateway.

The React scene uses the isolated `three180` package. Existing candidates retain
their current Three.js versions. Local imagery, airport geometry, and models
remain in `candidates/`. Blender authoring files for the added airport detail are
in `assets/source/sfo-overview/`; runtime loading does not require Blender.

## Data and visual limits

Replay reads the existing PostgreSQL archive through the history API. Each target
uses the last original observation at or before the clock, no older than 15 seconds.
Positions are not interpolated or extrapolated. Trails cover at most two minutes
and break at gaps or new flight legs. Ground flags permit surface placement;
airborne observations without altitude stay in the evidence register only.

The detailed shoreline uses Census data and imagery uses USGS NAIP. Elevation,
vegetation, aircraft scale, lighting, and added airport detail are illustrative.
Distant land uses simplified US Atlas / Census 2017 county boundaries. It does
not establish terrain elevation or complete map coverage. FAA daily operation
totals are separate from regional target counts. Safety and delay metrics remain
unevaluated. The separate tower view is a simulation.

## Verification

Run the browser checks from `web/` with a running frontend and real history API:

```sh
UITA_OVERVIEW_URL=http://127.0.0.1:5193 npx e2e run \
  tests/showcase-overview.e2e.ts tests/showcase-overview-layout.e2e.ts \
  tests/showcase-overview-regression.e2e.ts \
  tests/showcase-overview-continuation.e2e.ts \
  tests/showcase-overview-shipping.e2e.ts \
  --config e2e.overview.config.ts
```

The original integration verified all seven dates, source coordinates and
freshness, target search, playback, week boundaries, failure recovery, and 320 px
reflow. A real-source adapter audit checked 630 frames, 94,605 displayed targets,
and 1,186,041 trail points. This verifies sampled adapter behavior, not complete
archive quality. Two long journeys were interrupted by unrelated checkout and
server reloads; their remaining assertions passed in isolated follow-up runs.

For this separate-route release, TypeScript and both Vite builds pass, and all
31 existing showcase tests pass after rebasing onto the latest main. The packaged production gateway returns the
unchanged existing app HTML at `/`, serves both overview URL spellings, and
returns compiled JavaScript and CSS with the correct content types. The structured
code review found no actionable defects. Local Docker image validation was not
available because the container engine stopped; the packaged gateway was tested
with the same compiled file layout.

The packaged browser run verified compiled module URLs, original sample freshness
and coordinates against the real API, +10 seconds, play/pause, and 320 px controls.
Its final canvas click hit an aircraft label; a focused continuation used a visible
heading and passed real T-key switching in both frames and touch-button returns.
Replay stayed paused at the same timestamp throughout the tower round trip.

Physical-phone GPU performance is not measured. The overview bundle is about
873 KB minified and 239 KB gzip; Vite reports its large-chunk warning.
