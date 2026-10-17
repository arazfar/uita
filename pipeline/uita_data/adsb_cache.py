"""Upload fully scanned, locally cached ADSB.lol days to Railway; never download.

Original compressed traces remain recoverable as artifacts. Candidate matches
are queryable but are not accepted replay paths or safety-analysis inputs.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

from psycopg import sql
from psycopg.types.json import Jsonb

from .common import ROOT, write_json
from .store import connect

CACHE = ROOT / 'pipeline/.cache/adsb-lol/full-week'


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc) if value is not None else None


def prepare(cache):
    releases = json.loads((cache / 'releases.json').read_text())
    selected, scans, files, trace_sources = [], {}, {}, defaultdict(list)
    for release in releases:
        scan_path = cache / (release['tag'] + '-candidates.json')
        if not scan_path.exists():
            continue
        scan = json.loads(scan_path.read_text())
        if not scan.get('archive_scan_complete'):
            continue
        for asset in release['assets']:
            path = cache / asset['name']
            if not path.is_file() or path.stat().st_size != asset['size'] or 'sha256:' + digest(path) != asset['digest']:
                raise ValueError(f"Source archive verification failed: {asset['name']}")
        if scan['release'] != 'https://github.com/adsblol/globe_history_2026/releases/tag/' + release['tag']:
            raise ValueError('Scan release does not match archive manifest')
        for source in scan['retained_sources']:
            filename = source['retained_file']
            if Path(filename).name != filename:
                raise ValueError('Invalid retained trace filename')
            path = cache / 'traces' / filename
            if path.stat().st_size != source['bytes'] or digest(path) != source['sha256']:
                raise ValueError(f'Trace verification failed: {filename}')
            name = 'traces/' + filename
            files[name] = path
            trace_sources[name].append({'release_tag': release['tag'], **source})
        selected.append(release)
        scans[release['tag']] = scan
        files['scans/' + scan_path.name] = scan_path
    if not selected:
        raise ValueError('No complete, verified archive scans available; no data uploaded')
    files['releases.json'] = cache / 'releases.json'
    counts = {'complete_days': len(selected), 'original_traces': len(trace_sources),
              'candidate_matches': sum(len(s['candidates']) for s in scans.values())}
    identity = {'releases': selected, 'files': {name: {'sha256': digest(path), 'bytes': path.stat().st_size}
                                             for name, path in sorted(files.items())}}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    dataset_id = 'sfo-adsblol-cached-' + fingerprint
    manifest = {'id': dataset_id, 'schema_version': 1, 'kind': 'adsb_backfill_candidates',
                'source': 'https://github.com/adsblol/globe_history_2026',
                'license': 'ODbL-1.0', 'license_url': 'https://opendatacommons.org/licenses/odbl/1-0/',
                'full_week_complete': len(selected) == len(releases), 'counts': counts, **identity,
                'limits': ['Aircraft identities match the SFO roster; original traces also contain other airports.',
                           'Candidate operation matches require flight-leg review before replay or safety use.',
                           'Only complete verified local archives are included. Partial downloads remain local.',
                           'No global archive binaries are stored in PostgreSQL.']}
    out = cache / 'postgres' / dataset_id
    write_json(out / 'manifest.json', manifest)
    files['manifest.json'] = out / 'manifest.json'
    return manifest, files, trace_sources, scans, out


def trace_row(dataset_id, name, path, sources):
    content = path.read_bytes()
    doc = json.loads(gzip.decompress(content) if content[:2] == b'\x1f\x8b' else content)
    times = [doc['timestamp'] + p[0] for p in doc['trace']]
    return (dataset_id, name, doc['icao'], doc.get('r'), utc(min(times)) if times else None,
            utc(max(times)) if times else None, len(times), Jsonb(sources))


def verify(manifest, files, trace_sources, scans, out):
    dataset_id = manifest['id']
    expected_candidates = {(tag, item['operation_id']): item for tag, scan in scans.items() for item in scan['candidates']}
    with connect() as c:
        stored = c.execute('SELECT manifest FROM uita_data.datasets WHERE id=%s', (dataset_id,)).fetchone()
        if not stored or stored[0] != manifest:
            raise ValueError('Stored manifest differs from local snapshot')
        rows = c.execute("SELECT name, sha256, encode(sha256(payload),'hex'), octet_length(payload) FROM uita_data.artifacts WHERE dataset_id=%s", (dataset_id,)).fetchall()
        if {r[0] for r in rows} != set(files):
            raise ValueError('Stored artifact set differs from local snapshot')
        for name, declared, actual, size in rows:
            expected_hash = manifest['files'][name]['sha256'] if name != 'manifest.json' else digest(files[name])
            if declared != actual or actual != expected_hash or actual != digest(files[name]) or size != files[name].stat().st_size:
                raise ValueError('Stored artifact checksum mismatch: ' + name)
        traces = c.execute('SELECT artifact_name, icao24, registration, trace_start, trace_end, observation_count, sources FROM uita_data.adsb_trace_index WHERE dataset_id=%s', (dataset_id,)).fetchall()
        if {r[0] for r in traces} != set(trace_sources):
            raise ValueError('Stored trace index differs from local snapshot')
        for row in traces:
            expected = trace_row(dataset_id, row[0], files[row[0]], trace_sources[row[0]])
            if tuple(row[:-1]) != expected[1:-1] or row[-1] != trace_sources[row[0]]:
                raise ValueError('Stored trace metadata mismatch: ' + row[0])
        seen = set()
        with c.cursor(name='verify_adsb_candidates') as cursor:
            cursor.execute('SELECT release_tag, operation_id, kind, icao24, payload FROM uita_data.adsb_candidates WHERE dataset_id=%s', (dataset_id,))
            for tag, operation_id, kind, icao24, payload in cursor:
                key = (tag, operation_id)
                expected = expected_candidates.get(key)
                if payload != expected or kind != expected['kind'] or icao24 != expected['icao24']:
                    raise ValueError('Stored candidate differs from local scan')
                seen.add(key)
        if seen != set(expected_candidates):
            raise ValueError('Stored candidate set differs from local scan')
    report = {'passed': True, 'dataset_id': dataset_id, 'counts': manifest['counts'],
              'artifacts': len(files), 'stored_bytes': sum(p.stat().st_size for p in files.values()),
              'all_artifact_checksums_verified': True, 'all_query_rows_verified': True,
              'full_week_complete': manifest['full_week_complete'],
              'verified_at': datetime.now(timezone.utc).isoformat()}
    write_json(out / 'verification.json', report)
    print(json.dumps(report), flush=True)


def copy_rows(connection, table, columns, types, rows):
    """Stream binary rows, then merge inside the snapshot transaction."""
    target = sql.Identifier('uita_data', table)
    stage = sql.Identifier('stage_' + table)
    names = sql.SQL(',').join(map(sql.Identifier, columns))
    connection.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE {}) ON COMMIT DROP').format(stage, target))
    with connection.cursor() as cursor:
        with cursor.copy(sql.SQL('COPY {} ({}) FROM STDIN (FORMAT BINARY)').format(stage, names)) as copy:
            copy.set_types(types)
            for row in rows:
                copy.write_row(row)
    connection.execute(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT DO NOTHING').format(target, names, names, stage))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    manifest, files, trace_sources, scans, out = prepare(args.cache)
    dataset_id = manifest['id']
    print('Prepared', dataset_id, manifest['counts'], flush=True)
    if not args.verify_only:
        with connect() as c:
            c.execute((ROOT / 'pipeline/sql/adsb_cache.sql').read_text())
            existing = c.execute('SELECT manifest FROM uita_data.datasets WHERE id=%s', (dataset_id,)).fetchone()
            if existing and existing[0] != manifest:
                raise ValueError('Snapshot identifier already has a different manifest')
            c.execute('INSERT INTO uita_data.datasets(id,manifest) VALUES (%s,%s) ON CONFLICT DO NOTHING', (dataset_id, Jsonb(manifest)))
            # COPY streams large payloads without buffering pipeline commands.
            c.execute('SET LOCAL statement_timeout = 600000')

            def artifact_rows():
                for n, (name, path) in enumerate(files.items(), 1):
                    content = path.read_bytes()
                    if name != 'manifest.json' and hashlib.sha256(content).hexdigest() != manifest['files'][name]['sha256']:
                        raise ValueError('Local artifact changed during upload: ' + name)
                    yield dataset_id, name, hashlib.sha256(content).hexdigest(), content
                    if n == 1 or n % 100 == 0:
                        print('Sent artifacts', n, '/', len(files), flush=True)

            copy_rows(c, 'artifacts', ['dataset_id', 'name', 'sha256', 'payload'],
                      ['text', 'text', 'text', 'bytea'], artifact_rows())
            copy_rows(c, 'adsb_trace_index',
                      ['dataset_id', 'artifact_name', 'icao24', 'registration', 'trace_start', 'trace_end', 'observation_count', 'sources'],
                      ['text', 'text', 'text', 'text', 'timestamptz', 'timestamptz', 'int4', 'jsonb'],
                      (trace_row(dataset_id, name, files[name], sources) for name, sources in trace_sources.items()))
            copy_rows(c, 'adsb_candidates', ['dataset_id', 'release_tag', 'operation_id', 'kind', 'icao24', 'payload'],
                      ['text', 'text', 'text', 'text', 'text', 'jsonb'],
                      ((dataset_id, tag, item['operation_id'], item['kind'], item['icao24'], Jsonb(item))
                       for tag, scan in scans.items() for item in scan['candidates']))
            print('Committing snapshot', flush=True)
    verify(manifest, files, trace_sources, scans, out)


if __name__ == '__main__':
    main()
