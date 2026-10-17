"""Fixed normalized research-objective regression tests."""
import copy
import pytest
from uita.simulator import new_state,metrics
from uita.objectives import OBJECTIVE_CONFIG,OBJECTIVE_VERSION


def test_objective_is_fixed_weighted_normalized_sum():
    result=metrics(new_state(),horizon=2700)
    assert sum(OBJECTIVE_CONFIG['weights'].values())==pytest.approx(1)
    assert result['objective_version']==OBJECTIVE_VERSION
    assert result['score']==pytest.approx(sum(result['objective_weighted_components'].values()),abs=.00001)
    assert result['objective_components']['unfinished']==pytest.approx(result['backlog']/result['total'],abs=.000001)
    result['objective_config']['weights']['mean_delay']=999
    assert OBJECTIVE_CONFIG['weights']['mean_delay']==.24


def test_group_service_gap_and_starvation_use_unfinished_due_requests():
    state=new_state();state['aircraft']=state['aircraft'][:2]
    first,second=state['aircraft']
    first['group']=0;second['group']=1
    first['requested']=second['requested']=400
    first['scheduled']=600;second['scheduled']=10000
    result=metrics(state,horizon=2700)
    assert result['group_service']['0']['service_fraction']==1
    assert result['group_service']['1']['service_fraction']==0
    assert result['group_service_fraction_gap']==1
    assert result['starved_requests']==1
    assert result['objective_components']['starvation']==.5


def test_unfinished_aircraft_cannot_disappear_from_normalized_objective():
    state=new_state();result=metrics(state,slots=[],horizon=2700)
    assert result['backlog']==result['total']
    assert result['objective_components']['unfinished']==1
    assert all(group['completed']==0 for group in result['group_service'].values())


def test_night_exposure_uses_operation_time_and_explicit_local_window():
    state=new_state();state['aircraft']=state['aircraft'][:1]
    day=metrics(state,horizon=1000)
    night_state=copy.deepcopy(state)
    night_state['aircraft'][0]['scheduled']+=13*3600
    night_state['aircraft'][0]['requested']+=13*3600
    night=metrics(night_state,horizon=1000+13*3600)
    assert day['completed_night_operations']==0
    assert night['completed_night_operations']==1
    assert night['relative_night_noise_exposure']==pytest.approx(day['relative_noise_exposure']*10)
    assert night['objective_components']['relative_noise']>day['objective_components']['relative_noise']


def test_recovery_and_instability_report_defined_evidence():
    state=new_state();state['disruptions']=[{'kind':'gate_delay','time':1000}]
    state.update(verified_replan_times=[400,1100],plan_change_count=12,planning_decisions=4,schedule_shift_seconds=200)
    result=metrics(state,horizon=1500)
    assert result['verified_replan_recovery_seconds']==100
    assert result['verified_replan_recovery_status']=='replanned'
    assert result['objective_components']['plan_instability']==pytest.approx(.25)
    assert result['schedule_shift_seconds']==200
    state['verified_replan_times']=[]
    result=metrics(state,horizon=1500)
    assert result['verified_replan_recovery_status']=='pending'
    assert result['verified_replan_recovery_seconds']==500


def test_diverted_aircraft_is_unfinished_at_requested_destination():
    state=new_state();state['aircraft']=state['aircraft'][:1]
    state['aircraft'][0]['diverted']=True
    result=metrics(state,horizon=2700)
    assert result['completed']==0
    assert result['backlog']==1
    assert result['group_service']['0']['completed']==0


def test_postponing_every_flight_cannot_improve_normalized_score():
    state=new_state()
    current=metrics(state,horizon=2700)
    delayed=[{'aircraft_id':a['id'],'time':a['scheduled']+10000,'runway':a['runway']} for a in state['aircraft']]
    postponed=metrics(state,slots=delayed,horizon=2700)
    assert postponed['completed']==0
    assert postponed['score']>current['score']
    assert postponed['objective_components']['unfinished']>=current['objective_components']['unfinished']


def test_admission_delay_is_not_reported_as_actual_airborne_holding():
    result=metrics(new_state(),horizon=2700)
    assert result['arrival_admission_delay_seconds']>0
    assert result['airborne_hold_seconds'] is None
    assert result['taxi_hold_seconds'] is None
    assert 'gate/APU' in result['fuel_proxy_scope']
