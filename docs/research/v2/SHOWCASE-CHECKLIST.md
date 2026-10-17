# Showcase release blockers

Completed locally:
- Backend regression suite: 277 passed. Showcase suite: 16 passed.
- Rebuilt early-August historical replay passes the source audit (8,439 operations,
  4,128 paths); no new source collection.
- Authenticated shell, shared dashboard/tower frame, historical context,
  immutable Nemotron recording, closure evidence, matched comparison and export.
- Browser model-failure/budget fixtures, unsafe proposal rejection, run reload, offline/reconnect, scenario
  failure at 151 seconds, synchronized recorded comparison, expired session and
  renderer failure with accessible aircraft table.
- Desktop and 390px layout inspected; no page-width overflow. Legacy score and
  radio loops are excluded from connected views.
- Actual local worker SIGKILL/recovery passed: fencing token 1 → 2, committed
  clock continued after lease expiry; the browser surfaced the stall and recovery.
- Both frontend builds and explicit packaged-asset verification pass.
- One predefined paid recording retained: $0.000797 known / $0.001867 reserved.
  No model-issued flight clearance and no improvement over the baseline.

Remaining gates:
- **Next blocker: Docker image build and isolated Railway staging acceptance.**
  Docker daemon is unavailable; staging privileges were previously unavailable.
  Production service configuration has not been changed.
- Hosted PostgreSQL restoration rehearsal, worker takeover and HTTPS/session/SSE
  checks must pass before cutover. Existing runtime recovery/concurrency tests
  remain in the backend suite.
- Late-August archive and Google photoreal tiles need their optional upstream
  configuration; local acceptance used the bundled imagery fallback.

Product limitation: the recording demonstrates honest model failure handling,
not successful Nemotron flight control or a measured improvement. More favorable
outcomes must never be manufactured or selected from undisclosed attempts.
See [startup, demo and deferred work](SHOWCASE.md).
