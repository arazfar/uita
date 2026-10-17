"""Freeze cleaned replay, simulation inputs, and day-disjoint benchmark cases."""
from __future__ import annotations
from collections import Counter
import datetime as dt
import math
import re
import statistics
from zoneinfo import ZoneInfo
from .common import ROOT, CENTER, TZ, VERSION, bearing, distance, read_json, sha, write_json

OUT = ROOT / 'pipeline/build'
BUNDLE = ROOT / 'pipeline/bundle'
UTC = dt.timezone.utc


def epoch(value):
    return dt.datetime.fromisoformat(value).timestamp()


def split(day):
    return 'train' if day <= '2026-08-06' else 'validation' if day == '2026-08-07' else 'test'


def normalize_altitude(raw):
    # FAA reportedAlt_54aC is beacon-reported; bare simpleAltitude can be assigned.
    text = str(raw).strip()
    if re.fullmatch(r'\d{2,3}C', text):
        return int(text[:-1])*100, 'beacon_reported_hundreds_ft'
    return None, 'unknown_or_assigned_not_actual'


def normalize_track(track, counts):
    raw = track['points']
    kept = []
    segment = 0
    for i, p in enumerate(raw):
        t, lon, lat, alt, speed = p
        if not all(isinstance(v, (int,float)) and math.isfinite(v) for v in (t,lon,lat)) or not -180<=lon<=180 or not -90<=lat<=90:
            counts['invalid_coordinates'] += 1
            continue
        if distance(CENTER, (lon,lat)) > 80.05:
            counts['outside_radius'] += 1
            continue
        previous = kept[-1] if kept else None
        if previous:
            gap = t-previous['t']
            if gap <= 0:
                counts['non_increasing_time'] += 1
                continue
            kt = distance((previous['lon'],previous['lat']), (lon,lat))*3600/gap
            # Reject isolated spikes, then break at unexplained jumps. Never bridge them.
            if kt > 700 and i+1 < len(raw):
                nxt = raw[i+1]
                total = nxt[0]-previous['t']
                if total > 0 and distance((previous['lon'],previous['lat']), (nxt[1],nxt[2]))*3600/total <= 700:
                    counts['isolated_position_spikes_removed'] += 1
                    continue
            if gap > 120 or kt > 700:
                segment += 1
                counts['segment_breaks'] += 1
                previous = None
        altitude, reference = normalize_altitude(alt)
        derived_speed = heading = None
        if previous:
            derived_speed = round(distance((previous['lon'],previous['lat']), (lon,lat))*3600/(t-previous['t']),2)
            heading = round(bearing((previous['lon'],previous['lat']), (lon,lat)),2)
            if derived_speed < 10:
                heading = None
        # Retain unverified source speed without presenting it as a physical unit.
        kept.append({'t': t, 'lon': lon, 'lat': lat, 'altitude_ft': altitude,
                     'altitude_reference': reference, 'altitude_raw': alt, 'speed_raw': speed,
                     'groundspeed_kt': derived_speed, 'track_deg_true': heading, 'segment_id': segment})
    counts['points_retained'] += len(kept)
    return {'flight_id': 'a'+track['operation_id'], 'operation_id': track['operation_id'],
            'museum_wof_id': track['museum_wof_id'], 'match_method': track['match_method'],
            'source': 'SFO Museum swim-path', 'points': kept}


def entry_for(flight, track):
    if not track:
        return None
    for p in track['points']:
        if p['groundspeed_kt'] is not None and 90<=p['groundspeed_kt']<=550 and p['track_deg_true'] is not None:
            alt = p['altitude_ft']
            # Missing actual altitude must be explicit in simulator initial conditions.
            if alt is None:
                alt = min(18000, max(3000, round(distance(CENTER,(p['lon'],p['lat']))*300/100)*100))
            if not 1000 <= alt <= 30000 or distance(CENTER,(p['lon'],p['lat'])) < 8:
                continue
            return {'flight_id':flight['id'], 'callsign':flight['callsign'], 'aircraft_type':flight['type'],
                    'origin':flight['port'], 'spawn_time':p['t'],
                    'position':{'lon':p['lon'], 'lat':p['lat'], 'altitude_ft':alt},
                    'groundspeed_kt':p['groundspeed_kt'], 'track_deg_true':p['track_deg_true'],
                    'position_provenance':'observed',
                    'altitude_provenance':'beacon_reported' if p['altitude_ft'] is not None else 'synthetic_distance_profile',
                    'motion_provenance':'backward_difference_observed_points',
                    'template_flight_id':None}
    return None


def make_synthetic(flight, templates):
    candidates = [t for t in templates if t['origin']==flight['port']] or templates
    # Deterministic selection; neither target-day paths nor runway outcomes fit templates.
    import hashlib
    index = int(hashlib.sha256(flight['id'].encode()).hexdigest()[:8],16) % len(candidates)
    template = candidates[index]
    entry = {**template['entry'], 'position':dict(template['entry']['position'])}
    entry.update(flight_id=flight['id'], callsign=flight['callsign'], aircraft_type=flight['type'], origin=flight['port'],
                 spawn_time=flight['t']-template['lead_seconds'], position_provenance='synthetic_training_template',
                 altitude_provenance='synthetic_training_template', motion_provenance='synthetic_training_template',
                 template_flight_id=template['entry']['flight_id'])
    return entry


def geometry(airport):
    features=[]
    for cycle in airport['cycles']:
        ends = cycle['tables']['APT_RWY_END.csv']
        for runway in cycle['tables']['APT_RWY.csv']:
            candidates=[e for e in ends if e['RWY_ID']==runway['RWY_ID']]
            coords=[]
            for end in candidates:
                # NASR decimal fields are surveyed threshold/runway-end coordinates.
                lon=end.get('LONG_DECIMAL') or end.get('RWY_END_LONG_DECIMAL')
                lat=end.get('LAT_DECIMAL') or end.get('RWY_END_LAT_DECIMAL')
                if lon and lat:
                    coords.append([float(lon),float(lat)])
            if len(coords)==2:
                features.append({'type':'Feature','geometry':{'type':'LineString','coordinates':coords},
                    'properties':{'runway':runway['RWY_ID'], 'effective_date':cycle['effective_date'],
                                  'end_exclusive_date':cycle['end_exclusive_date'], 'source':'FAA NASR'}})
    if len(features)!=8:
        raise ValueError('Failed to derive all date-matched runway centerlines')
    return {'type':'FeatureCollection','features':features}


def main():
    arrivals=read_json(BUNDLE/'arrivals.json')
    raw_tracks=read_json(BUNDLE/'tracks.json')['tracks']
    wx=read_json(OUT/'weather.json')
    airport=read_json(OUT/'airport.json')
    quality=Counter()
    tracks={t['flight_id']:t for raw in raw_tracks if (t:=normalize_track(raw,quality))['points']}
    flights=[]
    for a in arrivals:
        day=a['arrival_operation_time_local'][:10]
        flights.append({'id':'a'+a['operation_id'], 'operation_id':a['operation_id'], 'kind':'arr',
            't':epoch(a['arrival_operation_time_utc']), 'local_date':day, 'split':split(day),
            'callsign':a['callsign'] or '', 'reg':a['registration'] or '', 'type':a['aircraft_type'] or '',
            'airline':a['airline_icao'] or '', 'port':a['origin'] or '', 'runway':a['runway'],
            'has_track':'a'+a['operation_id'] in tracks,
            'timestamp_meaning':'recorded_arrival_operation_not_verified_touchdown'})
    flights.sort(key=lambda f:(f['t'],f['id']))
    observed_entries={f['id']:e for f in flights if (e:=entry_for(f,tracks.get(f['id'])))}
    templates=[{'entry':observed_entries[f['id']], 'origin':f['port'], 'lead_seconds':f['t']-observed_entries[f['id']]['spawn_time']}
               for f in flights if f['split']=='train' and f['id'] in observed_entries
               and 120<=f['t']-observed_entries[f['id']]['spawn_time']<=2400]
    if not templates:
        raise ValueError('No training-day entry templates')
    entries=[observed_entries.get(f['id']) or make_synthetic(f,templates) for f in flights]
    for f,e in zip(flights,entries):
        e['split']=f['split']
        e['local_date']=f['local_date']
    entries.sort(key=lambda e:(e['spawn_time'],e['flight_id']))
    episodes=[]
    for offset in range(7):
        day=dt.date(2026,8,3)+dt.timedelta(days=offset)
        local_start=dt.datetime.combine(day,dt.time(),ZoneInfo(TZ))
        for hour in [6,9,12,15,18,21]:
            start=(local_start+dt.timedelta(hours=hour)).timestamp()
            end=start+1800
            warmup=start-900
            drain=end+1800
            selected=[e for e in entries if warmup<=e['spawn_time']<end and e['local_date']==str(day)]
            ids=[e['flight_id'] for e in selected]
            ops=[f for f in flights if start<=f['t']<end]
            episodes.append({'id':f'{day}-{hour:02d}00', 'split':split(str(day)), 'local_date':str(day),
                'warmup_start':warmup, 'start':start, 'end':end, 'drain_end':drain,
                'scenario_file':f'scenarios/{day}.json', 'flight_ids':ids,
                'spawn_count':len(ids), 'synthetic_spawn_count':sum(e['position_provenance']!='observed' for e in selected),
                'historical_operation_count_context_only':len(ops),
                'seeds':[17,29,43], 'disturbance_variants':['nominal','synthetic_delayed_readback','synthetic_runway_unavailable']})
    week={'start_utc':epoch('2026-08-03T00:00:00-07:00'), 'end_utc':epoch('2026-08-10T00:00:00-07:00'),'tz':TZ}
    files={
        'source/arrivals.json':arrivals, 'source/tracks.json':read_json(BUNDLE/'tracks.json'),
        'source/coverage.json':read_json(BUNDLE/'coverage.json'),
        'source/quality-notes.json':read_json(BUNDLE/'quality-notes.json'),
        'flights.json':{'week':week,'flights':flights},
        'tracks.json':{fid:[[p['t'],p['lon'],p['lat'],p['altitude_ft'],p['groundspeed_kt']] for p in tr['points']] for fid,tr in tracks.items()},
        'observations.json':list(tracks.values()), 'entries.json':entries,
        'episodes.json':episodes, 'templates.json':templates,
        'runways.geojson':geometry(airport),
        'quality.json':{'counts':dict(quality),'arrivals':len(flights),'tracks':len(tracks),
                       'observed_entries':len(observed_entries),'synthetic_entries':len(entries)-len(observed_entries),
                       'template_count':len(templates),'template_fit_days':['2026-08-03','2026-08-06'],
                       'altitude': 'Only C-suffixed beacon values populate observed altitude_ft. Others remain null.',
                       'speed':'Derived from previous same-segment position; source speed_raw remains unverified.',
                       'thresholds':{'max_groundspeed_kt':700,'max_continuous_gap_seconds':120},
                       'limits':['No genuine ATC commands or radio transcripts.','No touchdown or runway-clearance ground truth.',
                                 'Missing-path spawn time inferred backward from recorded operation time.',
                                 'tracks.json is a compact replay export; use observations.json for segment boundaries.',
                                 'No interpolation or human separation scoring across segment gaps or null altitudes.']},
    }
    for day in sorted({f['local_date'] for f in flights}):
        day_start=dt.datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(TZ)).timestamp()
        day_entries=[e for e in entries if e['local_date']==day]
        files[f'scenarios/{day}.json']={'schema_version':1,'dataset_id':VERSION,'id':day,'split':split(day),
            'clock_start':min([day_start]+[e['spawn_time'] for e in day_entries]), 'clock_end':day_start+86400,
            'entries':day_entries, 'weather':wx,
            'airport':airport, 'limits':'Future spawn queue is simulator-private. Expose only spawn_due(clock) to controller.'}
    for name,value in files.items():
        write_json(OUT/name,value)
    sources={name:sha(BUNDLE/name) for name in ['arrivals.json','tracks.json','provenance.json']}
    manifest={'schema_version':1,'id':VERSION,'week':week,'counts':files['quality.json'],
              'splits':{'train':['2026-08-03','2026-08-06'],'validation':['2026-08-07','2026-08-07'],'test':['2026-08-08','2026-08-09']},
              'sources':sources,'source_provenance':'provenance.json','reference_provenance':'reference-provenance.json',
              'files':{name:{'sha256':sha(OUT/name),'bytes':(OUT/name).stat().st_size} for name in sorted(files.keys()|{'weather.json','airport.json','reference-provenance.json'})},
              'live_demo_episode':max((e for e in episodes if e['split']=='train'),key=lambda e:e['spawn_count'])['id']}
    write_json(OUT/'provenance.json',read_json(BUNDLE/'provenance.json'))
    for name in ['README.md','SFO-Museum-LICENSE.txt','datasf-source-metadata.json']:
        (OUT/name).write_bytes((BUNDLE/name).read_bytes())
    for name in ['provenance.json','README.md','SFO-Museum-LICENSE.txt','datasf-source-metadata.json']:
        manifest['files'][name]={'sha256':sha(OUT/name),'bytes':(OUT/name).stat().st_size}
    write_json(OUT/'manifest.json',manifest)
    import duckdb
    db=duckdb.connect(str(OUT/'sfo.duckdb'))
    for table,name in [('arrivals','flights.json'),('weather','weather.json'),('episodes','episodes.json'),('entries','entries.json')]:
        value=files.get(name) or read_json(OUT/name)
        rows=value['flights'] if table=='arrivals' else value
        temp=OUT/f'.{table}.json'; write_json(temp,rows)
        db.execute(f'CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_json_auto(?)',[str(temp)])
        temp.unlink()
    db.close()
    print(f'Built {VERSION}: {len(flights)} arrivals, {len(tracks)} tracks, {len(episodes)} benchmark windows')
    print(f'Initial states: {len(observed_entries)} observed positions; {len(entries)-len(observed_entries)} synthetic templates')

if __name__=='__main__':
    main()
