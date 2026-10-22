"""Real isolated Admin/SQL acceptance. No live credentials, ports or providers."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

from verify_news_chat import PW, browser_mounts, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--node-modules', required=True, type=Path)
    args = parser.parse_args()
    suffix = uuid.uuid4().hex[:12]
    network = 'bee-admin-flow-test-' + suffix
    pg, redis, app = [network + '-' + kind for kind in ('pg', 'redis', 'app')]
    containers, created = [], False
    image = run('inspect', args.image, capture=True)
    if json.loads(image.stdout)[0]['Config']['Labels'].get('org.opencontainers.image.version') not in {'3.54.0', '3.54.1', '3.54.2'}:
        raise RuntimeError('A 3.54.x candidate is required')
    try:
        run('network', 'create', '--internal', network, capture=True); created = True
        run('run', '-d', '--name', pg, '--network', network, '--tmpfs', '/var/lib/postgresql/data:rw,size=512m,mode=0700',
            '-e', 'POSTGRES_DB=assistant_test', '-e', 'POSTGRES_USER=assistant_test',
            '-e', 'POSTGRES_PASSWORD=synthetic-admin-flow-database', 'postgres:17.10-alpine', capture=True)
        containers.append(pg)
        run('run', '-d', '--name', redis, '--network', network, 'redis:7.4.9-alpine',
            'redis-server', '--requirepass', 'synthetic-admin-flow-redis', capture=True)
        containers.append(redis)
        for attempt in range(60):
            check = subprocess.run(['docker', 'exec', pg, 'pg_isready', '-U', 'assistant_test'], capture_output=True)
            if check.returncode == 0: break
            if attempt == 59: raise RuntimeError('Synthetic PostgreSQL did not become ready')
            time.sleep(.5)
        values = {'ENVIRONMENT':'test', 'POSTGRES_HOST':pg, 'POSTGRES_DB':'assistant_test', 'POSTGRES_USER':'assistant_test',
            'POSTGRES_PASSWORD':'synthetic-admin-flow-database', 'REDIS_HOST':redis, 'REDIS_PASSWORD':'synthetic-admin-flow-redis',
            'SCHEDULER_ENABLED':'false', 'TELEGRAM_POLLING_ENABLED':'false', 'OPENAI_API_KEY':'', 'TELEGRAM_BOT_TOKEN':'',
            'GOOGLE_CLIENT_ID':'', 'GOOGLE_CLIENT_SECRET':'', 'GOOGLE_REDIRECT_URI':'', 'ADMIN_COOKIE_SECURE':'false',
            'OWNER_EMAIL':'admin-flow@gmail.com', 'ADMIN_BOOTSTRAP_USERNAME':'admin-flow',
            'ADMIN_BOOTSTRAP_PASSWORD':'synthetic admin flow violet herons cross lakes', 'CSP_STRICT':'true'}
        common = ['--network', network, '-w', '/app', '-e', 'PYTHONPATH=/app']
        for key, value in values.items(): common.extend(['-e', 'MARKET_INTELLIGENCE_' + key + '=' + value])
        run('run', '--rm', '--entrypoint', 'alembic', *common, args.image, 'upgrade', 'head')
        run('run', '-d', '--name', app, '--entrypoint', 'uvicorn', *common, args.image,
            'app.main:app', '--host', '0.0.0.0', '--port', '8010', '--no-access-log', capture=True)
        containers.append(app)
        for attempt in range(90):
            check = subprocess.run(['docker', 'exec', app, 'python', '-c',
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health',timeout=2)"], capture_output=True)
            if check.returncode == 0: break
            if attempt == 89: raise RuntimeError('Synthetic Admin did not become ready')
            time.sleep(.5)
        for script in ('verify_news_table_browser.mjs', 'verify_research_context_browser.mjs',
                       'verify_admin_lifecycle_browser.mjs', 'verify_admin_support.mjs',
                       'verify_ai_model_settings.mjs', 'verify_admin_locales.mjs'):
            run('run', '--rm', '--entrypoint', 'node', '--network', network, *browser_mounts(args.node_modules.resolve()),
                '-e', 'MARKET_INTELLIGENCE_ENVIRONMENT=test', '-e', 'BEE_ADMIN_URL=http://' + app + ':8010/admin',
                '-e', 'MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME=admin-flow',
                '-e', 'MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD=' + values['ADMIN_BOOTSTRAP_PASSWORD'],
                PW, 'scripts/' + script, timeout=360)
        run('stop', '--time', '30', app, capture=True)
        extra = ['-e', 'MARKET_INTELLIGENCE_CONTENTER_API_URL=https://contenter-review.invalid/api',
                 '-e', 'MARKET_INTELLIGENCE_CONTENTER_WEB_URL=https://contenter-review.invalid',
                 '-e', 'MARKET_INTELLIGENCE_CONTENTER_TOKEN=synthetic-ci-contenter-token-0123456789']
        for script in ('verify_media_pipeline.py', 'verify_product_reliability.py', 'verify_research_context_sql.py', 'verify_contenter_sql.py'):
            run('run', '--rm', '--entrypoint', 'python', *common, *extra, args.image, 'scripts/' + script)
        print('Admin analysis-flow acceptance passed: real login/HTTP, eight-language pagination/profile/configuration, Owner ACL, source dates, topic thresholds, cache reuse, read-only decisions, business context and Reader/Telegram gates. No live calls.')
    except Exception:
        if app in containers:
            result = run('logs', '--tail', '35', app, capture=True)
            print(result.stdout + result.stderr)
        raise
    finally:
        for name in reversed(containers): subprocess.run(['docker', 'rm', '-f', '-v', name], capture_output=True, timeout=30)
        if created: subprocess.run(['docker', 'network', 'rm', network], capture_output=True, timeout=30)


if __name__ == '__main__': main()
