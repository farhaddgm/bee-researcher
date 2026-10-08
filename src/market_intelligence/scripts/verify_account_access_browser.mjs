import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base=process.env.BEE_ADMIN_URL,userBase=process.env.BEE_USER_URL;
const username=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME,password=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if(!base||!userBase||!username||!password)throw Error('Account E2E requires isolated URLs and credentials');
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
page.setDefaultTimeout(15000);
const errors=[],userIds=[],projects=[];
page.on('pageerror',e=>errors.push(e.message));
async function api(path,method='GET',body){return page.evaluate(async({path,method,body})=>{
 const csrf=document.cookie.split('; ').find(x=>x.startsWith('research_bee_admin_csrf='))?.split('=').slice(1).join('=');
 const response=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},...(body?{body:JSON.stringify(body)}:{})});
 return {status:response.status,data:await response.json()};
},{path,method,body});}
async function login(){await page.goto(new URL('/admin/login-up',base).href);await page.locator('#loginUser').fill(username);await page.locator('#loginPass').fill(password);await page.locator('#loginSubmit').click();await page.locator('#app:not(.hidden)').waitFor();await page.waitForFunction(()=>window.__researchBeeState?.currentUser);}
try{
 for(let attempt=0;attempt<60;attempt++){const ready=await page.request.get(new URL('/health',base).href).catch(()=>null);if(ready?.ok())break;assert(attempt<59,'Isolated app never became healthy');await page.waitForTimeout(250);}
 // Server decides the login mode even before JavaScript executes.
 const noJS=await browser.newContext({javaScriptEnabled:false});const plain=await noJS.newPage();
 for(const url of [base,userBase]){await plain.goto(url);assert.equal(await plain.locator('#loginForm').evaluate(n=>getComputedStyle(n).display),'none');assert.equal(await plain.locator('#googleLoginBtn').count(),1);}
 await noJS.close();
 for(const url of [base,userBase]){
  await page.goto(url);await page.waitForFunction(()=>window.BeeAccountI18n);
  for(const language of ['fa','en','tr','ar','es','it','de','fr']){
   await page.evaluate(language=>{document.documentElement.lang=language;document.documentElement.dir=['fa','ar'].includes(language)?'rtl':'ltr';document.getElementById('login').lang=language;},language);
   await page.waitForFunction(()=>document.querySelector('#googleLoginBtn span')?.textContent===window.BeeAccountI18n.t('google'));
   for(const width of [1440,900,390,320]){
    await page.setViewportSize({width,height:1000});assert.equal(await page.locator('#loginForm').isVisible(),false);
    const bounds=await page.locator('#googleLoginBtn').boundingBox();assert(bounds.height>=44&&bounds.x>=-1&&bounds.x+bounds.width<=width+1,`Login overflow ${language}/${width}`);
   }
  }
 }
 await page.setViewportSize({width:1440,height:1000});await login();
 const meta=await api('/meta');assert.equal(meta.data.environment,'test');assert.equal(meta.data.pipeline.scheduler_enabled,false);
 assert.equal(meta.data.session_idle_minutes,30);assert.equal(meta.data.session_absolute_hours,12);
 const created=await api('/admin/api/assistants','POST',{name:'Synthetic account UI',slug:'account-ui-'+Date.now(),business_name:''});assert.equal(created.status,200);projects.push(created.data.id);
 await page.evaluate(()=>window.loadAll());await page.evaluate(()=>{window.setLanguage('en');window.setView('account')});await page.locator('#accountsPanel').waitFor();
 assert.equal(await page.locator('#accountsPanel h3').innerText(),'Accounts and access');
 assert.equal(await page.locator('#userRows').isVisible(),false,'Old directory still displayed');
 for(const language of ['fa','en','tr','ar','es','it','de','fr']){
  await page.evaluate(language=>window.setLanguage(language),language);await page.waitForFunction(language=>document.getElementById('accountsPanel')?.dataset.locale===language,language);await page.waitForTimeout(200);
  for(const width of [1440,900,390,320]){
   await page.setViewportSize({width,height:1000});
   await page.locator('#accountsPanel .accounts-head .primary').click();await page.locator('dialog.accounts-dialog[open]').waitFor();
   const dialog=page.locator('dialog.accounts-dialog'),box=await dialog.boundingBox();
   assert(box.x>=-1&&box.x+box.width<=width+1,`Account dialog overflow ${language}/${width}`);
   assert(await dialog.evaluate(n=>n.scrollWidth<=n.clientWidth+1),`Account form overflow ${language}/${width}`);
   assert.equal(await dialog.locator('#account-password').isVisible(),false,'Google-only password field shown');
   await dialog.locator('#account-method').selectOption('both');assert(await dialog.locator('#account-password').isVisible());
   await dialog.locator('#account-name').focus();await page.keyboard.press('Shift+Tab');assert(await dialog.evaluate(n=>n.contains(document.activeElement)));
   await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});
   assert(await page.locator('#accountsPanel .accounts-head .primary').evaluate(n=>n===document.activeElement),'Dialog did not restore focus');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),`Account page overflow ${language}/${width}`);
  }
 }
 await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>window.setLanguage('en'));
 await page.locator('#accountsPanel .accounts-head .primary').click();const dialog=page.locator('dialog.accounts-dialog');
 const email='uiaccount'+Date.now()+'@gmail.com';await dialog.locator('#account-name').fill('Account <b>not markup</b>');await dialog.locator('#account-address').fill(email);
 await dialog.locator('input[type=checkbox][value="'+projects[0]+'"]').check();
 const checks=dialog.locator('fieldset').last().locator('input');await checks.nth(0).check();await checks.nth(1).check();
 const saving=page.waitForResponse(r=>r.url().endsWith('/admin/api/accounts')&&r.request().method()==='POST');
 await dialog.locator('button[type=submit]').click();const response=await saving;assert.equal(response.status(),200);const item=await response.json();userIds.push(item.id);await dialog.waitFor({state:'detached'});
 const row=page.locator('#accountsPanel tbody tr').filter({hasText:email});await row.waitFor();assert.equal(await row.locator('b').count(),0);
 await row.getByRole('button',{name:'Edit',exact:true}).click();
 await page.locator('#account-method').selectOption('both');await page.locator('#account-password').fill('violet herons cross mountain lakes');
 const updating=page.waitForResponse(r=>r.url().endsWith('/admin/api/accounts/'+item.id)&&r.request().method()==='PATCH');
 await page.locator('dialog button[type=submit]').click();assert.equal((await updating).status(),200);await page.locator('dialog').waitFor({state:'detached'});
 const saved=(await api('/admin/api/accounts?q='+email)).data.accounts[0];assert(saved.user_portal_access&&saved.user_feedback_access&&saved.has_password&&saved.assistant_ids.includes(projects[0]));
 await page.locator('#accountsPanel .accounts-search').fill('no-such-account-'+Date.now());await page.waitForFunction(()=>document.querySelector('#accountsPanel tbody td[colspan]'));
 await page.locator('#accountsPanel .accounts-search').fill(email);await row.waitFor();
 await row.getByRole('button',{name:'Revoke Google sign-in',exact:true}).click();await page.locator('dialog button').first().click();await page.locator('dialog').waitFor({state:'detached'});
 assert.equal((await api('/admin/api/accounts?q='+email)).data.accounts[0].login_method,'both','Cancel changed permissions');
 await row.getByRole('button',{name:'Delete account',exact:true}).click();const deletion=page.waitForResponse(r=>r.url().endsWith('/admin/api/accounts/'+item.id)&&r.request().method()==='DELETE');await page.locator('dialog button.danger').click();assert.equal((await deletion).status(),200);await row.waitFor({state:'detached'});userIds.length=0;
 assert.deepEqual(errors,[]);
 console.log('Account browser passed: pre-JS Google-only login, both portals, 8 locales × 4 widths, native dialog focus/Escape, fields, real create/edit/search/delete, permission grants and escaped names; no browser errors.');
}finally{
 for(const id of userIds)await api('/admin/api/accounts/'+id,'DELETE');
 for(const id of projects)await api('/admin/api/assistants/'+id,'DELETE');
 await browser.close();
}
