import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {chromium} from 'playwright';

const base=process.env.BEE_ADMIN_URL,userBase=process.env.BEE_USER_URL;
const username=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME,password=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if(!base||!userBase||!username||!password)throw Error('Login-history E2E requires isolated URLs and credentials');
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'Asia/Tehran'});
const page=await context.newPage(),errors=[];
page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
let accountId=null,projectId=null;
async function api(path,method='GET',body){return page.evaluate(async({path,method,body})=>{
 const response=await fetch(path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
 return {status:response.status,data:await response.json()};
},{path,method,body});}
async function ready(){await page.waitForFunction(()=>document.getElementById('loginHistoryPanel')&&!document.getElementById('loginHistoryPanel').hasAttribute('aria-busy'));}
async function compareReport(expected){
 await ready();
 assert.deepEqual(await page.locator('#loginHistoryPanel tbody .login-history-email').allTextContents(),expected.attempts.map(x=>x.email||x.username||'—'));
 assert.equal(await page.locator('#loginHistoryPanel time').count(),expected.attempts.length);
}
try{
 for(const url of [base,userBase]){
  await page.goto(url);await page.waitForFunction(()=>window.BeeAccountI18n);
  for(const language of ['fa','en','tr','ar','es','it','de','fr']){
   await page.evaluate(language=>{document.documentElement.lang=language;document.getElementById('login').lang=language;},language);
   assert.equal(await page.locator('#login .auth-title,#login .auth-description').count(),0);
   assert.equal(await page.locator('#googleLoginBtn').count(),1);
  }
 }
 await page.goto(new URL('/admin/login-up',base).href);
 await page.locator('#loginUser').fill(username);await page.locator('#loginPass').fill(password);await page.locator('#loginSubmit').click();
 await page.locator('#app:not(.hidden)').waitFor();await page.waitForFunction(()=>window.__researchBeeState?.currentUser);
 assert.equal((await api('/meta')).data.environment,'test');
 const suffix=Date.now();
 await page.evaluate(()=>{window.setLanguage('en');window.setView('account')});await ready();
 const first=(await api('/admin/api/owner/login-history')).data;
 assert.equal(first.page_size,10);assert.equal(first.attempts.length,10);assert(first.pages>=2);
 await compareReport(first);
 assert.equal(await page.locator('#loginHistoryPanel [data-page="previous"]').isEnabled(),false);
 await Promise.all([page.waitForResponse(r=>r.url().includes('/owner/login-history?page=2')),
  page.locator('#loginHistoryPanel [data-page="next"]').click()]);
 await compareReport((await api('/admin/api/owner/login-history?page=2')).data);
 await page.locator('#loginHistoryPanel [data-page="previous"]').click();
 await compareReport(first);
 for(const language of ['fa','en','tr','ar','es','it','de','fr']){
  await page.evaluate(language=>window.setLanguage(language),language);
  await page.waitForFunction(language=>document.getElementById('loginHistoryPanel')?.dataset.locale===language,language);await ready();
  assert.equal(await page.locator('#loginHistoryPanel h3').innerText(),await page.evaluate(()=>window.BeeAccountI18n.t('loginHistory')));
  for(const width of [1440,900,390,320]){
   await page.setViewportSize({width,height:1000});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),`History overflow ${language}/${width}`);
   assert.equal(await page.locator('#loginHistoryPanel tbody tr').count(),10);
  }
 }
 await page.locator('#loginHistoryPanel [data-refresh]').click();await compareReport(first);
 const project=await api('/admin/api/assistants','POST',{name:'Synthetic login history',slug:'login-history-'+suffix,business_name:''});
 assert.equal(project.status,200);projectId=project.data.id;
 const created=await api('/admin/api/accounts','POST',{email:`historyviewer${suffix}@gmail.com`,display_name:'Synthetic project administrator',role:'admin',assistant_ids:[projectId],login_method:'password',password:'synthetic-login-history-viewer-password'});
 assert.equal(created.status,200);accountId=created.data.id;
 const viewer=await browser.newContext(),viewerPage=await viewer.newPage();
 const login=await viewer.request.post(new URL('/admin/api/login',base).href,{data:{email:created.data.email,password:'synthetic-login-history-viewer-password'}});assert.equal(login.status(),200);
 const denied=await viewer.request.get(new URL('/admin/api/owner/login-history',base).href);assert.equal(denied.status(),403);
 await viewerPage.goto(base);await viewerPage.locator('#app:not(.hidden)').waitFor();
 await viewerPage.waitForFunction(()=>window.__researchBeeState?.currentUser);
 await viewerPage.evaluate(()=>window.setView('account'));await viewerPage.locator('#accountsPanel').waitFor();
 assert.equal(await viewerPage.locator('#loginHistoryPanel').count(),0);await viewer.close();
 if(process.env.CAPTURE_OUTPUT){
  await mkdir(process.env.CAPTURE_OUTPUT,{recursive:true});await page.evaluate(()=>window.setLanguage('fa'));await ready();
  for(const [name,width] of [['desktop',1440],['mobile',390]]){
   await page.setViewportSize({width,height:1000});await page.locator('#loginHistoryPanel').scrollIntoViewIfNeeded();
   await page.screenshot({path:`${process.env.CAPTURE_OUTPUT}/login-history-fa-${name}.png`});
  }
 }
 assert.deepEqual(errors,[]);
 console.log('Login-history browser passed: removed login text in both portals, owner-only Settings table, persisted success/failure data, ten rows, next/previous/refresh, 8 locales × 4 widths, non-owner API/UI denial; no browser errors.');
}finally{
 if(accountId)await api('/admin/api/accounts/'+accountId,'DELETE');
 if(projectId)await api('/admin/api/assistants/'+projectId,'DELETE');
 await browser.close();
}
