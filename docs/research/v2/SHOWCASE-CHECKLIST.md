# Immersive demo release checklist

Verified locally:
- 282 backend tests; 17 showcase tests. Fresh-database pack import/checksums,
  geographic interpolation boundaries, public/private access and atomic budgets.
- Both frontend builds and explicit shipped-asset checks pass.
- PostgreSQL additive migration and demo-pack installation completed. All source
  collections preserved. Backup restored all 209 legacy records into an isolated DB.
- Guided scripted episode: 20 presented minutes, 4 completions, 28 backlog,
  no modeled violations/rejected proposals. Authentic episodes retained separately.
- Browser checks cover baseline/map/table alignment, run replacement, closure,
  rejected proposals, model/budget fixtures, failed scenario, exports and reconnect.
- Prior worker SIGKILL/lease takeover check passed; hosted takeover remains separate.

Current gates:
- Local final browser rerun passed; hosted final rerun is in progress.
- Matched Railway images built; public health, catalog, recordings and data return 200.
- Hosted SSE, worker recovery and production demo smoke acceptance.

Performance sample: Apple M1 Pro/macOS, headless Chromium 155, 10 reported hardware threads,
1280×720, five-second animation-frame samples: 60.2 FPS normal, 55.3 FPS with an
explicit synthetic 200-target rendering fixture; p95 frame interval 16.8 ms.
390×844 viewport emulation measured 60.1 FPS. These are short browser scheduling
samples, not GPU benchmarks or physical-mobile results. Extended memory, mobile
hardware and four concurrent 200-aircraft simulations are not certified here.

Limits: historical hour has 55 tracks/868 points, 61 measured altitude samples.
Unknown altitude stays unknown. New Nemotron episode 2 had 10 rejected proposals,
3 completions versus baseline 4; no superiority claim. Guided mode is visibly
scripted, never labeled authentic model output. Unsupported ATC capabilities remain
unresolved. New campaign known cost $0.0054961; reservations $0.0980682.

See [startup, demo script, outcomes and rollback](SHOWCASE.md).
