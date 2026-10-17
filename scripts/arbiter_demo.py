"""Live Shared Brain conflict arbitration: two agents disagree, You.com + Crusoe settle it.

  PYTHONPATH=backend .venv-agent/bin/python scripts/arbiter_demo.py --search-only
  CRUSOE_MAX_SPEND_USD=0.05 PYTHONPATH=backend .venv-agent/bin/python scripts/arbiter_demo.py
"""
import argparse
import json
import os
from pathlib import Path

from uita.arbiter import CrusoeJudge, YouSearch, arbitrate, gather
from uita.brain import Brain

TOPIC='FAA arrival wake turbulence separation minimum, small aircraft behind heavy'


def load_env(path=Path(__file__).resolve().parents[1]/'.env'):
    if not path.exists():return
    for line in path.read_text().splitlines():
        key,sep,value=line.partition('=')
        if sep and not key.startswith('#') and key.strip() not in os.environ:os.environ[key.strip()]=value.strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--search-only',action='store_true');parser.add_argument('--db',default=':memory:')
    args=parser.parse_args();load_env()
    brain=Brain(args.db)
    print('scout writes   :',brain.write(TOPIC,'Small behind heavy on final requires 6 NM','6 NM','scout').status)
    conflict=brain.write(TOPIC,'Small behind heavy on final requires 4 NM','4 NM','verifier')
    print('verifier writes: conflict ->',[f"{e.written_by}={e.value}" for e in conflict.entries])
    print('agents now read:',brain.read(TOPIC),'(disputed claims are hidden)')
    search=YouSearch()
    if args.search_only:
        sources,queries=gather(search,conflict)
        print(json.dumps({'queries':queries,'sources':sources},indent=2));return
    judge=CrusoeJudge()
    verdict=arbitrate(brain,conflict,search,judge)
    print(json.dumps({'verdict':verdict,'brain':[e.model_dump() for e in brain.read(TOPIC)],'crusoe_usage':judge.usage,'record':brain.arbitrations()[-1]['record']},indent=2,default=str))


if __name__=='__main__':main()
