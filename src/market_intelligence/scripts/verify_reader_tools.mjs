/* Actual SQL/API/SSE and browser; synthetic actors and providers only. */
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import AxeBuilder from '@axe-core/playwright';
const base=process.env.BEE_CHAT_TEST_URL;
if(process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test'||!base||new URL(base).hostname!=='127.0.0.1')throw Error('Isolated loopback fixture required');
const aid='10000000-0000-4000-8000-000000000003',otherAid='10000000-0000-4000-8000-000000000001';
const pids=['40000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000002'];
const peerId='30000000-0000-4000-8000-000000000011';
const browser=await chromium.launch({headless:true}),ctx=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'Asia/Tehran'}),peerCtx=await browser.newContext({viewport:{width:1440,height:1000}}),outsiderCtx=await browser.newContext();
const page=await ctx.newPage(),peer=await peerCtx.newPage(),outsider=await outsiderCtx.newPage(),errors=[];
for(const p of [page,peer,outsider]){p.setDefaultTimeout(20000);p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept())}
async function api(p,path,method='GET',body){return p.evaluate(async({path,method,body})=>{const csrf=document.cookie.split('; ').find(c=>c.startsWith('research_bee_user_csrf='))?.split('=').slice(1).join('=');const r=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','x-csrf-token':decodeURIComponent(csrf||'')},...(body?{body:JSON.stringify(body)}:{})});return {status:r.status,data:await r.json().catch(()=>({}))}},{path,method,body})}
const endpoint=s=>'/user/api/assistants/'+aid+'/research/'+s;
const field=(form,key)=>form.locator('[data-tools-field='+key+']');
async function login(p,name,project=aid){await p.goto(base+'/user/login-up');await p.locator('#username').fill(name);await p.locator('#password').fill('synthetic violet herons cross mountain lakes');await p.locator('#loginButton').click();await p.locator('#app:not(.hidden)').waitFor();await p.locator('#assistantSelect').selectOption(project);await p.evaluate(()=>{document.documentElement.lang='en';document.documentElement.dir='ltr'})}
async function desk(p=page){await p.locator('#readerResearchDesk > summary').click();await p.locator('#readerResearchDesk[data-ready=true]').waitFor()}
async function tab(key,p=page){await p.locator('#research-tab-'+key).click();await p.locator('#research-view-'+key+':not([hidden])').waitFor()}
try{
  for(let n=0;n<80;n++){try{if((await page.request.get(base+'/health')).ok())break}catch{}assert(n<79);await page.waitForTimeout(250)}
  await login(page,'tools-reader');await login(peer,'tools-peer');await login(outsider,'chat-reader',otherAid);await desk();await desk(peer);
  assert.deepEqual(errors,[],'Initial reader tools runtime errors');
  assert.equal((await api(outsider,endpoint('expert-requests'))).status,404);
  assert.equal((await api(outsider,endpoint('corrections'))).status,404);
  const colleagues=(await api(page,endpoint('colleagues'))).data.colleagues;assert(colleagues.some(c=>c.id===peerId));assert(colleagues.every(c=>!('email' in c)));
  await tab('meetings');const meeting=page.locator('[data-tools-form=meeting]');await field(meeting,'title').fill('Synthetic product review');await field(meeting,'meetingObjective').fill('Decide which battery evidence needs validation');await field(meeting,'meetingMinutes').fill('45');await field(meeting,'meetingAt').fill('2026-10-13T10:00');
  for(const pid of pids)await meeting.locator('[data-tools-news="'+pid+'"]').check();
  let requests=(await api(page,endpoint('usage'))).data.requests_today;assert.equal(requests,0,'Opening initiated a paid call');
  const generated=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await meeting.getByRole('button',{name:'Generate an AI draft',exact:true}).click();const meetingResponse=await generated;assert.equal(meetingResponse.status(),202,await meetingResponse.text());const meetingGeneration=await meetingResponse.json();
  await page.waitForFunction(()=>document.querySelector('[data-tools-field=meetingAgenda]').value.includes('45')&&!document.querySelector('[data-tools-field=meetingAgenda]').disabled);
  const meetingMessages=(await api(page,'/user/api/conversations/'+meetingGeneration.conversation_id+'/messages')).data;assert.deepEqual(meetingMessages.context.source_ids,pids);assert.equal(meetingMessages.context.include_business,false);assert.deepEqual(meetingMessages.context.memory_ids,[]);
  assert.equal((await api(page,endpoint('records?kind=meeting'))).data.records.length,0,'Meeting draft was automatically saved');
  // Editing and explicit save preserve timezone and original source links.
  await field(meeting,'meetingAgenda').fill((await field(meeting,'meetingAgenda').inputValue())+'\nUSER_EDITED_AGENDA');
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/research/records')&&r.request().method()==='POST');await meeting.getByRole('button',{name:'Confirm and save meeting',exact:true}).click();assert.equal((await saveResponse).status(),201);
  const saved=(await api(page,endpoint('records?kind=meeting'))).data.records[0];assert(saved.body.includes('USER_EDITED_AGENDA'));assert.equal(saved.attributes.duration_minutes,45);assert.equal(new Date(saved.attributes.meeting_at).toISOString(),'2026-10-13T06:30:00.000Z');assert.deepEqual(saved.publication_ids,pids);
  assert.equal((await api(peer,endpoint('records?kind=meeting'))).data.records.length,0);
  const download=page.waitForEvent('download');await meeting.getByRole('button',{name:'Download agenda',exact:true}).click();assert((await download).suggestedFilename().endsWith('.md'));
  const sharedBefore=(await api(peer,endpoint('records?kind=shared'))).data.records.length;
  await meeting.getByRole('button',{name:'Draft agenda sharing',exact:true}).click();await page.locator('#research-view-sharedResults:not([hidden])').waitFor();assert((await page.locator('[data-research-form=shared] [data-research-field=description]').inputValue()).includes('USER_EDITED_AGENDA'));assert.equal((await api(peer,endpoint('records?kind=shared'))).data.records.length,sharedBefore,'Sharing a draft published it');
  console.log('Meeting draft, explicit save, source binding, timezone, export and sharing preview passed.');

  await tab('analyze');const analysis=page.locator('#research-view-analyze');await analysis.locator('[data-research-field=ask]').fill('EXPLICIT_ANALYSIS_CANARY: The battery result proves universal applicability.');const critiqueResponse=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await analysis.locator('[data-research-intent=critique]').click();assert.equal((await critiqueResponse).status(),202);const critique=await (await critiqueResponse).json();await page.waitForFunction(()=>document.querySelector('#researchOutput').textContent.includes('Counterargument')&&!document.querySelector('[data-research-intent=critique]').disabled);
  const critData=(await api(page,'/user/api/conversations/'+critique.conversation_id+'/messages')).data;assert.equal(critData.messages[0].intent,'critique');assert(critData.messages[0].question.includes('EXPLICIT_ANALYSIS_CANARY'));
  await analysis.getByRole('button',{name:'Save conversation',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#readerResearchDesk .research-status').textContent===window.BeeNewsChatI18n.t('conversationSaved'));
  // Another user's generation is never a valid critique target.
  const privateStart=(await api(peer,'/user/api/publications/'+pids[0]+'/conversations','POST',{model_key:'openai:fixture-v1'})).data;
  const invalid=await api(peer,'/user/api/conversations/'+privateStart.id+'/messages','POST',{model_key:'openai:fixture-v1',question:'Critique selected answer',intent:'critique',target_generation_id:critique.id,context_version:privateStart.context.version,language:'en',idempotency_key:crypto.randomUUID()});assert.equal(invalid.status,404);
  assert.equal((await api(peer,endpoint('usage'))).data.requests_today,0);
  console.log('Explicit critique target, actual prompt, private save and cross-user refusal passed.');

  await tab('expertInbox');const expert=page.locator('[data-tools-form=expert]');await field(expert,'title').fill('Check the sampling assumption');await field(expert,'chooseColleague').selectOption(peerId);await field(expert,'expertQuestion').fill('Which sampling evidence would change this conclusion?');await field(expert,'selectedExcerpt').fill('EXPLICIT_EXCERPT_ONLY');
  assert.equal((await api(peer,endpoint('expert-requests'))).data.requests.length,0);
  const sent=page.waitForResponse(r=>r.url().endsWith('/expert-requests')&&r.request().method()==='POST');await expert.getByRole('button',{name:'Confirm and send to this colleague',exact:true}).click();const sentResponse=await sent;assert.equal(sentResponse.status(),201,await sentResponse.text());const question=await sentResponse.json();await page.locator('[data-tools-thread="'+question.id+'"]').waitFor();
  const pending=(await api(peer,endpoint('expert-requests'))).data;assert.equal(pending.requests.length,1);assert.equal(pending.unread_count,1);assert.equal(pending.requests[0].excerpt,'EXPLICIT_EXCERPT_ONLY');assert(!JSON.stringify(pending).includes('EXPLICIT_ANALYSIS_CANARY'));assert(!JSON.stringify(pending).includes('conversation_id'));
  assert.equal((await api(outsider,endpoint('expert-requests/'+question.id))).status,404);
  assert.equal((await api(peer,endpoint('expert-requests/'+question.id+'/state'),'PUT',{version:1,status:'closed'})).status,404);
  const forged=await api(peer,endpoint('expert-requests/'+question.id+'/replies'),'POST',{id:crypto.randomUUID(),version:1,body:'Pretend reply',author_id:'30000000-0000-4000-8000-000000000010'});assert.equal(forged.status,422);
  await tab('expertInbox',peer);await peer.locator('[data-tools-request="'+question.id+'"]').getByRole('button',{name:'View question and replies',exact:true}).click();const reply=peer.locator('[data-tools-form=reply]');await field(reply,'humanReply').fill('HUMAN_REPLY_CANARY: Need an independently collected sample. <img src=x onerror=window.injected=true>');
  const replied=peer.waitForResponse(r=>r.url().endsWith('/replies')&&r.request().method()==='POST');await reply.getByRole('button',{name:'Send reply',exact:true}).click();assert.equal((await replied).status(),201);await peer.locator('[data-tools-reply]').waitFor();assert.equal(await peer.evaluate(()=>window.injected),undefined);
  const response=(await api(page,endpoint('expert-requests/'+question.id))).data;assert.equal(response.replies[0].kind,'human');assert.equal(response.replies[0].author.id,peerId);assert(response.replies[0].body.includes('HUMAN_REPLY_CANARY'));assert.equal(response.status,'answered');
  assert.equal((await api(page,endpoint('expert-requests/'+question.id+'/state'),'PUT',{version:1,status:'closed'})).status,409);
  let closed=await api(page,endpoint('expert-requests/'+question.id+'/state'),'PUT',{version:response.version,status:'closed'});assert.equal(closed.status,200);
  assert.equal((await api(peer,endpoint('expert-requests/'+question.id+'/replies'),'POST',{id:crypto.randomUUID(),version:closed.data.version,body:'Late reply'})).status,409);
  assert.equal((await api(page,endpoint('expert-requests/'+question.id+'/state'),'PUT',{version:closed.data.version,status:'open'})).status,200);
  console.log('Real colleague inbox, explicit excerpt, authenticated human reply, notifications, race and state controls passed.');

  await tab('corrections');await page.locator('[data-tools-watch="'+pids[0]+'"]').waitFor();assert.equal((await api(page,endpoint('corrections'))).data.watches.length,2);
  const checked=page.waitForResponse(r=>r.url().endsWith('/check')&&r.request().method()==='POST');await page.locator('[data-tools-watch="'+pids[0]+'"]').getByRole('button',{name:'Check source now',exact:true}).click();assert.equal((await checked).status(),200);await page.locator('[data-tools-revision]').waitFor();
  const history=(await api(page,endpoint('corrections/'+pids[0]))).data;assert.equal(history.revisions[0].channel,'source');assert.equal(history.revisions[0].notice,'correction_notice');assert(history.revisions[0].diff.includes('PUBLIC_CORRECTION_CANARY'));assert(!JSON.stringify(history).includes('INTERNAL FULL ORIGINAL'));assert.equal(history.revisions[0].before_available,false);
  const review=(await api(page,endpoint('review-needed'))).data.items;assert(review.some(r=>r.id===saved.id&&r.kind==='meeting'));assert(review.some(r=>r.id===critique.conversation_id&&r.kind==='memory'));assert.equal((await api(peer,endpoint('review-needed'))).data.items.length,0);
  const beforeCorrection=(await api(page,endpoint('usage'))).data.requests_today;assert.equal(beforeCorrection,2,'Source checks or colleague messages called AI');
  const changeAnalysis=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await page.locator('[data-tools-revision]').first().getByRole('button',{name:'Analyze this change with AI',exact:true}).click();assert.equal((await changeAnalysis).status(),202);const correctionGeneration=await (await changeAnalysis).json();await page.waitForFunction(()=>document.getElementById('toolsCorrectionOutput').textContent.includes('corrected value of 25')&&document.querySelector('#research-view-corrections [data-tools-key=stop]').disabled);
  const correctionMessages=(await api(page,'/user/api/conversations/'+correctionGeneration.conversation_id+'/messages')).data;assert.deepEqual(correctionMessages.context.revision_ids,[history.revisions[0].id]);assert(correctionMessages.messages[0].citations.some(c=>c.scope==='selected_public_source_revision'));
  assert.equal((await api(page,endpoint('corrections/'+pids[0]+'/seen'),'POST',{version:history.version})).status,200);
  assert((await api(page,endpoint('review-needed'))).data.items.some(r=>r.id===saved.id),'Reading the alert silently reviewed a decision');
  await page.locator('[data-tools-review="'+saved.id+'"]').getByRole('button',{name:'I reviewed this item',exact:true}).click();await page.waitForFunction(id=>!document.querySelector('[data-tools-review="'+id+'"]'),saved.id);
  assert.equal((await api(page,endpoint('corrections/'+pids[0]+'/check'),'POST')).data.status,'cooldown');
  console.log('Actual source recheck, immutable evidence, private dependency warnings, explicit revision analysis and separate review acknowledgment passed.');

  // New news tools use the actual modal. Critique stays within this user's news conversation.
  await page.locator('.news-card[data-news-id="'+pids[0]+'"] [data-action=open]').click();await page.locator('#newsChat [type=submit]:not([disabled])').waitFor();await page.locator('#newsCorrectionAlert:not([hidden])').waitFor();await page.locator('#news-chat-question').fill('Discuss this corrected report carefully.');await page.locator('#newsChat [type=submit]').click();await page.locator('#newsChat [type=submit]:not([disabled])').waitFor();await page.locator('#newsChat .chat-answer').last().waitFor();
  const modalCritic=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await page.locator('#newsChat [data-chat-key=critiqueAnswer]').last().click();assert.equal((await modalCritic).status(),202);await page.locator('#newsChat [type=submit]:not([disabled])').waitFor();assert((await page.locator('#newsChat .chat-answer').last().innerText()).includes('Counterargument'));
  await page.locator('#newsChat .reader-tools-news-actions [data-reader-tool=expertInbox]').click();await page.locator('#research-view-expertInbox:not([hidden])').waitFor();assert.equal((await api(peer,endpoint('expert-requests'))).data.requests.length,1,'Opening a colleague draft sent it');
  await tab('meetings');await field(meeting,'title').fill('UNSUBMITTED_PRIVATE_MEETING');await field(meeting,'title').focus();
  for(const locale of ['fa','en','tr','ar','es','it','de','fr'])for(const width of [1440,900,390,320]){
    await page.setViewportSize({width,height:1000});await page.evaluate(locale=>{document.documentElement.lang=locale;document.documentElement.dir=['fa','ar'].includes(locale)?'rtl':'ltr'},locale);await page.waitForTimeout(20);
    assert.equal(await field(meeting,'title').inputValue(),'UNSUBMITTED_PRIVATE_MEETING');assert.equal(await page.evaluate(()=>document.activeElement.dataset.toolsField),'title');assert(await page.locator('#readerResearchDesk').evaluate(n=>n.scrollWidth<=n.clientWidth+2),'Reader tools overflow '+locale+'/'+width);
    for(const key of ['meetings','expertInbox','corrections']){await tab(key);assert(await page.locator('#research-view-'+key).evaluate(n=>n.scrollWidth<=n.clientWidth+2),'Tools view overflow '+key+'/'+locale+'/'+width)}
    await tab('meetings');await field(meeting,'title').focus();
  }
  for(const key of ['meetings','expertInbox','corrections']){await tab(key);const axe=await new AxeBuilder({page}).include('#readerResearchDesk').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();assert.deepEqual(axe.violations.filter(v=>['critical','serious'].includes(v.impact)).map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),[])}
  if(process.env.BEE_CHAT_ARTIFACT_DIR){await page.evaluate(()=>{document.documentElement.lang='fa';document.documentElement.dir='rtl'});await page.setViewportSize({width:1440,height:1000});await tab('meetings');await page.screenshot({path:process.env.BEE_CHAT_ARTIFACT_DIR+'/reader-tools-meetings-fa.png',fullPage:true});await tab('expertInbox');await page.screenshot({path:process.env.BEE_CHAT_ARTIFACT_DIR+'/reader-tools-experts-fa.png',fullPage:true});await tab('corrections');await page.screenshot({path:process.env.BEE_CHAT_ARTIFACT_DIR+'/reader-tools-corrections-fa.png',fullPage:true})}
  const beforeLogout=await page.evaluate(()=>localStorage.getItem('bee_reader_settings'));assert(!String(beforeLogout).includes('UNSUBMITTED_PRIVATE_MEETING'));
  await page.goto(base+'/user/settings');await page.reload();assert.equal((await api(page,endpoint('records?kind=meeting'))).data.records.length,1,'Saved meeting disappeared on reload');assert.deepEqual(errors,[]);
  console.log('Reader tools 1/7/9/4 browser gate passed: actual DB/API/SSE, synthetic public source and AI only, role/privacy/quotes, feedback loops, reload, eight locales × four widths, accessibility and no real messages.');
}finally{await outsiderCtx.close();await peerCtx.close();await ctx.close();await browser.close()}
