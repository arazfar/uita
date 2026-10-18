# UITA showcase

> **Current connected demo:** the production entry is the immersive research shell,
> with an explicitly scripted guided episode, authentic saved Nemotron attempts,
> historical context, synchronized comparison and export. Use the
> [current startup, data, deployment and rollback instructions](../docs/research/v2/SHOWCASE.md).
> The standalone voice/gallery descriptions below describe separate experiments;
> they do not control connected research runs. Production uses `showcase/server.mjs`,
> not the Vite development server. Public demo access needs no login.

## Separate SFO overview

Open `/sfo-overview/` for the Three.js landscape, recorded August 24–30 replay,
source observations, and optional tower simulation. The existing `/` page and
its research workflow remain unchanged. This route uses local scenery assets
and the existing `/uita/api/history/` API; it needs no browser Maps key.

`npm run build:overview` compiles the two new pages and their assets into
`dist-overview/candidates/`. `Dockerfile.showcase-frontend` includes that build
without rebuilding or replacing the existing app pages. For local development,
set `UITA_SERVER_URL` to the research API server and run `npm run dev`.

See [SFO_OVERVIEW.md](SFO_OVERVIEW.md) for data limits and verification.


**Connected research demo:** the existing dashboard and tower cab now support
shared historical/recorded/live research state, evidence inspection, matched
comparison and export. Follow the [connected startup and staging guide](../docs/research/v2/SHOWCASE.md).
It uses the FastAPI host rather than this directory’s legacy Vite server.
The recorded Nemotron attempt fell back to the deterministic controller; no
improvement is claimed. The standalone gallery remains scripted as described below.

The demo frontend for UITA's recursive-agent ATC: a photoreal SFO dashboard with a Tower! Simulator-style cab view, an agent radio loop with voice, and 20 visualization candidates. **Research simulation only; not operational ATC.** Traffic, agent decisions and scores are scripted or mocked unless a page says otherwise.

## Run

```sh
cd showcase
npm ci
npm run dev        # http://127.0.0.1:5173
```

Open `/candidates/app.html` for the shipped app, or `/candidates/` for the gallery. Node 22.12 or newer.

Server-side environment variables, read by the dev server and never exposed to page code except the Maps key:

| Variable | Used for |
|---|---|
| `OPENAI_API_KEY` | `/api/tts` agent voices (gpt-4o-mini-tts), `/api/stt` push-to-talk, `/api/agent` fallback |
| `GOOGLE_MAPS_API_KEY` | Google Photorealistic 3D Tiles in 11 and 19, served by `/api/maps-key`. It's a browser key, so restrict it by HTTP referrer. |
| `CRUSOE_API_KEY`, `CRUSOE_BASE_URL`, `CRUSOE_MODEL` | Optional: sector agent on Crusoe instead of OpenAI |
| `DEMO_PASSWORD` | Required whenever the server binds beyond localhost. HTTP Basic auth over every page and API. |
| `DEMO_HOSTS` | Comma-separated public hostnames allowed in hosted mode |

`npm start` is the hosted entry point (`vite --host 0.0.0.0 --port $PORT`). It refuses to start without `DEMO_PASSWORD`. The Railway service `frontend` in project `uita` runs it.

## What's here

- `candidates/app.html` is the shipped app. It opens on **11 Photoreal SFO**; **T**, or the switch, toggles to **19 Tower cab interior**. Only one 3D view renders at a time.
- `candidates/01–20` are the visualization candidates; `candidates/index.html` is the gallery. 20 is a week-replay evaluation console whose mock `DATA` matches `docs/api.openapi.json` and `docs/evaluation/fixture-result.json`.
- `candidates/radio-audio.js` is one half-duplex frequency, with VHF filtering and baked OpenAI voices. Clips are cached under `candidates/audio/` (not committed; generated on first play).
- `src/radio.mjs` handles structured clearance → phraseology → parse → field-by-field readback check (`npm test`). `src/atc.mjs` and `src/voice.mjs` contain the browser radio loop, push-to-talk and the tool-calling sector agent. The scheduler stays the only writer.
- `candidates/data/` holds the Bay coastline, SFO/OAK aeroways (OSM, ODbL), OpenSky tracks and METAR. Sources are in its README.

Credits: Google Maps Platform 3D Tiles; OpenStreetMap contributors (ODbL); US Census; OpenSky Network; NOAA/NWS; "Airplane" by Poly by Google and "Boeing 747" by Miha Lunar (CC BY 3.0).

## Recorded SFO week

The default dashboard now shows **August 24–30, 2026, America/Los_Angeles**.
`/` redirects to `/candidates/app.html`. The dashboard reads PostgreSQL through
`/uita/api/history/catalog` and `/uita/api/history/window`; credentials stay on
FastAPI. The tower switch is explicitly **Tower simulation**. The old dashboard
remains available at `/candidates/11-photoreal-sfo.html?mode=simulation`.

Start the existing FastAPI service with a server-side `UITA_HISTORY_DATABASE_URL`
pointing at the imported database (`atc_sfo_w35`). A PostgreSQL `DATABASE_URL` or
repository `.env.local` is also supported. Replay connections enforce read-only
transactions. In local development, the showcase history proxy defaults to
`http://127.0.0.1:8001`; override with `UITA_SERVER_URL` for another backend.
Hosted instances require `UITA_SERVER_URL` as before.

Playback includes play/pause, 1×–600× speed, seven date selectors, a week slider,
PDT time input, ±15-minute jumps, +10 seconds, restart and week end. The browser
owns its replay clock. It holds while loading and stops at the week boundary.
Each displayed target uses an original observation at or before the replay time,
within 15 seconds. Trails break at gaps and new legs. Ground flags permit surface
placement; airborne targets without altitude remain in the source list.

The panel reports current regional targets, map placement coverage, and FAA
OPSNET's daily SFO operation totals. Regional targets include surface vehicles,
nearby airports and overflights. This is not an airport-matched flight roster.
Safety events, landing delay, arrival rate, runway use and operation-level path
coverage remain unevaluated. No scripted radio, agent decisions or fabricated
scores appear in recorded mode. Photoreal tiles need the existing Maps key; the
local imagery pack is the fallback.

The API reads one actual sample per five-second bucket, in 15-minute windows.
The catalog is cached for five minutes; windows are bounded in memory and keyed
by import revision. A cold database read can take tens of seconds. Loading and
errors are explicit, and unavailable dates are disabled.

Verification (run both local servers first):

```sh
# Source-row comparison, using the same server-side database configuration:
PYTHONPATH=backend UITA_HISTORY_VERIFY_URL=http://127.0.0.1:8001/api/history \
  .venv/bin/python showcase/scripts/verify-history.py

# Browser suite uses showcase on port 5190; test dependencies live in web/:
cd web
npx e2e run tests/showcase-history.e2e.ts --config e2e.showcase.config.ts
```

Verified on October 17, 2026: **12,394,470 source observations** across the seven
PDT dates. The source comparison checked five observations in each day's noon
window: all **35 matched** the database's timestamp, coordinates, measurements,
identity and metadata. This is a sample-based wiring check, not a claim of
complete flight coverage or validated safety detection.

The connected showcase defaults to login-free public demo access. Visitors share
the research workspace, including explicit budgeted live runs. Set
`UITA_ACCESS_MODE=private` to require accounts. See
[access and startup instructions](../docs/research/v2/SHOWCASE.md).

The connected showcase now uses the sparse `backup/71b23cc-sparse` presentation.
Open **UITA · Menu** for data sources, live runs, comparison and evidence.
The original camera toolbar and aircraft cards operate on shared backend frames;
the compact controller panel shows actual proposal explanations, verification,
and issued clearances. Click its aircraft to inspect the assigned runway.
See `docs/research/v2/SHOWCASE.md` for controls and validation limitations.
Browser regression: `playwright-cli run-code --filename showcase/scripts/sparse-acceptance.js`.

### Simulation reasoning panel

Before serving the showcase locally, run `npm ci --prefix frontend` and `npm run build:trace --prefix frontend` from the repository root. The production Docker build includes this panel. See [Simulation trace](../docs/SIMULATION_TRACE.md) for its provider, replay, and spending boundaries.

Historical / Simulation now switch directly from the scene and remember separate
playback positions and selections. Sources preload automatically. **Follow landing**
focuses an arrival without automatic camera changes during mode switching.
Historical approach cues are explicitly inferred; the current packaged windows
have insufficient evidence to qualify under the conservative heuristic.
Run `showcase/scripts/switch-acceptance.js` and `live-switch-acceptance.js` through
`playwright-cli run-code --filename` against a local API and fixture worker.

The default **busy arrivals** recording contains 6–8 airborne aircraft across its
20-minute presentation, with a clearly labeled deterministic controller. Decision
cards appear over the map as clearances and pilot events occur. Use **Overview**
for the regional arrival queue, **Airport** for airport detail, and **Follow landing**
for an explicit aircraft follow. The three-aircraft queue opens inspection and evidence.
Rebuild with `PYTHONPATH=backend python scripts/build_dense_demo.py`, then run the
existing research pre-deploy/bootstrap command to install the bundled data.
See [measured coverage and limitations](../docs/research/v2/SHOWCASE.md#busy-arrivals-demonstration-dense-demo-v1).
Browser acceptance: `playwright-cli run-code --filename showcase/scripts/dense-acceptance.js`.
