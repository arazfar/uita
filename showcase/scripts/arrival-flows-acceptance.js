async page => {
  const origin=new URL(page.url()).origin;
  await page.unrouteAll();await page.setViewportSize({width:1440,height:900});await page.goto(origin);
  await page.waitForFunction(()=>document.querySelector('#scene').contentWindow.__uitaFrame?.source_id==='arrival-flows-v1');
  const opening=await page.evaluate(()=>document.querySelector('#scene').contentWindow.__uitaFrame);
  const families=[...new Set(opening.aircraft.filter(a=>a.status==='approach').map(a=>a.route?.id))];
  if(families.length<2)throw Error('Opening lacks distinct route families');
  await page.locator('#arrivals-queue [data-aircraft]').first().click();
  await page.waitForTimeout(600);
  await page.screenshot({path:'output/playwright/arrival-flows-desktop.png'});
  const card=await page.frameLocator('#scene').locator('#fcGrid').innerText();
  if(!card.toLowerCase().includes('route remaining'))throw Error('Route detail unavailable');
  await page.getByRole('button',{name:'Tower cab',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('iframe:not([hidden])').contentWindow.__uitaFrame?.aircraft.some(a=>a.route));
  await page.screenshot({path:'output/playwright/arrival-flows-tower.png'});
  await page.locator('[data-camera=dashboard]').click();
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);
  await page.screenshot({path:'output/playwright/arrival-flows-mobile.png'});
  await page.route('**/api/v2/**',r=>r.abort());await page.waitForTimeout(1500);
  const retained=await page.evaluate(()=>!!document.querySelector('#scene').contentWindow.__uitaFrame);
  await page.unrouteAll();await page.reload();await page.waitForFunction(()=>document.querySelector('#scene').contentWindow.__uitaFrame?.source_id==='arrival-flows-v1');
  await page.frameLocator('#scene').locator('canvas').first().evaluate(canvas=>canvas.dispatchEvent(new Event('webglcontextlost')));
  await page.waitForFunction(()=>document.querySelector('#render-status').textContent.includes('Renderer unavailable'));
  await page.locator('#drawer-toggle').click();
  if(await page.locator('#traffic tr').count()<6)throw Error('Renderer fallback lost traffic');
  return {rendererFallback:true,families,openingAirborne:opening.aircraft.filter(a=>a.status==='approach').length,routeCard:card,retained,reconnected:true};
}
