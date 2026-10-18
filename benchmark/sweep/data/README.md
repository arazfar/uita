# Frozen August 24–30 demand

This pack contains real recorded arrival demand with reconstructed initial states.
All 1,029 selected initial states are synthetic. They are not observed late-week aircraft positions.

The DataSF query returned 4,126 arrival-operation records for August 24–30, 2026.
The builder excluded 50 records without a named runway, leaving 4,076 eligible operations.
It selected six fixed windows per day, containing 1,029 unique operations in total.
Each selected window contains between 3 and 37 requests.

| Local date | Selected windows | Selected operations |
|---|---:|---:|
| August 24 | 6 | 143 |
| August 25 | 6 | 146 |
| August 26 | 6 | 145 |
| August 27 | 6 | 156 |
| August 28 | 6 | 149 |
| August 29 | 6 | 133 |
| August 30 | 6 | 157 |
| Total | 42 | 1,029 |

Windows start at 06:00, 09:00, 12:00, 15:00, 18:00 and 21:00 in `America/Los_Angeles`.
Requests release from 15 minutes before each start until 30 minutes after it.
The simulation continues until 60 minutes after the start.
No source operation repeats across windows. These windows do not cover the full week's demand.

## Initial states and weather

The cached SFO Museum monthly archive contains 13,633 arrival metadata records dated August 24–30.
None has a matching `swim-path` variant in this archive.
The builder therefore uses the unchanged 1,152 entry templates fitted on August 3–6.
Template selection uses a deterministic hash, with origin-matched templates preferred.
Each request's release time equals its actual late-week recorded operation time minus its development template's lead time.
This creates historical-demand reconstruction. It does not recover an observed entry time or a human clearance.

An independent check reconstructed all 1,029 selected entries from the late-week roster and development templates.
Every field matched the frozen pack. The template file checksum also matches the original pipeline manifest.
Its fit days contain 303, 274, 272 and 303 templates for August 3, 4, 5 and 6 respectively.

The weather query returned 243 KSFO METAR/SPECI reports from August 23 through August 31 UTC.
The extra UTC day covers the final August 30 local evening window.
Weather becomes available five minutes after its observation time, following the existing benchmark assumption.
Actual receipt times are unavailable. Each window includes its latest prior report and reports available before its horizon.
The latest prior report is at most 44 minutes old at each window's warmup start.
The model receives only reports available at its current simulation clock.

DataSF timestamps are naive. The builder interprets them as `America/Los_Angeles`, matching the original benchmark assumption.
Recorded operation times are not verified touchdown times. This pack contains no actual airline delay or human action labels.

## Loading and source evidence

```python
from benchmark.sweep.traffic import DATA_DIR, load_episodes

episodes = load_episodes()  # All 42 runner-private episode queues.
```

Do not give complete episode queues to a model. Release requests and weather causally.
Run matching scripted and deterministic references on these same 42 windows.
August 7 scores remain historical references; they are not matched late-week comparisons.

Rebuild with cached sources or download missing date-matched sources:

```sh
pipeline/.venv/bin/python -m benchmark.sweep.traffic
```

`manifest.json` records artifact hashes and counts. `provenance.json` records complete queries and source hashes.
`verification.json` records construction checks. Frozen source hashes include:

- DataSF roster: `8191f4796799132ad0e2343ba602092fc46ef53d7743e8ba8065290f51c73596`
- Monthly archive: `c3bfa8320110aba8d3c9f5a0ab30dd2a7ddf53ac7f4dc9debd596a20a9f27c43`
- Development templates: `405a10f11b001a37a0ff032b8e352af3db4e4bf7ba071204e8353c07b25bd413`
- Weather CSV: `e4f825c99b6264390d3149ef79405f5e18974c56926d34ebce5eeb3a5a145b5f`

August 8–9 are excluded from data construction, model inputs and evaluation.
The builder filters archive metadata to August 24–30, then selects path variants only for those IDs.
An initial source-discovery diagnostic loaded archive path timestamps before filtering for late-week coverage.
It did not display, inspect, use or score August 8–9 row values, or access their outcomes.
This distinction means the audit does not claim that held-out archive bytes were never loaded.
