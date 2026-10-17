"""Read-only demo data HTTP adapter over Railway. The agent never receives DATABASE_URL."""
import argparse
import hashlib
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
from .common import VERSION, ROOT
from .store import connect


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8100)
    parser.add_argument('--dataset-id',default=VERSION)
    parser.add_argument('--directory',type=Path,default=ROOT/'pipeline/build',help='Local frozen cache; each file is checked against the database hash')
    parser.add_argument('--include-test',action='store_true',help='Allow trusted evaluation runner to read test artifacts')
    parser.add_argument('--cors-origin',action='append',default=['http://localhost:5173','http://127.0.0.1:5173'])
    args=parser.parse_args()
    cached_manifest=args.directory/'manifest.json'
    if cached_manifest.exists() and json.loads(cached_manifest.read_text()).get('id')!=args.dataset_id:
        raise SystemExit('Cache directory belongs to another dataset; choose --directory explicitly')
    # Development API exposes only development scenario packs and static references.
    # Whole-week replay/outcome artifacts require explicit trusted evaluation mode.
    public={'airport.json','weather.json','runways.geojson','reference-provenance.json','provenance.json',
            'README.md','SFO-Museum-LICENSE.txt','datasf-source-metadata.json','manifest.json','episodes.json'}
    public.update(f'scenarios/2026-08-0{n}.json' for n in range(3,8))
    # Fetch only hashes first. Frozen cache files avoid large database transfers before a demo.
    assets={}
    with connect() as c, c.cursor(binary=True) as cur:
        cur.execute('SELECT name,sha256 FROM uita_data.artifacts WHERE dataset_id=%s AND (%s OR name=ANY(%s))',
                    (args.dataset_id,args.include_test,list(public)))
        rows=cur.fetchall()
        if not rows:raise SystemExit('No dataset found; run the Railway upload first')
        for name,checksum in rows:
            cache=(args.directory/name).resolve()
            if not cache.is_relative_to(args.directory.resolve()):raise ValueError('Invalid artifact path')
            payload=cache.read_bytes() if cache.exists() else None
            if payload is None or hashlib.sha256(payload).hexdigest()!=checksum:
                cur.execute('SELECT payload FROM uita_data.artifacts WHERE dataset_id=%s AND name=%s',(args.dataset_id,name))
                payload=bytes(cur.fetchone()[0])
                if hashlib.sha256(payload).hexdigest()!=checksum:raise ValueError(f'Corrupt artifact: {name}')
                cache.parent.mkdir(parents=True,exist_ok=True)
                cache.write_bytes(payload)
            assets[name]=(payload,checksum)
    manifest=json.loads(assets['manifest.json'][0])
    episodes=json.loads(assets['episodes.json'][0]) if 'episodes.json' in assets else []
    if not args.include_test:
        manifest={**manifest,'files':{k:v for k,v in manifest['files'].items() if k in public},
                  'access':'development; test and whole-week replay artifacts withheld'}
        episodes=[e for e in episodes if e['split']!='test']
    def encoded(value):
        data=(json.dumps(value,separators=(',',':'))+'\n').encode()
        return data,hashlib.sha256(data).hexdigest()
    assets['manifest.json']=encoded(manifest)
    assets['episodes.json']=encoded(episodes)
    public.update(['manifest.json','episodes.json'])
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name=unquote(urlsplit(self.path).path).removeprefix('/api/data/').lstrip('/')
            if name=='health':
                body=json.dumps({'status':'ok','dataset_id':args.dataset_id,'source':'Railway PostgreSQL'}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body);return
            if name not in assets or (not args.include_test and name not in public):
                self.send_error(404,'Artifact unavailable');return
            body,checksum=assets[name]
            if self.headers.get('If-None-Match')=='"'+checksum+'"':
                self.send_response(304);self.end_headers();return
            self.send_response(200)
            self.send_header('Content-Type','application/json' if name.endswith(('.json','.geojson')) else 'text/plain; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('ETag','"'+checksum+'"')
            self.send_header('Cache-Control','public, max-age=3600, immutable')
            origin=self.headers.get('Origin')
            if origin in args.cors_origin:
                self.send_header('Access-Control-Allow-Origin',origin);self.send_header('Vary','Origin')
            self.end_headers();self.wfile.write(body)
    print(f'Railway data adapter listening on {args.host}:{args.port}; dataset={args.dataset_id}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()

if __name__=='__main__':main()
