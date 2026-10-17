#!/usr/bin/env python3
"""Build an auditable, flight-leg-scoped ADSB.lol supplement from complete scans.

Original daily traces are combined before matching, so UTC midnight cannot cut a
local-day flight in two. This output is separate from the Museum source bundles.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

from adsb_lol import load_operations, normalized_points, registration, distance_nm
from build_web_data import kept_points

HERE = Path(__file__).resolve().parent
DEFAULT_CACHE = HERE / '.cache/adsb-lol/full-week'
DEFAULT_OUTPUT = HERE / 'adsb-backfill'


def flight_legs(points, boundaries=()):
    """Never join across a reported ground point, leg-start flag, or long gap."""
    leg = []
    pending = iter(sorted(boundaries))
    boundary = next(pending, None)
    for point in points:
        crossed = False
        while boundary is not None and boundary <= point['t']:
            crossed = True
            boundary = next(pending, None)
        if crossed or point['ground'] or point['flags'] & 2 or leg and point['t'] - leg[-1]['t'] > 1200:
            if leg:
                yield leg
            leg = []
        if not point['ground'] and not point['flags'] & 1:
            leg.append(point)
    if leg:
        yield leg


def match_leg(op, peers, legs):
    lo, hi = ((op['t'] - 5400, op['t'] + 600) if op['kind'] == 'arr'
              else (op['t'] - 600, op['t'] + 5400))
    for peer in peers:
        if peer['t'] < op['t']:
            lo = max(lo, (peer['t'] + op['t']) / 2)
        elif peer['t'] > op['t']:
            hi = min(hi, (peer['t'] + op['t']) / 2)
    matches = []
    for leg in legs:
        window = [p for p in leg if lo <= p['t'] <= hi]
        if len(window) < 3:
            continue
        # Arrival evidence belongs at the end of a flight; departure evidence at
        # the start. Merely passing SFO or taxiing there cannot establish a match.
        terminal = window[-1] if op['kind'] == 'arr' else window[0]
        if not (abs(terminal['t'] - op['t']) <= 900 and terminal['alt'] is not None
                and terminal['alt'] <= 1000 and distance_nm(terminal['lat'], terminal['lon']) <= 3):
            continue
        regional = [p for p in window if distance_nm(p['lat'], p['lon']) <= 80]
        if not any(distance_nm(p['lat'], p['lon']) >= 3 and p['alt'] is not None and p['alt'] >= 1000 for p in regional):
            continue
        raw = [[p['t'], p['lon'], p['lat'], p['alt'], p['gs']] for p in regional]
        cleaned = kept_points(raw)
        # Reject a problematic flight rather than silently changing its terminal
        # identity evidence. Ordinary isolated coordinate spikes can be removed.
        if len(cleaned) < 3 or len(cleaned) < 0.95 * len(raw) or terminal['t'] not in {p[0] for p in cleaned}:
            continue
        flags = {p['t']: p['flags'] for p in regional}
        matches.append(dict(points=cleaned, point_flags=[flags[p[0]] for p in cleaned],
                            airport_evidence_time_utc=terminal['t'], dropped_points=len(raw)-len(cleaned)))
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    releases = json.loads((args.cache / 'releases.json').read_text())
    dates = {r['tag'].split('-')[0] for r in releases}
    assert dates == {f'v2026.08.{day:02d}' for day in range(3, 11)}, 'All eight UTC dates are required'
    by_reg, by_hex, _ = load_operations(True)
    files_by_identity, manifests, counts = defaultdict(list), [], Counter()
    for release in releases:
        scan_path = args.cache / (release['tag'] + '-candidates.json')
        scan = json.loads(scan_path.read_text())
        assert scan['archive_scan_complete'] and not scan['scan_error'], 'A source archive was incomplete'
        assert scan['release'].endswith('/' + release['tag'])
        assets = []
        for asset in release['assets']:
            path = args.cache / asset['name']
            assert path.stat().st_size == asset['size'], 'Changed source archive size'
            digest = path.with_suffix(path.suffix + '.sha256').read_text().strip()
            assert asset.get('digest') == 'sha256:' + digest, 'Source digest was not verified against GitHub'
            assets.append(dict(name=asset['name'], bytes=asset['size'], sha256=digest, url=asset['url']))
        manifests.append(dict(tag=release['tag'], assets=assets, scan_summary=scan['summary']))
        for source in scan['retained_sources']:
            content = (args.cache / 'traces' / source['retained_file']).read_bytes()
            assert hashlib.sha256(content).hexdigest() == source['sha256'], 'Changed retained source trace'
            doc = json.loads(gzip.decompress(content) if content[:2] == b'\x1f\x8b' else content)
            key = (doc['icao'], registration(doc.get('r')))
            if not re.fullmatch(r'[0-9a-f]{6}', key[0]):
                counts['non_icao_source_files_excluded'] += 1
                continue
            files_by_identity[key].append(dict(source, release=scan['release']))
    candidates = defaultdict(list)
    for (hex_id, reg), sources in sorted(files_by_identity.items()):
        peers = {op['id']: op for op in by_reg.get(reg, []) + by_hex.get(hex_id, [])}
        observations, boundaries = {}, set()
        conflicting = set()
        for source in sources:
            content = (args.cache / 'traces' / source['retained_file']).read_bytes()
            doc = json.loads(gzip.decompress(content) if content[:2] == b'\x1f\x8b' else content)
            # Stale points cannot draw a path, but their ground/new-leg markers
            # still stop a path. Otherwise dropping one could join two flights.
            for p in normalized_points(doc, include_stale=True):
                if p['ground'] or p['flags'] & 2:
                    boundaries.add(p['t'])
                prior = observations.get(p['t'])
                if prior and prior != p:
                    conflicting.add(p['t'])
                observations[p['t']] = p
        # Conflicting simultaneous observations do not establish a single path.
        points = [p for t, p in sorted(observations.items()) if t not in conflicting]
        counts['conflicting_observations_excluded'] += len(conflicting)
        legs = list(flight_legs(points, boundaries))
        for op in peers.values():
            matches = match_leg(op, peers.values(), legs)
            if len(matches) != 1:
                counts['ambiguous_leg_matches' if matches else 'unmatched_identity_operations'] += 1
                continue
            item = matches[0]
            candidates[op['id']].append(dict(item, icao24=hex_id, registration=reg, kind=op['kind'],
                operation_time_utc=op['t'], source_files=sources, match_method='identity_terminal_airborne_leg'))
    accepted, rejected = {}, []
    for oid, options in sorted(candidates.items()):
        if len(options) == 1:
            accepted[oid] = options[0]
        else:
            rejected.append(dict(operation_id=oid, reason='multiple_source_identities'))
    # One received aircraft cannot supply two simultaneous roster operations.
    by_aircraft = defaultdict(list)
    for oid, candidate in accepted.items():
        by_aircraft[candidate['icao24']].append((oid, candidate))
    overlaps = set()
    for items in by_aircraft.values():
        items.sort(key=lambda item: item[1]['points'][0][0])
        for i, (oid, item) in enumerate(items):
            for other_id, other in items[i+1:]:
                if other['points'][0][0] > item['points'][-1][0]:
                    break
                overlaps.update((oid, other_id))
    for oid in sorted(overlaps):
        del accepted[oid]
        rejected.append(dict(operation_id=oid, reason='overlapping_same_aircraft_operations'))
    counts.update(accepted_operations=len(accepted), rejected_operations=len(rejected),
                  points=sum(len(c['points']) for c in accepted.values()),
                  measured_altitude_points=sum(p[3] is not None for c in accepted.values() for p in c['points']))
    assert accepted, 'No usable airborne paths matched'
    args.output.mkdir(parents=True, exist_ok=True)
    payload = dict(version=1, source='https://github.com/adsblol/globe_history_2026', license='ODbL-1.0',
                   point_columns=['UTC_seconds','longitude','latitude','barometric_feet_or_null','source_knots_or_null'],
                   tracks=accepted)
    encoded = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
    compressed = gzip.compress(encoded, mtime=0)
    (args.output / 'tracks.json.gz').write_bytes(compressed)
    report = dict(version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                  archive_scan_complete=True, releases=manifests, summary=dict(counts), rejected=rejected,
                  supplement_sha256=hashlib.sha256(compressed).hexdigest(),
                  limits=['Archive completeness does not establish receiver coverage.',
                          'Identity plus terminal flight-leg evidence is a heuristic match, not a verified touchdown.',
                          'Ground observations, stale positions and geometric altitudes do not support safety checks.'])
    (args.output / 'provenance.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
