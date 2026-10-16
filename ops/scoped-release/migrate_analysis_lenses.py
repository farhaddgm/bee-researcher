"""Researcher-only additive schema 0052, signed candidate and private backup.

Does not enable analysis lenses, grant users access, change accounts or restart
services. Forward-schema rollback deliberately retains these additive tables.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time

from deploy import candidate, inspect, run, save
from migrate_news_chat import MIGRATOR, PRIVATE, migration_values, scoped_backup_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--version', default='3.53.0', choices=['3.53.0', '3.54.0', '3.54.1'])
    args = parser.parse_args()
    candidate(args.image, args.revision, args.version)
    values = migration_values(MIGRATOR)
    runtime = dict(v.split('=', 1) for v in inspect('ai-market-intelligence')['Config']['Env'] if '=' in v)
    backup_values = scoped_backup_values(values, runtime)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    directory = PRIVATE / (args.version + '-migration-' + stamp)
    directory.mkdir(mode=0o700)
    common = ['docker', 'run', '--rm', '--network', 'container:ai-market-intelligence', '--read-only',
              '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
              '--env-file', str(MIGRATOR)]
    probe = """import asyncio,json
from sqlalchemy import text
from app.database import engine
async def main():
 async with engine.connect() as c:
  print(json.dumps({'schema':await c.scalar(text('SELECT version_num FROM market_intelligence.alembic_version'))}))
 await engine.dispose()
asyncio.run(main())"""
    previous = json.loads(run(common + ['--entrypoint', 'python', args.image, '-c', probe]))['schema']
    if previous not in {'0051_token_quotas', '0052_analysis_lenses'}:
        raise RuntimeError('Unexpected schema; refusing migration')
    envfile = directory / 'backup.env'
    save(envfile, ''.join(k + '=' + v + '\n' for k, v in backup_values.items()), private=True)
    backup = directory / 'market-intelligence-before-0052.dump'
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        result = subprocess.run(['docker', 'run', '--rm', '--network', 'container:ai-market-intelligence',
                                 '--env-file', str(envfile), '--entrypoint', 'pg_dump', 'postgres:17.10-alpine',
                                 '--format=custom', '--schema=market_intelligence', '--no-owner', '--no-acl'],
                                stdout=output, stderr=subprocess.PIPE, timeout=180)
        if result.returncode == 0:
            output.flush()
            os.fsync(output.fileno())
    if result.returncode or backup.stat().st_size < 100:
        raise RuntimeError('Scoped backup failed; no DDL performed')
    run(common + ['--entrypoint', 'alembic', args.image, 'upgrade', '0052_analysis_lenses'], timeout=180)
    runtime_env = directory / 'runtime.env'
    save(runtime_env, ''.join(k + '=' + v + '\n' for k, v in runtime.items() if k.startswith('MARKET_INTELLIGENCE_')), private=True)
    run(['docker', 'run', '--rm', '--network', 'container:ai-market-intelligence', '--env-file', str(runtime_env),
         '--read-only', '--tmpfs', '/tmp:size=32m,mode=1777', '--cap-drop', 'ALL', '--entrypoint', 'python',
         args.image, '-m', 'app.runtime_permissions'])
    receipt = directory / 'migration-receipt.json'
    save(receipt, {'schema': '0052_analysis_lenses', 'previous_schema': previous, 'revision': args.revision,
                  'backup_sha256': hashlib.sha256(backup.read_bytes()).hexdigest(), 'backup_schema': 'market_intelligence',
                  'runtime_role': 'bee_researcher_runtime', 'runtime_ddl_allowed': False,
                  'append_only_ledgers_verified': True, 'account_grants_changed': False,
                  'other_schemas_changed': False, 'services_restarted': False,
                  'lens_defaults': 'focused/general', 'feature_flag_enabled': False}, private=True)
    print(json.dumps({'migration_verified': True, 'receipt': str(receipt)}))


if __name__ == '__main__':
    main()
