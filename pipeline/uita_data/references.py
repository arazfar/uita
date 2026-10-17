"""Download only the historical reference dates required by the August brief."""
import csv
import datetime as dt
import hashlib
import io
import urllib.parse
import urllib.request
import zipfile
import requests
from .common import ROOT, write_json

CACHE = ROOT / 'pipeline/.cache/references'


def fetch(name, url):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / name
    if not p.exists():
        response = requests.get(url, timeout=90, headers={'User-Agent': 'UpInTheAir/1.0 historical research'})
        response.raise_for_status()
        content = response.content
        temp = p.with_suffix('.part')
        temp.write_bytes(content)
        temp.replace(p)
    data = p.read_bytes()
    return data, {'file': name, 'url': url, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def weather():
    params = dict(station='SFO', data='all', year1=2026, month1=8, day1=2, year2=2026, month2=8, day2=11,
                  tz='Etc/UTC', format='onlycomma', latlon='yes', elev='yes', missing='M', trace='T', direct='no')
    query = urllib.parse.urlencode(params) + '&report_type=3&report_type=4'
    data, source = fetch('ksfo-metar-2026-08-02_10.csv', 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?' + query)
    rows = []
    text = '\n'.join(l for l in data.decode().splitlines() if not l.startswith('#'))
    for r in csv.DictReader(io.StringIO(text)):
        t = dt.datetime.fromisoformat(r['valid']).replace(tzinfo=dt.timezone.utc).timestamp()
        rows.append({'id': f'KSFO-{int(t)}', 'observed_at': t, 'available_at': t+300,
                     'availability_assumption': 'observation timestamp plus 300 seconds; actual receipt time unavailable',
                     'wind_direction_deg_true': number(r.get('drct')), 'wind_speed_kt': number(r.get('sknt')),
                     'wind_gust_kt': number(r.get('gust')), 'visibility_sm': number(r.get('vsby')),
                     'altimeter_inhg': number(r.get('alti')), 'temperature_f': number(r.get('tmpf')),
                     'cloud_layers': [{'cover': r.get(f'skyc{i}'), 'base_ft_agl': number(r.get(f'skyl{i}'))}
                                      for i in range(1,5) if r.get(f'skyc{i}') not in (None,'M','')],
                     'metar': r.get('metar'), 'source': 'IEM KSFO METAR/SPECI'})
    rows.sort(key=lambda r: r['available_at'])
    if not rows:
        raise ValueError('IEM returned no weather observations')
    return rows, source


def airport():
    cycles = []
    sources = []
    for label, effective, until in [('09_Jul_2026','2026-07-09','2026-08-06'), ('06_Aug_2026','2026-08-06','2026-09-03')]:
        url = f'https://nfdc.faa.gov/webContent/28DaySub/extra/{label}_APT_CSV.zip'
        legacy = ROOT / f'pipeline/.cache/{label}_APT_CSV.zip'
        target = CACHE / f'{label}_APT_CSV.zip'
        if legacy.exists() and not target.exists():
            CACHE.mkdir(parents=True, exist_ok=True)
            target.write_bytes(legacy.read_bytes())
        data, source = fetch(target.name, url)
        sources.append(source)
        tables = {}
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for filename in ['APT_BASE.csv','APT_RWY.csv','APT_RWY_END.csv']:
                member = next(n for n in z.namelist() if n.endswith(filename))
                reader = csv.DictReader(io.StringIO(z.read(member).decode('utf-8-sig')))
                tables[filename] = [r for r in reader if r.get('ARPT_ID') == 'SFO' and r.get('STATE_CODE') == 'CA']
        if len(tables['APT_RWY.csv']) != 4 or len(tables['APT_RWY_END.csv']) != 8:
            raise ValueError(f'Unexpected FAA runway coverage for {effective}')
        cycles.append({'effective_date': effective, 'end_exclusive_date': until,
                       'source': 'FAA NASR APT CSV', 'tables': tables,
                       'limits': 'Surveyed geometry; no historical closure, NOTAM, or active runway configuration record.'})
    return {'airport': 'KSFO', 'cycles': cycles}, sources


def main():
    out = ROOT / 'pipeline/build'
    wx, wx_source = weather()
    apt, apt_sources = airport()
    write_json(out / 'weather.json', wx)
    write_json(out / 'airport.json', apt)
    write_json(out / 'reference-provenance.json', {'sources': [wx_source, *apt_sources]})
    print(f'References: {len(wx)} weather reports; {len(apt["cycles"])} date-matched FAA cycles')

if __name__ == '__main__':
    main()
