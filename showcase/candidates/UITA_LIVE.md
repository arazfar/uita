# Uita live data layer

`uita-live.js` connects a candidate page to the team's Uita FastAPI simulator (Railway) through the dev-server proxy at `/uita/*`. The proxy adds the bearer token on the server side, so pages never hold a token. The module has no dependencies. Proof page: `uita-live-test.html`.

```html
<script src="uita-live.js"></script>
<script>
  UitaLive.on("state", s => render(s))         // fires on every poll and after each mutation
          .on("offline", () => useScriptedDemo())  // server unreachable: keep the scripted demo running
          .on("online", () => useLive());
  UitaLive.start({ intervalMs: 1000 });
</script>
```

## API
| Call | What it does |
|---|---|
| `start({intervalMs=1000})` / `stop()` | Polls `GET /uita/api/state` with one request in flight at a time. Polling pauses while the page is hidden or after `postMessage({uita:'pause'})`, and resumes on `{uita:'play'}` or `{uita:'resume'}`. |
| `on/off(event, fn)` | Events: `state`, `online`, `offline`, and `step` (kernel progress: `{step, phase: start\|done\|error}`). |
| `toLonLat(x, y, runway?)` | Converts backend ENU nautical miles to `[lon, lat]`. Pass the aircraft's runway (see the fit section). |
| `control(action, extra)` | `action` is one of `play`, `pause`, `step`, `speed`, `reset`. Extras: `{speed: 0.25–30}`, `{seconds}` for step, `{seed, scenario}` for reset. |
| `disrupt(body \| kind)` | `kind` is one of `runway_closure`, `weather`, `emergency`, `communications`, `arrival_surge`, `gate_delay`. Optional fields: `runway` (default 28R), `aircraft_id`, `severity` (0–5). |
| `proposeVerifyCommit()` | Runs the agent proposal, then the kernel's independent verification, then a commit only if verification passes. Resolves to `{propose, verify, commit, verdict, ok}`, where each step is `{ok, ms, result \| error, status}`. It never rejects. |
| `replay(t)`, `health()` | `GET /api/replay?time=t` (normalized) and `GET /api/health`. |
| `UitaLive.state`, `UitaLive.online` | Last normalized state; `online` is `true`, `false` or `null` (unknown). |

Normalized state has the shape `{aircraft:[{id,callsign,type,wake,op,status,lon,lat,altFt,heading,speedKt,runway,delayS,emergency,path:[[lon,lat,altFt,t]]}], runways:[{id,a,b,closed,lengthFt}], metrics, events, proposals, reservations, weather, disruptions, time, running, speed, revision, raw}`.
- `status` is one of `pending`, `approach`, `taxi`, `complete` and so on.
- `metrics` is passed through unchanged: `completed`, `total`, `mean_delay`, `p95_delay`, `conflicts`, `throughput`, `backlog`, `score`, and more.
- `raw` holds the original snapshot.

## Latency
The server is slow: each state request takes 2–10 s. Effective updates therefore arrive every few seconds, not every second. Dead-reckon between polls using `heading` and `speedKt`, or interpolate along `path` using sim `time` and `path[i][3]` (t). When a request fails, the module backs off for up to 10 s and emits `offline` once.

## The ENU → lon/lat fit
The backend frame has no geodetic origin. Runway lengths match OSM to within 12 m, so scale is 1. The fit is rigid (rotation plus translation) against OSM SFO runway ends.
- **28L/28R** (transform `T28`): RMS 1.0 m, max 1.5 m. Rotation −0.81°.
- **01L/01R** fitted with `T28`: off by about 560 m, because the backend misplaces the 01 pair relative to the 28 pair. No single rigid transform fits all four runways; a combined fit leaves about 280 m RMS error.
- **01L/01R** (transform `T01`): RMS 36 m, max 42 m.

`toLonLat` uses `T01` when `runway` starts with 01 or 19, and `T28` otherwise. The module applies one transform to each aircraft's whole path, chosen by its runway, so there are no jumps. As a result, departures (01L/01R) and arrivals (28L/28R) each sit on the correct real runway.

**Gap:** the backend's synthetic gate/ramp point (−1.86, −0.6 nm) lands about 2.5 km west of the runways, which is off-airport. Ramp and taxi positions are not geographically meaningful, so hide them or clamp them to the terminal.

## What each candidate should show
- **11 photoreal SFO and 19 tower cab:** draw aircraft at `lon/lat/altFt` with `heading`. Use `path` for approach ribbons, colour by `op`, and treat `emergency` as red. Hide aircraft whose status is `pending` and whose altitude is 5000 ft at the entry fix, or show them as distant traffic.
- **HUD:** show `completed/total`, `mean_delay`, `conflicts`, `backlog` and the latest `events` message.
- **On-stage beat:** a button or voice command calls `disrupt('runway_closure')`, then `proposeVerifyCommit()`, while each `step` event is shown as a ticker. Commit appends a `commit` event and bumps `revision`.
- **Offline:** on `offline`, keep the existing scripted data. On `online`, switch back.

Avoid `/api/learning/train`, which starts paid jobs.
