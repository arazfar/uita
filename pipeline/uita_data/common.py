from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENTER = (-122.3790, 37.6213)
TZ = 'America/Los_Angeles'
VERSION = 'sfo-2026-08-03_09-v1'


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def distance(a, b):
    """WGS84 longitude/latitude pairs; great-circle distance in nautical miles."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(h)))


def bearing(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    return math.degrees(math.atan2(math.sin(lon2-lon1)*math.cos(lat2),
        math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(lon2-lon1))) % 360


def load_env():
    # Never print values or pass credentials through shell arguments.
    for name in ('.env', '.env.local'):
        p = ROOT / name
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('\"\''))
