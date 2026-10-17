# UITA showcase

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
