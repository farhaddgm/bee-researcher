"""Add only Report schema 0046, after a private Researcher-only backup.

No account grants, business consents, other schemas or service restarts.
The exact signed candidate must already have passed release verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from deploy import candidate, inspect, run, save
from migrate_news_chat import MIGRATOR, PRIVATE, migration_values, scoped_backup_values


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--revision',required=True)
    args=parser.parse_args()
    candidate(args.image,args.revision,'3.41.0')
    values=migration_values(MIGRATOR)
    runtime=dict(v.split('=',1) for v in inspect('ai-market-intelligence')['Config']['Env'] if '=' in v)
    pg=scoped_backup_values(values,runtime)
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    directory=PRIVATE/('3.41.0-migration-'+stamp);directory.mkdir(mode=0o700)
    common=['docker','run','--rm','--network','container:ai-market-intelligence','--read-only',
        '--tmpfs','/tmp:size=32m,mode=1777','--cap-drop','ALL','--security-opt','no-new-privileges:true','--env-file',str(MIGRATOR)]
    probe="""import asyncio,json
from sqlalchemy import text
from app.database import engine
async def main():
 async with engine.connect() as c:
  print(json.dumps({'schema':await c.scalar(text('SELECT version_num FROM market_intelligence.alembic_version'))}))
 await engine.dispose()
asyncio.run(main())"""
    before=json.loads(run(common+['--entrypoint','python',args.image,'-c',probe]))['schema']
    if before not in {'0045_news_chat','0046_report_portal'}:
        raise RuntimeError('Unexpected schema; refusing migration')
    pgfile=directory/'backup.env';save(pgfile,''.join(k+'='+v+'\n' for k,v in pg.items()),private=True)
    backup=directory/'market-intelligence-before-0046.dump'
    descriptor=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as output:
        result=subprocess.run(['docker','run','--rm','--network','container:ai-market-intelligence',
            '--env-file',str(pgfile),'--entrypoint','pg_dump','postgres:17.10-alpine',
            '--format=custom','--schema=market_intelligence','--no-owner','--no-acl'],
            stdout=output,stderr=subprocess.PIPE,timeout=180)
        if result.returncode==0:output.flush();os.fsync(output.fileno())
    if result.returncode or backup.stat().st_size<100:
        raise RuntimeError('Scoped backup failed; no DDL performed')
    run(common+['--entrypoint','alembic',args.image,'upgrade','0046_report_portal'],timeout=180)
    # Check effective grants with the actual restricted identity, not merely
    # the migrator's ability to create tables.
    envfile=directory/'runtime.env'
    save(envfile,''.join(k+'='+v+'\n' for k,v in runtime.items() if k.startswith('MARKET_INTELLIGENCE_')),private=True)
    run(['docker','run','--rm','--network','container:ai-market-intelligence','--env-file',str(envfile),
        '--read-only','--tmpfs','/tmp:size=32m,mode=1777','--cap-drop','ALL','--entrypoint','python',
        args.image,'-m','app.runtime_permissions'])
    receipt=directory/'migration-receipt.json'
    save(receipt,{'schema':'0046_report_portal','previous_schema':before,'revision':args.revision,
        'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'backup_schema':'market_intelligence',
        'runtime_role':'bee_researcher_runtime','runtime_ddl_allowed':False,'append_only_ledgers_verified':True,
        'account_grants_changed':False,'business_consents_changed':False,'other_schemas_changed':False,
        'services_restarted':False},private=True)
    print(json.dumps({'migration_verified':True,'receipt':str(receipt)}))


if __name__=='__main__':main()
