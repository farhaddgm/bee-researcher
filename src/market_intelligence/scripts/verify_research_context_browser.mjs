import assert from 'node:assert/strict';
import {chromium} from 'playwright';

const base=process.env.BEE_ADMIN_URL, username=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME, password=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if(!base||!username||!password||process.env.MARKET_INTELLIGENCE_ENVIRONMENT!=='test')throw new Error('Isolated test URL and synthetic credentials required');
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900}});
page.setDefaultTimeout(15000);
const errors=[],projects=[],users=[];
page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
async function api(target,path,method='GET',body){return target.evaluate(async({path,method,body})=>{
  const csrf=document.cookie.split('; ').find(x=>x.startsWith('research_bee_admin_csrf='))?.split('=').slice(1).join('=');
  const response=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},...(body?{body:JSON.stringify(body)}:{})});
  return {status:response.status,data:await response.json()};
},{path,method,body});}
async function login(target,user,pass){await target.goto(base,{waitUntil:'domcontentloaded'});await target.locator('#loginUser').fill(user);await target.locator('#loginPass').fill(pass);await target.locator('#loginSubmit').click();await target.locator('#app:not(.hidden)').waitFor();await target.waitForFunction(()=>window.__researchBeeState?.currentUser&&window.__researchBeeState.assistantId);}
async function select(id){await page.locator('#workspaceSelect').selectOption(id);await page.waitForFunction(id=>window.__researchBeeState.assistantId===id,id);await page.locator('.nav-btn[data-view="businesses"]').click();await page.waitForFunction(id=>document.getElementById('researchContextCard')?.dataset.loadedAssistant===id,id);}
try{
  await login(page,username,password);
  const meta=await api(page,'/meta');assert.equal(meta.data.environment,'test');assert.equal(meta.data.pipeline.scheduler_enabled,false);
  for(let n=0;n<2;n++){const result=await api(page,'/admin/api/assistants','POST',{name:'Research context browser '+n,slug:`research-context-${Date.now()}-${n}`,business_name:'',config:{active_business_id:null}});assert.equal(result.status,200);projects.push(result.data.id);}
  const business=await api(page,`/admin/api/assistants/${projects[0]}/businesses`,'POST',{business_name:'Acme <b>synthetic</b>',description:'Battery technology supplier',products_services:'Battery systems',target_customers:'Manufacturers',markets:'Europe'});
  assert.equal(business.status,200);
  await page.evaluate(()=>window.loadAll());await select(projects[0]);
  for(const locale of ['fa','en','tr','ar','es','it','de','fr']){
    await page.evaluate(locale=>window.setLanguage(locale),locale);
    const heading=await page.locator('#researchContextCard h3').innerText();if(!['fa','ar'].includes(locale))assert(!/[پچژگک]/.test(heading),locale);
    for(const width of [1440,900,390,320]){
      await page.setViewportSize({width,height:900});await page.locator('#researchConfigure').click();const modal=page.locator('#modalRoot [role=dialog]');await modal.waitFor();
      assert.equal(await modal.locator('select').count(),4);
      assert.equal(await modal.locator('#researchSections').isVisible(),false);
      await modal.locator('#researchSource').selectOption('local');await modal.locator('#researchMode').selectOption('focused');
      assert.equal(await modal.locator('#researchThresholdField').isVisible(),true);
      assert.equal(await modal.locator('#researchSections input').count(),8);
      assert.equal(await modal.locator('#researchLocal b').count(),0,'Business name executed as HTML');
      await modal.locator('#researchConsent').check();
      assert.equal(await modal.locator('#researchPublic').isChecked(),false,'Public disclosure enabled by default');
      await modal.locator('#researchPreview').click();await modal.locator('#researchActivate:not([disabled])').waitFor();
      assert((await modal.locator('#researchResult').innerText()).length>60);
      await modal.locator('#researchRollout').selectOption('live');assert.equal(await modal.locator('#researchActivate').isDisabled(),true,'Edited preview stayed valid');
      await modal.locator('#researchPreview').click();await modal.locator('#researchPreview:not([disabled])').waitFor();
      assert.equal(await modal.locator('#researchActivate').isDisabled(),true,'Live activation allowed without news evaluation');
      const help=modal.locator('.research-help .info-tip').first();await help.focus();
      const tip=page.locator('#beeUiTooltip:not([hidden])');await tip.waitFor();
      assert.equal(await tip.innerText(),await help.getAttribute('data-tooltip'),'Translated help differs from its field');
      const tipBounds=await tip.boundingBox();assert(tipBounds.x>=0&&tipBounds.x+tipBounds.width<=width&&tipBounds.y>=0&&tipBounds.y+tipBounds.height<=900,`Help overflow ${locale}/${width}`);
      await page.keyboard.press('Escape');assert.equal(await tip.count(),0);assert.equal(await modal.count(),1,'Closing help also closed its form');
      const bounds=await modal.boundingBox();assert(bounds.x>=-1&&bounds.x+bounds.width<=width+1,`Modal overflow ${locale}/${width}`);
      assert(await modal.evaluate(n=>n.scrollWidth<=n.clientWidth+1),`Modal content overflow ${locale}/${width}`);
      await modal.locator('#researchSource').focus();await page.keyboard.press('Tab');assert(await modal.evaluate(n=>n.contains(document.activeElement)));
      await page.keyboard.press('Escape');assert.equal(await modal.count(),0);
    }
  }
  await page.setViewportSize({width:1440,height:900});await page.evaluate(()=>window.setLanguage('en'));
  // Real HTTP activation: compilation-only shadow never changes publication.
  await page.locator('#researchConfigure').click();await page.locator('#researchSource').selectOption('local');await page.locator('#researchMode').selectOption('contextual');await page.locator('#researchConsent').check();await page.locator('#researchPreview').click();await page.locator('#researchActivate:not([disabled])').waitFor();
  const activation=page.waitForResponse(r=>r.url().endsWith('/research-context/activate'));await page.locator('#researchActivate').click();assert.equal((await activation).status(),200);
  await page.waitForFunction(()=>!document.querySelector('[data-research-actor]'));
  const own=`/admin/api/assistants/${projects[0]}/research-context`,other=`/admin/api/assistants/${projects[1]}/research-context`;
  assert.equal((await api(page,own)).data.active.rollout,'shadow');assert.equal((await api(page,other)).data.active,null);
  // Same compiled preview cannot be transferred; project switching closes the dialog.
  await page.locator('#researchConfigure').click();await page.locator('#workspaceSelect').selectOption(projects[1]);await page.waitForFunction(()=>!document.querySelector('[data-research-actor]'));
  for(const role of ['viewer','editor']){
    const user=`research-${role}-${Date.now()}`,pass='synthetic-research-context-password';const created=await api(page,'/admin/api/users','POST',{username:user,password:pass,role,assistant_ids:[projects[0]]});assert.equal(created.status,200);users.push(created.data.id);
    const session=await browser.newContext();const member=await session.newPage();member.on('pageerror',e=>errors.push(e.message));await login(member,user,pass);
    assert.equal((await api(member,own)).status,200);assert.equal((await api(member,other)).status,403);
    assert.equal((await api(member,own+'/preview','POST',{source:'none',mode:'topics'})).status,role==='viewer'?403:200);
    await member.locator('.nav-btn[data-view="businesses"]').click();await member.waitForFunction(()=>document.getElementById('researchContextCard')?.dataset.loadedAssistant===window.__researchBeeState.assistantId);
    assert.equal(await member.locator('#researchConfigure').count(),role==='viewer'?0:1);
    assert.equal((await api(member,own+'/activate','POST',{preview_id:'00000000-0000-0000-0000-000000000001',confirmed:true})).status,role==='viewer'?403:409);
    await session.close();
  }
  assert.equal(errors.length,0,errors.join('; '));
  console.log('Research context browser E2E passed: real APIs, 8 locales × 4 widths, escaped names, fields/help, preview invalidation, live refusal without evaluation, real shadow activation, modal keyboard/project switching, viewer/editor ACL and project isolation.');
}finally{
  for(const id of users)await api(page,`/admin/api/users/${id}`,'DELETE');
  for(const id of projects)await api(page,`/admin/api/assistants/${id}`,'DELETE');
  await browser.close();
}
