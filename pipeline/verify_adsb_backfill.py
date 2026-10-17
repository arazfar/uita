#!/usr/bin/env python3
"""Audit the delivered week against original received points and exhaustive pairs."""
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
import gzip
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from adsb_lol import normalized_points, registration
from build_web_data import sample_grid, dist_nm, paired_approach, usable_interval

HERE = Path(__file__).resolve().parent
CACHE = HERE / '.cache/adsb-lol/full-week'
WEB = HERE.parent / 'web/public/data'


def main():
    supplement = json.loads(gzip.decompress((HERE/'adsb-backfill/tracks.json.gz').read_bytes()))['tracks']
    by_aircraft = defaultdict(list)
    for oid, track in supplement.items():
        by_aircraft[(track['icao24'], track['registration'])].append((oid, track))
    source_points = 0
    for identity, candidates in by_aircraft.items():
        raw, conflicts, boundaries = {}, set(), set()
        sources = {s['sha256']: s for _, c in candidates for s in c['source_files']}
        for digest, source in sources.items():
            data = (CACHE/'traces'/source['retained_file']).read_bytes()
            assert hashlib.sha256(data).hexdigest() == digest
            doc = json.loads(gzip.decompress(data))
            assert (doc['icao'], registration(doc.get('r'))) == identity
            for p in normalized_points(doc, include_stale=True):
                if p['ground'] or p['flags'] & 2:
                    boundaries.add(p['t'])
                if p['t'] in raw and raw[p['t']] != p:
                    conflicts.add(p['t'])
                raw[p['t']] = p
        occupied = set()
        for oid, candidate in candidates:
            first, last = candidate['points'][0][0], candidate['points'][-1][0]
            for point, flags in zip(candidate['points'], candidate['point_flags'], strict=True):
                t, lon, lat, altitude, speed = point
                assert t not in conflicts and t not in occupied, f'Conflicting/shared observation {oid}'
                original = raw[t]
                assert [t, lon, lat, altitude, speed] == [original[k] for k in ('t','lon','lat','alt','gs')], f'Changed source observation {oid}'
                assert not original['ground'] and not flags & 1 and flags == original['flags']
                assert altitude is None or not flags & 8, f'Geometric altitude treated as barometric {oid}'
                occupied.add(t)
                source_points += 1
            # Every received ground/new-leg boundary in the original interval
            # must survive as a split, even if that point was not exported.
            assert not any(first < t <= last for t in boundaries), f'Bridged source leg {oid}'
    payload = json.loads((WEB/'flights.json').read_text())
    flights = payload['flights']; by_id = {f['id']: f for f in flights}; week = payload['week']
    tracks = json.loads((WEB/'tracks.json').read_text())
    kpis = json.loads((WEB/'kpis.json').read_text())
    steps = defaultdict(list)
    for oid, points in tracks.items():
        for sample in sample_grid([p for p in points if week['start_utc'] <= p[0] < week['end_utc']]):
            steps[sample[0]].append((oid, *sample))
    hits, excluded = defaultdict(list), 0
    for time, points in steps.items():
        # Exhaustive pairs validate the builder's spatial-cell optimization.
        for p, q in combinations(points, 2):
            if by_id[p[0]]['reg'] and by_id[p[0]]['reg'] == by_id[q[0]]['reg']:
                continue
            feet = abs(p[4] - q[4])
            if feet >= 1000 or abs(p[3]-q[3]) > 0.051:
                continue
            nm = dist_nm(p[1:], q[1:])
            if nm >= 3:
                continue
            if paired_approach(p,q,by_id):
                excluded += 1
                continue
            hits[tuple(sorted((p[0],q[0])))].append((time,nm,feet))
    events = []
    for (a,b), samples in hits.items():
        runs = []
        for hit in sorted(samples):
            if not runs or hit[0]-runs[-1][-1][0] > 20:
                runs.append([])
            runs[-1].append(hit)
        for run in runs:
            events.append(dict(t_start=run[0][0], t_end=run[-1][0], a=a,b=b,
                               min_nm=round(min(p[1] for p in run),2),min_ft=round(min(p[2] for p in run))))
    events.sort(key=lambda e:(e['t_start'],e['a'],e['b']))
    assert events == kpis['sep_events'], 'Exhaustive pair scan disagrees with shipped separation KPIs'
    assert excluded == kpis['methodology']['separation']['paired_samples_excluded']
    for event in kpis['go_arounds']:
        full = tracks[event['id']]
        points = [p for p in full if event['low_t'] <= p[0] <= event['t']]
        assert points[0][0] == event['low_t'] and points[-1][0] == event['t']
        assert points[0][3] == event['low_ft'] < 1500 and points[-1][3] == event['confirmed_ft']
        assert dist_nm(points[0], (0,-122.3790,37.6213)) < 6 and event['t']-event['low_t'] <= 300
        assert all(usable_interval(a,b) for a,b in zip(points,points[1:])), 'Go-around crosses unknown/gapped evidence'
        low_index = next(i for i,p in enumerate(full) if p[0] == event['low_t'])
        peak = event['low_ft']
        for i in range(low_index, 0, -1):
            if full[i-1][0] < week['start_utc'] or not usable_interval(full[i-1],full[i]):
                break
            peak = max(peak, full[i-1][3])
        assert peak - event['low_ft'] >= 100, 'Go-around lacks measured approach descent'
        sustained = []
        for point in reversed(points):
            if point[3] < event['low_ft'] + 1000:
                break
            sustained.append(point)
        assert len(sustained)>=2 and sustained[0][0]-sustained[-1][0]>=10, 'Go-around lacks sustained climb'
    days = defaultdict(Counter)
    for flight in flights:
        day = datetime.fromtimestamp(flight['t'], ZoneInfo('America/Los_Angeles')).date().isoformat()
        days[day]['operations'] += 1
        days[day]['paths'] += flight['has_track']
        days[day]['adsb_paths'] += flight.get('track_source') == 'adsb.lol'
    missing = Counter(f['airline'] or 'Unknown' for f in flights if not f['has_track'])
    report = dict(status='pass', original_observations_verified=source_points,
        exhaustive_separation_candidates=len(events), paired_samples_excluded=excluded,
        multi_aircraft_sample_times=sum(len(p)>=2 for p in steps.values()),
        coverage=kpis['coverage'], per_local_day=dict(sorted(days.items())),
        missing_paths_by_airline=dict(missing.most_common()),
        go_around_candidates=kpis['go_arounds'])
    (HERE/'adsb-backfill/audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
