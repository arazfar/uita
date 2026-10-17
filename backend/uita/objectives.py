"""Versioned research objectives and group/predictability/environmental metrics.

All constants are fixed across a matched comparison. These are synthetic research
preferences and proxies, not FAA thresholds, measured emissions, CNEL or workload.
"""
from datetime import datetime, timedelta, timezone
import math
import copy

OBJECTIVE_VERSION='normalized-research-objectives-1'
OBJECTIVE_CONFIG={
    'version':OBJECTIVE_VERSION,
    'weights':{'mean_delay':.24,'tail_delay':.12,'unfinished':.28,'fuel':.10,'relative_noise':.06,'group_service_gap':.08,'starvation':.04,'plan_instability':.04,'verified_replan_recovery':.04},
    'normalizers':{'mean_delay_seconds':600,'tail_delay_seconds':1200,'fuel_kg_per_flight':120,'relative_noise_units_per_flight':14,'recovery_seconds':600},
    'starvation_threshold_seconds':1800,
    'fuel_proxy_kg_per_delay_second':{'arrival_admission':.12,'departure_gate_equivalent':.015},
    'fuel_proxy_wake_multiplier':{'medium':1,'heavy':1.8},
    'co2_proxy_kg_per_fuel_kg':3.16,
    'night_window_local_hours':[22,7],
    'night_relative_weight':10,
    'scenario_epoch_utc':'2026-10-17T16:00:00+00:00',
    'scenario_utc_offset_hours':-7,
    'recovery_scope':'elapsed logical time from latest disruption to next passing replan; not backlog/capacity recovery',
    'group_scope':'synthetic demand group IDs; service fraction among requests due by the metric horizon',
}
assert math.isclose(sum(OBJECTIVE_CONFIG['weights'].values()),1)


def _night(logical_time):
    epoch=datetime.fromisoformat(OBJECTIVE_CONFIG['scenario_epoch_utc'])
    hour=(epoch+timedelta(seconds=logical_time,hours=OBJECTIVE_CONFIG['scenario_utc_offset_hours'])).hour
    start,end=OBJECTIVE_CONFIG['night_window_local_hours']
    return hour>=start or hour<end


def enrich_metrics(state,schedule,horizon,base):
    """Add fixed normalized cost and explicit proxy/fairness/recovery evidence."""
    aircraft=state['aircraft'];n=max(1,len(aircraft));result=dict(base)
    delays={a['id']:max(0,schedule.get(a['id'],horizon+600)-a['requested']) for a in aircraft}
    completed={a['id'] for a in aircraft if not a.get('diverted') and not a.get('admission_hold') and a['id'] in schedule and schedule[a['id']]+(a['exit_occupancy']+90 if a['operation']=='arrival' else 300)<=horizon}
    groups={}
    for a in aircraft:
        group=groups.setdefault(str(a['group']),{'total':0,'due':0,'completed':0,'delays':[],'unfinished_waits':[]})
        group['total']+=1;group['delays'].append(delays[a['id']])
        if a['requested']<=horizon:
            group['due']+=1
            if a['id'] in completed:group['completed']+=1
            else:group['unfinished_waits'].append(max(0,horizon-a['requested']))
    for group in groups.values():
        values=group.pop('delays');waits=group.pop('unfinished_waits')
        group.update(service_fraction=round(group['completed']/group['due'],4) if group['due'] else None,mean_delay_seconds=round(sum(values)/len(values),2),maximum_unfinished_wait_seconds=round(max(waits,default=0),2),starved_requests=sum(w>OBJECTIVE_CONFIG['starvation_threshold_seconds'] for w in waits))
    fractions=[g['service_fraction'] for g in groups.values() if g['service_fraction'] is not None]
    gap=max(fractions,default=0)-min(fractions,default=0)
    starvation=sum(g['starved_requests'] for g in groups.values())
    requested=sorted(aircraft,key=lambda a:(a['requested'],a['id']))
    scheduled=sorted(aircraft,key=lambda a:(schedule.get(a['id'],float('inf')),a['id']))
    rank={a['id']:i for i,a in enumerate(requested)}
    displacements=[abs(i-rank[a['id']]) for i,a in enumerate(scheduled)]
    fuel=sum(delays[a['id']]*OBJECTIVE_CONFIG['fuel_proxy_kg_per_delay_second']['arrival_admission' if a['operation']=='arrival' else 'departure_gate_equivalent']*OBJECTIVE_CONFIG['fuel_proxy_wake_multiplier'][a['wake']] for a in aircraft)
    day_noise=0;night_noise=0;night_operations=0
    for a in aircraft:
        if a['id'] not in completed:continue
        exposure=1.4 if a['wake']=='heavy' else 1
        if _night(schedule[a['id']]):night_noise+=exposure*OBJECTIVE_CONFIG['night_relative_weight'];night_operations+=1
        else:day_noise+=exposure
    latest=max((d['time'] for d in state.get('disruptions',[]) if d['time']<=horizon),default=None)
    passes=[t for t in state.get('verified_replan_times',[]) if latest is not None and latest<=t<=horizon]
    recovery=0 if latest is None else min(passes)-latest if passes else max(0,horizon-latest)
    recovery_status='not-applicable' if latest is None else 'replanned' if passes else 'pending'
    changes=state.get('plan_change_count',state.get('plan_changes',0));decisions=max(1,state.get('planning_decisions',1))
    normalizers=OBJECTIVE_CONFIG['normalizers']
    normalized={'mean_delay':base['mean_delay']/normalizers['mean_delay_seconds'],'tail_delay':base['p95_delay']/normalizers['tail_delay_seconds'],'unfinished':base['backlog']/n,'fuel':fuel/(n*normalizers['fuel_kg_per_flight']),'relative_noise':(day_noise+night_noise)/(n*normalizers['relative_noise_units_per_flight']),'group_service_gap':gap,'starvation':starvation/n,'plan_instability':changes/(n*decisions),'verified_replan_recovery':recovery/normalizers['recovery_seconds']}
    weighted={name:value*OBJECTIVE_CONFIG['weights'][name] for name,value in normalized.items()}
    result.update(objective_version=OBJECTIVE_VERSION,objective_config=copy.deepcopy(OBJECTIVE_CONFIG),objective_components={name:round(value,6) for name,value in normalized.items()},objective_weighted_components={name:round(value,6) for name,value in weighted.items()},score=round(sum(weighted.values()),6),normalized_score=round(sum(weighted.values()),6),legacy_delay_plus_unfinished_seconds=base['score'],group_service=groups,group_service_fraction_gap=round(gap,4),starved_requests=starvation,maximum_resequence_positions=max(displacements,default=0),mean_resequence_positions=round(sum(displacements)/n,3),plan_changes=changes,schedule_shift_seconds=round(state.get('schedule_shift_seconds',0),2),verified_replan_recovery_seconds=recovery,verified_replan_recovery_status=recovery_status,recovery_metric_scope=OBJECTIVE_CONFIG['recovery_scope'],airborne_hold_seconds=None,taxi_hold_seconds=None,arrival_admission_delay_seconds=sum(delays[a['id']] for a in aircraft if a['operation']=='arrival'),departure_schedule_delay_seconds=sum(delays[a['id']] for a in aircraft if a['operation']=='departure'),hold_metric_scope='Actual airborne/taxi holding is not inferred from admission or gate delay; no holding-time measurement is available',fuel_proxy_scope='Delay-equivalent proxy: upstream admission delay and departure gate/APU-equivalent delay use separate synthetic rates and wake multipliers; not measured fuel burn',fuel_proxy_kg=round(fuel,2),emissions_proxy_kg=round(fuel*OBJECTIVE_CONFIG['co2_proxy_kg_per_fuel_kg'],2),relative_noise_exposure=round(day_noise+night_noise,3),relative_night_noise_exposure=round(night_noise,3),completed_night_operations=night_operations,nighttime_definition='22:00–07:00 modeled local UTC−07:00; unitless exposure proxy, not dB/CNEL')
    return result
