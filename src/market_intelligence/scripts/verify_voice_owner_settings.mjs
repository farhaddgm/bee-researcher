/* Real owner login, CSRF, key writes, SQL policy and eight-language rendering. */
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import {mkdir} from 'node:fs/promises';
const base=process.env.BEE_CHAT_TEST_URL;
if(process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test'||!base||new URL(base).hostname!=='127.0.0.1')throw Error('Synthetic loopback app required');
const browser=await chromium.launch({headless:true}),context=await browser.newContext({viewport:{width:1440,height:1100}}),page=await context.newPage(),errors=[];
page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
const secret='synthetic-elevenlabs-owner-key-never-real';
async function api(path,method='GET',body,csrf=true){return page.evaluate(async({path,method,body,csrf})=>{const token=document.cookie.split('; ').find(v=>v.startsWith('research_bee_admin_csrf='))?.split('=').slice(1).join('=');const revision=method==='PUT'&&path.endsWith('/news-voice/policy')?(await (await fetch(path)).json()).credential.revision:null;const response=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json',...(csrf?{'X-CSRF-Token':decodeURIComponent(token||'')}:{}),...(revision?{'X-Voice-Credential-Revision':revision}:{})},...(body?{body:JSON.stringify(body)}:{})});return {status:response.status,data:await response.json().catch(()=>({}))}},{path,method,body,csrf})}
async function language(locale){await page.evaluate(locale=>window.setLanguage(locale),locale);await page.waitForFunction(locale=>document.documentElement.lang===locale&&!document.documentElement.classList.contains('locale-switching'),locale);assert.equal(await page.evaluate(()=>window.BeeNewsChatI18n.lang()),locale);await page.waitForTimeout(80)}
try{
  await page.goto(base+'/admin/login-up');await page.locator('#loginUser').fill('chat-owner');await page.locator('#loginPass').fill('synthetic violet herons cross mountain lakes');await page.locator('#loginSubmit').click();await page.locator('#app:not(.hidden)').waitFor();
  await page.evaluate(()=>window.setView('settings'));await page.locator('#newsVoiceAdmin').waitFor();await language('en');
  assert.equal(await page.locator('#view-account #newsVoiceAdmin').count(),0);
  const original=(await api('/admin/api/news-voice/policy')).data.policy;
  const initial=(await api('/admin/api/news-voice/policy')).data.credential;
  assert(initial.editable);assert(!JSON.stringify(initial).includes(secret));
  // The app wraps browser fetch to inject CSRF. Use the independent request
  // client with the same cookies, not that wrapper, to test a missing header.
  const noCsrf=await context.request.put(base+'/admin/api/news-voice/credential',{data:{action:'set',expected_revision:initial.revision,api_key:secret}});
  assert.equal(noCsrf.status(),403,'Missing CSRF allowed secret update');
  let reads=0;page.on('request',r=>{if(r.url().endsWith('/admin/api/news-voice/policy')&&r.method()==='GET')reads++});
  const panel=await page.locator('#newsVoiceAdmin').elementHandle();const key=page.locator('#elevenlabs-api-key');await key.fill(secret);
  const input=page.locator('input[data-voice-label=voiceInputSeconds]');await input.fill('99');await input.focus();
  for(const locale of ['fa','en','tr','ar','es','it','de','fr'])for(const width of [390,768,1440,1920]){
    await page.setViewportSize({width,height:1100});await language(locale);
    assert(await panel.evaluate(n=>n.isConnected),'Locale replaced form');assert.equal(await input.inputValue(),'99');assert.equal(await key.inputValue(),secret);
    assert.equal(await page.locator('#newsVoiceAdmin h3').textContent(),await page.evaluate(locale=>window.BeeNewsChatI18n.words.voiceAdmin[window.BeeNewsChatI18n.languages.indexOf(locale)],locale));
    const layout=await panel.evaluate(n=>({width:n.clientWidth,scroll:n.scrollWidth,overflow:[...n.querySelectorAll('*')].filter(e=>e.scrollWidth>e.clientWidth+3&&e.clientWidth>0).slice(0,8).map(e=>({tag:e.tagName,cls:e.className,key:e.dataset.voiceLabel,width:e.clientWidth,scroll:e.scrollWidth}))}));
    assert(layout.scroll<=layout.width+2,'Owner voice panel overflow '+locale+'/'+width+' '+JSON.stringify(layout));
    assert.equal(await page.locator('#newsVoiceAdmin').getAttribute('data-owner-only'),'true');
  }
  assert.equal(reads,0,'Locale overwrote unsaved settings');await page.setViewportSize({width:1440,height:1100});await language('en');
  await page.locator('#newsVoiceAdmin [data-voice-key=voiceCheckConnection]').click();await page.getByText('Connection and catalog retrieval succeeded.',{exact:false}).first().waitFor();assert.equal(await key.inputValue(),secret,'Connection check saved or erased draft key');
  const saved=page.waitForResponse(r=>r.url().endsWith('/admin/api/news-voice/credential')&&r.request().method()==='PUT');await page.locator('#newsVoiceAdmin [data-voice-key=voiceSaveKey]').click();assert.equal((await saved).status(),200);assert.equal(await key.inputValue(),'');
  const credential=(await api('/admin/api/news-voice/policy')).data.credential;assert.equal(credential.source,'owner');assert(!JSON.stringify(credential).includes(secret));
  assert.equal(await page.locator('input[data-voice-label=voiceSttTested]').isChecked(),false,'Rotating key retained old capability approval');
  const account=await api('/admin/api/news-voice/account-check','POST',{});assert.equal(account.status,200);assert.equal(account.data.tier,'trial');assert.equal(account.data.zero_retention_verified,false);assert.equal(account.data.audio_tested,false);
  await page.locator('input[data-voice-label=voiceSttTested]').check();await page.locator('input[data-voice-label=voiceTested]').first().check();
  assert.equal((await api('/admin/api/news-voice/credential','PUT',{action:'set',expected_revision:initial.revision,api_key:secret+'-stale'})).status,409);
  await page.locator('#newsVoiceAdmin [data-voice-key=voiceLoadVoices]').click();await page.waitForFunction(()=>document.querySelector('#newsVoiceAdmin datalist option'));
  await page.locator('select[data-voice-label=voiceAccountVoice]').selectOption('syntheticvoice001');await page.locator('#newsVoiceAdmin [data-voice-key=voiceUseVoice]').click();
  assert.equal(await page.locator('input[data-voice-label=voiceId]').last().inputValue(),'syntheticvoice001');
  assert.equal(await page.locator('input[data-voice-label=voiceTested]').last().isChecked(),false);
  await page.locator('#newsVoiceAdmin .voice-owner-profile [data-voice-key=voiceRemoveProfile]').last().click();
  await page.locator('#newsVoiceAdmin [data-voice-key=voiceMoreVoices]').click();await page.waitForFunction(()=>document.querySelector('[data-voice-key=voiceMoreVoices]').disabled);
  const policySaved=page.waitForResponse(r=>r.url().endsWith('/admin/api/news-voice/policy')&&r.request().method()==='PUT');await page.locator('#elevenlabs-policy-form [type=submit]').click();assert.equal((await policySaved).status(),200);
  const policy=(await api('/admin/api/news-voice/policy')).data.policy;assert.equal(policy.max_input_seconds,99);assert.deepEqual(policy.voices,original.voices);assert(!JSON.stringify(policy).includes(secret));
  assert.equal((await api('/admin/api/news-voice/policy','PUT',original)).status,200);
  for(const locale of ['fa','en']){await language(locale);const result=await new AxeBuilder({page}).include('#newsVoiceAdmin').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();assert.deepEqual(result.violations.filter(v=>['critical','serious'].includes(v.impact)).map(v=>v.id),[],'Voice settings accessibility '+locale)}
  if(process.env.BEE_CHAT_ARTIFACT_DIR){await mkdir(process.env.BEE_CHAT_ARTIFACT_DIR,{recursive:true});await page.locator('#newsVoiceAdmin').screenshot({path:process.env.BEE_CHAT_ARTIFACT_DIR+'/elevenlabs-settings-fa.png'})}
  await language('en');const removed=page.waitForResponse(r=>r.url().endsWith('/admin/api/news-voice/credential')&&r.request().method()==='PUT');await page.locator('#newsVoiceAdmin [data-voice-key=voiceDeleteKey]').click();assert.equal((await removed).status(),200);
  let state=(await api('/admin/api/news-voice/policy')).data;assert.equal(state.configured,false);assert.equal(state.credential.source,'disabled');
  const restore=await api('/admin/api/news-voice/credential','PUT',{action:'set',expected_revision:state.credential.revision,api_key:secret});assert.equal(restore.status,200);
  assert.equal((await api('/admin/api/news-voice/policy','PUT',original)).status,200);
  await page.reload();await page.locator('#app:not(.hidden)').waitFor();await page.evaluate(()=>window.setView('settings'));await page.locator('#newsVoiceAdmin').waitFor();assert.equal(await page.locator('#elevenlabs-api-key').inputValue(),'');
  assert(!await page.locator('body').textContent().then(v=>v.includes(secret)),'Secret rendered in document');assert.deepEqual(errors,[]);
  const peerContext=await browser.newContext(),peer=await peerContext.newPage();
  await peer.goto(base+'/admin/login-up');await peer.locator('#loginUser').fill('voice-reader');await peer.locator('#loginPass').fill('synthetic violet herons cross mountain lakes');await peer.locator('#loginSubmit').click();await peer.locator('#app:not(.hidden)').waitFor();
  const denied=await peer.evaluate(async secret=>{const csrf=document.cookie.split('; ').find(v=>v.startsWith('research_bee_admin_csrf='))?.split('=').slice(1).join('=');const results=[];for(const [path,method,body] of [['policy','GET',null],['credential','PUT',{action:'set',expected_revision:'server',api_key:secret}],['connection-check','POST',{}],['account-check','POST',{}]]){const r=await fetch('/admin/api/news-voice/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},...(body?{body:JSON.stringify(body)}:{})});results.push({status:r.status,data:await r.json()})}return results},secret);
  assert(denied.every(r=>r.status===403&&r.data.detail==='owner_required'),'Non-owner had voice administration access');
  assert.equal(await peer.locator('#newsVoiceAdmin').count(),0);await peerContext.close();
  console.log('Owner voice settings: encrypted key CRUD, CSRF, revisions, catalog, real policy save, 8 languages x 4 widths and accessibility passed.');
}finally{await browser.close()}
