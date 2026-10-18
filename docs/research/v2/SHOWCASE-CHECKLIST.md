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
- Local SIGKILL/lease takeover and hosted worker replacement recovery passed.

Hosted release checks:
- Local and hosted final browser suites passed, including fixture failures and exports.
- Matched Railway images built; public health, catalog, recordings and data return 200.
- Hosted SSE and worker replacement recovery passed (same run, revision 2 → 94).
- Dedicated pre-deploy job installed v2 history (55 tracks); readiness checks every packaged artifact.
- Public release: https://uita.up.railway.app. Final alias/merged-overlay smoke check pending.

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

Nonblocking validation limitation: the standalone gallery tower suite passed its wind
and connected-authority checks (2/3); its real-time landing-roll → stopped assertion
exceeded 30 seconds under SwiftShader. The connected research flow passed. That
separate gallery timing issue is deferred; no simulator/verifier criteria were changed.

See [startup, demo script, outcomes and rollback](SHOWCASE.md).
