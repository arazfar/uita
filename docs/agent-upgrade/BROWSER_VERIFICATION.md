# Agent upgrade browser verification

The running React application and FastAPI service were inspected on October 17, 2026 using Playwright Chromium on an Apple Silicon Mac, macOS 26.6.2. The API used Python 3.11.17 and the migrated SQLite database. These checks used actual local API responses, not mocked browser routes. Experiments used the explicitly labeled offline `FunctionModel` fixture; browser checks made no paid requests.

## Observed workflow

- Launched an experiment from Learning with one permitted revision. The launch interaction returned in 102 ms in the measured run; optimization continued in the isolated worker while the interface remained usable.
- Job `18a9eb07-a322-4997-b2d3-456e8643d238` completed in 2.76 seconds with 18 persisted events, four fixture model requests, two inspection tools, three development evaluations and three independent validation evaluations. It produced two proposals, froze the first by its development result, and rejected it at the fixed validation gate. Provider calls, provider tokens and inference cost were all zero.
- Expanded both revision records and loaded raw JSON on demand. The displayed program and frozen hash matched the exported backend artifact: `11b054755739fc4b00703ece734295d5362d8f9eccc5af331faf88c6ef8fcab8`.
- Cancelled job `d47fe897-e768-44d1-b490-15fdc03b2524` during inspection. Its terminal cancellation and four events survived reload. The prior historical jobs and original rejected live candidate remained readable.
- Reloaded the browser and restarted the real API with the migrated database. Completed and cancelled records remained intact. The original database was preserved as an ignored local `uita-before-agent.db` backup; the upgraded app now uses the normal `uita.db` path.
- Repeated the fixture workflow after the final `investigator-2` migration: job `62f4b604-6d08-4ed9-8b79-92bbe1be5441` completed/rejected in 2.43 seconds with the same 18-event lifecycle and resource counts. The API reports historical one-shot verification separately from `agent_loop_verified: false`.
- Exported the evidence bundle and parsed it independently: the completed job, all 18 events, frozen program/hash, policies and checkpoint history were present. Download: `output/playwright/agent-browser-export.json` (local verification artifact, not committed).
- Opened the actual baseline/candidate comparison. Both views reported the same checkpoint and matched exogenous events, independently verified plans, and backend metrics. Keyboard replay reached the exact 2,700-second horizon. These checkpoint metrics are separate from the promotion study; they are not evidence of a learning gain.
- Scrubbed checkpoint replay, observed the replay banner, and returned to current state. Existing scenario, operational scene and timeline controls remained available.

## Layout and corrections

Inspected screenshots at **1440 × 1000** and **390 × 844**. Narrow document width remained 390 pixels with no horizontal overflow. Experiment controls, rejection state, separate development/validation evaluation counts, elapsed time, lineage and evidence stayed readable in the scrollable inspector.

The review corrected misleading held-out wording, distinguished provider tokens from fixture accounting, and showed total job time rather than investigation time alone. Comparison policy labels originally overlapped aircraft labels; an opaque identity strip now preserves their readability. Fractional checkpoint times originally conflicted with the comparison slider's implicit integer step; explicit continuous stepping and a clamped final increment now reach the exact horizon.

Final polling inspection found new development artifacts duplicated in scene updates. Removing bulk job/policy evidence from these summaries reduced the measured `/api/state` response from 864,902 to 41,020 bytes for the saved demo history. After restarting and reloading, the complete two-proposal history still loaded from its dedicated endpoint and rendered correctly. Full exports retain the artifacts.

Local screenshots (ignored output artifacts):

- `output/playwright/agent-desktop-complete.png` — actual revision/program evidence beside the operational scene.
- `output/playwright/agent-narrow-complete.png` — experiment controls and terminal status.
- `output/playwright/agent-narrow-evidence.png` — lineage, resource counts and revision history.
- `output/playwright/agent-comparison.png` — corrected comparison identity and exact final replay time.

Frontend type checking and the production build passed. The existing Rapier bundle-size warning remains. Transient proxy errors were observed during the intentional API replacement; the restarted service recovered. No new rendering or interaction failure remained in the exercised workflow. This is a local interaction check, not a device-wide performance benchmark or a successful live-agent claim. See the separate [live capability results](live-evaluation.md) and [independent backend validation](INDEPENDENT_VALIDATION.md).
