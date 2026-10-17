# Browser verification — 2026-10-17

The application was exercised at http://127.0.0.1:5173 against the local FastAPI service on port 8001. Screenshots and downloaded evidence are retained locally under `output/playwright/` (ignored generated artifacts).

## Verified workflow

- Play/pause changed server-owned aircraft positions and logical time. Desktop and 390px layouts displayed the same backend traffic, weather, reservations and metrics.
- Closing 28R changed the proposal to 28L arrivals. Independent verification passed, commitment succeeded, and reload preserved revision 4 and the closure.
- Delaying observations produced **unresolved** verification. The Commit button was disabled; evidence explicitly identified the 15-second freshness requirement.
- A fixture experiment launched through the UI completed three candidate evaluations in 3.19 seconds. Job `02519490-3059-404a-b05c-c359fea96e98`, iteration 2, parent `static`, persisted across reload. It used zero provider calls. Candidate rejection and raw evidence remained inspectable.
- Rejected-candidate comparison opened two independently verified matched plans. The shared replay clock advanced both views. Its summary values are backend planning projections at episode end; the replay is explicitly labeled as trajectory sampling, not a new closed-loop experiment.
- Checkpoint replay showed recorded state without changing current server revision or logical time. Evidence export downloaded valid JSON. The independent startup smoke additionally verified replay before a closure.
- Keyboard focus plus Enter selected UAL214 through the accessible traffic table. Top-down and orbit controls changed view state.
- Reduced-motion preference was detected. Simulated browser network loss displayed an error; reconnect cleared it. No claim of a full assistive-technology audit is made.

## Measured performance

Device: MacBookPro18,1, Apple M1 Pro, 16 GB, macOS 26.6.2. Browser: Playwright HeadlessChrome 155, ANGLE Metal Apple M1 Pro. Vite development build, 1440×1000 viewport, device pixel ratio 1. Scene: seed 42, 12 modeled flights, two active arrivals near logical second 585, original Blender assets, trajectories enabled.

Over a five-second animation sample: 300 frame intervals, mean **16.666 ms**, p95 **16.700 ms** (approximately 60 fps). Renderer instrumentation reported **106 draw calls**, **35,261 triangles**, render pixel ratio 1.00. Browser experiment launch click took **59 ms**, and switching to Traffic while the worker ran took **46 ms**, measured around Playwright actions. These are local smoke measurements, not cross-device performance guarantees.

Narrow inspection: 390×844 viewport, full-page capture; document width **390px**, no horizontal document overflow. Captures: `desktop-final.png`, `mobile-final.png`, and `comparison.png`.

## Defects corrected during verification

Removed independently mounted 3D HTML roots that produced React unmount errors, made offshore aircraft discoverable, separated runway labels, tightened camera framing, bounded lazy raw-evidence rendering, enabled research comparison of rejected candidates, corrected current proposal selection and replay controls, and added error boundaries and missing favicon. Expected console failures during deliberate network loss, a server restart, and one test probe of a nonexistent endpoint are distinguished from application errors.

Final independent visual review used a fresh custom GPT-6 Astra reviewer, equivalent to the skill's named finish-review role (the harness has no named-role selector). It found two material defects: heading/aircraft-label overlap and an invariant north indicator. The fixes were recaptured at both widths; there were zero heading/aircraft-label intersections. Camera-projected north measured 45.82° in overview and 0° in top view. The reviewer returned **ship**, scoring both fixes resolved with no visible fix-induced regressions. This verdict covers those findings, not an unrestricted audit. The final production build passed. Camera damping/follow interpolation also honor reduced motion, and checkpoint reservation windows now follow the replay time.

The development agents' preview processes ended with their sessions. Both services were restarted under the main session, the browser was reloaded before final captures, and the database restored the recorded jobs and paused state. Health reported the database connected and retained the prior verified live Crusoe job. No new inference was needed.

Backend evidence is separate: [independent validation](INDEPENDENT_VALIDATION.md), [startup/restart smoke](evaluation/startup-smoke.json), [dependency installation](evaluation/dependency-lock-smoke.json), and [final live-program reevaluation](evaluation/live-program-reevaluation.md). Docker/PostgreSQL deployment was not run: the local Docker daemon was unavailable. No service was published.
