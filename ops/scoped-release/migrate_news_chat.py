"""Additive 0045 migration with a private, Researcher-schema-only backup.

Uses the existing runtime role for backup and migrator role for DDL;
never changes roles, secrets,
other schemas, account grants, runtime flags or service containers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from deploy import candidate, inspect, run, save

PRIVATE = Path('/opt/ai-assistant/ops/bee-researcher-direct/private')
MIGRATOR = PRIVATE / '3.39.0-security/migration.env'


def migration_values(path: Path) -> dict[str, str]:
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError('Existing private migrator env required')
    values = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
    if (values.get('MARKET_INTELLIGENCE_POSTGRES_USER') != 'bee_researcher_migrator'
            or values.get('MARKET_INTELLIGENCE_POSTGRES_DB') != 'assistant'):
        raise RuntimeError('Researcher-only database and migrator required')
    return values


def scoped_backup_values(migrator: dict[str, str], runtime: dict[str, str]) -> dict[str, str]:
    # DDL permission is not SELECT permission on historical tables. Snapshot
    # with the already-configured restricted reader; do not elevate migrator
    # privileges, exclude tables, or reach for a shared database administrator.
    prefix = 'MARKET_INTELLIGENCE_POSTGRES_'
    if runtime.get(prefix+'USER') != 'bee_researcher_runtime' or runtime.get(prefix+'DB') != 'assistant':
        raise RuntimeError('Existing restricted Researcher backup identity required')
    for key in ('HOST', 'DB', 'PORT'):
        default = '5432' if key == 'PORT' else ''
        if runtime.get(prefix+key, default) != migrator.get(prefix+key, default):
            raise RuntimeError('Backup and migration must target the same Researcher database')
    result = {key: runtime.get(prefix+suffix, '') for key, suffix in
              [('PGHOST', 'HOST'), ('PGDATABASE', 'DB'), ('PGUSER', 'USER'), ('PGPASSWORD', 'PASSWORD')]}
    result['PGPORT'] = runtime.get(prefix+'PORT', '5432')
    if any(not value or '\n' in value or '\r' in value for value in result.values()):
        raise RuntimeError('Single-line configured Researcher backup values required')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True);parser.add_argument('--revision',required=True)
    args=parser.parse_args();candidate(args.image,args.revision,'3.40.0')
    values=migration_values(MIGRATOR)
    current=inspect('ai-market-intelligence')
    runtime=dict(item.split('=',1) for item in current['Config']['Env'] if '=' in item)
    pg=scoped_backup_values(values,runtime)
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    directory=PRIVATE/('3.40.0-migration-'+stamp);directory.mkdir(mode=0o700)
    common=['docker','run','--rm','--network','container:ai-market-intelligence',
        '--read-only','--tmpfs','/tmp:size=32m,mode=1777','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--env-file',str(MIGRATOR)]
    probe="""import asyncio,json
from sqlalchemy import text
from app.database import engine
async def main():
 async with engine.connect() as c:
  revision=await c.scalar(text('SELECT version_num FROM market_intelligence.alembic_version'))
  print(json.dumps({'schema_revision':revision}))
 await engine.dispose()
asyncio.run(main())"""
    revision=json.loads(run(common+['--entrypoint','python',args.image,'-c',probe]))['schema_revision']
    if revision not in {'0044_security_events','0045_news_chat'}:
        raise RuntimeError('Unexpected schema; refusing broad migration')
    pgfile=directory/'pg.env';save(pgfile,''.join(k+'='+v+'\n' for k,v in pg.items()),private=True)
    backup=directory/'market-intelligence-before-0045.dump'
    descriptor=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as output:
        result=subprocess.run(['docker','run','--rm','--network','container:ai-market-intelligence',
            '--env-file',str(pgfile),'--entrypoint','pg_dump','postgres:17.10-alpine',
            '--format=custom','--schema=market_intelligence','--no-owner','--no-acl'],
            stdout=output,stderr=subprocess.PIPE,timeout=180)
        if result.returncode == 0:
            output.flush()
            os.fsync(output.fileno())
    if result.returncode or backup.stat().st_size<100:
        raise RuntimeError('Private scoped backup failed; no migration performed')
    run(common+['--entrypoint','alembic',args.image,'upgrade','0045_news_chat'],timeout=180)
    verify="""import asyncio,json
from sqlalchemy import text
from app.database import engine
async def main():
 async with engine.connect() as c:
  version=await c.scalar(text('SELECT version_num FROM market_intelligence.alembic_version'))
  tables=['news_chat_policy','news_chat_conversations','news_chat_generations']
  for name in tables:
   for privilege in ['SELECT','INSERT','UPDATE','DELETE']:
    assert await c.scalar(text('SELECT has_table_privilege(:role,:table,:privilege)'),{'role':'bee_researcher_runtime','table':'market_intelligence.'+name,'privilege':privilege})
  assert not await c.scalar(text("SELECT has_schema_privilege('bee_researcher_runtime','market_intelligence','CREATE')"))
  assert version=='0045_news_chat'
  print(json.dumps({'schema':version,'runtime_grants_verified':True,'runtime_ddl_allowed':False}))
 await engine.dispose()
asyncio.run(main())"""
    verified=json.loads(run(common+['--entrypoint','python',args.image,'-c',verify]))
    receipt=directory/'migration-receipt.json'
    save(receipt,{**verified,'revision':args.revision,'backup_schema':'market_intelligence',
        'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'previous_schema':revision,
        'backup_role':'bee_researcher_runtime','migration_role':'bee_researcher_migrator',
        'roles_or_grants_changed':False,
        'secrets_rekeyed':False,'other_schemas_changed':False,'services_restarted':False},private=True)
    print(json.dumps({'migration_verified':True,'receipt':str(receipt)}))


if __name__=='__main__':main()
