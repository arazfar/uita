# SFO replay design verification

Verified locally on October 17, 2026, against `DESIGN.md` and the existing
Museum-only replay bundle (`sfo-replay-kpis-v2`).

## Applied design

The map is the dominant dark display. Warm equipment faces frame the identity,
controls, and evidence panel. Locally served IBM Plex fonts separate labels from
operational values. Arrivals use pale green; departures use cyan across the map,
legend, and roster. Orange identifies readings and fixed reference geometry.
The selected aircraft gets brackets and a paper flight strip.

The existing clock, timeline, day controls, data calculations, path gaps, and
selection behavior remain in place. Small screens use document scrolling.
A visible feed link exposes records below the metrics. Keyboard focus uses
surface-specific colors. Reduced motion removes control transitions without
stopping user-controlled replay.

Concurrent ADS-B work added optional provenance fields during this migration.
Compatibility edits keep the local display readable with either format. Those
provenance fields and compatibility edits remain with the concurrent data work;
they are excluded from the design commit.

## Evidence

- TypeScript and Vite production compilation passed with `bunx tsc -b && bunx vite build`.
- Nine browser tests passed in headed Chromium: the seven replay checks plus
  narrow-screen selection and reduced-motion/keyboard checks. Runtime: 99.29 seconds.
- Browser widths included 1440, 800, 640, 390, and 320 CSS pixels. No page-level
  horizontal overflow occurred in the tested narrow layouts. The 640px and
  320px checks cover equivalent reflow widths for a 1280px window at 200% and
  400%; actual browser zoom and physical phones were not tested.
- The committed Museum-only data verifier passed against the generated bundle:
  8,439 operations, 4,128 paths, 93,095 points, and 729 gaps over 120 seconds.
  The design changes do not regenerate or edit those records.
- Codex Browser inspection confirmed the geographic map and selected flight strip.
  Saved test screenshots cover the desktop, selected aircraft, narrow controls,
  narrow flight strip, and failed-basemap state.
- Calculated text contrast includes 15.38:1 on display glass, 7.29:1 on equipment
  faces, 4.51:1 for muted panel labels, and 7.30:1 for muted paper labels.
- `git diff --check` passed.

The browser suite used the running Vite server at `http://127.0.0.1:5176` through
a temporary configuration extending `web/e2e.config.ts`. This preserved the
existing generated bundle while the separate data pipeline was changing.
Local screenshots, the nine-test report, and data hashes are saved under
`output/design/` (ignored by Git).

## Limits observed

`bun run build` stopped in its data-generation hook because the concurrent
pipeline requires `pipeline/adsb-backfill/tracks.json.gz`, which was absent.
Frontend compilation passed separately. The new ADS-B bundle is outside this
visual verification; it needs its own data checks when available.

An initial headless run timed out amid WebGL ReadPixels stalls. The headed run
passed. Vite still reports the existing large main JavaScript chunk, about
2.04 MB before gzip. External basemap access can fail; the tested fallback
retains aircraft, controls, and roster evidence.

## Design-only commit snapshot

The staged design changes were exported to a separate temporary directory before
commit. Concurrent data edits were excluded, including changes to KPI logic,
provenance types, pipeline scripts, and ADS-B browser tests.

That snapshot passed `bun run build`, `python3 ../pipeline/verify_web_data.py`,
and `npx e2e run --headed` from its `web/` directory. All nine browser tests
passed in 47.71 seconds. The normal data-generation hook succeeded against the
committed Museum-only pipeline. The earlier build-hook limitation applies to
the concurrent working tree, not to this design-only commit.
