// Fixture only: verifies that browsing history never pauses the durable worker.
async page => {
  await page.unrouteAll();
  const origin=new URL(page.url()).origin;
  const created=await page.request.post(origin+'/api/v2/runs',{data:{scenario_id:'fixture-august-v2',controller:'fixture',spend_cap_usd:0.5,idempotency_key:'switch-'+Date.now()}});
  if(!created.ok())throw Error('Fixture creation failed');
  const run=await created.json();
  await page.goto(origin+'/?run='+encodeURIComponent(run.id));
  await page.locator('#play').waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.querySelector('#play').disabled,null,{timeout:10000});
  await page.locator('#play').click();
  await page.waitForFunction(()=>document.querySelector('#play').textContent==='Pause run',null,{timeout:10000});
  await page.getByRole('button',{name:'Historical',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#scene').contentWindow.__uitaFrame?.mode==='historical',null,{timeout:10000});
  const read=async()=>await (await page.request.get(origin+`/api/v2/runs/${run.id}`)).json();
  const before=await read();
  await page.waitForTimeout(1500);
  const after=await read();
  if(after.state.clock<=before.state.clock||after.status!=='running')throw Error('History browsing paused worker');
  await page.getByRole('button',{name:'Simulation',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#scene').contentWindow.__uitaFrame?.mode==='simulation',null,{timeout:10000});
  if(new URL(page.url()).searchParams.get('run')!==run.id)throw Error('Live identity lost');
  await page.locator('#play').click();
  return {passed:true,workerAdvanced:after.state.clock-before.state.clock};
}
