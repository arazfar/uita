"""Read-only August 24–30 SFO replay over recorded PostgreSQL observations."""
from datetime import datetime, timezone
from functools import lru_cache
import logging
import os
from pathlib import Path
import time
from threading import Lock

from fastapi import APIRouter, HTTPException, Query
import psycopg

router = APIRouter(prefix='/api/history', tags=['Recorded SFO replay'])
START = int(datetime(2026, 8, 24, 7, tzinfo=timezone.utc).timestamp())
END = START + 7 * 86400
CHUNK = 900
log = logging.getLogger('uita.history')
_catalog_lock = Lock()


def connection():
    url = os.environ.get('UITA_HISTORY_DATABASE_URL') or os.environ.get('DATABASE_URL', '')
    if not url.startswith(('postgresql', 'postgres:')):
        path = Path(__file__).resolve().parents[2] / '.env.local'
        values = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    k, v = line.split('=', 1)
                    values[k.strip()] = v.strip().strip('\"\'')
        url = values.get('UITA_HISTORY_DATABASE_URL') or values.get('DATABASE_URL', '')
    if not url.startswith(('postgresql', 'postgres:')):
        raise HTTPException(503, 'Recorded traffic database is not configured. Set UITA_HISTORY_DATABASE_URL on the server.')
    return psycopg.connect(url.replace('postgresql+psycopg://', 'postgresql://'), connect_timeout=30,
                          options='-c default_transaction_read_only=on -c statement_timeout=30000')


def epoch(value):
    return value.timestamp() if value else None


@lru_cache(maxsize=2)
def catalog_cache(minute):
    with connection() as c:
        days = c.execute('''SELECT (t_utc AT TIME ZONE 'America/Los_Angeles')::date,
            count(*), min(t_utc), max(t_utc) FROM atc_sfo_w35.positions
            WHERE utc_date BETWEEN (to_timestamp(%s) AT TIME ZONE 'UTC')::date
                               AND (to_timestamp(%s) AT TIME ZONE 'UTC')::date
              AND t_utc >= to_timestamp(%s) AND t_utc < to_timestamp(%s)
            GROUP BY 1 ORDER BY 1''', (START, END - 1, START, END)).fetchall()
        runways = c.execute('''SELECT runway, threshold_lat, threshold_lon, departure_end_lat,
            departure_end_lon FROM atc_sfo_w35.sfo_runways ORDER BY runway''').fetchall()
        daily = c.execute('SELECT date_local, total_ops FROM atc_sfo_w35.opsnet_daily ORDER BY date_local').fetchall()
        loaded = c.execute("SELECT max(loaded_at) FROM atc_sfo_w35.load_log WHERE table_name='positions'").fetchone()[0]
    return {'start': START, 'end': END, 'timezone': 'America/Los_Angeles', 'chunk_seconds': CHUNK,
            'source': 'ADSB.lol · Railway atc_sfo_w35.positions', 'source_url': 'https://github.com/adsblol/globe_history_2026',
            'license': 'ODbL-1.0', 'loaded_at': loaded.isoformat() if loaded else None,
            'days': [{'date': str(d), 'rows': n, 'first': epoch(lo), 'last': epoch(hi)} for d, n, lo, hi in days],
            'runways': [{'id': r[0], 'start': r[1:3], 'end': r[3:5]} for r in runways],
            'daily_operations': [{'date': str(d), 'total': n} for d, n in daily],
            'limits': ['Regional observations are not an airport-operation roster.',
                       'Map uses one recorded sample per aircraft per five seconds; no position extrapolation.',
                       'Targets disappear after 15 seconds without an observation. Trails break across gaps and new legs.',
                       'Safety, landing delay and runway-use KPIs require validated flight matching.']}


def current_catalog():
    # One catalog scan per five minutes, even when several viewers connect.
    with _catalog_lock:
        return catalog_cache(int(time.monotonic() // 300))


@router.get('/catalog')
def catalog():
    try:
        return current_catalog()
    except psycopg.Error:
        log.warning('Historical catalog query failed', exc_info=False)
        raise HTTPException(503, 'Recorded traffic could not load from PostgreSQL. Retry the connection.') from None


@lru_cache(maxsize=12)
def window_cache(start, revision):
    end = min(start + CHUNK, END)
    with connection() as c:
        # Keep actual observations, not bucket averages. The 120-second lookback
        # gives the first frame a history trail without borrowing future points.
        rows = c.execute('''SELECT DISTINCT ON (icao24, floor(extract(epoch FROM t_utc)/5))
            icao24, callsign, registration, type_code, extract(epoch FROM t_utc)::double precision,
            lat, lon, alt_baro_ft, gs_kt, track_deg, on_ground,
            bool_or(coalesce(flag_new_leg, false)) OVER
              (PARTITION BY icao24, floor(extract(epoch FROM t_utc)/5)) AS flag_new_leg
            FROM atc_sfo_w35.positions
            WHERE utc_date BETWEEN (to_timestamp(%s) AT TIME ZONE 'UTC')::date
                               AND (to_timestamp(%s) AT TIME ZONE 'UTC')::date
              AND t_utc >= to_timestamp(%s) AND t_utc < to_timestamp(%s)
              AND NOT coalesce(flag_stale, false) AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180
            ORDER BY icao24, floor(extract(epoch FROM t_utc)/5), t_utc DESC,
                     alt_baro_ft NULLS LAST, registration NULLS LAST, lat, lon
            LIMIT 60001''', (max(START, start - 120), end - 1, max(START, start - 120), end)).fetchall()
        weather = c.execute('''SELECT extract(epoch FROM hour_utc)::double precision, vsby, ceiling_ft, sknt, drct
            FROM atc_sfo_w35.weather_hourly WHERE hour_utc >= to_timestamp(%s)
            AND hour_utc < to_timestamp(%s) ORDER BY hour_utc''', (start - 3600, end)).fetchall()
    if len(rows) > 60000:
        raise HTTPException(503, 'This interval exceeds the replay row limit. No partial traffic was displayed.')
    flights = {}
    for hex_id, callsign, reg, aircraft_type, *point in rows:
        flight = flights.setdefault(hex_id, {'id': hex_id, 'callsign': callsign or reg or hex_id,
                                            'registration': reg, 'type': aircraft_type, 'points': []})
        # Callsign is carried on each observation because one aircraft can fly
        # different flights during the same replay window.
        flight['points'].append([*point, callsign or reg or hex_id, reg, aircraft_type])
    for flight in flights.values():
        flight['points'].sort(key=lambda p: p[0])
    return {'start': start, 'end': end, 'flights': list(flights.values()), 'weather': weather,
            'sample_seconds': 5, 'stale_after_seconds': 15}


@router.get('/window')
def window(start: int = Query(..., ge=START, lt=END)):
    try:
        anchor = START + ((start - START) // CHUNK) * CHUNK
        return window_cache(anchor, current_catalog()['loaded_at'])
    except psycopg.Error:
        log.warning('Historical window query failed', exc_info=False)
        raise HTTPException(503, 'Recorded traffic could not load from PostgreSQL. Retry this interval.') from None
