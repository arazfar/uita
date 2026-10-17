"""Compare seven real API windows against original PostgreSQL observations.
Run from the repository: PYTHONPATH=backend .venv/bin/python showcase/scripts/verify-history.py
"""
import json
import os
from pathlib import Path
import time
from urllib.request import urlopen
from uita.history import connection

base = os.environ.get('UITA_HISTORY_VERIFY_URL', 'http://127.0.0.1:8017/api/history')
def read(path):
    with urlopen(base + path, timeout=120) as response:
        return json.load(response)

catalog = read('/catalog')
assert len(catalog['days']) == 7, 'Not all local dates are loaded'
report = {'dates': catalog['days'], 'source_rows': sum(d['rows'] for d in catalog['days']), 'windows': []}
with connection() as db:
    assert db.execute('show transaction_read_only').fetchone()[0] == 'on'
    for day in range(7):
        start = catalog['start'] + day * 86400 + 43200
        begun = time.monotonic()
        window = read('/window?start=' + str(start))
        assert window['start'] == start
        assert window['flights'], f'Empty noon window on day {day}'
        samples = [(f['id'], f['points'][len(f['points']) // 2]) for f in window['flights'][:5]]
        clauses = ' OR '.join('(icao24=%s AND t_utc=to_timestamp(%s))' for _ in samples)
        args = [value for hex_id, point in samples for value in (hex_id, point[0])]
        rows = db.execute('''SELECT icao24, extract(epoch FROM t_utc)::double precision,
            lat,lon,alt_baro_ft,gs_kt,track_deg,on_ground,coalesce(nullif(callsign,''),nullif(registration,''),icao24),registration,type_code
            FROM atc_sfo_w35.positions WHERE ''' + clauses, args).fetchall()
        actual = set(rows)
        for hex_id, p in samples:
            assert (hex_id, *p[:7], *p[8:]) in actual, f'API sample differs from source: {hex_id}'
        for f in window['flights']:
            assert all(catalog['start'] <= p[0] < window['end'] for p in f['points'])
            assert all(a[0] < b[0] for a,b in zip(f['points'],f['points'][1:]))
        result = {'date': catalog['days'][day]['date'], 'aircraft_in_window': len(window['flights']),
                  'samples': sum(len(f['points']) for f in window['flights']), 'source_matches': len(samples),
                  'elapsed_seconds': round(time.monotonic()-begun,2)}
        report['windows'].append(result)
        print(json.dumps(result), flush=True)
Path('/tmp/uita-showcase-source-verification.json').write_text(json.dumps(report, indent=2))
print('PASS: all seven dates; 35 API observations match original database rows.')
