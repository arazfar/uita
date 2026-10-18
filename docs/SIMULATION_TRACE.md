# Simulation agent trace

The deployed Simulation tab exposes the shadcn / AI Elements chain-of-thought pattern in **Traffic & evidence**. It reuses the existing React/Radix component and its Apache-2.0 license. The tower controls and traffic renderer remain independent.

## Data path

```
Pydantic AI Agent → CrusoeModel → reserved HTTP transport → Nemotron
                                    ↓
                   bounded provider reasoning + proposal
                                    ↓
             worker journal → independent traffic verifier
                                    ↓
                live events / saved recording → React panel
```

The controller enables the pinned model's medium-effort thinking mode. Only the provider's `reasoning_content` or `reasoning` field becomes reasoning text. The shared journal helper bounds the serialized excerpt. Text is rendered by React, never interpreted as HTML. Proposal explanations, independent verifier results, discarded responses, and controller failures remain distinct.

One agent run permits one paid request, with no SDK, transport, or output-repair retries. The existing shared, team, and run caps reserve spending before dispatch. Actual usage is settled before output validation. Ambiguous failures retain their reservation. The worker keeps its existing freshness and independent verification checks; returned reasoning cannot authorize a clearance. This integration does not give the model new tools or traffic access.

The journal updates after each response completes; it does not stream private token-by-token reasoning. Old recordings are unchanged and may contain no reasoning. Fixtures are labeled as authored steps. The panel only shows events at or before the playback clock, resets when the source changes, and limits the visible journal to its latest 60 relevant events. Full evidence remains exportable.

## Build and run

From the repository root:

```
npm ci --prefix frontend
npm run build:trace --prefix frontend
```

This builds `showcase/candidates/trace-assets/`, which is ignored. Run this build before serving the showcase locally. `Dockerfile.showcase` builds and copies the panel automatically. A missing panel bundle leaves traffic playback and raw evidence usable.

## Verification

- Existing backend inference/runtime tests cover spending rejection, timeout, invalid output, provider failure, worker ownership, and independent traffic state.
- `web/tests/simulation-trace.e2e.ts` uses saved backend recordings to check fixture labeling, old-recording reasoning absence, keyboard collapse, backward seeking, and retained tower controls.
- A local live verification passed a real Nemotron response through Pydantic AI, then loaded its actual returned reasoning as a local-only QA recording. That recording and its inference ledger are not shipped.

Component reference: https://www.shadcn.io/ai/chain-of-thought
Source and license: `frontend/src/components/ai/chain-of-thought.tsx` and `frontend/src/components/ai/LICENSE`.
