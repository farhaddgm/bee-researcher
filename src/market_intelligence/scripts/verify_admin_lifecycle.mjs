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
