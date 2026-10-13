/* Real isolated HTTP/PostgreSQL/worker and browser, synthetic providers only. */
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import AxeBuilder from '@axe-core/playwright';
const base=process.env.BEE_CHAT_TEST_URL;
if(!base||process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test'||new URL(base).hostname!=='127.0.0.1')throw Error('Isolated loopback test fixture required');
const browser=await chromium.launch({headless:true}),contexts=[],errors=[],requests=[];let stage='boot';
const aid='10000000-0000-4000-8000-000000000004',pid='60000000-0000-4000-8000-000000000001';
async function page(){const context=await browser.newContext({viewport:{width:1440,height:1100},reducedMotion:'reduce'});contexts.push(context);const page=await context.newPage();page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.request().method()!=='GET')requests.push({path:new URL(r.url()).pathname,status:r.status()})});page.on('dialog',d=>d.accept());return page}
async function api(page,path,method='GET',body){return page.evaluate(async({path,method,body})=>{const prefix=path.startsWith('/admin')?'research_bee_admin_csrf=':'research_bee_user_csrf=';const csrf=document.cookie.split('; ').find(v=>v.startsWith(prefix))?.split('=').slice(1).join('=')||'';const r=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf)},...(body?{body:JSON.stringify(body)}:{})});return {status:r.status,data:await r.json().catch(()=>({}))}},{path,method,body})}
async function login(page,name,admin=false){await page.goto(base+(admin?'/admin/login-up':'/user/login-up'));await page.locator(admin?'#loginUser':'#username').fill(name);await page.locator(admin?'#loginPass':'#password').fill('synthetic violet herons cross mountain lakes');await page.locator(admin?'#loginSubmit':'#loginButton').click();await page.locator('#app:not(.hidden)').waitFor();await locale(page,'en')}
async function locale(page,value){
  await page.evaluate(value=>{if(typeof window.setLanguage==='function')window.setLanguage(value);else{document.documentElement.lang=value;document.documentElement.dir=['fa','ar'].includes(value)?'rtl':'ltr'}},value);
  await page.waitForFunction(value=>document.documentElement.lang===value&&!document.documentElement.classList.contains('locale-switching'),value);
  await page.waitForTimeout(80);
}
try{
  for(let attempt=0;attempt<60;attempt++){try{const response=await fetch(base+'/health');if(response.ok)break}catch{}if(attempt===59)throw Error('Synthetic fixture did not start');await new Promise(r=>setTimeout(r,500))}
  const owner=await page(),reader=await page(),other=await page();await login(owner,'chat-owner',true);await login(reader,'lens-reader');await login(other,'chat-admin',true);
  const original=(await api(owner,'/admin/api/analysis-lenses')).data.policy;
  assert.equal((await api(other,'/admin/api/analysis-lenses')).status,403);
  await owner.evaluate(()=>window.setView('settings'));await owner.locator('#analysisLensesAdmin').waitFor();
  const policyWrite=await api(owner,'/admin/api/analysis-lenses/policy','PUT',{...original,enabled:true});assert.equal(policyWrite.status,200);
  const catalog=(await api(reader,'/user/api/analysis-lenses?assistant_id='+aid+'&language=en')).data;assert.equal(catalog.lenses.length,4);
  const countBefore=(await api(owner,'/admin/api/news-chat/usage')).data.requests.length;
  await reader.locator(`.news-card[data-news-id="${pid}"] [data-action=open]`).click();await reader.locator('#readerAnalysisLenses:not([hidden])').waitFor();
  assert.equal((await api(owner,'/admin/api/news-chat/usage')).data.requests.length,countBefore,'Opening incurred AI cost');
  const panel=reader.locator('#readerAnalysisLenses'),scope=panel.locator('.lens-controls select').nth(0),lens=panel.locator('.lens-controls select').nth(1);
  let paidRuns=0;
  // Both scopes, every lens, continued chat, no automatic paid selection.
  for(const row of catalog.lenses){
    await lens.selectOption(row.id);
    for(const kind of ['focused','contextual']){
      stage=row.key+'/'+kind;console.log('Lens browser scenario:',stage);
      await scope.selectOption(kind);
      if(kind==='contextual'){await panel.locator('.lens-source input').first().waitFor();await panel.locator('.lens-source input').first().check()}
      const before=(await api(owner,'/admin/api/news-chat/usage')).data.requests.length;
      // Production deliberately caps one reader at five requests/minute.
      // Pace the matrix; do not bypass that admission rule in the fixture.
      if(paidRuns===5)await new Promise(r=>setTimeout(r,61000));
      const sent=reader.waitForRequest(r=>r.url().endsWith('/messages')&&r.method()==='POST');await panel.locator('[data-lens-key=analyze]').click();const request=await sent;assert.equal(request.postDataJSON().intent,'lens_analysis');assert(request.postDataJSON().analysis_version);
      paidRuns++;
      await reader.waitForFunction(()=>document.querySelector('.chat-turn:last-child .chat-status')?.textContent===window.BeeNewsChatI18n.t('completed'));
      const answer=await reader.locator('.chat-turn .chat-answer').last().innerText();assert(answer.length>40);assert(!answer.trim().startsWith('{'),'Raw JSON leaked into UI');
      assert.equal((await api(owner,'/admin/api/news-chat/usage')).data.requests.length,before+1);
    }
  }
  await reader.locator('#news-chat-question').fill('Explain the uncertainty in this analysis.');await reader.locator('#newsChat [type=submit]').click();await reader.waitForFunction(()=>document.querySelectorAll('.chat-turn').length===2&&document.querySelector('.chat-turn:last-child .chat-status')?.textContent===window.BeeNewsChatI18n.t('completed'));
  const noPaidBefore=(await api(owner,'/admin/api/news-chat/usage')).data.requests.length;
  for(const lang of ['fa','en','tr','ar','es','it','de','fr']){
    await locale(reader,lang);await reader.waitForFunction(()=>document.querySelector('#readerAnalysisLenses h3').textContent===window.BeeLensI18n.t('title'));
    for(const width of [360,768,1280,1920]){await reader.setViewportSize({width,height:1100});if(width<=900)await reader.locator('.chat-tabs [data-tab=chat]').click();assert(await panel.evaluate(n=>n.scrollWidth<=n.clientWidth+2),`Lens overflow ${lang}/${width}`);assert(await reader.locator('#newsDialog').evaluate(n=>n.scrollWidth<=n.clientWidth+2),`Dialog overflow ${lang}/${width}`)}
  }
  assert.equal((await api(owner,'/admin/api/news-chat/usage')).data.requests.length,noPaidBefore,'Locale or viewport changes incurred AI cost');
  await reader.setViewportSize({width:1440,height:1100});await locale(reader,'en');
  const a11y=await new AxeBuilder({page:reader}).include('#readerAnalysisLenses').withRules(['label','button-name','select-name']).analyze();assert.deepEqual(a11y.violations,[]);
  await reader.locator('#readerAnalysisLenses .lens-info button').focus();assert(await reader.locator('#readerAnalysisLenses .lens-tip').isVisible());await reader.keyboard.press('Escape');assert(await reader.locator('#newsDialog').isVisible());assert.equal(await reader.locator('#readerAnalysisLenses .lens-info button').evaluate(n=>n===document.activeElement),true);assert.equal(await reader.locator('#readerAnalysisLenses .lens-tip').isVisible(),false);
  await reader.locator('#closeDialog').click();
  // Editing and live preview must work through the actual Owner form.
  await owner.locator('#analysisLensesAdmin .lens-owner-item').filter({hasText:'General'}).locator('button').first().click();
  const editor=owner.locator('.lens-owner-editor');const objective=editor.locator('[data-lens-label=objective]');await objective.fill((await objective.inputValue())+' Browser-tested clarification.');
  const saved=owner.waitForResponse(r=>r.url().includes('/draft')&&r.request().method()==='PUT');await editor.locator('[data-lens-key=saveDraft]').click();assert.equal((await saved).status(),200);
  await editor.locator('[data-lens-history] option[value="2"]').waitFor({state:'attached'});
  await editor.locator('.lens-preview-controls select').nth(0).selectOption(aid);await editor.locator('.lens-preview-controls select').nth(1).locator(`option[value="${pid}"]`).waitFor({state:'attached'});
  const previewResponse=owner.waitForResponse(r=>/\/preview$/.test(r.url())&&r.request().method()==='POST');await editor.locator('[data-lens-key=preview]').click();const preview=await previewResponse;assert.equal(preview.status(),202,await preview.text());const previewData=await preview.json();
  await owner.waitForFunction(()=>document.querySelector('#analysisLensesAdmin .lens-status')?.textContent===window.BeeLensI18n.t('complete'));
  assert.equal((await api(reader,'/user/api/chat-generations/'+previewData.generation.id+'/events')).status,404,'Owner preview leaked to User');
  stage='owner/comparison';const beforeComparison=(await api(owner,'/admin/api/news-chat/usage')).data.requests.length;
  await editor.locator('[data-lens-key=compareRevision]').click();
  await owner.waitForFunction(()=>document.querySelector('#analysisLensesAdmin .lens-status')?.textContent===window.BeeLensI18n.t('complete'));
  assert.equal((await api(owner,'/admin/api/news-chat/usage')).data.requests.length,beforeComparison+2,'Revision comparison must be exactly two explicitly requested generations');
  assert.equal(await editor.locator('.lens-preview-result').nth(0).isVisible(),true);
  const approve=editor.locator('[data-lens-key=approved] input');await approve.check();assert.equal(await editor.locator('[data-lens-key=publish]').isEnabled(),true,'Approval marked the definition dirty');
  const published=owner.waitForResponse(r=>r.url().endsWith('/publish')&&r.request().method()==='POST');await editor.locator('[data-lens-key=publish]').click();assert.equal((await published).status(),200,await (await published).text());
  for(const lang of ['fa','en','tr','ar','es','it','de','fr']){await locale(owner,lang);await owner.waitForFunction(()=>document.querySelector('#analysisLensesAdmin h3').textContent===window.BeeLensI18n.t('title'));assert(await owner.locator('#analysisLensesAdmin').evaluate(n=>n.scrollWidth<=n.clientWidth+2));
    const mismatches=await owner.locator('#analysisLensesAdmin').evaluate(panel=>{const clean=text=>String(text).replace(/[۰-۹٠-٩]/g,v=>'۰۱۲۳۴۵۶۷۸۹'.includes(v)?String('۰۱۲۳۴۵۶۷۸۹'.indexOf(v)):String('٠١٢٣٤٥٦٧٨٩'.indexOf(v))).trim();return [...panel.querySelectorAll('[data-lens-key]')].filter(n=>n.dataset.lensKey&&clean(n.firstChild?.textContent)!==clean(window.BeeLensI18n.t(n.dataset.lensKey))).map(n=>n.dataset.lensKey)});
    assert.deepEqual(mismatches,[],'Legacy translation rewrote scoped lens copy in '+lang);
    if(process.env.BEE_CHAT_ARTIFACT_DIR&&['fa','en'].includes(lang))await owner.screenshot({path:process.env.BEE_CHAT_ARTIFACT_DIR+'/lens-owner-'+lang+'.png'})}
  await owner.evaluate(()=>window.setView('assistants'));assert.equal(await owner.locator('#analysisLensesAdmin').isVisible(),false,'Lens panel leaked outside Settings');
  const current=(await api(owner,'/admin/api/analysis-lenses')).data.policy;assert.equal((await api(owner,'/admin/api/analysis-lenses/policy','PUT',{...current,enabled:original.enabled,default_key:original.default_key})).status,200);
  assert.deepEqual(errors,[]);console.log('Analysis lenses: both scopes, four lenses, actual Owner draft/preview/publish, isolation, eight locales, four widths and keyboard checks passed.');
}catch(e){console.error('Lens gate failed:',stage,e.message,JSON.stringify({errors,requests:requests.slice(-12)}));for(const [index,c] of contexts.entries())for(const p of c.pages()){try{console.error('Fixture UI status:',index,await p.locator('.chat-error,.lens-status').allTextContents());if(process.env.BEE_CHAT_ARTIFACT_DIR)await p.screenshot({path:process.env.BEE_CHAT_ARTIFACT_DIR+'/lens-failure-'+index+'.png',fullPage:true})}catch{}}throw e}finally{for(const context of contexts)await context.close();await browser.close()}
