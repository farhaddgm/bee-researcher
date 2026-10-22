import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {refreshAdmin} from './admin_browser_helpers.mjs';

const base=process.env.BEE_ADMIN_URL;
const username=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if(!base||!username||!password||process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test')throw Error('Isolated lifecycle fixture required');
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',error=>errors.push(error.message));page.setDefaultTimeout(15000);
try{
  await page.goto(new URL('/admin/login-up',base).href,{waitUntil:'domcontentloaded'});
  await page.locator('#loginUser').fill(username);await page.locator('#loginPass').fill(password);
  await page.locator('#loginSubmit').click();await page.locator('#app:not(.hidden)').waitFor();
  // Do not repair first paint by refreshing first: a newly authorized default
  // workspace must hydrate model controls during the original login load.
  await page.waitForFunction(()=>state.runtimeSettings?.assistant_id===state.assistantId&&document.getElementById('analysisModel')?.disabled===false);
  await refreshAdmin(page,{collectGarbage:true});
  const expected=['product','backoffice','contenter','research-context','analysis-tools','model-settings','support','locale-reconcile','digits'];
  const initial=await page.evaluate(()=>window.BeeAdminLifecycle.diagnostics());
  for(const owner of expected)assert(initial.owners.includes(owner),`Missing lifecycle owner ${owner}`);
  const ownerCount=initial.owners.length;
  await page.evaluate(()=>{window.__researchBeeReleaseLocale();window.setLanguage('en');});
  await page.waitForFunction(()=>!document.documentElement.classList.contains('locale-pending')&&!document.documentElement.classList.contains('locale-switching'));
  assert.equal(await page.evaluate(()=>{window.__researchBeeReleaseLocale();return document.documentElement.classList.contains('locale-pending');}),false,'Late hydration re-hid the visible shell');
  for(const language of ['fa','en','tr','ar','es','it','de','fr']){
    await page.evaluate(language=>window.setLanguage(language),language);
    await page.waitForFunction(language=>document.documentElement.lang===language,language);
    await page.waitForFunction(()=>!document.documentElement.classList.contains('locale-pending')&&!document.documentElement.classList.contains('locale-switching'));
    for(const view of ['assistants','sources','topics','support','settings','businesses','content']){
      await page.evaluate(view=>window.setView(view),view);
      await page.locator('#view-'+view+'.active').waitFor();
      const state=await page.evaluate(()=>({
        supportRoots:document.querySelectorAll('#view-support').length,
        forms:document.querySelectorAll('#view-support [data-support-v4-form]').length,
        legacyStyles:document.querySelectorAll('#support-v2-style').length,
        supportActive:document.getElementById('view-support').classList.contains('active'),
        active:document.querySelector('.view.active')?.id,
        diagnostics:window.BeeAdminLifecycle.diagnostics()}));
      assert.equal(state.supportRoots,1);assert.equal(state.forms,1);assert.equal(state.legacyStyles,0);
      assert.equal(state.supportActive,view==='support');assert.equal(state.active,'view-'+view);
      assert.equal(state.diagnostics.owners.length,ownerCount,'Hooks accumulated after navigation');
      assert.equal(state.diagnostics.hook_errors,0,JSON.stringify(state.diagnostics.samples.filter(row=>row.outcome==='error')));
    }
    await refreshAdmin(page,{collectGarbage:true});
  }
  await page.waitForFunction(()=>window.BeeAdminLifecycle.diagnostics().active_refreshes===0);
  const final=await page.evaluate(()=>window.BeeAdminLifecycle.diagnostics());
  assert.equal(final.hook_errors,0);assert(final.samples.length<=100);assert.equal(final.owners.length,ownerCount);
  assert.deepEqual(errors,[]);
  console.log(`Admin lifecycle browser passed: ${ownerCount} registered owners, 8 locales × 7 views, one Support controller, forced GC, no accumulated hooks/errors and bounded profiling.`);
}finally{await browser.close();}
