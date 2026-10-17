# Optional ADSB.lol backfill

The current replay works without this backfill. Keep the complete DataSF roster
in the feed and operation KPIs. Draw aircraft only when a received path exists.

`adsb_lol.py` writes **review candidates only**. It does not change the source
bundles, web payloads, existing Museum paths, or coverage counts.

## Verified source, October 17, 2026

The official [2026 archive](https://github.com/adsblol/globe_history_2026) has a
daily release for every requested UTC date. The database uses
[ODbL 1.0](https://github.com/adsblol/globe_history_2026/blob/main/LICENSE-ODbL.txt).
The archive consists of split, uncompressed tar files. Individual aircraft traces
inside them are gzip-compressed JSON. They are readsb trace observations, not
the original radio-message stream. See the
[readsb trace format](https://github.com/wiedehopf/readsb/blob/dev/README-json.md#trace-jsons).

The table uses the official
[preferred-release list](https://github.com/adsblol/globe_history_2026/blob/main/PREFERRED_RELEASES.txt)
and GitHub release asset sizes. The release list can change.

| UTC date | Preferred replica | Tar parts | Total bytes |
|---|---|---:|---:|
| 2026-08-03 | prod-0 | 2 | 3,850,736,640 |
| 2026-08-04 | prod-0 | 3 | 4,046,559,744 |
| 2026-08-05 | prod-0 | 2 | 3,980,952,576 |
| 2026-08-06 | prod-0 | 3 | 4,036,545,024 |
| 2026-08-07 | prod-0 | 3 | 4,062,955,008 |
| 2026-08-08 | staging-0 | 2 | 3,747,849,216 |
| 2026-08-09 | staging-0 | 2 | 2,379,456,000 |
| 2026-08-10 | prod-0 | 2 | 3,813,343,744 |

UTC August 3–9 totals **26.11 GB**. The replay uses local dates in PDT.
Its local week ends at August 10, 07:00 UTC, so a full backfill also needs
August 10. Those eight archives total **29.92 GB**. Operation matching near the
week boundary may also need a small time margin.

August 9 is substantially smaller than the other days. This does not establish
missing SFO traffic, but release availability alone does not prove completeness.
No near-100% coverage estimate is supported yet.

## Small real sample

We downloaded the first **4 MiB** of the August 3 prod archive. The partial scan
read 103 complete aircraft traces and 133,081 usable observed points. It found
four previously untracked roster operations for SkyWest **N979SW**, ICAO
**ada6b9**:

| Operation | Direction | Candidate points | Nearest airport point minus roster time |
|---|---|---:|---:|
| 45880714 | Departure | 333 | −10.40 s |
| 45881479 | Arrival | 536 | +2.87 s |
| 45881958 | Departure | 349 | +0.14 s |
| 45882857 | Arrival | 412 | −7.24 s |

These are candidate matches from real received paths. The importer did not
invent points or add these paths to the replay. This small, ordered archive
sample cannot estimate SFO coverage, general-aviation coverage, or full-week
coverage.

Reproduce the bounded sample from the repository root:

```sh
mkdir -p pipeline/.cache/adsb-lol
curl --fail --location --range 0-4194303 --max-filesize 4194304 \
  --output pipeline/.cache/adsb-lol/aug03-first4m.tar \
  https://github.com/adsblol/globe_history_2026/releases/download/v2026.08.03-planes-readsb-prod-0/v2026.08.03-planes-readsb-prod-0.tar.aa
python3 pipeline/adsb_lol.py \
  --release v2026.08.03-planes-readsb-prod-0 \
  --archive pipeline/.cache/adsb-lol/aug03-first4m.tar \
  --allow-partial \
  --output pipeline/.cache/adsb-lol/aug03-sample-candidates.json
```

The JSON reports `archive_scan_complete: false`, an expected truncated-tar error,
and four candidate operations. Without `--allow-partial`, truncated input fails.
No partial result silently replaces an earlier output.

## Full extraction options

| Approach | Benefit | Cost |
|---|---|---|
| Stream ordered parts into the importer | Avoids retaining global archives and a second concatenated copy | Still transfers every byte; interrupted downloads are harder to resume |
| Download split parts, then scan them in order | Easy to retry, inspect, and preserve exact source files | Needs about 4 GB of temporary disk per day; delete only after review |

Start with one **local** day. That requires UTC August 3 and 4, about 7.90 GB.
Check recovered arrival/departure counts, registration matches, airport evidence,
track gaps, and runway approach geometry before extending to the full week.
Sequential regional filtering saves disk space; it does not avoid global
downloads. The official archive provides no regional member-offset index.

Example for the first UTC day, once a full download is intended:

```sh
mkdir -p pipeline/.cache/adsb-lol/2026-08-03
gh release download v2026.08.03-planes-readsb-prod-0 \
  --repo adsblol/globe_history_2026 --pattern '*.tar.a?' \
  --dir pipeline/.cache/adsb-lol/2026-08-03
python3 pipeline/adsb_lol.py \
  --release v2026.08.03-planes-readsb-prod-0 \
  --archive \
    pipeline/.cache/adsb-lol/2026-08-03/v2026.08.03-planes-readsb-prod-0.tar.aa \
    pipeline/.cache/adsb-lol/2026-08-03/v2026.08.03-planes-readsb-prod-0.tar.ab \
  --output pipeline/.cache/adsb-lol/aug03-candidates.json
```

Pass all parts in order, including `.ac` on three-part days. Alternatively,
`--archive -` reads a concatenated tar stream from standard input.
`--trace-directory DIR` reads already extracted original `.json` or `.json.gz`
traces. A directory scan always reports incomplete archive coverage because its
source completeness is unknown.

## Match and review contract

The importer considers missing Museum paths by default. `--include-covered`
also produces comparison candidates for operations with existing paths.

It requires a matching registration, or an explicit ICAO address when the roster
supplies one. Callsign alone never establishes identity. Each candidate needs a
received ground point or a point at or below 1,000 barometric feet, within 3 NM
of SFO and 15 minutes of the roster operation time.

Candidate windows cover up to 90 minutes before an arrival or after a departure,
plus a 10-minute opposite-side margin. Windows stop at the midpoint to adjacent
roster movements of the same aircraft. Positions remain within 80 NM of SFO.
Multiple ICAO addresses matching the same operation are rejected as ambiguous.
These thresholds screen candidates; they do not certify landing or takeoff.

The output preserves the canonical release link and each source member's hash.
Points use `[UTC seconds, longitude, latitude, barometric feet or null, knots or
null]`. Separate arrays retain source flags and ground state. Stale positions
are excluded. Ground and geometric altitudes remain null. The importer does
not interpolate, infer runway use, or calculate safety events.

Readsb flag bit 4 describes the **vertical rate's** geometric reference; it does
not mark altitude interpolation. Bit 8 marks geometric altitude, which this
export leaves null. Bit 4 alone does not remove a barometric altitude.

Review point continuity and readsb leg-start flags before accepting candidates.
Missing gaps and partial terminal paths remain possible. A successful scan means
the supplied tar input ended correctly, with no nonzero trailing data; it does not verify that the downloaded
release has complete source coverage. Keep ODbL attribution and licensing with
any redistributed ADSB.lol-derived data. Rebuild coverage and track-derived KPIs
only after explicitly accepting and integrating reviewed paths.

The independent October dataset under `data/` already has a larger archive
downloader. Its dates, region, and data contract differ from this August replay.
This work does not change that dataset.
