# Cached ADSB.lol data in Railway

The `pipeline.uita_data.adsb_cache` importer stores a frozen snapshot of **complete,
verified local archive scans**. It never downloads data. Partial tar downloads
remain in `pipeline/.cache/adsb-lol/full-week/` for the separate full-week task.

The source is [ADSB.lol's 2026 archive](https://github.com/adsblol/globe_history_2026/releases),
licensed under ODbL 1.0. Every imported archive part must match its release-manifest
size and SHA-256. Original compressed traces must match their scan checksums.

Run from the repository root after scanning the available complete archives:

```sh
pipeline/.venv/bin/python -m pipeline.uita_data.adsb_cache
pipeline/.venv/bin/python -m pipeline.uita_data.adsb_cache --verify-only
```

The existing server-only `DATABASE_URL` selects Railway. The importer creates an
immutable dataset ID from the source manifest and file hashes. Repeating an
unchanged import is safe. Each import commits atomically and leaves prior replay,
benchmark, and controller data unchanged.

- `uita_data.datasets`: source manifest, imported UTC dates, counts, license,
  checksums, and `full_week_complete`.
- `uita_data.artifacts`: original compressed aircraft traces, scan reports, and
  manifests. Global tar archives are not uploaded.
- `uita_data.adsb_trace_index`: aircraft identity, time range, observation count,
  and source archive members. Join `artifact_name` to `artifacts.name`.
- `uita_data.adsb_candidates`: candidate arrival/departure matches, keyed by
  dataset, release, and operation ID. The JSON `payload` contains observed points,
  source files, flags, and airport/time matching evidence.

These are candidate matches, not accepted flight legs. Original aircraft traces
also contain movements at other airports. Do not use this dataset as a complete
week or as validated replay/safety data. The separate full-week task must finish
extraction, review flight legs, and validate the final supplement.

Find uploaded snapshots:

```sql
SELECT id, manifest->'counts' AS counts, manifest->'releases' AS releases,
       manifest->'full_week_complete' AS full_week_complete
FROM uita_data.datasets
WHERE manifest->>'kind' = 'adsb_backfill_candidates';
```

Download a snapshot's original files with the existing artifact downloader:

```sh
pipeline/.venv/bin/python -m pipeline.uita_data.store download \
  --dataset-id DATASET_ID --directory /tmp/adsb-snapshot
```

Local manifests and database verification receipts are saved under
`pipeline/.cache/adsb-lol/full-week/postgres/DATASET_ID/`. Verification compares
all stored artifact hashes and every candidate and trace-index row to local data.

## Verified snapshot — October 17, 2026

Dataset: `sfo-adsblol-cached-0e89cdc06eb9832d`.

- Complete source archives: August 3 and 4, 2026 UTC. This is **not the full week**.
- 4,006 original traces containing 14,172,810 raw observations.
- 1,983 candidate operation matches: 779 from August 3 and 1,204 from August 4.
- 4,010 stored artifacts, totaling 405,552,422 bytes.
- All database artifact checksums and all candidate/index rows matched the local snapshot.
- A compressed trace was read back from PostgreSQL, hash-checked, and decoded successfully.
- The three pre-existing datasets retained their artifact counts and byte totals.

The reusable importer uses binary COPY into temporary tables, then merges those
rows inside one transaction. Interrupted transfers roll back. Archive downloads
remain paused and are outside this importer.

Scoped review used `autoreview --mode local --engine codex --model gpt-6.1-sol
--thinking high`. The accepted string-ID mismatch was fixed with a text column.
The final review, including the bulk-transfer change, reported no actionable
findings. Runtime proof comes from the real database upload and readback above.

Receipts: `pipeline/.cache/adsb-lol/full-week/postgres/sfo-adsblol-cached-0e89cdc06eb9832d/{verification,readback}.json`.
