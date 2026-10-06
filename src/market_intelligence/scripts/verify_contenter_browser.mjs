import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.BEE_ADMIN_URL;
const username = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME;
const password = process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if (!base || !username || !password || process.env.MARKET_INTELLIGENCE_ENVIRONMENT !== 'test') {
  throw new Error('Contenter E2E requires an isolated test application with synthetic credentials.');
}
const browser = await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH}:{})});
const page = await browser.newPage({viewport:{width:1440,height:900}});
page.setDefaultTimeout(15000);
const errors = [], assistants = [], users = [], contexts = [];
page.on('pageerror', error => errors.push(error.message));
page.on('dialog', dialog => dialog.accept());
page.on('response', response => {if(response.url().endsWith('/admin/api/login')) console.log('Isolated login HTTP status:',response.status());});

async function api(target, path, method='GET', body) {
  return target.evaluate(async ({path,method,body}) => {
    const csrf = document.cookie.split('; ').find(x=>x.startsWith('research_bee_admin_csrf='))?.split('=').slice(1).join('=');
    const response=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},...(body?{body:JSON.stringify(body)}:{})});
    return {status:response.status,data:await response.json()};
  }, {path,method,body});
}
async function login(target,user,pass) {
  await target.goto(base,{waitUntil:'domcontentloaded'});
  await target.locator('#loginUser').fill(user);
  await target.locator('#loginPass').fill(pass);
  await target.locator('#loginSubmit').click();
  await target.locator('#app:not(.hidden)').waitFor();
  await target.waitForFunction(()=>state.currentUser && state.assistantId && state.runtimeSettings?.assistant_id===state.assistantId);
}
async function selectProject(id) {
  await page.locator('#workspaceSelect').selectOption(id);
  await page.waitForFunction(id=>state.assistantId===id && state.runtimeSettings?.assistant_id===id,id);
  await page.locator('.nav-btn[data-view="businesses"]').click();
  await page.waitForFunction(id=>document.getElementById('contenterBusinessCard')?.dataset.loadedAssistant===id,id);
  await page.locator('#contenterBusinessCard [data-contenter-action="choose"]').waitFor();
}
try {
  for(let attempt=0;attempt<30;attempt++) {
    try {if((await page.request.get(new URL('/health',base).href,{timeout:1000})).ok())break;} catch (_) {}
    if(attempt===29)throw new Error('Isolated application did not become ready.');
    await new Promise(resolve=>setTimeout(resolve,250));
  }
  await login(page,username,password);
  const metadata=await api(page,'/meta');
  assert.equal(metadata.status,200,'Cannot verify the server test environment');
  assert.equal(metadata.data.environment,'test','Refusing to create fixtures outside a server-confirmed test environment');
  assert.equal(metadata.data.pipeline.scheduler_enabled,false,'The isolated news scheduler must be disabled');
  for (let n=0;n<2;n++) {
    const result=await api(page,'/admin/api/assistants','POST',{name:`Contenter browser fixture ${n}`,slug:`contenter-e2e-${Date.now()}-${n}`,business_name:'',description:'Isolated synthetic fixture',config:{active_business_id:null}});
    assert.equal(result.status,200);assistants.push(result.data.id);
  }
  await page.evaluate(()=>window.loadAll());
  await selectProject(assistants[0]);
  const pickerResponse=page.waitForResponse(r=>r.url().includes('/contenter/businesses?') && r.status()===200);
  await page.locator('#contenterBusinessCard [data-contenter-action="choose"]').click();
  await pickerResponse;
  await page.locator('[data-link-business="biz1"]').waitFor();
  await page.locator('#contenterSearch').fill('Synthetic Researcher');
  await page.locator('#contenterSearch').press('Enter');
  await page.locator('[data-link-business="biz1"]:not([disabled])').waitFor();
  const linkResponse=page.waitForResponse(r=>r.url().endsWith('/contenter') && r.request().method()==='PUT');
  await page.locator('[data-link-business="biz1"]').click();
  const linked=await linkResponse;assert.equal(linked.status(),200);
  assert.equal((await linked.json()).ai_usage_enabled,false);
  await page.locator('#contenterBusinessCard [data-contenter-action="profile"]').waitFor();
  assert.equal((await api(page,`/admin/api/assistants/${assistants[0]}/contenter`)).data.version,1);
  await page.locator('#contenterBusinessCard [data-contenter-action="sync"]').click();
  await page.locator('#contenterBusinessCard [data-contenter-action="sync"]:not([disabled])').waitFor();
  assert.equal((await api(page,`/admin/api/assistants/${assistants[0]}/contenter`)).data.version,1);

  for (const locale of ['fa','en','tr','ar','es','it','de','fr']) {
    await page.evaluate(locale=>window.setLanguage(locale),locale);
    const notice=await page.locator('#contenterBusinessCard .notice').innerText();
    assert(notice.length>40);
    if (!['fa','ar'].includes(locale)) assert(!/[پچژگک]/.test(notice),`Persian UI in ${locale}`);
    for (const width of [1440,900,390,320]) {
      await page.setViewportSize({width,height:900});
      await page.locator('#contenterBusinessCard [data-contenter-action="profile"]').click();
      const modal=page.locator('#modalRoot [role="dialog"]');
      await modal.waitFor();
      assert.equal(await modal.locator('img').count(),0,'Stored profile HTML executed');
      assert((await modal.innerText()).includes('<img src=x onerror=alert(1)>'));
      assert.equal(await modal.locator('.contenter-profile>section').count(),20);
      const bounds=await modal.boundingBox();
      assert(bounds.x>=-1 && bounds.x+bounds.width<=width+1,`Modal overflow: ${locale}/${width}`);
      await page.keyboard.press('Tab');
      assert(await modal.evaluate(node=>node.contains(document.activeElement)),'Focus left modal');
      await page.keyboard.press('Escape');
      assert.equal(await modal.count(),0);
    }
  }
  await page.setViewportSize({width:1440,height:900});
  await page.evaluate(()=>window.setLanguage('en'));
  await page.locator('.nav-btn[data-view="settings"]').click();
  await page.locator('#contenterTestBtn').waitFor();
  const connectionResponse=page.waitForResponse(r=>r.url().endsWith('/contenter/test'));
  await page.locator('#contenterTestBtn').click();
  assert.equal((await (await connectionResponse).json()).state,'healthy');
  await selectProject(assistants[1]);
  assert.equal(await page.locator('#contenterBusinessCard [data-contenter-action="profile"]').count(),0);
  assert(!(await page.locator('#contenterBusinessCard').innerText()).includes('Synthetic Researcher Business'));
  await selectProject(assistants[0]);
  await page.locator('#contenterBusinessCard [data-contenter-action="profile"]').waitFor();

  // Real account sessions, not client-side role substitution.
  for (const role of ['viewer','editor']) {
    const user=`contenter-${role}-${Date.now()}`,pass='synthetic-contenter-test-password';
    const result=await api(page,'/admin/api/users','POST',{username:user,password:pass,role,assistant_ids:[assistants[0]]});
    assert.equal(result.status,200);users.push(result.data.id);
    const context=await browser.newContext({viewport:{width:1440,height:900}});contexts.push(context);
    const member=await context.newPage();member.on('pageerror',error=>errors.push(error.message));
    await login(member,user,pass);
    const own=`/admin/api/assistants/${assistants[0]}/contenter`,other=`/admin/api/assistants/${assistants[1]}/contenter`;
    assert.equal((await api(member,own)).status,200);
    assert.equal((await api(member,other)).status,403);
    assert.equal((await api(member,'/admin/api/contenter/status')).status,403);
    assert.equal((await api(member,'/admin/api/contenter/test','POST')).status,403);
    assert.equal((await api(member,own+'/businesses')).status,role==='viewer'?403:200);
    assert.equal((await api(member,own+'/sync','POST')).status,role==='viewer'?403:200);
    assert.equal((await api(member,other+'/sync','POST')).status,403);
    if(role==='editor') {
      await member.locator('.nav-btn[data-view="businesses"]').click();
      await member.locator('#contenterBusinessCard [data-contenter-action="choose"]').waitFor();
      assert.equal(await member.locator('#contenterConnectionCard').isVisible(),false);
    }
    await context.close();
  }
  await page.locator('#contenterBusinessCard [data-contenter-action="unlink"]').click();
  await page.waitForFunction(()=>!document.querySelector('#contenterBusinessCard [data-contenter-action="profile"]'));
  assert.equal((await api(page,`/admin/api/assistants/${assistants[0]}/contenter`)).data.linked,false);
  // Current/future businesses use the same dynamic list, not a hard-coded catalog.
  const catalog=await api(page,`/admin/api/assistants/${assistants[0]}/contenter/businesses`);
  assert.equal(catalog.status,200);
  assert(catalog.data.items.some(item=>item.id==='biz2'),'Business created after startup is missing');
  assert.equal(errors.length,0,`Browser errors: ${errors.join('; ')}`);
  console.log('Contenter browser E2E passed: actual HTTPS APIs, search/connect/sync/unlink, profile escaping, 8 locales × 4 widths, keyboard modal, per-project isolation and real viewer/editor sessions.');
} catch (error) {
  console.error('Isolated browser diagnostics:', JSON.stringify({errors,loginError:await page.locator('#loginMsg').textContent().catch(()=>null)}));
  throw error;
} finally {
  for (const id of users) await api(page,`/admin/api/users/${id}`,'DELETE');
  for (const id of assistants) await api(page,`/admin/api/assistants/${id}`,'DELETE');
  for (const context of contexts) await context.close();
  await browser.close();
}
