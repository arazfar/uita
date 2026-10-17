import json

import httpx
import pytest

from uita.arbiter import ArbiterError, YouSearch, arbitrate, queries_for
from uita.brain import Brain, Conflict

TOPIC='Arrival wake separation, small aircraft behind heavy'
FAA={'url':'https://www.faa.gov/air_traffic/publications/atpubs/atc_html/chap5_section_5.html','title':'FAA JO 7110.65 5-5-4','text':'Separate aircraft operating directly behind a heavy: small behind heavy 6 miles.'}
BLOG={'url':'https://example.com/blog','title':'Blog','text':'Most controllers use 5 miles for everything.'}


def seeded():
    brain=Brain()
    assert brain.write(TOPIC,'Small behind heavy needs 6 NM','6 NM','scout').status=='active'
    conflict=brain.write(TOPIC,'Small behind heavy needs 5 NM','5 NM','verifier')
    assert isinstance(conflict,Conflict) and len(conflict.entries)==2
    return brain,conflict


def judge_for(value,quote=FAA['text'],verdict=None):
    def judge(messages):
        claims=json.loads(messages[1]['content'])['claims']
        label=verdict or next(k for k,v in claims.items() if v['value']==value)
        return {'verdict':label,'citations':[{'source':0,'quote':quote}],'reason':'Regulator states the minimum.'}
    return judge


def test_conflicting_write_hides_both_claims_until_resolved():
    brain,_=seeded()
    assert brain.read(TOPIC)==[]
    assert len(brain.conflicts())==1


def test_agreeing_quote_verified_verdict_resolves_with_lineage():
    brain,conflict=seeded()
    verdict=arbitrate(brain,conflict,lambda q:[FAA,BLOG],judge_for('6 NM'))
    assert verdict['outcome']=='resolved'
    [active]=brain.read(TOPIC)
    assert active.value=='6 NM' and active.written_by=='arbiter'
    assert active.sources[0].url==FAA['url'] and set(active.supersedes)=={e.id for e in conflict.entries}
    assert brain.conflicts()==[] and len(brain.history(TOPIC))==3


def test_fabricated_quote_is_not_accepted():
    brain,conflict=seeded()
    verdict=arbitrate(brain,conflict,lambda q:[FAA],judge_for('6 NM',quote='The FAA requires 6 miles for every aircraft pairing always.'))
    assert verdict['outcome']=='needs_human' and brain.read(TOPIC)==[]


def test_position_biased_judge_is_not_accepted():
    brain,conflict=seeded()
    verdict=arbitrate(brain,conflict,lambda q:[FAA],judge_for(None,verdict='A'))
    assert verdict['outcome']=='needs_human' and 'disagreed' in verdict['reason']
    assert len(brain.conflicts())==1


def test_insufficient_and_judge_errors_stay_disputed():
    brain,conflict=seeded()
    def broken(messages):raise ValueError('bad json')
    assert arbitrate(brain,conflict,lambda q:[FAA],broken)['outcome']=='needs_human'
    assert arbitrate(brain,conflict,lambda q:[],judge_for('6 NM'))['outcome']=='needs_human'
    assert len(brain.arbitrations())==2


def test_queries_with_callsigns_or_replay_dates_are_refused():
    brain=Brain()
    brain.write('UAL123 arrival slot','first','1','a')
    conflict=brain.write('UAL123 arrival slot','second','2','b')
    with pytest.raises(ArbiterError):queries_for(conflict)


def test_you_search_parses_highlights_and_excludes_trackers():
    seen={}
    def handler(request):
        seen['key']=request.headers['X-API-Key'];seen['body']=json.loads(request.content)
        return httpx.Response(200,json={'results':{'web':[{'url':FAA['url'],'title':'FAA','contents':{'highlights':['small behind heavy 6 miles']}},{'url':'https://x.test','title':'empty'}]}})
    rows=YouSearch(key='test',transport=httpx.MockTransport(handler))('wake separation')
    assert seen['key']=='test' and 'flightaware.com' in seen['body']['exclude_domains']
    assert rows==[{'url':FAA['url'],'title':'FAA','text':'small behind heavy 6 miles'}]
