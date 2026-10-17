"""Explicit bounded live tool/typed-output probe; never retries a failed request."""
import asyncio
import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Literal
os.environ.setdefault('PYDANTIC_AI_NO_BANNER','1')
from pydantic import BaseModel,ConfigDict
from pydantic_ai import Agent,ToolOutput,NativeOutput
from pydantic_ai.usage import UsageLimits
from uita.agent_provider import open_model
from uita.agent_contracts import AgentLimits
from uita.provider import ProviderError

class CapabilityResult(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    status:Literal['ok']

async def main(native_output=False):
    path=Path('docs/agent-upgrade/live-capability-native-output.json' if native_output else 'docs/agent-upgrade/live-capability-profile-2.json')
    if path.exists():raise ValueError('Capability evidence already exists; do not overwrite a live attempt')
    record={'source':'crusoe-live','purpose':'Explicit new capability experiment with documented native compatibility profile; no failed request replay','output_mode':'native-json-schema' if native_output else 'output-tool','events':[]}
    def emit(kind,message,data):
        record['events'].append({'kind':kind,'message':message,'data':data});path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(record,indent=2)+'\n')
    limits=AgentLimits(model_requests=3,request_output_tokens=1500,spend_usd=.003)
    model,sdk,transport=await open_model('capability-profile-2-'+str(uuid.uuid4()),limits,emit)
    agent=Agent(model,output_type=NativeOutput(CapabilityResult,name='capability_result',strict=True) if native_output else ToolOutput(CapabilityResult,name='finish_capability',max_retries=0,strict=True),retries=0,model_settings={'max_tokens':1500,'temperature':0,'parallel_tool_calls':False})
    @agent.tool_plain(retries=0,sequential=True)
    async def capability_echo(value:Literal['ok'])->Literal['ok']:
        emit('tool_capability_verified','Native function tool executed with validated arguments',{'value':value});return value
    try:
        prompt='First call capability_echo with value ok. Then return a JSON object with status ok matching the output schema. No additional reasoning or text is needed.' if native_output else 'First call capability_echo with value ok. Then call finish_capability with status ok. No additional reasoning or text is needed.'
        result=await agent.run(prompt,usage_limits=UsageLimits(request_limit=3,tool_calls_limit=2))
        record['status']='complete' if any(e['kind']=='tool_capability_verified' for e in record['events']) else 'failed-no-function-tool'
        record['output']=result.output.model_dump()
    except Exception as exc:
        record['status']='failed';record['error_type']=type(exc).__name__
        if isinstance(exc,ProviderError):record['error']=str(exc)
    finally:
        record['usage']=transport.usage;await sdk.close();path.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'status':record['status'],'usage':record['usage'],'metadata':[e['data'] for e in record['events'] if e['kind']=='inference_metadata']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--native-output',action='store_true');args=parser.parse_args()
    asyncio.run(main(args.native_output))
