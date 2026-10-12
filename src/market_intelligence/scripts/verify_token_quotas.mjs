/* Actual authenticated UI/API/worker; synthetic providers and isolated network. */
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {chromium} from 'playwright';
import AxeBuilder from '@axe-core/playwright';
const base=process.env.BEE_CHAT_TEST_URL;
if(process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test'||!base||new URL(base).hostname!=='127.0.0.1')throw Error('Isolated fixture required');
const aid='10000000-0000-4000-8000-000000000001',pid='20000000-0000-4000-8000-000000000001',uid='30000000-0000-4000-8000-000000000012';
const browser=await chromium.launch({headless:true}),ctx=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'Asia/Tehran'}),peerCtx=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await ctx.newPage(),peer=await peerCtx.newPage(),errors=[];
for(const p of [page,peer]){p.setDefaultTimeout(20000);p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept())}
async function api(p,path,method='GET',body){if(method==='PUT'&&path.includes('/token-quotas'))body=Object.fromEntries(['assistant_id','user_id','inherit','limits','version'].map(k=>[k,body[k]]));return p.evaluate(async({path,method,body})=>{const name=location.pathname.startsWith('/admin')?'research_bee_admin_csrf':'research_bee_user_csrf';const csrf=document.cookie.split('; ').find(c=>c.startsWith(name+'='))?.split('=').slice(1).join('=');const r=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},...(body?{body:JSON.stringify(body)}:{})});return {status:r.status,data:await r.json().catch(()=>({}))}},{path,method,body})}
async function login(p,name,admin=false){await p.context().clearCookies();await p.goto(base+(admin?'/admin/login-up':'/user/login-up'));await p.locator(admin?'#loginUser':'#username').fill(name);await p.locator(admin?'#loginPass':'#password').fill('synthetic violet herons cross mountain lakes');await p.locator(admin?'#loginSubmit':'#loginButton').click();await p.locator('#app:not(.hidden)').waitFor();await p.evaluate(()=>{document.documentElement.lang='en';document.documentElement.dir='ltr'})}
const editor=key=>page.locator('[data-token-editor='+key+']');
async function saveForm(box){const response=page.waitForResponse(r=>r.url().includes('/token-quotas')&&r.request().method()==='PUT');await box.locator('button[type=submit]').click();assert.equal((await response).status(),200);await box.locator('.token-status').filter({hasText:'Saved'}).waitFor()}
async function policy(body){const r=await api(page,'/user/api/token-quotas/owner','PUT',body);assert.equal(r.status,200);return r.data}
const empty={six_hours:null,daily:null,monthly:null,total:null};
let cleanup=[];
try{
  await login(page,'chat-owner');await page.goto(base+'/user/settings?section=limits');await page.locator('#tokenLimits').waitFor();await editor('default').locator('input[data-token-field=daily]').waitFor();
  for(const w of Object.keys(empty))await editor('default').locator('[data-token-field='+w+']').fill('100000');await saveForm(editor('default'));assert.equal(await editor('project').locator('[data-token-field=daily]').inputValue(),'100000');
  await page.locator('#tokenOwnerProject').selectOption(aid);await editor('project').waitFor({state:'visible'});await editor('project').locator('input[type=checkbox]').uncheck();await editor('project').locator('[data-token-field=daily]').fill('200000');await saveForm(editor('project'));cleanup.push({assistant_id:aid,user_id:null});
  await page.locator('#tokenOwnerUser').selectOption(uid);await editor('user').locator('input[type=checkbox]').uncheck();await editor('user').locator('[data-token-field=six_hours]').fill('50000');await saveForm(editor('user'));cleanup.push({assistant_id:aid,user_id:uid});
  const catalog=await api(page,'/user/api/token-quotas/owner?assistant_id='+aid);assert.equal(catalog.data.users.find(u=>u.id===uid).policy.limits.six_hours,50000);
  await login(peer,'quota-reader');await peer.goto(base+'/user/settings?section=report');await peer.locator('#tokenReport').waitFor();await peer.locator('[data-token-window=total]').waitFor();assert.equal(await peer.locator('#tokenLimits').count(),0);assert.equal((await api(peer,'/user/api/token-quotas/owner')).status,403);
  let report=(await api(peer,'/user/api/assistants/'+aid+'/token-report')).data;assert.equal(report.limit_source,'user');assert.equal(report.windows[0].limit,50000);assert(!JSON.stringify(report).includes('question'));
  const started=await api(peer,'/user/api/publications/'+pid+'/conversations','POST',{model_key:'openai:fixture-v1'});assert.equal(started.status,201);
  const cid=started.data.id,q={question:'Explain this published news',model_key:'openai:fixture-v1',context_version:started.data.context.version,idempotency_key:randomUUID(),language:'en'};
  const sent=await api(peer,'/user/api/conversations/'+cid+'/messages','POST',q);assert.equal(sent.status,202);
  let done=false;for(let n=0;n<60;n++){const r=await api(peer,'/user/api/conversations/'+cid+'/messages');const g=r.data.messages?.find(g=>g.id===sent.data.id);if(g?.status==='completed'){done=true;break}await peer.waitForTimeout(100)}assert(done,'Synthetic worker completed');
  report=(await api(peer,'/user/api/assistants/'+aid+'/token-report')).data;const measured=report.requests.find(g=>g.id===sent.data.id);assert.equal(measured.input_tokens,120);assert.equal(measured.output_tokens,25);assert.equal(measured.reserved_tokens,0);
  const userPolicy=catalog.data.users.find(u=>u.id===uid).policy;const blocked=await policy({...userPolicy,version:userPolicy.version,limits:{...empty,total:0}});
  const denial=await api(peer,'/user/api/conversations/'+cid+'/messages','POST',{...q,idempotency_key:randomUUID()});assert.equal(denial.status,429);assert.equal(denial.data.detail.code,'token_quota_exhausted');
  await api(peer,'/user/api/conversations/'+cid,'DELETE');report=(await api(peer,'/user/api/assistants/'+aid+'/token-report')).data;assert(report.requests.some(g=>g.id===sent.data.id&&g.input_tokens===120));
  await policy({...blocked,limits:empty,inherit:true});
  // Server rejects stale simultaneous changes without replacing a newer limit.
  const d=(await api(page,'/user/api/token-quotas/owner')).data.default;
  const race=await Promise.all([api(page,'/user/api/token-quotas/owner','PUT',{...d,limits:empty}),api(page,'/user/api/token-quotas/owner','PUT',{...d,limits:{...empty,daily:1234}})]);assert.deepEqual(race.map(r=>r.status).sort(),[200,409]);
  // Draft, caret and focus survive language updates; tables scroll inside their region.
  const draft=editor('default').locator('[data-token-field=total]');await draft.fill('12345');await draft.focus();
  for(const locale of ['fa','en','tr','ar','es','it','de','fr'])for(const width of [1440,900,390,320]){
    await page.setViewportSize({width,height:1000});await page.evaluate(locale=>{document.documentElement.lang=locale;document.documentElement.dir=['fa','ar'].includes(locale)?'rtl':'ltr'},locale);
    assert.equal(await draft.inputValue(),'12345');assert.equal(await draft.evaluate(n=>document.activeElement===n),true);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'Settings overflow '+locale+'/'+width);
    assert.equal(await page.locator('#tokenLimits [data-token-key=limits]').textContent(),await page.evaluate(()=>window.BeeTokenI18n.t('limits')));
  }
  const a11y=await new AxeBuilder({page}).include('#tokenLimits').include('#tokenReport').withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();assert.deepEqual(a11y.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>[v.id,v.nodes.map(n=>n.target)]),[]);
  await page.evaluate(()=>{document.documentElement.lang='fa';document.documentElement.dir='rtl'});if(process.env.BEE_CHAT_ARTIFACT_DIR)await page.screenshot({path:process.env.BEE_CHAT_ARTIFACT_DIR+'/token-owner-settings-fa.png',fullPage:true});
  await login(peer,'quota-no-grant');await peer.goto(base+'/user/settings?section=report');await peer.locator('[data-token-window=total]').waitFor();assert.equal((await api(peer,'/user/api/assistants/'+aid+'/token-report')).status,200);
  // The same owner control is reachable in the Admin account settings.
  await login(page,'chat-owner',true);await page.evaluate(()=>window.setView('account'));await page.locator('#tokenLimits').waitFor();assert.equal((await api(page,'/admin/api/token-quotas')).status,200);await editor('default').locator('[data-token-field=daily]').fill('8888');await saveForm(editor('default'));assert.equal((await api(page,'/admin/api/token-quotas')).data.default.limits.daily,8888);
  assert.deepEqual(errors,[]);console.log('Token quota browser passed: owner controls, private report, real synthetic token settlement, denial, erasure, all locales/widths and accessibility.');
}finally{
  // Cleanup through owner API, whichever portal is still open.
  const path=new URL(page.url()).pathname.startsWith('/admin')?'/admin/api/token-quotas':'/user/api/token-quotas/owner';
  try{for(const item of cleanup){const data=(await api(page,path+'?assistant_id='+item.assistant_id)).data;const row=item.user_id?data.users.find(u=>u.id===item.user_id).policy:data.project;await api(page,path,'PUT',{...row,limits:empty,inherit:true})}const data=(await api(page,path)).data;await api(page,path,'PUT',{...data.default,limits:empty})}catch(_){}
  await browser.close();
}
