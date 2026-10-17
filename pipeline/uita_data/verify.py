"""Verify frozen data contracts, causal playback, and train/test isolation end to end."""
import hashlib
import math
from collections import Counter
from .adapter import ScenarioAdapter
from .common import ROOT, distance, read_json, sha, write_json


def main():
    out=ROOT/'pipeline/build'
    manifest=read_json(out/'manifest.json')
    for name,info in manifest['files'].items():
        assert sha(out/name)==info['sha256'],name
    flights=read_json(out/'flights.json')['flights']
    tracks=read_json(out/'observations.json')
    entries=read_json(out/'entries.json')
    templates=read_json(out/'templates.json')
    episodes=read_json(out/'episodes.json')
    assert len(flights)==4220 and len({f['id'] for f in flights})==4220
    assert len(tracks)==2164 and len(entries)==len(flights)
    by_id={f['id']:f for f in flights}
    assert all(by_id[t['entry']['flight_id']]['split']=='train' for t in templates)
    assert all(e['template_flight_id'] is None or by_id[e['template_flight_id']]['split']=='train' for e in entries)
    for track in tracks:
        points=track['points']
        assert all(a['t']<b['t'] for a,b in zip(points,points[1:]))
        for a,b in zip(points,points[1:]):
            if a['segment_id']==b['segment_id']:
                assert b['t']-a['t']<=120
                assert distance((a['lon'],a['lat']),(b['lon'],b['lat']))*3600/(b['t']-a['t'])<=700.001
    forbidden={'t','runway','recorded_arrival_time','template_flight_id','local_date','split'}
    spawn_total=0
    for day in sorted({f['local_date'] for f in flights}):
        pack=read_json(out/f'scenarios/{day}.json')
        driver=ScenarioAdapter(pack)
        seen=[]
        clocks=sorted({pack['clock_start']-1,*[e['spawn_time'] for e in pack['entries']],pack['clock_end']})
        for clock in clocks:
            frame=driver.advance(clock)
            assert not forbidden.intersection(frame)
            for spawn in frame['spawned']:
                assert spawn['spawn_time']<=clock
                assert not forbidden.intersection(spawn)
                assert all(math.isfinite(v) for v in spawn['position'].values())
                seen.append(spawn['flight_id'])
            if frame['weather']:
                assert frame['weather']['available_at']<=clock
        assert len(seen)==len(set(seen))==len(pack['entries'])
        assert driver.advance(clocks[-1])['spawned']==[]
        try:driver.advance(clocks[0])
        except ValueError:pass
        else:raise AssertionError('Backward clock was accepted')
        spawn_total+=len(seen)
    assert spawn_total==4220
    for ep in episodes:
        assert all(by_id[fid]['split']==ep['split'] for fid in ep['flight_ids'])
        assert ep['warmup_start']<ep['start']<ep['end']<ep['drain_end']
    report={'passed':True,'arrivals':len(flights),'tracks':len(tracks),'spawns_verified':spawn_total,
        'episodes':len(episodes),'episode_splits':dict(Counter(e['split'] for e in episodes)),
        'checks':['artifact checksums','complete roster','unique IDs','position speed and gap bounds',
            'training-only synthesis templates','all week spawns exactly once','no future weather',
            'no historical outcomes in controller entry state','clock rewind rejection','episode day isolation']}
    write_json(out/'verification.json',report)
    print(report)

if __name__=='__main__':main()
