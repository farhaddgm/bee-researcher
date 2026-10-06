import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base=process.env.BEE_ADMIN_URL;
const username=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if(!base||!username||!password)throw Error('Diagnostics E2E requires an isolated URL and credentials.');
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
page.setDefaultTimeout(12000);
const errors=[];page.on('pageerror',error=>errors.push(error.message));
let quota=true, reads=0;
const articles=Array.from({length:53},(_,index)=>({id:`fixture-${index}`,title:`Original article ${index}`,source_name:'Original publisher',source_url:`https://example.org/${index}`,relevance_state:index===0?'pending':index%2?'selected':'rejected',relevance_score:index%2?.93:.04,relevance_threshold:.7,relevance_confidence:.9,relevance_topic:'AI',relevance_reason:'Original decision rationale',relevance_evidence:['Original quoted evidence']}));
const json=(route,value)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(value)});
await page.route(/\/operations\/status(?:\?.*)?$/,route=>{
  reads++;return json(route,{assistant_id:'fixture',model:'gpt-6-luna',timezone:'Pacific/Honolulu',pending_ai_articles:17,blockers:quota?['provider_quota_exhausted']:[],provider:{state:quota?'blocked':'last_attempt_succeeded',code:quota?'provider_quota_exhausted':null,observed_at:new Date().toISOString()},budgets:{relevance_model:{used_requests:2,request_cap:10},analysis_model:{used_requests:1,request_cap:5}}});
});
await page.route(/\/publications\/relevance-assessments(?:\?.*)?$/,route=>{
  const url=new URL(route.request().url()),offset=Number(url.searchParams.get('offset')||0),q=url.searchParams.get('query')||'',state=url.searchParams.get('state');
  const filtered=articles.filter(row=>(!q||row.title.includes(q))&&(!state||row.relevance_state===state));
  return json(route,{articles:filtered.slice(offset,offset+25),total:filtered.length,counts:{pending:1,selected:26,rejected:26,borderline:0},window_capped:false,no_external_request:true});
});
try{
  await page.goto(new URL("/admin/login-up",base).href,{waitUntil:'domcontentloaded'});
  await page.locator('#loginUser').fill(username);await page.locator('#loginPass').fill(password);await page.locator('#loginSubmit').click();
  await page.waitForFunction(()=>window.__researchBeeState?.currentUser?.username);
  await page.evaluate(()=>window.setView('overview'));
  await page.waitForFunction(()=>document.querySelector('[data-product-health]')?.textContent.includes('gpt-6-luna'));
  for(const language of ['en','fa','tr','ar','es','it','de','fr']){
    await page.evaluate(language=>window.setLanguage(language),language);
    const panel=page.locator('#view-overview [data-product-health]');
    const text=await panel.innerText();assert(text.includes('gpt-6-luna'));
    if(!['fa','ar'].includes(language))assert(!/[\u0600-\u06ff]/.test(text),`Persian leaked into ${language} status`);
    assert.equal(await panel.getAttribute('class'),'product-health needs-attention');
  }
  quota=false;await page.evaluate(()=>window.__beeProductRefresh());
  await page.waitForFunction(()=>!document.querySelector('#view-overview [data-product-health]')?.classList.contains('needs-attention'));
  await page.evaluate(()=>{window.setLanguage('en');window.setView('content');});
  await page.locator('#productTriage summary').click();
  await page.waitForFunction(()=>document.querySelectorAll('.product-triage-row').length===25);
  assert.equal(await page.locator('[data-triage-page]').count(),3);
  await page.locator('[data-triage-page="1"]').click();
  await page.waitForFunction(()=>document.querySelector('.product-triage-row')?.textContent.includes('Original article 25'));
  await page.locator('#triageSearch').fill('Original article 51');await page.locator('#triageSearch').press('Enter');
  await page.waitForFunction(()=>document.querySelectorAll('.product-triage-row').length===1);
  await page.locator('[data-triage-detail]').click();
  await page.waitForFunction(()=>document.querySelector('#modalRoot [role="dialog"]'));
  assert.match(await page.locator('.product-assessment-detail').innerText(),/Original decision rationale/);
  assert.match(await page.locator('.product-assessment-detail').innerText(),/Original quoted evidence/);
  assert.equal(await page.locator('#modalRoot .modal-foot button').count(),1);
  await page.keyboard.press('Escape');await page.waitForFunction(()=>document.getElementById('modalRoot').classList.contains('hidden'));
  await page.waitForFunction(()=>document.activeElement===document.querySelector('[data-triage-detail]'));
  assert(await page.locator('[data-triage-detail]').evaluate(node=>document.activeElement===node),'Dialog did not restore focus');
  await page.locator('#triageSearch').fill('');await page.locator('#triageFilter').selectOption('pending');
  await page.waitForFunction(()=>document.querySelectorAll('.product-triage-row').length===1&&document.querySelector('.product-triage-row')?.textContent.includes('Original article 0'));
  await page.locator('[data-triage-detail]').click();
  assert.match(await page.locator('.product-assessment-detail').innerText(),/cannot be published/);
  assert.equal(await page.locator('.product-assessment-detail blockquote').count(),0,'Pending decision masquerades as verified AI evidence');
  await page.keyboard.press('Escape');
  for(const language of ['fa','ar','tr','it','es','de','fr','en']){
    await page.evaluate(language=>window.setLanguage(language),language);
    assert.equal(await page.locator('.product-triage-row h4').innerText(),'Original article 0','UX translation changed original article');
    const text=await page.locator('.product-triage-body').innerText();
    if(!['fa','ar'].includes(language))assert(!/[\u0600-\u06ff]/.test(text),`Persian leaked into ${language} triage`);
  }
  for(const width of [1920,1024,390]){
    await page.setViewportSize({width,height:1000});
    const rect=await page.locator('#productTriage').boundingBox();assert(rect.width>0&&rect.width<=width,`Triage overflows at ${width}`);
    assert(await page.locator('#triageSearch').evaluate(node=>node.scrollWidth<=node.clientWidth+2));
  }
  const requestsBefore=reads;await page.waitForTimeout(1800);assert.equal(reads,requestsBefore,'Diagnostics unexpectedly polls');
  await page.route(/\/metrics(?:\?.*)?$/,route=>json(route,{scope:new URL(route.request().url()).searchParams.get('assistant_id')}));
  const scopes=await page.evaluate(async()=>{
    const saved=window.__researchBeeState.assistantId;
    try{
      window.__researchBeeState.assistantId='00000000-0000-4000-8000-000000000001';
      const first=await window.req('/metrics');
      window.__researchBeeState.assistantId='00000000-0000-4000-8000-000000000002';
      const second=await window.req('/metrics');
      return [first.scope,second.scope];
    }finally{window.__researchBeeState.assistantId=saved;}
  });
  assert.deepEqual(scopes,['00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000002'],'Short read cache leaked between rapidly switched workspaces');
  assert.deepEqual(errors,[]);
  console.log('Diagnostics browser passed: honest quota recovery, 8 locales, original prose isolation, search/decision filters/numbered pages, pending fail-closed, keyboard focus, 3 viewports, no polling.');
}finally{await browser.close();}
