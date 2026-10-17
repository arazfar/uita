#!/usr/bin/env python3
"""Resume the eight UTC archives needed for the August 3–9 SFO local replay.

Downloads are verified against GitHub sizes and SHA-256 digests. Only complete
archives are scanned. Global tar parts remain in the ignored cache for retries.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
CACHE = HERE / '.cache/adsb-lol/full-week'
API = 'https://api.github.com/repos/adsblol/globe_history_2026/releases/tags/'
PREFERRED = 'https://raw.githubusercontent.com/adsblol/globe_history_2026/main/PREFERRED_RELEASES.txt'


def get_json(url):
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def manifest(cache):
    path = cache / 'releases.json'
    if path.exists():
        return json.loads(path.read_text())
    with urlopen(PREFERRED, timeout=60) as response:
        lines = response.read().decode().splitlines()
    releases = []
    for day in range(3, 11):
        matches = [line for line in lines if f'/v2026.08.{day:02d}-' in line]
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one preferred release for August {day}')
        tag = matches[0].split('/download/')[1].split('/')[0]
        doc = get_json(API + tag)
        assets = [dict(name=a['name'], url=a['browser_download_url'], size=a['size'], digest=a['digest'])
                  for a in doc['assets'] if '.tar.a' in a['name']]
        releases.append(dict(tag=tag, assets=sorted(assets, key=lambda a: a['name'])))
    path.write_text(json.dumps(releases, indent=2)+'\n')
    return releases


def download(cache, asset):
    path = cache / asset['name']
    partial = path.with_suffix(path.suffix + '.partial')
    if path.exists():
        digest = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
        if path.stat().st_size != asset['size'] or asset['digest'] != 'sha256:' + digest:
            raise ValueError(f'Existing archive fails source checksum: {path.name}')
        path.with_suffix(path.suffix + '.sha256').write_text(digest+'\n')
        return path
    for attempt in range(12):
        result = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
            '--continue-at', '-', '--connect-timeout', '20', '--speed-limit', '10000', '--speed-time', '45',
            '--max-time', '1800', '--output', str(partial), asset['url']])
        if partial.exists() and partial.stat().st_size == asset['size']:
            digest = hashlib.file_digest(partial.open('rb'), 'sha256').hexdigest()
            if asset['digest'] != 'sha256:' + digest:
                raise ValueError(f'Download fails source checksum: {path.name}')
            partial.rename(path)
            path.with_suffix(path.suffix + '.sha256').write_text(digest+'\n')
            print('Verified', path.name, asset['size'], flush=True)
            return path
        print('Retry', asset['name'], attempt + 1, 'curl status', result.returncode, flush=True)
        time.sleep(2)
    raise RuntimeError(f'Download failed; retained resumable partial: {partial}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    releases = manifest(args.cache)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {asset['name']: pool.submit(download, args.cache, asset)
                   for release in releases for asset in release['assets']}
        for release in releases:
            paths = [pending[asset['name']].result() for asset in release['assets']]
            output = args.cache / (release['tag'] + '-candidates.json')
            if output.exists():
                scan = json.loads(output.read_text())
                if (scan.get('archive_scan_complete') and scan.get('retained_sources')
                        and all((args.cache/'traces'/s['retained_file']).is_file() for s in scan['retained_sources'])):
                    continue
            subprocess.run([sys.executable, str(HERE/'adsb_lol.py'), '--archive', *map(str, paths),
                '--release', release['tag'], '--include-covered', '--retain-matched', str(args.cache/'traces'),
                '--output', str(output)], check=True)
    print('All eight archives verified and scanned. Run accept_adsb_backfill.py next.', flush=True)


if __name__ == '__main__':
    main()
