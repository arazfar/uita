# Hackathon demo release checklist

Scope: early-August synthetic metering → autonomous fixture control → runway
closure → decision/verifier evidence → matched deterministic baseline → export.

- [x] Complete regression suite: 262 passing tests after touchdown fix.
- [x] Original production frontend stays the default; research mode is opt-in.
- [x] Independent verification preserved; unsafe historical scenario still fails.
- [x] Model timeout and budget faults fall back visibly; fixture mode costs $0.
- [x] Free comparison freezes executed candidate and replays its timed disruptions.
- [x] Early-August demo artifacts bundled with checksums; no source DB needed at startup.
- [x] Browser acceptance: complete flow, both exports, model/budget fault fixtures,
  offline reconnect, failed historical scenario, narrow layout and keyboard focus.
- [x] Final PostgreSQL lease/idempotency/budget validation and migration smoke check.
- [x] Actual worker SIGKILL/restart: fenced takeover after lease expiry, no lost state.
- [x] Final deployment runbook and fresh migration/bootstrap/readiness check.
- [x] Dependency consistency, credential scan, type checks and both frontend builds.

Deployment status: **configuration-only staging delivery**, as requested. Railway
rejected isolated environment creation with `Not Authorized`; no environment or
production configuration was changed. Docker image and hosted staging acceptance
remain unverified because the local Docker daemon is unavailable and no staging
credentials are configured. Do not cut over production on the strength of local
checks.

Local demo gates are complete. Detailed results: [validation.json](validation.json).
Next deployment gate: build the Docker image and run the same acceptance flow in
an isolated Railway staging environment with appropriate account access. Hosted
backup restoration and monitoring remain required before production cutover.

## Connected showcase integration

See [the showcase checklist](SHOWCASE-CHECKLIST.md) for its separate current
acceptance evidence and deployment blockers. The existing production Vite entry
remains preserved until explicit cutover.
