/* Real browser capture, HTTP, WebSocket, workers and SQL; synthetic provider. */
import assert from 'node:assert/strict';
import {startVirtualAudio,resumeNativeWorklets} from './voice_browser_audio.mjs';
const stopVirtualAudio=await startVirtualAudio();
import {chromium} from 'playwright';
import AxeBuilder from '@axe-core/playwright';
const base=process.env.BEE_CHAT_TEST_URL;
if(process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test'||!base||new URL(base).hostname!=='127.0.0.1')throw Error('Isolated synthetic loopback app required');
const aid='10000000-0000-4000-8000-000000000001',pid='20000000-0000-4000-8000-000000000001';
const browser=await chromium.launch({headless:false,channel:'chromium',ignoreDefaultArgs:['--mute-audio'],args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
await resumeNativeWorklets(browser);
const context=await browser.newContext({permissions:['microphone'],viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
await page.addInitScript(()=>{window.workletCreated=0;const Native=window.AudioWorkletNode;window.AudioWorkletNode=new Proxy(Native,{construct(target,args){window.workletCreated++;return Reflect.construct(target,args)}})});
page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
async function api(path,method='GET',body){return page.evaluate(async({path,method,body})=>{
  const csrf=document.cookie.split('; ').find(c=>c.startsWith('research_bee_user_csrf='))?.split('=').slice(1).join('=');
  const r=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},...(body?{body:JSON.stringify(body)}:{})});
  return {status:r.status,data:await r.json().catch(()=>({}))};
},{path,method,body})}
async function login(){await page.goto(base+'/user/login-up');await page.locator('#username').fill('voice-reader');await page.locator('#password').fill('synthetic violet herons cross mountain lakes');const response=page.waitForResponse(r=>r.url().endsWith('/user/api/login'));await page.locator('#loginButton').click();assert.equal((await response).status(),200);await page.locator('#app:not(.hidden)').waitFor();await page.locator('#assistantSelect').selectOption(aid);await page.evaluate(()=>{document.documentElement.lang='en';document.documentElement.dir='ltr'})}
async function bytes(id){return page.evaluate(async id=>{const r=await fetch('/user/api/voice-audio/'+id+'/download');const a=new Uint8Array(await r.arrayBuffer());return {status:r.status,size:a.length,header:String.fromCharCode(...a.slice(0,4)),hash:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',a))).map(v=>v.toString(16).padStart(2,'0')).join('')}},id)}
try{
  for(let i=0;i<60;i++){try{if((await page.request.get(base+'/health')).ok())break}catch(_){}assert(i<59,'Synthetic voice app did not become ready');await page.waitForTimeout(250)}
  await login();assert.equal((await api('/user/api/preferences','PATCH',{chat:{voice_consent:true,retain_voice:true}})).status,200);const cap=await api('/user/api/voice/capabilities?assistant_id='+aid);assert.equal(cap.status,200,JSON.stringify(cap.data));assert(cap.data.enabled);
  await page.locator('.news-card[data-news-id="'+pid+'"] [data-action=open]').click();await page.locator('#newsChat [type=submit]:not([disabled])').waitFor();
  assert.equal(await page.locator('#newsChat .voice-settings').count(),0);
  await page.locator('#news-chat-response-mode [data-mode=both]').click();
  const startResponse=page.waitForResponse(r=>r.url().endsWith('/voice-sessions')&&r.request().method()==='POST');
  await page.locator('#news-chat-microphone').click();const started=await startResponse;assert.equal(started.status(),201,await started.text());
  await page.waitForFunction(()=>document.querySelector('#news-chat-microphone').getAttribute('aria-pressed')==='true');await page.waitForTimeout(900);await page.locator('#news-chat-microphone').click();
  await page.waitForFunction(()=>document.getElementById('news-chat-question').value==='Synthetic speech about published batteries.');
  assert(await page.evaluate(()=>window.workletCreated>0),'Microphone used fallback instead of native AudioWorklet');
  const recognized=(await started.json()).id;await page.locator('#news-chat-question').fill('Edited question from genuine microphone capture');
  const generationResponse=page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST');await page.locator('#newsChat [type=submit]').click();
  const generated=await generationResponse;assert.equal(generated.status(),202,await generated.text());const generation=await generated.json();assert.deepEqual(generation.voice_session_ids,[recognized]);
  await page.evaluate(cid=>window.voiceTestCid=cid,generation.conversation_id);
  const streamingProof=await page.evaluate(async gid=>{for(let i=0;i<60;i++){const c=await fetch('/user/api/conversations/'+window.voiceTestCid+'/voice-audio');const data=await c.json();const asset=data.audio?.find(a=>a.generation_id===gid);if(asset){const r=await fetch('/user/api/voice-audio/'+asset.id+'/stream');const reader=r.body.getReader();const result=await reader.read();await reader.cancel();return {first:new TextDecoder().decode(result.value),running:document.querySelector('[data-generation="'+gid+'"] .chat-status')?.textContent.includes('Generating')}}await new Promise(r=>setTimeout(r,50))}throw Error('No progressive asset')},generation.id);assert(streamingProof.first.includes('pcm'),'No PCM arrived during text generation');assert(streamingProof.running,'First PCM arrived after LLM completion');
  await page.locator('.voice-output audio').last().waitFor();assert(await page.locator('.chat-answer').last().isVisible());
  const audioId=await page.locator('.voice-output .voice-player').last().getAttribute('data-audio-id'),original=await bytes(audioId);assert.equal(original.status,200);assert.equal(original.header,'RIFF');assert.equal(original.size,192044); // two genuine PCM segments
  const savedAudio=(await api('/user/api/conversations/'+generation.conversation_id+'/voice-audio')).data.audio.find(a=>a.id===audioId);assert(savedAudio.metadata.complete);assert.equal(savedAudio.metadata.spoken_text,'First synthetic sentence grounded in the report . Final synthetic sentence.');
  const cid=generation.conversation_id,firstList=(await api('/user/api/conversations/'+cid+'/voice-audio')).data;
  const countBefore=(await api('/user/api/voice/usage?assistant_id='+aid)).data.operations.find(o=>o.kind==='tts').units;
  await page.getByRole('button',{name:'Play answer',exact:true}).last().click();await page.waitForTimeout(100);
  const countAfter=(await api('/user/api/voice/usage?assistant_id='+aid)).data.operations.find(o=>o.kind==='tts').units;assert.equal(countBefore,countAfter,'Replay generated new charged speech');
  await page.locator('#newsChat').getByRole('button',{name:'Save audio',exact:true}).click();const dialog=page.locator('dialog.voice-save-dialog');await dialog.waitFor();
  await dialog.getByLabel('File contents',{exact:true}).selectOption('dialogue');await dialog.getByLabel('Audio title',{exact:true}).fill('Voice browser private dialogue');await dialog.locator('input[type=checkbox]').last().check();
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/audio-saves')&&r.request().method()==='POST');await dialog.getByRole('button',{name:'Confirm save',exact:true}).click();const savedJob=await (await saveResponse).json();await dialog.waitFor({state:'detached'});
  const job=(await api('/user/api/conversations/'+cid+'/audio-saves/'+savedJob.id)).data;assert.equal(job.status,'completed');
  const savedId=job.asset_id,snapshot=await bytes(savedId);assert.equal(snapshot.status,200);assert(snapshot.size>original.size);
  const manifest=(await api('/user/api/voice-audio/'+savedId+'/manifest')).data;assert.deepEqual(manifest.segments.map(s=>s.speaker),['user','ai']);assert.equal(manifest.segments[0].submitted_question,'Edited question from genuine microphone capture');
  assert.equal(manifest.segments[0].recognized_text,'Synthetic speech about published batteries.');
  assert.equal((await api('/user/api/conversations/'+cid+'/memory','DELETE')).status,409,'Unsave must disclose linked file deletion');
  await page.locator('#closeDialog').click();await page.reload();await page.locator('#app:not(.hidden)').waitFor();await page.evaluate(()=>{document.documentElement.lang='en';document.documentElement.dir='ltr'});
  assert.equal((await bytes(savedId)).hash,snapshot.hash,'Reload changed stored audio');
  await page.locator('#projectChatMemory summary').first().click();
  await page.locator('.voice-library summary').click();const savedPlayer=page.locator('.voice-library [data-audio-id="'+savedId+'"]');await savedPlayer.waitFor();
  for(const locale of ['fa','en','tr','ar','es','it','de','fr'])for(const width of [390,768,1440,1920]){
    await page.setViewportSize({width,height:1000});await page.evaluate(locale=>{document.documentElement.lang=locale;document.documentElement.dir=['fa','ar'].includes(locale)?'rtl':'ltr'},locale);
    assert(await savedPlayer.evaluate(n=>n.scrollWidth<=n.clientWidth+2),'Voice player overflow '+locale+'/'+width);
  }
  await page.evaluate(()=>{document.documentElement.lang='en';document.documentElement.dir='ltr'});
  const a11y=await new AxeBuilder({page}).include('.voice-library').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  assert.deepEqual(a11y.violations.filter(v=>['critical','serious'].includes(v.impact)).map(v=>v.id),[]);
  await savedPlayer.getByRole('button',{name:'Delete audio',exact:true}).click();await page.waitForFunction(id=>!document.querySelector('.voice-library [data-audio-id="'+id+'"]'),savedId);
  assert.equal((await bytes(savedId)).status,404);assert.equal((await api('/user/api/conversations/'+cid+'/memory-reference')).status,200,'Audio deletion removed text memory');
  // No browser SpeechRecognition/SpeechSynthesis API is part of this path.
  assert.deepEqual(errors,[]);console.log('Voice browser passed: real browser microphone PCM, private WebSocket STT, edited Send, simultaneous text/audio, cost-free replay, genuine dialogue save/reload/download, project audio gallery, independent deletion, 8 languages × 4 widths and accessibility. Synthetic provider only; no claim about live ElevenLabs voice quality.');
}catch(e){console.log('Synthetic voice DOM diagnostics',await page.evaluate(()=>({locale:document.documentElement.lang,project:document.getElementById('assistantSelect')?.value,memoryOpen:document.getElementById('projectChatMemory')?.open,galleries:[...document.querySelectorAll('.voice-library')].map(n=>({open:n.open,text:n.textContent.slice(0,180)})),players:[...document.querySelectorAll('.voice-library [data-audio-id]')].map(n=>n.dataset.audioId),status:document.querySelector('#projectChatMemory > .chat-status')?.textContent})));throw e}finally{await context.close();await browser.close();stopVirtualAudio()}
