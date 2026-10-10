import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';

const base=process.env.BEE_ADMIN_URL;
const username=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if(!base||!username||!password||process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test')throw Error('News regression E2E requires an isolated test app.');
const fixtures=Array.from({length:42},(_,i)=>({id:`news-fixture-${i}`,status:'preview',
 message_text:`Original headline ${i}: پژوهش تازه دربارهٔ هوش مصنوعی، بازار و فناوری — ${'longword'.repeat(12)}`,
 source_name:'Original publisher '+('source'.repeat(15)),relevance_state:['pending','selected','borderline','rejected'][i%4],
 review_only:i%4!==1,publishable:i%4===1,can_approve:i%4===2,analysis_ready:true,
 relevance_score:i%4===0?null:.8,relevance_threshold:.75,created_at:'2026-10-10T12:00:00Z'}));
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
page.setDefaultTimeout(15000);
const json=(route,value)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(value)});
await page.route(/\/publications(?:\?.*)?$/,route=>json(route,{publications:fixtures}));
let bulkRequest=null;
await page.route(/\/publications\/bulk$/,route=>{
 bulkRequest=route.request().postDataJSON();
 fixtures.filter(x=>bulkRequest.ids.includes(x.id)).forEach(x=>{x.status='rejected';});
 return json(route,{status:'completed'});
});
try{
 await page.goto(new URL('/admin/login-up',base).href);
 await page.locator('#loginUser').fill(username);await page.locator('#loginPass').fill(password);await page.locator('#loginSubmit').click();
 await page.waitForFunction(()=>window.__researchBeeState?.projectListReady);
 assert.equal((await (await page.request.get(new URL('/meta',base).href)).json()).environment,'test');
 await page.evaluate(()=>window.loadAll());
 await page.evaluate(()=>{window.setView('content');document.getElementById('publicationStatus').value='';window.renderPublications();});
 await page.locator('#publicationRows tr[data-publication-row]').first().waitFor();
 for(const language of ['fa','en','ar','tr','es','it','de','fr']){
  await page.evaluate(language=>window.setLanguage(language),language);
  for(const width of [1440,900,390,320]){
   await page.setViewportSize({width,height:1000});
   for(const theme of ['honey','dark']){
    await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;window.renderPublications();},theme);
    const geometry=await page.locator('#publicationRows').evaluate(body=>{
     const headers=[...body.closest('table').tHead.rows[0].cells].map(n=>n.getBoundingClientRect());
     return [...body.rows].map(row=>({count:row.cells.length,
      aligned:[...row.cells].every((cell,i)=>Math.abs(cell.getBoundingClientRect().x-headers[i].x)<2&&Math.abs(cell.getBoundingClientRect().width-headers[i].width)<2),
      titleWidth:row.querySelector('.publication-news-cell>.btn')?.getBoundingClientRect().width,
      contained:[...row.querySelectorAll('.publication-news-cell>.btn,.status')].every(n=>{const a=n.getBoundingClientRect(),b=n.closest('td').getBoundingClientRect();return a.left>=b.left&&a.right<=b.right&&a.top>=b.top&&a.bottom<=b.bottom;}),
      checkbox:row.querySelectorAll('input[data-publication-id]').length}));
    });
    assert.equal(geometry.length,20);
    assert(geometry.every(x=>x.count===7&&x.aligned&&x.titleWidth>150&&x.contained&&x.checkbox===1),`${language}/${width}/${theme}: ${JSON.stringify(geometry)}`);
    assert.equal(await page.locator('#bulkNewsBar').count(),1,'Repeated renders duplicated the bulk toolbar');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'Table escapes its scroll region');
   }
  }
 }
 await page.setViewportSize({width:1440,height:1000});
 await page.evaluate(()=>{window.setLanguage('en');document.documentElement.dataset.theme='honey';});
 const title=page.locator('#publicationRows .publication-news-cell>.btn').first();
 await title.scrollIntoViewIfNeeded();
 const box=await title.boundingBox();await page.mouse.click(box.x+box.width/2,box.y+box.height/2);
 await page.locator('#articleDrawer.open').waitFor();assert((await page.locator('#articleDetail').innerText()).includes('Original headline 0'));
 await page.locator('#closeDrawer').click();
 const all=page.locator('[data-publication-select-all] input');
 await page.locator('#publicationRows input[data-publication-id]').first().check();
 assert(await all.evaluate(n=>n.indeterminate));
 assert(await page.locator('#bulkNewsBar').evaluate(n=>n.classList.contains('active')));
 await all.check();assert.equal(await page.locator('#publicationRows input:checked').count(),20);
 await page.locator('[data-publication-page="next"]').click();
 assert.equal(await page.locator('#publicationRows input:checked').count(),0);assert(!(await all.isChecked()));
 await page.locator('[data-publication-page="prev"]').click();assert.equal(await page.locator('#publicationRows input:checked').count(),20);
 await all.uncheck();assert.equal(await page.locator('#publicationRows input:checked').count(),0);
 await page.locator('#publicationRows input').first().check();
 await page.evaluate(()=>{
  const saved=state.assistantId;state.assistantId='synthetic-other-project';state.lastBulk={ids:['news-fixture-0'],at:Date.now()};
  window.renderPublications();state.assistantId=saved;window.renderPublications();
 });
 assert.equal(await page.locator('#publicationRows input:checked').count(),0);
 assert.equal(await page.evaluate(()=>state.lastBulk),null,'Undo carried into a different project');
 await page.locator('[data-publication-page="next"]').click();
 await page.locator('#publicationSearch').fill('Original headline 41:');await page.locator('#publicationFilterBtn').click();
 assert.equal(await page.locator('#publicationRows tr').count(),1);assert((await title.innerText()).includes('Original headline 41'));
 await page.locator('#publicationSearch').fill('No such fixture');await page.locator('#publicationFilterBtn').click();
 assert.equal(await page.locator('#publicationRows td[colspan]').getAttribute('colspan'),'7');assert(await all.isDisabled());
 await page.locator('#publicationSearch').fill('');await page.locator('#publicationFilterBtn').click();
 await page.locator('#publicationRows input').first().check();
 page.once('dialog',d=>d.accept());await page.locator('#bulkRejectBtn').click();
 await page.waitForFunction(()=>!document.querySelector('#bulkNewsBar')?.classList.contains('active'));
 assert.deepEqual(bulkRequest,{ids:['news-fixture-0'],action:'reject',label:null});
 await page.waitForFunction(()=>state.publications[0]?.status==='rejected');
 assert.equal(await page.locator('#bulkNewsBar').count(),1);

 // A response for the previous project must not install its undo IDs in
 // the project selected while that request was in flight.
 let releaseBulk,requestStarted;
 const held=new Promise(resolve=>{releaseBulk=resolve;});
 const started=new Promise(resolve=>{requestStarted=resolve;});
 await page.route(/\/publications\/bulk$/,async route=>{requestStarted();await held;await json(route,{});});
 const originalProject=await page.evaluate(()=>state.assistantId);
 await page.locator('#publicationRows input').nth(1).check();
 page.once('dialog',d=>d.accept());await page.locator('#bulkRejectBtn').click();await started;
 await page.evaluate(()=>{state.assistantId='synthetic-inflight-project';window.renderPublications();});
 const finished=page.waitForResponse(r=>r.url().endsWith('/publications/bulk'));
 releaseBulk();await finished;await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>state.lastBulk),null,'An old project response populated the new project undo state');
 await page.evaluate(id=>{state.assistantId=id;window.renderPublications();},originalProject);

 // Exercise the active/inactive business action through the CSP dispatcher.
 let activeBusiness=991,toggleRequest=null;
 await page.route(/\/admin\/api\/assistants\/[^/]+\/businesses(?:\?.*)?$/,route=>json(route,{assistant_id:new URL(route.request().url()).pathname.split('/')[4],active_business_id:activeBusiness,businesses:[{id:991,business_name:'Synthetic business',description:'Isolated action test'}]}));
 await page.route(/\/admin\/api\/assistants\/[^/]+\/runtime-settings$/,route=>{
  if(route.request().method()==='PUT'){toggleRequest=route.request().postDataJSON();activeBusiness=toggleRequest.deactivate_business?null:toggleRequest.active_business_id;return json(route,{});}
  return json(route,{assistant_id:new URL(route.request().url()).pathname.split('/')[4]});
 });
 await page.evaluate(async()=>{window.setView('businesses');await window.refreshBusinessUi();});
 const toggle=page.locator('[data-business-toggle="991"]');
 const labels=await page.evaluate(()=>({activate:translatedCopy('فعال‌سازی'),deactivate:translatedCopy('غیرفعال‌سازی')}));
 await toggle.waitFor();assert.equal(await toggle.innerText(),labels.deactivate);
 page.once('dialog',d=>d.accept());await toggle.click();
 await page.waitForFunction(label=>document.querySelector('[data-business-toggle]')?.textContent===label,labels.activate);
 assert.deepEqual(toggleRequest,{deactivate_business:true});
 await toggle.click();await page.waitForFunction(label=>document.querySelector('[data-business-toggle]')?.textContent===label,labels.deactivate);
 assert.deepEqual(toggleRequest,{active_business_id:991});
 assert.equal(await page.locator('#view-businesses [onclick]').count(),0);
 if(process.env.CAPTURE_OUTPUT){
  await page.evaluate(()=>{window.setLanguage('fa');window.setView('content');});
  await fs.mkdir(process.env.CAPTURE_OUTPUT,{recursive:true});
  await page.screenshot({path:path.join(process.env.CAPTURE_OUTPUT,'news-table-fa-after.png'),fullPage:true});
 }
 assert.deepEqual(errors,[]);
 console.log('News/action regressions passed: 8 locales × 4 widths × 2 themes, seven aligned columns, readable titles, real pointer clicks, bounded badges, one toolbar, select all/partial/pagination/filter/empty states, project isolation including delayed responses, bulk request and CSP-safe business deactivate/reactivate.');
}finally{await browser.close();}
