import copy
import pytest
from uita.research.arrival_cues import historical_cue, simulation_cue, recording_frame
from uita.research.geometry import geographic


def point(t,x,alt):
    lon,lat=geographic(x,0)
    return dict(t=t,lon=lon,lat=lat,altitude_ft=alt,track_deg_true=270,segment_id='one')


def test_historical_boundaries_and_no_lookahead():
    p=[point(0,4,3000),point(20,3.5,2800),point(40,3,2500)]
    result=historical_cue(p,1,20)
    assert result['basis']=='inferred' and result['runway'] is None
    assert result['evidence_time']==20
    assert historical_cue(p[:2],1,20)==result
    assert historical_cue(p,1,36) is None
    assert historical_cue(p,2,39) is None
    for field,value in [('altitude_ft',None),('altitude_ft',199),('altitude_ft',5001),('track_deg_true',90),('segment_id','other')]:
        changed=copy.deepcopy(p);changed[1][field]=value
        assert historical_cue(changed,1,20) is None
    for gap in (9,61):
        changed=[point(0,4,3000),point(gap,3.5,2800)]
        assert historical_cue(changed,1,gap) is None
    assert historical_cue([point(0,8.5,3000),point(20,8.1,2800)],1,20) is None
    assert historical_cue([point(0,3,3000),point(20,3.5,2800)],1,20) is None


def test_simulation_phases_do_not_infer_authority_from_assignment():
    a=dict(id='a',status='approach',runway='28L',x_nm=2,y_nm=1,landing_authorized=False)
    state=dict(clock=20,closed_runways=[],clearances=[])
    assert simulation_cue(a,state)['phase']=='approaching'
    c=dict(id='c',aircraft_id='a',kind='landing',target='28L',status='issued',expires_at=50)
    state['clearances']=[c]
    assert simulation_cue(a,state)['phase']=='clearance_issued'
    a['landing_authorized']=True;c['status']='completed'
    assert simulation_cue(a,state)['phase']=='landing_authorized'
    c['status']='cancelled'
    assert simulation_cue(a,state)['phase']=='approaching'
    c['status']='issued'
    assert simulation_cue(a,state)['phase']=='clearance_issued'
    state['closed_runways']=['28L']
    assert simulation_cue(a,state)['phase']=='approaching'
    a['status']='go_around'
    assert simulation_cue(a,state) is None
    a['status']='taxi'
    assert simulation_cue(a,state)['phase']=='on_ground'
    a.update(status='complete',surface_seconds=75)
    assert simulation_cue(a,state)['phase']=='arrival_completed'


def test_old_recording_cues_are_causal_and_immutable():
    a=dict(id='a',status='approach',runway='28L',longitude=-122.3,latitude=37.6)
    original=dict(clock=10,aircraft=[a],closed_runways=[])
    events=[dict(sequence=1,clock=10,kind='clearance_issued',payload={'clearance':dict(id='c',aircraft_id='a',kind='landing',target='28L',status='issued',expires_at=30)}),dict(sequence=2,clock=12,kind='pilot_acknowledged',payload={'clearance_id':'c'})]
    before=copy.deepcopy(original)
    assert recording_frame(original,events)['aircraft'][0]['arrival_cue']['phase']=='clearance_issued'
    assert original==before
    later={**original,'clock':12}
    assert recording_frame(later,events)['aircraft'][0]['arrival_cue']['phase']=='landing_authorized'
    events.append(dict(sequence=3,clock=13,kind='clearance_cancelled',payload={'clearance_id':'c'}))
    assert recording_frame({**original,'clock':13},events)['aircraft'][0]['arrival_cue']['phase']=='approaching'
    assert recording_frame(original,[])['aircraft'][0]['arrival_cue']['phase']=='approaching'
