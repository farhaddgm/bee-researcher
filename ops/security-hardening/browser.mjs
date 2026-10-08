import assert from 'node:assert/strict';
const {chromium}=await import(process.env.BEE_PLAYWRIGHT_MODULE||'playwright');

const base=process.env.BEE_HARDENING_URL||'http://127.0.0.1:18039';
const browser=await chromium.launch({headless:true,executablePath:process.env.BEE_CHROMIUM_EXECUTABLE});
const page=await browser.newPage({viewport:{width:1280,height:900}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function signIn(portal){
  await page.goto(base+'/'+portal+'/login-up');
  await page.locator(portal==='admin'?'#loginUser':'#username').fill('security-fixture-owner');
  await page.locator(portal==='admin'?'#loginPass':'#password').fill('violet herons cross mountain lakes');
  await page.locator(portal==='admin'?'#loginSubmit':'#loginButton').click();
  await page.waitForFunction(()=>!document.getElementById('app')?.classList.contains('hidden'));
}
try{
  assert(['http://127.0.0.1:18039','http://bee-researcher-security-test-web:8010'].includes(new URL(base).origin),'Browser checks only permit the isolated fixture');
  assert.equal((await page.request.get(base+'/meta')).status(),401);
  await page.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
  await signIn('admin');
  const admin=await page.evaluate(async()=>{
    const meta=await (await fetch('/meta')).json();
    if(meta.environment!=='test')throw new Error('Browser checks require isolated test metadata');
    const changed=await fetch('/admin/api/account/preferences',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:'dark'})});
    return {environment:meta.environment,status:changed.status,idle:meta.session_idle_minutes,absolute:meta.session_absolute_hours};
  });
  assert.equal(admin.environment,'test');assert.equal(admin.status,200);assert.equal(admin.idle,30);assert.equal(admin.absolute,12);
  await signIn('user');
  const user=await page.evaluate(async()=>{
    const changed=await fetch('/user/api/preferences',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:'dark'})});
    const me=await fetch('/user/api/me');
    const csrf=document.cookie.split(';').some(x=>x.trim().startsWith('research_bee_user_csrf='));
    return {status:changed.status,me:me.status,csrf};
  });
  assert.equal(user.status,200);assert.equal(user.me,200);assert(user.csrf);
  for(const width of [1280,390]){
    await page.setViewportSize({width,height:900});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
  }
  const logout=await page.evaluate(async()=> (await fetch('/user/api/logout',{method:'POST'})).status);
  assert.equal(logout,200);
  assert.deepEqual(errors,[]);
  console.log('PASS: browser Admin/User password login, automatic signed CSRF on real mutations, idle/absolute metadata, User logout, desktop/mobile layout; no page errors or external providers.');
}finally{await browser.close();}
