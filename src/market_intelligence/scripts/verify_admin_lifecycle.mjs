/* Deterministic lifecycle contract: no browser, provider or credentials. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../app/admin_lifecycle.js', import.meta.url), 'utf8');
const window = {}, context = vm.createContext({window, performance});
vm.runInContext(source, context);
const lifecycle = window.BeeAdminLifecycle;
let actor='alice:one', calls=0, settles=0, resolve, reject;
window.setView = name => name;
window.loadAll = () => {calls++; return new Promise((yes,no) => {resolve=yes;reject=no;});};
lifecycle.register('test', ['loadAll'], {settled: () => {settles++;}});
lifecycle.install(['loadAll','setView'], () => actor);
const sameFunction=window.loadAll;
lifecycle.install(['loadAll','setView'], () => actor);
assert.equal(window.loadAll, sameFunction);
const a=window.loadAll(), b=window.loadAll();
assert.equal(a,b);await Promise.resolve();assert.equal(calls,1);
resolve('original-result');assert.equal(await a,'original-result');assert.equal(settles,1);
const stale=window.loadAll();await Promise.resolve();actor='alice:two';resolve('old');await stale;
assert.equal(settles,1,'A stale actor must not trigger another actor’s render hooks');
const failure=window.loadAll();await Promise.resolve();reject(Error('original failure'));
await assert.rejects(failure,/original failure/);
assert.equal(lifecycle.diagnostics().active_refreshes,0);
let events=[];
const dispose=lifecycle.register('replaceable',['setView'],{after:()=>events.push('old')});
lifecycle.register('replaceable',['setView'],{after:()=>events.push('new')});dispose();
lifecycle.register('faulty',['setView'],{after:()=>{throw Error('private text must not be logged');}});
lifecycle.register('async-faulty',['setView'],{after:()=>Promise.reject(Error('private text'))});
assert.equal(window.setView('sources'),'sources');await new Promise(setImmediate);
assert.deepEqual(events,['new']);assert.equal(lifecycle.diagnostics().hook_errors,2);
assert.ok(!JSON.stringify(lifecycle.diagnostics()).includes('private text'));
for(let i=0;i<150;i++)window.setView('topics');
await new Promise(setImmediate);assert.ok(lifecycle.diagnostics().samples.length<=100);
const other=window.loadAll();await Promise.resolve();const resolveOther=resolve;
actor='bob:one';const independent=window.loadAll();await Promise.resolve();
assert.notEqual(other,independent);resolve('new');resolveOther('old');await Promise.all([other,independent]);
assert.equal(lifecycle.diagnostics().active_refreshes,0);
console.log('Admin lifecycle contracts passed: ownership, disposal, idempotence, scope isolation, bounded profiling, errors and single-flight.');

// Authorization can legitimately choose the first accessible workspace.
// It must trigger fresh hooks without allowing an unrelated stale response.
actor='carol:';let authorizedHook=0;
lifecycle.register('authorization-result',['loadAll'],{after:()=>{authorizedHook++;}});
const initialLoad=window.loadAll();await Promise.resolve();actor='carol:default';
resolve({__beeLifecycleScope:actor});await initialLoad;assert.equal(authorizedHook,1);

const bootstrapSource=fs.readFileSync(new URL('../app/admin_workspace_bootstrap.js',import.meta.url),'utf8');
// Slow unrelated metadata must not keep authorized, rendered controls inert.
let releaseAuthorizedShell=0,finishMetadata;
const firstPaintState={currentUser:{id:'alice'},assistantId:'one',language:'en'};
const firstPaintContext=vm.createContext({state:firstPaintState,
  window:{__researchBeeReleaseLocale:()=>releaseAuthorizedShell++},
  req:path=>path==='/meta'?new Promise(resolve=>finishMetadata=resolve):Promise.resolve(
    path==='/admin/api/assistants'?{assistants:[{id:'one',name:'Authorized project'}]}:{}),
  localStorage:{getItem:()=>null},friendlyError:String,esc:String,
  $:()=>({}),renderAssistants:()=>{assert.equal(firstPaintState.projectListReady,true)}});
vm.runInContext(bootstrapSource,firstPaintContext);
const firstPaint=vm.runInContext('loadAll()',firstPaintContext);
await new Promise(setImmediate);
assert.equal(releaseAuthorizedShell,1,'Authorized first paint waited for metadata to become clickable');
firstPaintState.currentUser={id:'bob'};finishMetadata({});await firstPaint;
async function staleBootstrap(change){
  const state={currentUser:{id:'alice'},assistantId:'one',language:'en'};let finish;
  const req=path=>path==='/admin/api/assistants'?new Promise(yes=>finish=yes):Promise.resolve({});
  const context=vm.createContext({state,req,localStorage:{getItem:()=>null},friendlyError:String});
  vm.runInContext(bootstrapSource,context);
  const run=vm.runInContext('loadAll()',context);change(state);finish({assistants:[{id:'one',name:'Private old actor project'}]});
  await run;assert.equal(state.assistants,undefined);assert.equal(state.projectListReady,undefined);
}
await staleBootstrap(state=>state.currentUser={id:'bob'});
await staleBootstrap(state=>state.assistantId='two');
console.log('Canonical bootstrap contracts passed: no stale authorization paint on account or project change.');

const cacheState={currentUser:{id:'alice'},assistantId:'one'};
let requests=0, releaseRead;
const cacheWindow={req:async(path,options={})=>{requests++;if(path==='/slow')return new Promise(yes=>releaseRead=yes);return {requests};}};
const cacheContext=vm.createContext({window:cacheWindow,state:cacheState,document:{getElementById:()=>null}});
vm.runInContext(fs.readFileSync(new URL('../app/admin_ui_modules/55-admin-performance-guards.js',import.meta.url),'utf8'),cacheContext);
await cacheWindow.req('/items');await cacheWindow.req('/items');assert.equal(requests,1);
const read=cacheWindow.req('/slow');await cacheWindow.req('/write',{method:'POST'});releaseRead({old:true});await read;
const nextRead=cacheWindow.req('/slow');releaseRead({fresh:true});await nextRead;
assert.equal(requests,4,'An old read must not repopulate the cache after a mutation');
await cacheWindow.req('/items');cacheState.assistantId='two';await cacheWindow.req('/items');assert.equal(requests,6);
await cacheWindow.req('/admin/api/me');await cacheWindow.req('/admin/api/me');assert.equal(requests,8);
await cacheWindow.req('/items');await cacheWindow.req('/items',{coalesceGet:false});assert.equal(requests,10);
console.log('Admin read-cache contracts passed: mutation race, actor isolation, authentication freshness and explicit refresh.');

const pendingHttp=[];
const requestContext=vm.createContext({window:{},state:{currentUser:{id:'alice'}},authTransition:0,
  performance,AbortController:undefined,scoped:path=>path,requestHeaders:()=>({}),friendlyError:String,
  fetch:(path,options)=>new Promise(resolve=>pendingHttp.push({path,options,resolve}))});
const coreSource=fs.readFileSync(new URL('../app/admin_ui_modules/04-Independent.js',import.meta.url),'utf8');
vm.runInContext(coreSource.slice(coreSource.indexOf('const pendingGetRequests=new Map();'),coreSource.indexOf('// Authentication must have a bounded wait.')),requestContext);
const oldRead=vm.runInContext("req('/admin/api/support/tickets?limit=200')",requestContext);
const writing=vm.runInContext("req('/admin/api/support/tickets/one/messages',{method:'POST'})",requestContext);
const duringWrite=vm.runInContext("req('/admin/api/support/tickets?limit=200')",requestContext);
assert.equal(pendingHttp.length,3,'A mutation reused its pre-write GET');
const respond=(index,value)=>pendingHttp[index].resolve({status:200,ok:true,text:async()=>JSON.stringify(value)});
respond(1,{saved:true});await writing;
const afterWrite=vm.runInContext("req('/admin/api/support/tickets?limit=200')",requestContext);
assert.equal(pendingHttp.length,4,'Post-write refresh joined an in-flight pre-commit GET');
respond(0,{old:true});respond(2,{during:true});respond(3,{reply:'persisted'});
await oldRead;await duringWrite;assert.equal((await afterWrite).reply,'persisted');
console.log('Request coalescer contracts passed: writes detach both pre-write and during-write GET flights.');

let cacheWriteDone,readCount=0;
const commitWindow={req:async(path,options={})=>{
  if(options.method==='POST')return new Promise(resolve=>cacheWriteDone=resolve);
  readCount++;return {readCount};}};
vm.runInContext(fs.readFileSync(new URL('../app/admin_ui_modules/55-admin-performance-guards.js',import.meta.url),'utf8'),
  vm.createContext({window:commitWindow,state:cacheState,document:{getElementById:()=>null}}));
const commitWrite=commitWindow.req('/write',{method:'POST'});
await commitWindow.req('/read-during-write');cacheWriteDone({saved:true});await commitWrite;
await commitWindow.req('/read-during-write');assert.equal(readCount,2,'Cache retained a snapshot read before commit');

// /user uses the shared tooltip/toast presentation, not the admin registry.
// Executing the real controller must work without any admin globals.
const readerWindow={addEventListener(){}},readerDocument={
  documentElement:{classList:{add(){}}},addEventListener(){},
  getElementById:()=>null,querySelectorAll:()=>[]
};
vm.runInContext(fs.readFileSync(new URL('../app/backoffice_ui.js',import.meta.url),'utf8'),
  vm.createContext({window:readerWindow,document:readerDocument}));
assert.equal(readerWindow.__beeUiPresentation,true);
assert.equal(typeof readerWindow.__beeShowToast,'function');
assert.equal(readerWindow.BeeAdminLifecycle,undefined);
console.log('Shared reader presentation passed without an admin lifecycle dependency.');

// Competing first-paint/language transactions must never strand either
// visibility class. Late data hydration must not hide an exposed shell.
const classes=new Set(),timers=new Map(),frames=[];let timerId=0;
const localeWindow={setLanguage:language=>language},localeRoot={classList:{
  add:(...names)=>names.forEach(name=>classes.add(name)),
  remove:(...names)=>names.forEach(name=>classes.delete(name))}};
const localeContext=vm.createContext({window:localeWindow,state:{language:'en'},
  setLanguage:localeWindow.setLanguage,document:{documentElement:localeRoot,querySelectorAll:()=>[]},
  localStorage:{setItem(){},getItem:()=>null},console,
  setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),
  requestAnimationFrame:fn=>frames.push(fn)});
vm.runInContext(fs.readFileSync(new URL('../app/admin_ui_modules/48-MI-LOCALE-ATOMIC.js',import.meta.url),'utf8'),localeContext);
function flushLocale(){
  for(let i=0;timers.size||frames.length;i++){
    assert(i<20,'Locale release did not settle');
    const pending=[...timers.values()];timers.clear();for(const fn of pending)fn();
    const animation=frames.splice(0);for(const fn of animation)fn();
  }
}
localeWindow.__researchBeeReleaseLocale();localeWindow.setLanguage('tr');flushLocale();
assert.equal(classes.size,0,'Language switch stranded the pending shell');
localeWindow.__researchBeeReleaseLocale();
assert.equal(classes.has('locale-pending'),false,'Late bootstrap hid usable controls');flushLocale();
localeWindow.setLanguage('fa');localeWindow.__researchBeeReleaseLocale();flushLocale();
assert.equal(classes.size,0,'Shell release stranded the language switch');
assert.equal(localeRoot.lang,'fa');assert.equal(localeRoot.dir,'rtl');
classes.add('locale-pending');localeWindow.__researchBeeReleaseLocale();
assert.equal(classes.size,0,'Authorized shell release left a frame with pointer-inert controls');
console.log('Atomic locale contracts passed: overlapping transactions release both classes; late hydration never re-hides controls.');
