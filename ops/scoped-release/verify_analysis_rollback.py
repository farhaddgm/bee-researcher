"""Real 3.52-on-0052 rollback boot, exclusively disposable synthetic fixtures."""
import argparse
import json
import subprocess
import time
import uuid

import deploy
from verify_news_chat import run, startup_healthcheck_options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--previous', required=True)
    args = parser.parse_args()
    candidate = deploy.inspect(args.candidate)
    previous = deploy.inspect(args.previous)
    version = candidate['Config']['Labels'].get('org.opencontainers.image.version')
    if version not in {'3.53.0', '3.54.0', '3.54.1'} or previous['Config']['Labels'].get('org.opencontainers.image.version') != '3.52.0':
        raise RuntimeError('Explicit reviewed 3.53 or 3.54 candidate and 3.52 previous image required')
    suffix = uuid.uuid4().hex[:12]
    net = 'bee-news-chat-test-' + suffix
    pg = 'bee-news-chat-pg-' + suffix
    redis = 'bee-news-chat-redis-' + suffix
    old = 'bee-lens-rollback-' + suffix
    containers = []
    network = False
    try:
        run('network', 'create', '--internal', net, capture=True)
        network = True
        run('run', '-d', '--name', pg, '--network', net, '-e', 'POSTGRES_DB=news_chat_test',
            '-e', 'POSTGRES_USER=news_chat_test', '-e', 'POSTGRES_PASSWORD=synthetic-chat-database-fixture',
            'postgres:17.10-alpine', capture=True)
        containers.append(pg)
        run('run', '-d', '--name', redis, '--network', net, 'redis:7.4.9-alpine',
            'redis-server', '--requirepass', 'synthetic-chat-redis-fixture', capture=True)
        containers.append(redis)
        for attempt in range(60):
            check = subprocess.run(['docker', 'exec', pg, 'pg_isready', '-U', 'news_chat_test'], capture_output=True)
            if check.returncode == 0:
                break
            if attempt == 59:
                raise RuntimeError('Synthetic PostgreSQL did not become ready')
            time.sleep(.5)
        values = {'POSTGRES_HOST': pg, 'POSTGRES_DB': 'news_chat_test', 'POSTGRES_USER': 'news_chat_test',
                  'POSTGRES_PASSWORD': 'synthetic-chat-database-fixture', 'REDIS_HOST': redis,
                  'REDIS_PASSWORD': 'synthetic-chat-redis-fixture', 'ENVIRONMENT': 'test',
                  'SCHEDULER_ENABLED': 'false', 'TELEGRAM_POLLING_ENABLED': 'false', 'NEWS_CHAT_ENABLED': 'false',
                  'OPENAI_API_KEY': '', 'NEWS_CHAT_ANTHROPIC_KEY': '', 'NEWS_CHAT_GOOGLE_KEY': ''}
        def options(configuration):
            result = ['--network', net, '--read-only', '--tmpfs', '/tmp:size=32m,mode=1777',
                      '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true']
            for key, value in configuration.items():
                result += ['-e', 'MARKET_INTELLIGENCE_' + key + '=' + value]
            return result
        run('run', '--rm', '--entrypoint', 'alembic', *options(values), args.candidate,
            'upgrade', '0052_analysis_lenses')
        run('run', '--rm', '--entrypoint', 'python', *options(values), args.candidate,
            'scripts/seed_runtime_boot_sql.py')
        run('exec', redis, 'redis-cli', '-a', 'synthetic-chat-redis-fixture', 'ACL', 'SETUSER',
            'startup-fixture', 'on', '>synthetic-startup-redis-fixture', '~*', '+@all', capture=True)
        values.update({'ENVIRONMENT': 'production', 'POSTGRES_USER': 'startup_fixture',
                       'POSTGRES_PASSWORD': 'synthetic-startup-database-fixture', 'REDIS_USERNAME': 'startup-fixture',
                       'REDIS_PASSWORD': 'synthetic-startup-redis-fixture', 'ADMIN_COOKIE_SECURE': 'true',
                       'OWNER_EMAIL': 'chat-owner@gmail.com', 'DOMAIN': 'startup-fixture.invalid',
                       'CSRF_SIGNING_SECRET': 'synthetic-csrf-startup-secret-at-least-32',
                       'MFA_ENCRYPTION_SECRET': 'synthetic-encryption-startup-secret-at-least-32',
                       'GOOGLE_CLIENT_ID': 'synthetic-startup.apps.googleusercontent.com',
                       'GOOGLE_CLIENT_SECRET': 'synthetic-startup-google-client-secret',
                       'GOOGLE_REDIRECT_URI': 'https://startup-fixture.invalid/auth/google/callback',
                       'ADMIN_BOOTSTRAP_USERNAME': 'chat-owner',
                       'ADMIN_BOOTSTRAP_PASSWORD': 'synthetic violet herons cross mountain lakes'})
        # The NEW package verifies forward-schema least privilege; the OLD
        # app's 0051-only startup verifier cannot understand additive 0052.
        run('run', '--rm', '--entrypoint', 'python', *options(values), args.candidate,
            '-m', 'app.runtime_permissions')
        configuration = {'Image': args.previous, 'Config': previous['Config']}
        command = deploy.rollback_service(configuration, {}, version)['command']
        run('run', '-d', '--name', old, '--entrypoint', command[0], *options(values),
            *startup_healthcheck_options(), args.previous, *command[1:], capture=True)
        containers.append(old)
        probe = """import json,urllib.request
for path in ['/health','/ready']:
 r=urllib.request.urlopen('http://127.0.0.1:8010'+path,timeout=2)
 assert r.status==200 and json.load(r)['version']=='3.52.0'
for path in ['/admin','/user','/auth/providers']:
 r=urllib.request.urlopen('http://127.0.0.1:8010'+path,timeout=2)
 assert r.status==200
"""
        for attempt in range(100):
            check = subprocess.run(['docker', 'exec', old, 'python', '-c', probe], capture_output=True)
            if check.returncode == 0:
                break
            if attempt == 99 or not deploy.inspect(old)['State']['Running']:
                raise RuntimeError('Forward-schema rollback did not become healthy; diagnostics withheld')
            time.sleep(.5)
        stopped_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        run('stop', '--time', '30', old, capture=True)
        deploy.verify_shutdown(deploy.inspect(old), stopped_at)
        print(json.dumps({'forward_schema_rollback': 'passed', 'previous_version': '3.52.0',
                          'schema': '0052_analysis_lenses', 'restricted_role': True, 'oauth_configuration_checked': True,
                          'graceful_shutdown_checked': True, 'database': 'synthetic_disposable', 'live_writes': False}))
    finally:
        for name in reversed(containers):
            subprocess.run(['docker', 'rm', '-f', '-v', name], capture_output=True, timeout=30)
        if network:
            subprocess.run(['docker', 'network', 'rm', net], capture_output=True, timeout=30)


if __name__ == '__main__':
    main()
