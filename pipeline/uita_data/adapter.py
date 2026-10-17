"""Causal scenario driver. Do not hand its private scenario payload to an agent."""
from bisect import bisect_right
from copy import deepcopy
import math
from .common import read_json


class ScenarioAdapter:
    def __init__(self,scenario):
        self._scenario=deepcopy(scenario)
        self._entries=sorted(scenario['entries'],key=lambda e:(e['spawn_time'],e['flight_id']))
        self._weather=sorted(scenario['weather'],key=lambda w:w['available_at'])
        self._times=[w['available_at'] for w in self._weather]
        self._cursor=0
        self._clock=float('-inf')

    @classmethod
    def from_file(cls,path):return cls(read_json(path))

    def advance(self,clock):
        if not math.isfinite(clock) or clock<self._clock:
            raise ValueError('Clock must advance monotonically; construct a new adapter to replay')
        self._clock=clock
        spawned=[]
        while self._cursor<len(self._entries) and self._entries[self._cursor]['spawn_time']<=clock:
            e=self._entries[self._cursor]
            # Explicit allowlist prevents provenance IDs and future outcome leakage.
            spawned.append({k:deepcopy(e[k]) for k in ['flight_id','callsign','aircraft_type','origin','spawn_time',
                'position','groundspeed_kt','track_deg_true','position_provenance','altitude_provenance','motion_provenance']})
            self._cursor+=1
        index=bisect_right(self._times,clock)-1
        weather=deepcopy(self._weather[index]) if index>=0 else None
        if weather:
            weather['age_seconds']=clock-weather['observed_at']
            weather['stale']=weather['age_seconds']>7200
        # This returns new spawns only. The simulator owns all later motion.
        return {'clock':clock,'spawned':spawned,'weather':weather}
