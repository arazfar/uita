"""Archive teammates' actual arrival/departure UI export separately from controller inputs."""
from collections import Counter
import hashlib
from pathlib import Path
from psycopg.types.json import Jsonb
from .common import ROOT, read_json, sha, write_json
from .store import connect

DATASET_ID='sfo-traffic-replay-2026-08-03_09-v1'


def main():
    out=ROOT/'pipeline/build/ui-replay'
    out.mkdir(parents=True,exist_ok=True)
    for name in ['flights.json','tracks.json','runways.geojson']:
        source=ROOT/'web/public/data'/name
        if not source.exists():raise ValueError(f'Missing teammate UI export: {name}')
        (out/name).write_bytes(source.read_bytes())
    flights=read_json(out/'flights.json');tracks=read_json(out/'tracks.json')
    ids=[f['id'] for f in flights['flights']]
    if len(ids)!=len(set(ids)) or not set(tracks).issubset(ids):raise ValueError('UI flight/track identity mismatch')
    sources={}
    for kind,folder in [('arrivals','bundle'),('departures','departures-bundle')]:
        sources[kind]=read_json(ROOT/f'pipeline/{folder}/provenance.json')
        for name in ['provenance.json','coverage.json','quality-notes.json','SFO-Museum-LICENSE.txt','datasf-source-metadata.json']:
            target=out/f'source/{kind}/{name}';target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/f'pipeline/{folder}/{name}').read_bytes())
    provenance={'producer':'existing teammate pipeline/build_web_data.py','source_provenance':sources,
        'limits':['Historical replay, not agent outcomes or ATC command labels.',
                  'Existing UI exporter interprets altitude digits as hundreds of feet and assumes raw speed is knots.',
                  'Use arrival benchmark observations for provenance-aware altitude and separation analysis.',
                  'Arrival and departure operation times are not verified touchdown or takeoff events.']}
    write_json(out/'provenance.json',provenance)
    names=[str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ['manifest.json','verification.json']]
    manifest={'schema_version':1,'id':DATASET_ID,'kind':'traffic_replay','week':flights['week'],
        'counts':{**dict(Counter(f['kind'] for f in flights['flights'])),'flights':len(ids),'tracks':len(tracks)},
        'files':{name:{'sha256':sha(out/name),'bytes':(out/name).stat().st_size} for name in sorted(names)}}
    write_json(out/'manifest.json',manifest)
    with connect() as c:
        c.execute((ROOT/'pipeline/sql/schema.sql').read_text())
        prior=c.execute('SELECT manifest FROM uita_data.datasets WHERE id=%s',(DATASET_ID,)).fetchone()
        if prior and prior[0]!=manifest:raise ValueError('Changed UI replay needs a new version')
        c.execute('INSERT INTO uita_data.datasets(id,manifest) VALUES (%s,%s) ON CONFLICT DO NOTHING',(DATASET_ID,Jsonb(manifest)))
        print('Railway UI replay transaction started',flush=True)
        for name in ['manifest.json',*manifest['files']]:
            payload=(out/name).read_bytes()
            c.execute('INSERT INTO uita_data.artifacts VALUES (%s,%s,%s,%b) ON CONFLICT DO NOTHING',
                      (DATASET_ID,name,hashlib.sha256(payload).hexdigest(),payload))
            print(f'Stored {name}: {len(payload)} bytes',flush=True)
    with connect() as c:
        rows=c.execute("SELECT name,sha256,encode(sha256(payload),'hex') FROM uita_data.artifacts WHERE dataset_id=%s",(DATASET_ID,)).fetchall()
    if len(rows)!=len(manifest['files'])+1:raise ValueError('Stored UI artifact count mismatch')
    for name,expected,actual in rows:
        if expected!=actual or actual!=sha(out/name):raise ValueError(f'Stored UI checksum mismatch: {name}')
    report={'passed':True,'dataset_id':DATASET_ID,'counts':manifest['counts'],'artifacts':len(rows),'all_checksums_verified':True}
    write_json(out/'verification.json',report);print(report)

if __name__=='__main__':main()
