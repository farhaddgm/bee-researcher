import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const admin=process.env.BEE_ADMIN_URL,user=process.env.BEE_USER_URL;
const username=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME,password=process.env.MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD;
if(!admin||!user||!username||!password)throw Error('UI E2E requires isolated URLs and credentials');
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
page.setDefaultTimeout(15000);
const overflow=()=>page.evaluate(()=>Math.max(0,document.documentElement.scrollWidth-innerWidth));
try{
 await page.goto(admin,{waitUntil:'domcontentloaded'});
 await page.locator('#loginUser').fill(username);await page.locator('#loginPass').fill(password);await page.locator('#loginSubmit').click();
 await page.waitForFunction(()=>window.__researchBeeState?.currentUser);
 await page.locator('#app:not(.hidden)').waitFor();await page.waitForFunction(()=>window.__researchBeeState?.projectListReady);
 for(const language of ['en','fa','tr','ar','es','it','de','fr']){
  await page.evaluate(language=>window.setLanguage(language),language);
  for(const width of [1440,900,390,320]){
   await page.setViewportSize({width,height:1000});
   for(const view of ['assistants','overview','content','quality','businesses','sources','topics','schedule','template-content','operations','support','settings']){
    await page.evaluate(view=>window.setView(view),view);await page.waitForTimeout(120);
    assert(await overflow()<=2,`${language}/${view}/${width}: page overflow ${await overflow()}`);
   }
  }
  console.log(`UI viewport matrix verified: ${language}`);
 }
 await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>{window.setLanguage('en');window.setView('assistants');});
 const geometry=await page.locator('#view-assistants .page-head .actions>.btn').evaluateAll(nodes=>nodes.map(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height,font:getComputedStyle(n).fontSize,order:getComputedStyle(n).order,primary:n.classList.contains('primary')})));
 assert(new Set(geometry.map(x=>Math.round(x.width))).size>1,'Actions were assigned equal text widths');
 assert(geometry.every(x=>x.height>=40&&x.font==='13px'));
 assert.equal(geometry.find(x=>x.primary).order,'99');
 const cards=await page.locator('#assistantGrid .assistant-card').evaluateAll(nodes=>nodes.map(n=>({card:n.getBoundingClientRect().bottom,last:Math.max(...[...n.querySelectorAll('.card-actions .btn')].map(b=>b.getBoundingClientRect().bottom))})));
 assert(cards.every(x=>x.last<=x.card),'Card action protrudes');
 await page.evaluate(()=>window.__researchBeeAdminUxV325.markLoading(true));
 assert(await page.locator('#assistantGrid .admin-ux-skeleton').count()>=3,'Skeleton covers only two assistant cards');
 await page.evaluate(()=>window.__researchBeeAdminUxV325.markLoading(false));
 assert.equal(await page.locator('.admin-ux-skeleton-host').count(),0,'Loading left overflow-hidden hosts behind');
 await page.evaluate(()=>window.setView('sources'));
 await page.locator('#mobileToggle').click();assert.equal(await page.locator('.view.active').getAttribute('id'),'view-sources');assert(await overflow()<=2);
 await page.locator('#sidebarAccountTrigger').click();await page.locator('#sidebarAccountMenu:not([hidden])').waitFor();
 const labels=await page.locator('#sidebarAccountMenu [data-account-label]').evaluateAll(nodes=>nodes.map(n=>({text:n.textContent.trim(),width:n.getBoundingClientRect().width})));
 assert(labels.every(n=>n.text&&n.width>15),'Collapsed account menu lost its labels');
 await page.locator('#sidebarAccountTrigger').click();
 await page.locator('#mobileToggle').click();
 await page.evaluate(()=>{const img=document.createElement('img');img.src='data:image/png;base64,broken';document.getElementById('sidebarAccountAvatar').replaceChildren(img);});
 await page.waitForFunction(()=>document.querySelector('#sidebarAccountAvatar [data-avatar-initials]')?.textContent.trim());
 assert.equal(await page.locator('#sidebarAccountAvatar img').evaluate(n=>getComputedStyle(n).display),'none');
 await page.evaluate(()=>window.setView('support'));
 const widths=await page.locator('.support-v4-layout>.support-v4-card:not(.all)').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().width));assert(Math.abs(widths[0]-widths[1])<2,'Support columns unequal');
 await page.evaluate(()=>{document.documentElement.dataset.theme='dark';});
 assert.notEqual(await page.locator('#supportV4Category').evaluate(n=>getComputedStyle(n).backgroundColor),'rgb(255, 255, 255)');
 await page.evaluate(()=>{document.documentElement.dataset.theme='light';window.setView('content');window.__researchBeeState.publications=[];window.renderPublications();});
 const empty=page.locator('#publicationRows td[colspan]');assert.equal(Number(await empty.getAttribute('colspan')),await page.locator('#view-content thead th').count());
 assert(await empty.evaluate(n=>n.getBoundingClientRect().width)>500,'Empty state squeezed into checkbox column');
 for(const [view,button] of [['sources','#addSourceBtn'],['topics','#addTopicBtn']]){
  await page.evaluate(view=>window.setView(view),view);await page.locator(button).click();await page.locator('#modalRoot [role=dialog]').waitFor();
  await page.keyboard.press('Escape');await page.waitForFunction(()=>document.getElementById('modalRoot').classList.contains('hidden'));
 }
 await page.evaluate(()=>{window.setView('settings');});await page.setViewportSize({width:320,height:900});
 const help=page.locator('#view-settings .info-tip').first();await help.focus();await page.locator('#beeUiTooltip:not([hidden])').waitFor();
 const box=await page.locator('#beeUiTooltip').boundingBox();assert(box.x>=0&&box.x+box.width<=320);
 await page.keyboard.press('Escape');assert(await page.locator('#beeUiTooltip').evaluate(n=>n.hidden));
 assert.notEqual(await help.getAttribute('aria-describedby'),'beeUiTooltip','Dismissed help retains another field’s shared description');
 await page.evaluate(()=>window.toast('Safe test error',true));assert.equal(await page.locator('#toast').getAttribute('role'),'alert');await page.waitForTimeout(4600);assert(await page.locator('#toast').isVisible());await page.locator('#toast button').click();assert(await page.locator('#toast').evaluate(n=>n.classList.contains('hidden')));
 await page.setViewportSize({width:1440,height:1000});await page.goto(user+'/settings',{waitUntil:'domcontentloaded'});
 await Promise.race([page.locator('#login:not(.hidden)').waitFor({state:'visible'}),page.locator('#app:not(.hidden)').waitFor({state:'visible'})]);
 if(await page.locator('#login:not(.hidden)').isVisible()){await page.locator('#username').fill(username);await page.locator('#password').fill(password);await page.locator('#loginButton').click();}
 await page.locator('#settingsPanel:not(.hidden)').waitFor();
 for(const width of [1440,900,390,320]){
  await page.setViewportSize({width,height:1000});await page.waitForTimeout(250);assert(await overflow()<=2,`Reader settings overflow at ${width}`);
  const controls=await page.locator('#settingsPanel select').evaluateAll(nodes=>nodes.map(n=>({height:n.getBoundingClientRect().height,radius:getComputedStyle(n).borderRadius})));
  assert(controls.every(x=>x.height>=44&&x.radius==='10px'));
 }
 await page.locator('#settingsPanel .info-button').last().focus();await page.locator('#beeUiTooltip:not([hidden])').waitFor();await page.keyboard.press('Escape');
 assert.equal(await page.locator('#settingsPanel .setting').count(),9);
 await page.locator('#mobileMenuButton').click();await page.locator('#sidebar.open').waitFor();await page.locator('#sidebarOverlay').click({position:{x:310,y:700}});assert.equal(await page.locator('#sidebar.open').count(),0);
 await page.goto(user,{waitUntil:'domcontentloaded'});await page.locator('#app:not(.hidden)').waitFor();await page.waitForTimeout(250);assert(await overflow()<=2);
 assert.equal(errors.length,0,errors.join('\n'));
 console.log('Backoffice UI E2E passed: 8 locales × 4 widths × 12 admin views; buttons, cards, skeleton cleanup, collapse, support, dark fields, empty table, Add dialogs, keyboard/tap tooltips, persistent errors, 9 reader settings, mobile navigation; zero uncaught errors.');
}finally{await browser.close();}
