# Historical SFO replay data

Build the local map and KPI inputs from the existing August 3–9, 2026 bundles:

```sh
python3 pipeline/build_web_data.py
python3 pipeline/verify_web_data.py
```

Both commands use the Python standard library. The exporter writes ignored files in
`web/public/data/`. Source bundles remain unchanged. The verification command reads
the delivered JSON and checks it against the original roster and source points.

## What each input supports

The full DataSF roster supplies throughput, runway use, and spacing between recorded
arrival operations. Operation time is not independently verified touchdown or
wheels-up time. Museum paths supply observed map positions. Missing paths stay
missing; those operations remain in the feed and roster metrics.

Museum's scheduled timestamp exists for matched arrivals only. The schedule offset
is DataSF arrival-operation time minus Museum scheduled arrival time. The sources do
not establish equivalent gate/touchdown semantics. Do not call this measured gate
delay or attribute it to controller performance. No departure schedule is available.

The map screens non-finite positions, non-increasing timestamps, and position jumps
above 700 knots. That threshold screens data errors; it is not a separation rule.
Speed comes from retained coordinates and elapsed time, because source speed units
are unverified. The map must split paths at gaps over 120 seconds. Position between
samples is a replay interpolation, not an additional observed point.

## Safety candidates and data limits

We considered two altitude methods. Converting every numeric altitude produces many
more candidate events, but bare SWIM values can be assigned heights. Treating them
as measured heights would invent evidence of physical climbs and vertical spacing.
The chosen method converts only explicit `C`-suffixed beacon heights. Other heights
remain null, including in the map. The publisher documents these suffixes in the
[August source README](https://github.com/sfomuseum-data/sfomuseum-data-flights-2026-08).

Separation candidates require under 3 NM horizontally and under 1,000 ft vertically.
The scanner samples every 10 seconds between consecutive beacon heights, within
120 seconds, below 700 knots, and below 6,000 ft/min vertical change. A missing
height or long gap prevents comparison across that interval. Pair hits separated
by at most 20 seconds form one candidate event. Sparse samples can miss events.
These counts cannot establish certified losses of separation or complete safety.

We also compared a broad airport-radius exclusion with a runway-aligned final
corridor. A broad exclusion wrongly removes same-runway or crossing traffic near
SFO. Globally removing opposite-runway arrivals also hides events far from final.
The chosen exclusion applies only to an opposite 28L/28R arrival pair when both are:

- Below 3,000 ft.
- Between the landing threshold and 8 NM before it.
- Within 0.5 NM of their own extended runway centerline.
- Moving within 20 degrees of runway heading 298 degrees true.

Thresholds and headings match `APT_RWY_END.csv` in the official FAA NASR
[July 9](https://nfdc.faa.gov/webContent/28DaySub/extra/09_Jul_2026_APT_CSV.zip) and
[August 6](https://nfdc.faa.gov/webContent/28DaySub/extra/06_Aug_2026_APT_CSV.zip)
cycles. Both cycles give these displaced landing thresholds and heading:

| Runway | Longitude | Latitude | True heading |
| --- | ---: | ---: | ---: |
| 28L | -122.35926477 | 37.61209650 | 298 degrees |
| 28R | -122.35805769 | 37.61391813 | 298 degrees |

These constants are recorded in the exporter. Building this replay does not depend
on ignored benchmark artifacts or network access. This corridor is a demo heuristic.
Actual visual clearances, weather permissions, and aircraft wake
categories are not established. It does not prove the pair had visual separation.
Existing runway display polygons carry October static-source metadata; historical
runway availability is unknown.

A go-around candidate requires a measured height under 1,500 ft within 6 NM of SFO,
then two consecutive measured points at least 1,000 ft higher, within five minutes.
The high points must span at least ten seconds. A gap, unknown height, or implausible
vertical jump resets the candidate. One high terminal point cannot create an event.
The eligible-arrival denominator requires at least two follow-up points after a
usable low observation. A zero denominator means unavailable, not zero go-arounds.

`kpis.json` preserves `sep_events` and `go_arounds`, with added `coverage` and
`methodology` objects. `coverage.separation_evaluable_tracks` counts paths with at
least one eligible sample interval, not complete flights. Safety metrics must show
this limited scope. `coverage.go_around_evaluable_arrivals` controls the unavailable
state. Throughput retains the user-selected reference of 54 arrivals/hour; that
reference is not verified capacity for the historical week.

## Verification snapshot: October 17, 2026

The real-data audit passed full roster identities and fields, source point lineage,
finite and chronological track tuples, measured-height provenance, schedule lineage,
path membership, and KPI coverage counters.

| Delivered data | Count |
| --- | ---: |
| Roster arrivals | 4,220 |
| Roster departures | 4,219 |
| Arrival paths | 2,164 |
| Departure paths | 1,964 |
| Retained points | 93,095 |
| Screened position/time outliers | 643 |
| Points with explicit beacon height | 2,671 |
| Path intervals longer than 120 seconds | 729 |
| Paths with an eligible separation interval | 300 |
| Arrival paths with an eligible separation interval | 114 |
| Arrivals with usable go-around observations | 0 |
| Arrivals with a valid schedule | 2,164 |

The median operation-minus-schedule offset was +4.85 minutes. No candidate
separation events appeared in the measured intervals. Only 99 sampled timestamps
had two or more eligible aircraft. No arrival path had a usable beacon height below
1,500 ft. Therefore the go-around result is unavailable. Missing heights and paths
prevent a complete safety result.

Thirteen crafted physical checks also passed: paired final excluded; same-runway,
outside-final, outbound, and cross-course pairs retained; unknown/gap separation
skipped; sustained climb detected; lone spike, implausible jump, unknown/gap climbs
rejected; altitude provenance enforced. These checks exercised branches absent from
the sparse real-data candidate set. They do not validate the heuristic operationally.

Source attribution and licenses remain in `bundle/` and `departures-bundle/`.
Additional ADS-B data can improve path and height coverage, but must be matched and
verified before changing these counts.
