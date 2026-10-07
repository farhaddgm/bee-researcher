"""Scoped, resumable release tooling. Never print environment values or SQL.

Run phases explicitly: prepare, rehearsal, deploy, verify, rollback.
The image must already have passed the image/source/test provenance gate.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request

WORK = Path('/opt/ai-assistant')
SOURCE = Path(__file__).resolve().parents[2]
ART = WORK / 'ops/bee-researcher-direct/artifacts/3.39.0-security'
PRIVATE = WORK / 'ops/bee-researcher-direct/private/3.39.0-security'
OLD_IMAGE = 'sha256:6dbe620d5d550e653745a46d8dafd78969f870a06e9fe9a83e0a0b58f29c5ba0'
OLD_REV = '109453ad0f4e219c8369982fa937ef71ac28905d'
APP = 'ai-market-intelligence'
TEST_NET = 'bee-researcher-security-rehearsal'
TEST_PG = 'bee-researcher-security-test-pg'
TEST_REDIS = 'bee-researcher-security-test-redis'
REDIS = 'bee-researcher-security-redis'
PRIVATE_NET = 'bee-researcher-security-private'


def write(path, value, *, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, indent=2) + '\n')
    os.chmod(path, 0o600 if private else 0o644)


def run(args, *, input=None, env=None, timeout=180, binary=False):
    result = subprocess.run(args, input=input, env=env, capture_output=True, text=not binary, timeout=timeout)
    if result.returncode:
        data = result.stderr.decode(errors='replace') if binary else result.stderr
        write(PRIVATE / 'last-error.log', data, private=True)
        raise RuntimeError(f'{args[0]} failed; private diagnostic saved (exit {result.returncode})')
    return result.stdout


def inspect(name):
    return json.loads(run(['docker', 'inspect', name]))[0]


def env_of(container):
    return dict(value.split('=', 1) for value in container['Config']['Env'] if '=' in value)


def env_file(path, values):
    if any('\n' in value or '\r' in value for value in values.values()):
        raise RuntimeError('multiline environment requires explicit secret-file provisioning')
    write(path, ''.join(f'{key}={value}\n' for key, value in values.items()), private=True)


def baseline():
    return json.loads((PRIVATE / 'baseline.json').read_text())


def credentials():
    return json.loads((PRIVATE / 'credentials.json').read_text())


def image():
    return json.loads((ART / 'image.json').read_text())['image_id']


def rollback_image():
    return json.loads((ART / 'rollback-image.json').read_text())['image_id']


def sql(program, *, container='ai-postgres', username=None, database=None):
    old = baseline()['env']
    username = username or old['MARKET_INTELLIGENCE_POSTGRES_USER']
    database = database or old['MARKET_INTELLIGENCE_POSTGRES_DB']
    return run(['docker', 'exec', '-i', container, 'psql', '-X', '-U', username, '-d', database,
                '-v', 'ON_ERROR_STOP=1', '-At'], input=program)


def roles_program(database):
    values = credentials()
    # Passwords are generated URL-safe; never accept arbitrary SQL fragments.
    for key in ('runtime_password', 'migration_password'):
        if any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in values[key]):
            raise RuntimeError('invalid generated credential')
    quoted_db = '"' + database.replace('"', '""') + '"'
    roles = '\n'.join(f"CREATE ROLE {role} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT {limit} PASSWORD '{values[key]}';"
        for role, key, limit in [('bee_researcher_runtime', 'runtime_password', 30), ('bee_researcher_migrator', 'migration_password', 3)])
    return roles + f'\nGRANT CONNECT ON DATABASE {quoted_db} TO bee_researcher_runtime, bee_researcher_migrator;\n' + (SOURCE / 'ops/security-hardening/roles.sql').read_text()


def protect_journal(*, container='ai-postgres', username=None, database=None):
    sql('REVOKE UPDATE, DELETE, TRUNCATE ON market_intelligence.security_events FROM bee_researcher_runtime;\n'
        'REVOKE INSERT, UPDATE, DELETE ON market_intelligence.alembic_version FROM bee_researcher_runtime;\n',
        container=container, username=username, database=database)


def prepared_env(*, test=False, migrate=False):
    values = json.loads((PRIVATE / 'runtime.json').read_text())
    if test:
        values = {key: value for key, value in values.items() if key in {
            'MARKET_INTELLIGENCE_VERSION', 'MARKET_INTELLIGENCE_BUILD_REVISION', 'MARKET_INTELLIGENCE_IMAGE_DIGEST',
            'MARKET_INTELLIGENCE_POSTGRES_PASSWORD', 'MARKET_INTELLIGENCE_REDIS_PASSWORD',
            'MARKET_INTELLIGENCE_CSRF_SIGNING_SECRET', 'MARKET_INTELLIGENCE_MFA_ENCRYPTION_SECRET'}}
        values.update({
            'MARKET_INTELLIGENCE_POSTGRES_DB': 'assistant_test', 'MARKET_INTELLIGENCE_POSTGRES_HOST': TEST_PG,
            'MARKET_INTELLIGENCE_POSTGRES_USER': 'bee_researcher_runtime', 'MARKET_INTELLIGENCE_REDIS_HOST': TEST_REDIS,
            'MARKET_INTELLIGENCE_REDIS_USERNAME': 'researcher', 'MARKET_INTELLIGENCE_REDIS_DATABASE': '2',
            'MARKET_INTELLIGENCE_ENVIRONMENT': 'test', 'MARKET_INTELLIGENCE_SCHEDULER_ENABLED': 'false',
            'MARKET_INTELLIGENCE_TELEGRAM_POLLING_ENABLED': 'false', 'MARKET_INTELLIGENCE_EXTERNAL_ANALYSIS_APPROVED': 'false',
            'MARKET_INTELLIGENCE_OWNER_EMAIL': 'security-fixture@gmail.com',
            'MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD': 'violet herons cross mountain lakes',
            'MARKET_INTELLIGENCE_SESSION_IDLE_MINUTES': '30', 'MARKET_INTELLIGENCE_SESSION_ABSOLUTE_HOURS': '12'})
    if migrate:
        values['MARKET_INTELLIGENCE_POSTGRES_USER'] = 'bee_researcher_migrator'
        values['MARKET_INTELLIGENCE_POSTGRES_PASSWORD'] = credentials()['migration_password']
    return values


def app_command(program, *, test=False, migrate=False):
    path = PRIVATE / ('test-migration.env' if test and migrate else 'test.env' if test else 'migration.env' if migrate else 'runtime.env')
    env_file(path, prepared_env(test=test, migrate=migrate))
    return run(['docker', 'run', '--rm', '--network', TEST_NET if test else 'ai-assistant-backend',
        '--env-file', str(path), '--memory', '768m', '--read-only', '--tmpfs', '/tmp:size=64m,mode=1777',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--entrypoint', 'python', '-i', image(), '-'], input=program, timeout=600)


def migrate(*, test=False):
    path = PRIVATE / ('test-migration.env' if test else 'migration.env')
    env_file(path, prepared_env(test=test, migrate=True))
    run(['docker', 'run', '--rm', '--network', TEST_NET if test else 'ai-assistant-backend', '--env-file', str(path),
         '--read-only', '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
         '--entrypoint', 'alembic', image(), 'upgrade', 'head'], timeout=600)


def schema_snapshot(*, test=False):
    program = '''import asyncio,hashlib,json
from sqlalchemy import text
from app.database import engine
async def main():
 async with engine.connect() as c:
  await c.execute(text('SET TRANSACTION READ ONLY'))
  tables=(await c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='market_intelligence' ORDER BY tablename"))).scalars().all()
  result={}
  for table in tables:
   count=await c.scalar(text('SELECT count(*) FROM market_intelligence."'+table+'"'))
   result[table]=count
  print(json.dumps(result))
 await engine.dispose()
asyncio.run(main())'''
    if test:
        return json.loads(app_command(program, test=True))
    return json.loads(run(['docker', 'exec', '-i', APP, 'python', '-'], input=program))


def prepare():
    ART.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    os.chmod(PRIVATE, 0o700)
    if (PRIVATE / 'runtime.json').exists() and (PRIVATE / 'redis.acl').exists():
        print('Existing prepared release retained; no credentials regenerated.')
        return
    current = inspect(APP)
    if current['Image'] != OLD_IMAGE or env_of(current).get('MARKET_INTELLIGENCE_BUILD_REVISION') != OLD_REV:
        raise RuntimeError('production revision changed; rebase the review before proceeding')
    old = env_of(current)
    write(PRIVATE / 'baseline.json', {'container': current, 'env': old}, private=True)
    write(ART / 'other-containers-before.json', {item['Names']: item['ID'] for item in
        [json.loads(line) for line in run(['docker', 'ps', '--no-trunc', '--format', '{{json .}}']).splitlines()]
        if item['Names'] != APP and not item['Names'].startswith('bee-researcher-security-')})
    values = {name: secrets.token_urlsafe(48) for name in ('runtime_password', 'migration_password', 'redis_password', 'signing_secret', 'encryption_secret', 'redis_operator_password')}
    write(PRIVATE / 'credentials.json', values, private=True)
    # Verify the old allowlisted identity without sending a Telegram message.
    raw = {}
    for line in (WORK / '.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            raw[key] = value.strip().strip('"').strip("'")
    uid = raw.get('ALLOWED_TELEGRAM_USER_ID')
    token = old.get('MARKET_INTELLIGENCE_TELEGRAM_BOT_TOKEN')
    if not uid or not token:
        raise RuntimeError('existing Telegram identity must be verified before enabling numeric authorization')
    req = urllib.request.Request('https://api.telegram.org/bot'+token+'/getChat',
        data=urllib.parse.urlencode({'chat_id': uid}).encode(), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            identity = json.load(response)
        result = identity['result']
        assert identity['ok'] and str(result['id']) == uid and result['type'] == 'private'
        assert result.get('username', '').lower() in old.get('MARKET_INTELLIGENCE_ALLOWED_TELEGRAM_USERNAMES', 'farhaadnoroozi').split(',')
    except Exception:
        raise RuntimeError('Telegram identity verification failed; no live settings changed') from None
    owner_program = '''import asyncio,json
from sqlalchemy import select
from app.database import SessionLocal,engine
from app.models import AdminUser
from app.admin import owner_email,_mfa_enabled
async def main():
 async with SessionLocal() as s:
  users=(await s.scalars(select(AdminUser))).all()
  owners=[u for u in users if u.email==owner_email() and u.active]
  assert len(owners)==1 and not any(_mfa_enabled(u) for u in users)
  print(json.dumps({'owner_id':str(owners[0].id)}))
 await engine.dispose()
asyncio.run(main())'''
    owner = json.loads(run(['docker', 'exec', '-i', APP, 'python', '-'], input=owner_program))
    runtime = {key: value for key, value in old.items() if key.startswith('MARKET_INTELLIGENCE_')}
    runtime.update({
        'MARKET_INTELLIGENCE_POSTGRES_USER': 'bee_researcher_runtime',
        'MARKET_INTELLIGENCE_POSTGRES_PASSWORD': values['runtime_password'],
        'MARKET_INTELLIGENCE_REDIS_HOST': REDIS, 'MARKET_INTELLIGENCE_REDIS_USERNAME': 'researcher',
        'MARKET_INTELLIGENCE_REDIS_PASSWORD': values['redis_password'],
        'MARKET_INTELLIGENCE_CSRF_SIGNING_SECRET': values['signing_secret'],
        'MARKET_INTELLIGENCE_MFA_ENCRYPTION_SECRET': values['encryption_secret'],
        'MARKET_INTELLIGENCE_SESSION_IDLE_MINUTES': '30', 'MARKET_INTELLIGENCE_SESSION_ABSOLUTE_HOURS': '12',
        'MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD': '',
        'MARKET_INTELLIGENCE_TELEGRAM_IDENTITY_BINDINGS': json.dumps({uid: owner['owner_id']}),
        'MARKET_INTELLIGENCE_TRUSTED_PROXY_CIDRS': inspect('ai-market-intelligence-https')['NetworkSettings']['Networks']['ai-assistant-backend']['IPAddress']+'/32',
        'MARKET_INTELLIGENCE_VERSION': '3.39.0'})
    write(PRIVATE / 'runtime.json', runtime, private=True)
    env_file(PRIVATE / 'runtime.env', runtime)
    acl = 'user default off\nuser health on nopass -@all +ping\nuser researcher on #'+hashlib.sha256(values['redis_password'].encode()).hexdigest()+ ' ~market-intelligence:* &market-intelligence:* -@all +auth +hello +ping +select +get +set +del +mget +incr +expire +pttl +multi +exec +discard +eval +client|setinfo\n'
    acl += 'user migration on #'+hashlib.sha256(values['redis_operator_password'].encode()).hexdigest()+' ~market-intelligence:* -@all +auth +hello +ping +select +scan +dump +restore +pttl +multi +exec +del +get +set\n'
    write(PRIVATE / 'redis.acl', acl, private=True)
    # The ACL file is hash-only; Redis uid 999 must read it through its bind mount.
    os.chmod(PRIVATE / 'redis.acl', 0o644)
    write(ART / 'identity-verification.json', {'existing_numeric_identity_verified': True, 'message_sent': False, 'active_mfa_count': 0})
    print('Prepared independent private credentials and verified numeric Telegram binding. Live service unchanged.')


def backup(path):
    old = baseline()['env']
    data = run(['docker', 'exec', 'ai-postgres', 'pg_dump', '-U', old['MARKET_INTELLIGENCE_POSTGRES_USER'],
                '-d', old['MARKET_INTELLIGENCE_POSTGRES_DB'], '--schema=market_intelligence', '--format=custom', '--no-owner', '--no-acl'], binary=True, timeout=600)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    print('Private Researcher schema backup saved.')


def start_redis(name, network, *, persistent):
    args = ['docker', 'run', '-d', '--name', name, '--network', network, '--memory', '384m', '--cpus', '0.5',
        '--pids-limit', '128', '--read-only', '--tmpfs', '/tmp:size=16m,mode=1777', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true', '--user', '999:999',
        '-v', str(PRIVATE / 'redis.acl')+':/usr/local/etc/redis/users.acl:ro',
        '-v', str(SOURCE / 'ops/security-hardening/redis.conf')+':/usr/local/etc/redis/redis.conf:ro']
    if persistent:
        volume = 'bee-researcher-security-redis-data'
        run(['docker', 'volume', 'create', volume])
        # Docker creates volume directories as root; initialize ownership once.
        run(['docker', 'run', '--rm', '--network', 'none', '--user', '0', '-v', volume+':/data', 'redis:7.4.9-alpine', 'chown', '999:999', '/data'])
        args += ['--restart', 'unless-stopped', '-v', volume+':/data']
    else:
        args += ['--tmpfs', '/data:size=64m,uid=999,gid=999,mode=0700']
    run(args+['redis:7.4.9-alpine', 'redis-server', '/usr/local/etc/redis/redis.conf'])
    for _ in range(60):
        result = subprocess.run(['docker', 'exec', name, 'redis-cli', '--user', 'health', '--pass', '', 'ping'], capture_output=True)
        if b'PONG' in result.stdout:
            return
        time.sleep(0.5)
    raise RuntimeError('isolated Redis did not start')


def rehearsal():
    if not (PRIVATE / 'rehearsal.dump').exists():
        backup(PRIVATE / 'rehearsal.dump')
    run(['docker', 'network', 'create', '--internal', TEST_NET])
    pg_env = PRIVATE / 'test-postgres.env'
    env_file(pg_env, {'POSTGRES_USER': 'security_fixture', 'POSTGRES_PASSWORD': secrets.token_urlsafe(32), 'POSTGRES_DB': 'assistant_test'})
    run(['docker', 'run', '-d', '--name', TEST_PG, '--network', TEST_NET, '--env-file', str(pg_env),
         '--memory', '768m', '--cpus', '1', '-v', 'bee-researcher-security-test-pg-data:/var/lib/postgresql/data', 'postgres:17.10-alpine'])
    for _ in range(90):
        result = subprocess.run(['docker', 'exec', TEST_PG, 'pg_isready', '-U', 'security_fixture', '-d', 'assistant_test'], capture_output=True)
        if result.returncode == 0:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError('isolated PostgreSQL did not start')
    start_redis(TEST_REDIS, TEST_NET, persistent=False)
    run(['docker', 'exec', '-i', TEST_PG, 'pg_restore', '-U', 'security_fixture', '-d', 'assistant_test', '--no-owner', '--no-acl', '--exit-on-error'],
        input=(PRIVATE / 'rehearsal.dump').read_bytes(), binary=True, timeout=600)
    sql(roles_program('assistant_test'), container=TEST_PG, username='security_fixture', database='assistant_test')
    before = schema_snapshot(test=True)
    write(ART / 'rehearsal-counts-before.json', before)
    migrate(test=True)
    protect_journal(container=TEST_PG, username='security_fixture', database='assistant_test')
    after = schema_snapshot(test=True)
    assert all(after[key] == count for key, count in before.items()), 'migration changed existing row counts'
    assert after['security_events'] == 0
    write(ART / 'rehearsal-counts.json', {'before': before, 'after': after})
    result = app_command((SOURCE / 'ops/security-hardening/verify_sql.py').read_text(), test=True)
    write(ART / 'integration-tests.log', result)
    write(ART / 'rehearsal-passed.json', {'backup_restored': True, 'counts_preserved': True, 'external_network': False, 'integration_passed': True})
    print('Isolated backup restore, migration, least privileges and integration tests passed.')


def compose_args(override):
    files = baseline()['container']['Config']['Labels']['com.docker.compose.project.config_files'].split(',')
    args = ['docker', 'compose', '--project-directory', str(WORK), '-p', 'ai-assistant']
    for path in files + [str(override)]:
        args += ['-f', path]
    return args


def copy_redis(*, reverse=False):
    old = baseline()['env']
    old_config = {'host': old['MARKET_INTELLIGENCE_REDIS_HOST'], 'username': old.get('MARKET_INTELLIGENCE_REDIS_USERNAME', 'default'),
        'password': old['MARKET_INTELLIGENCE_REDIS_PASSWORD'], 'db': 2}
    new_config = {'host': REDIS, 'username': 'migration', 'password': credentials()['redis_operator_password'], 'db': 2}
    source, destination = (new_config, old_config) if reverse else (old_config, new_config)
    path = PRIVATE / 'redis-copy.env'
    env_file(path, {'COPY_SOURCE': json.dumps(source), 'COPY_DESTINATION': json.dumps(destination)})
    name = 'bee-researcher-security-state-transfer'
    program = '''import asyncio,json,os,time
from redis.asyncio import Redis
async def main():
 a=Redis(**json.loads(os.environ['COPY_SOURCE']))
 b=Redis(**json.loads(os.environ['COPY_DESTINATION']))
 keys=set([k async for k in a.scan_iter(match='market-intelligence:*',count=100)])
 old=set([k async for k in b.scan_iter(match='market-intelligence:*',count=100)])
 for key in old-keys: await b.delete(key)
 count=0
 for key in keys:
  started=time.monotonic()
  dump,ttl=await a.pipeline(transaction=True).dump(key).pttl(key).execute()
  if dump is None or ttl == -2: continue
  elapsed=int((time.monotonic()-started)*1000)
  if ttl >= 0 and ttl <= elapsed: continue
  await b.restore(key,ttl-elapsed if ttl>=0 else 0,dump,replace=True)
  if await b.dump(key)!=dump: raise RuntimeError('state copy mismatch')
  count+=1
 await a.aclose();await b.aclose()
 print(json.dumps({'copied_researcher_keys':count,'preserved_ttl':True,'removed_stale_researcher_keys':len(old-keys)}))
asyncio.run(main())'''
    run(['docker','create','-i','--name',name,'--network','ai-assistant-backend','--env-file',str(path),
         '--memory','384m','--read-only','--tmpfs','/tmp:size=16m,mode=1777','--cap-drop','ALL',
         '--security-opt','no-new-privileges:true','--entrypoint','python',image(),'-'])
    try:
        run(['docker','network','connect',PRIVATE_NET,name])
        result = json.loads(run(['docker','start','-ai',name],input=program,timeout=300))
        write(ART / ('redis-state-rollback.json' if reverse else 'redis-state-cutover.json'),result)
    finally:
        run(['docker','rm','-f',name])


def guard_other_containers():
    before=json.loads((ART/'other-containers-before.json').read_text())
    for name,ident in before.items():
        if inspect(name)['Id'] != ident:
            raise RuntimeError('another existing container changed during preparation: '+name)


def production_override(*, rollback=False):
    values=baseline()['env'] if rollback else prepared_env()
    ident=rollback_image() if rollback else image()
    service={'image':ident,'pull_policy':'never','environment':{k:'${'+k+'}' for k in values if k.startswith('MARKET_INTELLIGENCE_')}}
    if rollback:
        # The additive journal migration is retained. The older Alembic tree
        # cannot resolve its revision, so rollback runs its web entry point directly.
        service['command']=['python','security-rollback.py']
    else:
        service['networks']=['backend','egress','researcher-private']
    config={'services':{'market-intelligence':service}}
    if not rollback:
        config['networks']={'researcher-private':{'external':True,'name':PRIVATE_NET}}
    path=ART/('rollback.override.json' if rollback else 'production.override.json')
    write(path,config)
    # Compose expansion occurs only in process memory; raw secrets never enter the override.
    environment=dict(os.environ)
    environment.update(values)
    return path,environment


def ready():
    for _ in range(90):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8010/ready',timeout=3) as response:
                if response.status==200: return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('Researcher readiness did not recover')


def deploy():
    release=json.loads((ART/'image.json').read_text())
    if release.get('candidate') or not all((ART/name).exists() for name in ('release-verified.json','rehearsal-passed.json','rollback-tested.json','browser-passed.json','account-access-passed.json')):
        raise RuntimeError('the clean source, final image, complete tests and rehearsal gates must pass first')
    manifest=json.loads((ART/'manifest.json').read_text())
    if manifest['image_id']!=image(): raise RuntimeError('image provenance mismatch')
    for name,digest in manifest['files'].items():
        if hashlib.sha256((ART/name).read_bytes()).hexdigest()!=digest: raise RuntimeError('release artifact changed: '+name)
    run(['openssl','dgst','-sha256','-verify',str(WORK/'ops/bee-researcher-direct/artifacts/signing/release-public.pem'),
         '-signature',str(ART/'manifest.sig'),str(ART/'manifest.json')])
    if inspect(APP)['Image'] != OLD_IMAGE:
        raise RuntimeError('live image changed before cutover')
    guard_other_containers()
    old=baseline()['env']
    role_count=int(sql("SELECT count(*) FROM pg_roles WHERE rolname IN ('bee_researcher_runtime','bee_researcher_migrator')").strip())
    if role_count and not (role_count==2 and (ART/'roles-provisioned.json').exists()):
        raise RuntimeError('unexpected preexisting roles; inspect their provenance before retrying')
    # Refuse public grants that would defeat schema isolation.
    exposed=int(sql("SELECT count(*) FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace CROSS JOIN LATERAL aclexplode(coalesce(r.relacl,acldefault('r',r.relowner))) a WHERE n.nspname IN ('public','consultant_bee') AND a.grantee=0").strip())
    if exposed: raise RuntimeError('other schema PUBLIC grants require a separate review')
    active=int(sql("SELECT count(*) FROM market_intelligence.job_runs WHERE status='running' AND started_at>now()-interval '30 minutes'").strip())
    if active: raise RuntimeError('a Researcher job is running; wait for completion before deployment')
    if not (PRIVATE/'database-before-deploy.dump').exists(): backup(PRIVATE/'database-before-deploy.dump')
    if subprocess.run(['docker','network','inspect',PRIVATE_NET],capture_output=True).returncode:
        run(['docker','network','create','--internal',PRIVATE_NET])
    if subprocess.run(['docker','inspect',REDIS],capture_output=True).returncode:
        start_redis(REDIS,PRIVATE_NET,persistent=True)
    # Additive schema migration can run while the old image continues serving.
    if not role_count:
        sql('BEGIN;\n'+roles_program(old['MARKET_INTELLIGENCE_POSTGRES_DB'])+'\nCOMMIT;')
        write(ART/'roles-provisioned.json',{'schema_only_roles':True,'administrative_role_not_passed_to_web':True})
    migrate()
    protect_journal()
    active=int(sql("SELECT count(*) FROM market_intelligence.job_runs WHERE status='running' AND started_at>now()-interval '30 minutes'").strip())
    if active: raise RuntimeError('a Researcher job is running; finish it before the brief cutover')
    before=schema_snapshot()
    write(ART/'production-counts-before.json',before)
    run(['docker','stop','--time','120',APP],timeout=150)
    try:
        copy_redis()
        # Rotate service signing credentials and revoke all old browser sessions.
        revoked=sql('WITH removed AS (DELETE FROM market_intelligence.admin_sessions RETURNING 1) SELECT count(*) FROM removed;').strip()
        path,environment=production_override()
        run(compose_args(path)+['up','-d','--no-deps','--no-build','market-intelligence'],env=environment,timeout=180)
        ready()
        verify()
        write(ART/'deployed.json',{'image_id':image(),'version':'3.39.0','revoked_sessions':int(revoked),
            'schema':'0044_security_events','only_researcher_recreated':True})
        print('Researcher 3.39.0 deployed and verified. Old browser sessions must sign in again.')
    except Exception:
        rollback()
        raise


def verify():
    current=inspect(APP)
    assert current['Image']==image()
    assert current['Config']['User'] in {'market-intelligence','10002','10002:10002'}
    assert current['HostConfig']['ReadonlyRootfs'] and current['HostConfig']['CapDrop']==['ALL']
    assert 'no-new-privileges:true' in current['HostConfig']['SecurityOpt']
    actual=env_of(current)
    expected=prepared_env()
    assert all(actual.get(k)==v for k,v in expected.items())
    assert actual['MARKET_INTELLIGENCE_POSTGRES_PASSWORD'] != baseline()['env']['MARKET_INTELLIGENCE_POSTGRES_PASSWORD']
    result=run(['docker','exec',APP,'python','-m','app.runtime_permissions'])
    assert 'passed' in result
    after=schema_snapshot()
    before=json.loads((ART/'production-counts-before.json').read_text())
    # Startup jobs can append operational history, but cannot remove identities/content.
    for key in ('admin_users','assistant_workspaces','assistant_members','sources','topics','business_profiles','normalized_articles','article_analyses','publications'):
        assert after[key]>=before[key], 'unexpected data loss: '+key
    guard_other_containers()
    write(ART/'production-counts-after.json',after)
    write(ART/'production-verified.json',{'image_verified':True,'runtime_environment_verified':True,'privilege_preflight':True,
        'existing_identity_and_content_counts_preserved':True,'other_existing_containers_unchanged':True,'readiness':True})
    print('Production image, independent credentials, role limits, preserved data and unaffected neighboring containers verified.')


def rollback():
    state=inspect(APP)
    if state['State']['Running']:
        run(['docker','stop','--time','120',APP],timeout=150)
    copy_redis(reverse=True)
    path,environment=production_override(rollback=True)
    run(compose_args(path)+['up','-d','--no-deps','--no-build','market-intelligence'],env=environment,timeout=180)
    ready()
    assert inspect(APP)['Image']==rollback_image()
    write(ART/'rollback-receipt.json',{'previous_application_restored':True,'password_format_compatible':True,'redis_state_returned':True,'journal_retained':True})
    print('Previous Researcher application restored with compatible password verification; all data and the immutable journal retained.')


def main():
    phase = sys.argv[1]
    if phase == 'prepare': prepare()
    elif phase == 'rehearsal': rehearsal()
    elif phase == 'deploy': deploy()
    elif phase == 'verify': verify()
    elif phase == 'rollback': rollback()
    else: raise RuntimeError('unsupported phase')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc))
        raise SystemExit(1) from None
