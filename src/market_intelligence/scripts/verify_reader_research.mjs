/* Real HTTP, PostgreSQL, worker and browser; isolated synthetic data only. */
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
const base=process.env.BEE_CHAT_TEST_URL;
if(process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test'||!base||new URL(base).hostname!=='127.0.0.1')throw Error('Isolated loopback fixture required');
const aid='10000000-0000-4000-8000-000000000003',otherAid='10000000-0000-4000-8000-000000000002';
const pids=Array.from({length:8},(_,i)=>'40000000-0000-4000-8000-00000000000'+(i+1));
const mid='50000000-0000-4000-8000-000000000001',peerMid='50000000-0000-4000-8000-000000000003';
const browser=await chromium.launch({headless:true}),ctx=await browser.newContext({viewport:{width:1440,height:1000}});
await ctx.addInitScript(()=>{window.__briefSpeech=[];window.SpeechSynthesisUtterance=class{constructor(text){this.text=text}};Object.defineProperty(window,'speechSynthesis',{value:{getVoices:()=>['fa','en','tr','ar','es','it','de','fr'].map(lang=>({lang:lang+'-XX'})),speak:u=>{window.__briefSpeech.push(u.text);setTimeout(()=>u.onend?.(),5)},cancel:()=>{}},configurable:true})});
const page=await ctx.newPage(),errors=[];page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
const peerCtx=await browser.newContext(),peer=await peerCtx.newPage();peer.on('pageerror',e=>errors.push(e.message));
async function api(target,path,method='GET',body){return target.evaluate(async({path,method,body})=>{const csrf=document.cookie.split('; ').find(c=>c.startsWith('research_bee_user_csrf='))?.split('=').slice(1).join('=');const r=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','x-csrf-token':decodeURIComponent(csrf||'')},...(body?{body:JSON.stringify(body)}:{})});return {status:r.status,data:await r.json().catch(()=>({}))}},{path,method,body})}
const endpoint=s=>'/user/api/assistants/'+aid+'/research/'+s;
async function login(target,user){await target.goto(base+'/user/login-up');await target.locator('#username').fill(user);await target.locator('#password').fill('synthetic violet herons cross mountain lakes');const response=target.waitForResponse(r=>r.url().endsWith('/user/api/login'));await target.locator('#loginButton').click();assert.equal((await response).status(),200);await target.locator('#app:not(.hidden)').waitFor();await target.locator('#assistantSelect').selectOption(aid);await target.evaluate(()=>{document.documentElement.lang='en';document.documentElement.dir='ltr'})}
const field=(form,key)=>form.locator('[data-research-field='+key+']');
async function tab(key){await page.locator('#research-tab-'+key).click();await page.locator('#research-view-'+key+':not([hidden])').waitFor()}
async function recordList(kind){return (await api(page,endpoint('records?kind='+kind))).data.records}
async function analyze(intent){const response=page.waitForResponse(r=>r.url().includes('/conversations/')&&r.url().endsWith('/messages')&&r.request().method()==='POST');await page.locator('[data-research-intent='+intent+']').click();const r=await response;assert.equal(r.status(),202,await r.text());const generation=await r.json();await page.waitForFunction(()=>document.querySelector('#researchOutput')?.textContent&&!document.querySelector('[data-research-intent=compare]').disabled);return generation}
try{
  for(let i=0;i<60;i++){try{if((await page.request.get(base+'/health')).ok())break}catch{}assert(i<59,'Isolated fixture did not become ready');await page.waitForTimeout(250)}
  await login(page,'research-reader');await login(peer,'research-peer');
  assert.equal((await api(page,'/user/api/assistants/'+otherAid+'/research/profile')).status,404);
  assert.equal((await api(page,'/user/api/conversations/'+peerMid+'/memory-reference')).status,404);
  const startBody={model_key:'openai:fixture-v1',source_ids:[pids[0],'20000000-0000-4000-8000-000000000002']};
  assert.equal((await api(page,'/user/api/publications/'+pids[0]+'/conversations','POST',startBody)).status,404);
  assert.equal((await api(page,'/user/api/publications/'+pids[0]+'/conversations','POST',{model_key:'openai:fixture-v1',source_ids:[pids[0]],memory_ids:[peerMid]})).status,404);
  assert.deepEqual(errors,[],'Initial reader script errors');
  await page.locator('#readerResearchDesk > summary').click();await page.locator('#readerResearchDesk[data-ready=true]').waitFor();
  assert.equal((await api(page,endpoint('feed'))).data.news.length,8);
  assert.equal((await api(page,endpoint('usage'))).data.requests_today,0);
  const daily=page.locator('#research-view-dailyBrief');assert(await daily.locator('.research-card').count()>=1);
  await daily.getByRole('button',{name:'Play brief',exact:true}).click();await page.waitForFunction(()=>window.__briefSpeech.length>0);
  assert.equal((await api(page,endpoint('usage'))).data.requests_today,0,'Daily playback created a paid request');
  await daily.getByRole('button',{name:'Pause',exact:true}).click();
  // Private profile survives reload, applies to the feed, and cannot overwrite stale revisions.
  await tab('attention');const preferences=page.locator('#research-view-attention form');
  await field(preferences,'interests').fill('battery');await field(preferences,'mutedTerms').fill('research 6');await field(preferences,'hideDuplicates').check();await field(preferences,'businessContext').fill('USER_BUSINESS_CANARY: synthetic battery workshop');
  const savedProfile=page.waitForResponse(r=>r.url().endsWith('/research/profile')&&r.request().method()==='PUT');await preferences.getByRole('button',{name:'Confirm and save',exact:true}).click();assert.equal((await savedProfile).status(),200);
  await page.waitForFunction(()=>!document.querySelector('#research-view-attention button[type=submit]').disabled);
  const profile=(await api(page,endpoint('profile'))).data;assert.equal(profile.version,1);assert.equal((await api(peer,endpoint('profile'))).data.business_context,'');
  assert.equal((await api(page,endpoint('profile'),'PUT',{...profile,version:0})).status,409);
  await tab('analyze');const selection=page.locator('#research-view-analyze');
  assert.equal(await selection.locator('[data-research-news="'+pids[5]+'"]').count(),0);
  await field(selection,'showHidden').check();assert.equal(await selection.locator('[data-research-news="'+pids[5]+'"]').count(),1);
  await selection.locator('[data-research-news="'+pids[0]+'"]').check();await selection.locator('[data-research-news="'+pids[1]+'"]').check();
  const comparison=await analyze('compare');assert(await page.locator('#researchOutput table').count()===1,'Comparison did not render a safe table');
  const compareMessages=(await api(page,'/user/api/conversations/'+comparison.conversation_id+'/messages')).data;
  assert.deepEqual(compareMessages.context.source_ids,pids.slice(0,2));assert.equal(compareMessages.context.memory_ids.length,0);
  assert(compareMessages.messages[0].citations.every(c=>pids.slice(0,2).includes(c.publication_id)));
  assert.equal((await recordList('action')).length,0);
  await page.locator('#research-view-analyze').getByRole('button',{name:'Draft action from discussion',exact:true}).click();await page.locator('#research-view-actions:not([hidden])').waitFor();
  const actionForm=page.locator('[data-research-form=action]');assert.equal(await field(actionForm,'title').inputValue(),'Review battery evidence');assert.equal(await field(actionForm,'dueDate').inputValue(),'');assert.equal((await recordList('action')).length,0,'Draft was automatically persisted');
  await field(actionForm,'assignee').fill('Synthetic reviewer');await field(actionForm,'dueDate').fill('2026-11-01');
  const savedAction=page.waitForResponse(r=>r.url().endsWith('/research/records')&&r.request().method()==='POST');await actionForm.getByRole('button',{name:'Confirm and save',exact:true}).click();assert.equal((await savedAction).status(),201);const action=(await recordList('action'))[0];assert.equal(action.attributes.assignee,'Synthetic reviewer');assert.equal(action.attributes.due_on,'2026-11-01');assert.equal((await api(peer,endpoint('records?kind=action'))).data.records.length,0);
  await tab('analyze');await selection.locator('details summary').filter({hasText:'Memory for this answer'}).click();await selection.locator('[data-research-memory="'+mid+'"]').check();await field(selection,'includeBusiness').check();await field(selection,'ask').fill('EXPECT_SELECTED_MEMORY EXPECT_BUSINESS');
  const impact=await analyze('impact');const impactData=(await api(page,'/user/api/conversations/'+impact.conversation_id+'/messages')).data;assert.deepEqual(impactData.context.memory_ids,[mid]);assert.equal(impactData.context.include_business,true);
  await selection.getByRole('button',{name:'Save conversation',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#readerResearchDesk .research-status').textContent===window.BeeNewsChatI18n.t('conversationSaved'));
  const memory=(await api(page,'/user/api/assistants/'+aid+'/memory?q=EXPECT_BUSINESS&model=openai%3Afixture-v1')).data;assert(memory.memories.some(m=>m.id===impact.conversation_id));
  assert.equal((await api(peer,'/user/api/conversations/'+impact.conversation_id+'/memory-reference')).status,404);
  await selection.getByRole('button',{name:'Decision journal',exact:true}).click();const decisionForm=page.locator('[data-research-form=decision]');await field(decisionForm,'title').fill('Review battery sourcing');await field(decisionForm,'rationale').fill('Need independent evidence');await field(decisionForm,'reviewDate').fill('2026-12-01');const decisionSave=page.waitForResponse(r=>r.url().endsWith('/research/records')&&r.request().method()==='POST');await decisionForm.getByRole('button',{name:'Confirm and save',exact:true}).click();assert.equal((await decisionSave).status(),201);assert.equal((await recordList('decision'))[0].attributes.review_on,'2026-12-01');
  await tab('analyze');await selection.getByRole('button',{name:'Share this result',exact:true}).click();const sharedForm=page.locator('[data-research-form=shared]');await field(sharedForm,'title').fill('Selected team finding');await field(sharedForm,'description').fill('EXPLICIT_SHARED_RESULT: only this selected text');const shareSave=page.waitForResponse(r=>r.url().endsWith('/research/records')&&r.request().method()==='POST');await sharedForm.getByRole('button',{name:'Confirm and save',exact:true}).click();assert.equal((await shareSave).status(),201);
  const shared=(await api(peer,endpoint('records?kind=shared'))).data.records[0];assert.equal(shared.body,'EXPLICIT_SHARED_RESULT: only this selected text');assert.equal(shared.conversation_id,null);assert.equal(shared.owned,false);assert.equal((await api(peer,endpoint('records/'+shared.id)+'?version='+shared.version,'DELETE')).status,404);
  await tab('tracking');for(const kind of ['topic','watch']){const form=page.locator('[data-research-form='+kind+']');await field(form,'title').fill('Track batteries '+kind);await field(form,'term').fill('battery');const stored=page.waitForResponse(r=>r.url().endsWith('/research/records')&&r.request().method()==='POST');await form.getByRole('button',{name:'Confirm and save',exact:true}).click();assert.equal((await stored).status(),201)}
  await page.locator('#research-view-tracking .research-card').first().getByRole('button',{name:'Show timeline',exact:true}).click();assert(await page.locator('.research-timeline .research-card').count()===8);
  await page.locator('#research-view-tracking .research-card').first().getByRole('button',{name:'Mark reviewed now',exact:true}).click();await page.waitForFunction(()=>[...document.querySelectorAll('#research-view-tracking .research-card p')].some(p=>p.textContent==='Since last review: 0'));
  await tab('trends');assert(await page.locator('#research-view-trends .research-card').count()>0);
  // Removing chosen context creates a new, independent answer.
  await tab('analyze');await selection.locator('[data-research-memory="'+mid+'"]').uncheck();await field(selection,'includeBusiness').uncheck();await field(selection,'ask').fill('EXPECT_NO_PRIVATE_CONTEXT');await analyze('verify');await analyze('timeline');
  await tab('personalUsage');await page.waitForFunction(()=>document.querySelectorAll('#research-view-personalUsage .research-card').length>3);const usage=(await api(page,endpoint('usage'))).data;assert.equal(usage.requests_today,5);assert(usage.remaining_requests>=0);assert(usage.models.length===3);const ownRequest=usage.requests.find(r=>r.status==='completed');assert.equal((await api(page,endpoint('usage/'+ownRequest.id+'/feedback'),'POST',{value:1})).status,200);assert.equal((await api(peer,endpoint('usage/'+ownRequest.id+'/feedback'),'POST',{value:1})).status,404);
  // Locale switches preserve drafts, project identity and keyboard focus.
  await tab('decisions');await field(decisionForm,'title').fill('Unsubmitted private draft');await field(decisionForm,'title').focus();
  for(const locale of ['fa','en','tr','ar','es','it','de','fr'])for(const width of [390,768,1440,1920]){await page.setViewportSize({width,height:1000});await page.evaluate(locale=>{document.documentElement.lang=locale;document.documentElement.dir=['fa','ar'].includes(locale)?'rtl':'ltr'},locale);await page.waitForTimeout(30);assert.equal(await field(decisionForm,'title').inputValue(),'Unsubmitted private draft');assert(await page.locator('#readerResearchDesk').evaluate(n=>n.scrollWidth<=n.clientWidth+2),'Desk overflow '+locale+'/'+width);assert.equal(await page.evaluate(()=>document.activeElement.dataset.researchField),'title')}
  const a11y=await new AxeBuilder({page}).include('#readerResearchDesk').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();assert.deepEqual(a11y.violations.filter(v=>['critical','serious'].includes(v.impact)).map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),[]);
  const proof=await api(page,endpoint('records?kind=shared'));assert.equal(proof.data.records.length,1);
  // Convert a real Discuss answer to an editable action; a peer's private
  // conversation and action stay private to that peer.
  await peer.locator('.news-card[data-news-id="'+pids[0]+'"] [data-action=open]').click();await peer.locator('#newsChat [type=submit]:not([disabled])').waitFor();await peer.locator('#news-chat-question').fill('Convert this published report to a proposed action');await peer.locator('#newsChat [type=submit]').click();await peer.waitForFunction(()=>document.querySelector('.chat-turn')&&document.querySelector('#newsChat [type=submit]')&&!document.querySelector('#newsChat [type=submit]').disabled);await peer.locator('#newsChat').getByRole('button',{name:'Actions',exact:true}).click();await peer.locator('#readerResearchDesk[data-ready=true]').waitFor();await peer.locator('#research-view-actions:not([hidden])').waitFor();assert((await field(peer.locator('[data-research-form=action]'),'description').inputValue()).includes('Synthetic answer'));assert.equal((await api(peer,endpoint('records?kind=action'))).data.records.length,0,'Discuss draft created an action without confirmation');
  if(process.env.BEE_CHAT_ARTIFACT_DIR){await mkdir(process.env.BEE_CHAT_ARTIFACT_DIR,{recursive:true});await page.evaluate(()=>{document.documentElement.lang='fa';document.documentElement.dir='rtl'});await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:join(process.env.BEE_CHAT_ARTIFACT_DIR,'research-desk-fa-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:1000});await page.screenshot({path:join(process.env.BEE_CHAT_ARTIFACT_DIR,'research-desk-fa-mobile.png'),fullPage:true})}
  assert.deepEqual(errors,[],'Browser runtime errors');
  console.log('Reader ideas 6–20 passed: real HTTP/SQL/worker, speech stubs, selective context, privacy/sharing, actions/decisions, tracking/trends, consumption, 8 locales × 4 widths and accessibility.');
}finally{await peerCtx.close();await ctx.close();await browser.close()}
