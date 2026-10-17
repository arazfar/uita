# Data delivery handoff

Railway PostgreSQL stores two frozen datasets. Credentials stay in the ignored root `.env.local`.

- Arrival simulation: `sfo-2026-08-03_09-v1` — 4,220 arrivals, 2,164 tracks, 239 METAR/SPECI reports, 42 benchmark windows, 27 checksum-verified artifacts.
- Dashboard historical replay: `sfo-traffic-replay-2026-08-03_09-v1` — 8,439 operations (4,220 arrivals and 4,219 departures), 4,128 tracks, 15 checksum-verified artifacts. This preserves the teammate UI export and its documented field assumptions.

The read-only data adapter runs at `http://127.0.0.1:8100/api/data`. It serves development scenario packs and withholds test/outcome artifacts. The trusted historical replay adapter runs on port 8101, with the existing `flights.json`, `tracks.json` and `runways.geojson` contract. No browser receives the database credential. The UI and harness still need to wire their loaders to the adapters or local packs.

Integration instructions: `pipeline/README.md`. Python adapter: `pipeline/uita_data/adapter.py`. TypeScript adapters: `pipeline/typescript/`. Storage schema: `pipeline/sql/schema.sql`.

Benchmark and training recommendation: `context/data-benchmark-plan.md`. The benchmark reserves August 3–6 for training, August 7 for validation, and August 8–9 for final testing. It compares controllers under the same simulator. Authentic historical human clearances are absent.

Verification completed:

- Python scenario playback verified all 4,220 spawns, template isolation, weather timing, checksums, position bounds and split membership.
- TypeScript runtime verified all 4,220 spawns, replay staleness and FAA cycle/threshold selection.
- Strict TypeScript type checks passed.
- Railway counts and all artifact SHA-256 checks passed for both datasets.
- Arrival HTTP adapter returned a scenario identical to the local pack, blocked test/outcome routes, and passed cache/CORS checks.
- Exporter and score-summary smoke checks used temporary synthetic QA records. Held-out training examples and incomplete run matrices were rejected. Those records were deleted.

No real controller comparison, reviewed training-label corpus, paid fine-tuning job, or fine-tuned model deployment exists yet. The simulator team must implement and freeze disturbance behavior and checker/scoring definitions before reporting benchmark results.
