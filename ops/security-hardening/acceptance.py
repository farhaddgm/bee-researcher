import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import sys
import time
import urllib.request

SOURCE=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('release',SOURCE/'ops/security-hardening/release.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def python_job(program, *, ident=None, extra=None):
    values=r.prepared_env(test=True);values.update(extra or {})
    path=r.PRIVATE/'acceptance.env';r.env_file(path,values)
    return r.run(['docker','run','--rm','--network',r.TEST_NET,'--env-file',str(path),
        '--read-only','--memory','768m','--tmpfs','/tmp:size=64m,mode=1777','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--entrypoint','python','-i',ident or r.image(),'-'],input=program,timeout=600)

def accounts():
    result=r.app_command("import runpy;runpy.run_path('scripts/verify_account_access_sql.py',run_name='__main__')",test=True)
    r.write(r.ART/'account-access-tests.log',result)
    result=r.app_command("import runpy;runpy.run_path('scripts/verify_account_migration.py',run_name='__main__')",test=True,migrate=True)
    r.write(r.ART/'migration-floor-tests.log',result)
    r.write(r.ART/'account-access-passed.json',{'image_id':r.image(),'signed_oidc_pkce_state':True,'project_and_account_permissions':True,'permanent_journal_floor':True})
    print('PASS: full SQL/API/Google OIDC integration and permanent migration floor.',flush=True)

def rollback():
    program='''import asyncio,hashlib,runpy,uuid
runpy.run_path('security-rollback.py',run_name='compatibility_test')
from app import admin
from app.config import get_settings
from app.database import SessionLocal,engine
from app.models import AdminUser
from sqlalchemy import select,delete
from fastapi.testclient import TestClient
from app.main import app
cfg=get_settings()
assert cfg.environment=='test' and not cfg.scheduler_enabled and not cfg.google_login_ready and not cfg.telegram_ready
async def check():
 async with SessionLocal() as s:
  owner=await s.scalar(select(AdminUser).where(AdminUser.username=='security-fixture-owner'))
  assert owner.password_hash.startswith('scrypt$v2$')
 await engine.dispose()
asyncio.run(check())
salt=b'rollback-fixture';password='violet herons cross mountain lakes'
legacy='scrypt$'+salt.hex()+'$'+hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1).hex()
assert admin._check_password(password,legacy)
assert not admin._check_password('incorrect',legacy)
assert admin._check_password(password,admin._hash_password(password))
with TestClient(app,base_url='https://testserver') as c:
 for portal in ('admin','user'):
  response=c.post('/'+portal+'/api/login',json={'username':'security-fixture-owner','password':password})
  assert response.status_code==200,(portal,response.status_code)
  assert c.get('/'+portal+'/api/me').status_code==200
print('PASS: previous application on migrated DB, legacy+v2 hashes and both actual portal logins; no schema downgrade.')
'''
    result=python_job(program,ident=r.rollback_image())
    r.write(r.ART/'rollback-login-tests.log',result)
    print('PASS: rollback image accepts legacy and upgraded hashes in both portals.',flush=True)

def pressure():
    name='bee-researcher-security-test-pressure'
    r.run(['docker','run','-d','--name',name,'--network',r.TEST_NET,'--memory','64m','--read-only',
        '--user','999:999','--tmpfs','/data:size=16m,uid=999,gid=999','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '-v',str(r.PRIVATE/'redis.acl')+':/usr/local/etc/redis/users.acl:ro',
        '-v',str(SOURCE/'ops/security-hardening/redis.conf')+':/usr/local/etc/redis/redis.conf:ro',
        'redis:7.4.9-alpine','redis-server','/usr/local/etc/redis/redis.conf','--maxmemory','8mb','--appendonly','no','--save',''])
    try:
        program='''import asyncio
from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from app.config import get_settings
from app.security_controls import login_attempts_exceeded,login_attempt_key
async def main():
 cfg=get_settings();client=Redis.from_url(cfg.redis_url,decode_responses=True)
 assert not await login_attempts_exceeded(cfg,'pressure-account','pressure-ip')
 key=login_attempt_key(cfg,'pressure-account','pressure-ip')
 for i in range(1000):
  try:await client.set('market-intelligence:pressure:'+str(i),'x'*32768)
  except ResponseError as e:
   assert 'memory' in str(e).lower();break
 else:raise AssertionError('fixture did not reach memory pressure')
 assert int(await client.get(key))>=1
 try:await login_attempts_exceeded(cfg,'new-pressure-account','new-pressure-ip')
 except HTTPException as e:assert e.status_code==503
 else:raise AssertionError('authentication must fail closed under memory pressure')
 assert int(await client.get(key))>=1
 await client.aclose()
 print('PASS: noeviction retains counters at memory limit and admission fails closed with 503.')
asyncio.run(main())'''
        result=python_job(program,extra={'MARKET_INTELLIGENCE_REDIS_HOST':name})
        r.write(r.ART/'redis-memory-pressure-tests.log',result)
        print('PASS: Redis memory pressure retains counters and blocks authentication.',flush=True)
    finally:r.run(['docker','rm','-f',name])

def transfer():
    old='bee-researcher-security-test-old-redis'
    r.run(['docker','run','-d','--name',old,'--network',r.TEST_NET,'--memory','64m','--read-only',
        '--user','999:999','--tmpfs','/data:size=16m,uid=999,gid=999','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        'redis:7.4.9-alpine','redis-server','--save','','--appendonly','no'])
    tree=ast.parse((SOURCE/'ops/security-hardening/release.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='copy_redis')
    program=next(n.value.value for n in function.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='program' for t in n.targets))
    a={'host':old,'db':2};b={'host':r.TEST_REDIS,'db':2,'username':'migration','password':r.credentials()['redis_operator_password']}
    values={'COPY_SOURCE':json.dumps(a),'COPY_DESTINATION':json.dumps(b)}
    try:
        python_job('''import asyncio
from redis.asyncio import Redis
async def main():
 a=Redis(host='''+repr(old)+''',db=2)
 await a.set('market-intelligence:telegram-offset','8181')
 await a.set('market-intelligence:delivery-once','sent',px=120000)
 await a.set('another-service:sentinel','untouched')
 await a.aclose()
asyncio.run(main())''')
        forward=json.loads(python_job(program,extra=values))
        python_job('''import asyncio,json,os
from redis.asyncio import Redis
async def main():
 b=Redis(**json.loads(os.environ['COPY_DESTINATION']))
 assert await b.get('market-intelligence:telegram-offset')==b'8181'
 assert 0<await b.pttl('market-intelligence:delivery-once')<120000
 await b.set('market-intelligence:telegram-offset','8282')
 await b.delete('market-intelligence:delivery-once')
 await b.set('market-intelligence:new-delivery','done',px=60000)
 await b.aclose()
asyncio.run(main())''',extra=values)
        reverse=json.loads(python_job(program,extra={'COPY_SOURCE':json.dumps(b),'COPY_DESTINATION':json.dumps(a)}))
        python_job('''import asyncio,json,os
from redis.asyncio import Redis
async def main():
 a=Redis(**json.loads(os.environ['COPY_SOURCE']))
 assert await a.get('market-intelligence:telegram-offset')==b'8282'
 assert await a.get('market-intelligence:delivery-once') is None
 assert await a.get('market-intelligence:new-delivery')==b'done'
 assert 0<await a.pttl('market-intelligence:new-delivery')<60000
 assert await a.get('another-service:sentinel')==b'untouched'
 await a.aclose()
asyncio.run(main())''',extra=values)
        r.write(r.ART/'redis-transfer-tests.json',{'forward':forward,'reverse':reverse,'offset_and_idempotency_preserved':True,'ttl_not_reset':True,'unrelated_namespace_unchanged':True,'production_transfer_code_executed':True})
        print('PASS: actual state transfer code round-trip preserves offsets, TTL, deletions and unrelated keys.',flush=True)
    finally:r.run(['docker','rm','-f',old])
    r.write(r.ART/'rollback-tested.json',{'image_id':r.image(),'rollback_image_id':r.rollback_image(),'both_portals':True,'legacy_and_v2_hashes':True,'redis_round_trip':True})

def browser():
    name='bee-researcher-security-test-web'
    values=r.prepared_env(test=True);values['MARKET_INTELLIGENCE_ADMIN_COOKIE_SECURE']='false'
    path=r.PRIVATE/'browser.env';r.env_file(path,values)
    r.run(['docker','run','-d','--name',name,'--network',r.TEST_NET,'--env-file',str(path),
        '--read-only','--memory','768m','--tmpfs','/tmp:size=64m,mode=1777',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true',r.image()])
    target=r.inspect(name)['NetworkSettings']['Networks'][r.TEST_NET]['IPAddress']
    try:
        for i in range(60):
            try:
                with urllib.request.urlopen('http://'+target+':8010/health',timeout=2) as response:
                    if response.status==200:break
            except Exception:time.sleep(0.5)
        else:raise RuntimeError('isolated browser fixture unavailable')
        dependencies=r.ART/'browser-deps'
        shutil.copytree('/tmp/bee-context-browser-deps-vjtSRcka/playwright-core',dependencies/'playwright-core',dirs_exist_ok=True)
        runner=r.inspect('mcr.microsoft.com/playwright:v1.55.1-noble')['Id']
        result=r.run(['docker','run','--rm','--network',r.TEST_NET,'--memory','1g','--cpus','2',
            '--read-only','--tmpfs','/tmp:size=256m,mode=1777','--cap-drop','ALL','--security-opt','no-new-privileges:true',
            '-v',str(dependencies)+':/browser-deps:ro',
            '-v',str(SOURCE/'ops/security-hardening/browser.mjs')+':/checks/browser.mjs:ro',
            '-e','BEE_PLAYWRIGHT_MODULE=/browser-deps/playwright-core/index.mjs',
            '-e','BEE_HARDENING_URL=http://'+name+':8010',runner,'node','/checks/browser.mjs'],timeout=180)
        r.write(r.ART/'browser-tests.log',result)
        r.write(r.ART/'browser-passed.json',{'image_id':r.image(),'both_portals':True,'csrf_real_mutations':True,'desktop_mobile':True,'external_requests_blocked':True,'runner_image_id':runner,'external_network':False})
        print(result.strip(),flush=True)
    finally:
        r.run(['docker','rm','-f',name])

if __name__=='__main__':
    try:globals()[sys.argv[1]]()
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),flush=True)
        raise SystemExit(1) from None
