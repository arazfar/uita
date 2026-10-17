"""Transactional Railway import and checksum-verified download. No browser credentials."""
import argparse
import datetime as dt
import hashlib
import os
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb
from .common import ROOT, VERSION, load_env, read_json, sha, write_json


def connect():
    load_env()
    url=os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('Set server-only DATABASE_URL in .env.local')
    return psycopg.connect(url,connect_timeout=20,keepalives=1,keepalives_idle=30,
                           keepalives_interval=10,keepalives_count=3,
                           options='-c statement_timeout=120000 -c lock_timeout=15000')


def upload(directory):
    directory=Path(directory)
    manifest=read_json(directory/'manifest.json')
    dataset_id=manifest['id']
    # Refuse to relabel changed payloads under an existing frozen version.
    for name,info in manifest['files'].items():
        if sha(directory/name)!=info['sha256']:
            raise ValueError(f'Artifact checksum mismatch: {name}')
    utc=lambda t:dt.datetime.fromtimestamp(t,dt.timezone.utc)
    with connect() as c:
        c.execute((ROOT/'pipeline/sql/schema.sql').read_text())
        existing=c.execute('SELECT manifest FROM uita_data.datasets WHERE id=%s',(dataset_id,)).fetchone()
        if existing and existing[0]!=manifest:
            raise ValueError('Dataset version already exists with a different manifest. Bump VERSION.')
        c.execute('INSERT INTO uita_data.datasets(id,manifest) VALUES (%s,%s) ON CONFLICT DO NOTHING',(dataset_id,Jsonb(manifest)))
        for name in ['manifest.json',*manifest['files']]:
            payload=(directory/name).read_bytes()
            c.execute('INSERT INTO uita_data.artifacts VALUES (%s,%s,%s,%b) ON CONFLICT DO NOTHING',
                      (dataset_id,name,hashlib.sha256(payload).hexdigest(),payload))
        with c.cursor() as cur:
            cur.executemany('INSERT INTO uita_data.arrivals VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                [(dataset_id,f['id'],utc(f['t']),f['local_date'],f['split'],Jsonb(f)) for f in read_json(directory/'flights.json')['flights']])
            cur.executemany('INSERT INTO uita_data.tracks VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                [(dataset_id,t['flight_id'],Jsonb(t)) for t in read_json(directory/'observations.json')])
            cur.executemany('INSERT INTO uita_data.weather VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                [(dataset_id,w['id'],utc(w['observed_at']),utc(w['available_at']),Jsonb(w)) for w in read_json(directory/'weather.json')])
            cur.executemany('INSERT INTO uita_data.episodes VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                [(dataset_id,e['id'],e['split'],Jsonb(e)) for e in read_json(directory/'episodes.json')])
    return verify(dataset_id,directory)


def verify(dataset_id=VERSION,directory=None):
    with connect() as c:
        counts={table:c.execute(f'SELECT count(*) FROM uita_data.{table} WHERE dataset_id=%s',(dataset_id,)).fetchone()[0]
                for table in ['artifacts','arrivals','tracks','weather','episodes']}
        files=c.execute("SELECT name,sha256,encode(sha256(payload),'hex') FROM uita_data.artifacts WHERE dataset_id=%s",(dataset_id,)).fetchall()
        for name,checksum,actual in files:
            if actual!=checksum or (directory and sha(Path(directory)/name)!=actual):
                raise ValueError(f'Railway checksum failed: {name}')
        if directory:
            manifest=read_json(Path(directory)/'manifest.json')
            expected={'arrivals':manifest['counts']['arrivals'],'tracks':manifest['counts']['tracks'],
                      'weather':len(read_json(Path(directory)/'weather.json')),'episodes':len(read_json(Path(directory)/'episodes.json')),
                      'artifacts':len(manifest['files'])+1}
            if counts!=expected:
                raise ValueError(f'Railway count mismatch: {counts} expected {expected}')
    report={'passed':True,'dataset_id':dataset_id,'counts':counts,'all_artifact_checksums_verified':True,
            'verified_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    write_json(ROOT/'pipeline/build/railway-verification.json',report)
    print(report)
    return report


def download(dataset_id,output):
    output=Path(output)
    with connect() as c, c.cursor(binary=True) as cur:
        cur.execute('SELECT name,sha256,payload FROM uita_data.artifacts WHERE dataset_id=%s',(dataset_id,))
        rows=cur.fetchall()
    if not rows:
        raise ValueError(f'Unknown dataset: {dataset_id}')
    for name,checksum,payload in rows:
        target=(output/name).resolve()
        if not target.is_relative_to(output.resolve()):
            raise ValueError('Invalid artifact path')
        payload=bytes(payload)
        if hashlib.sha256(payload).hexdigest()!=checksum:
            raise ValueError(f'Checksum mismatch: {name}')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(payload)
    print(f'Downloaded and verified {len(rows)} artifacts')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['upload','verify','download'])
    parser.add_argument('--directory',default=str(ROOT/'pipeline/build'))
    parser.add_argument('--dataset-id',default=VERSION)
    args=parser.parse_args()
    if args.action=='upload':upload(args.directory)
    elif args.action=='verify':verify(args.dataset_id,args.directory)
    else:download(args.dataset_id,args.directory)

if __name__=='__main__':main()
