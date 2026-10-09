"""Reproducible isolated chat acceptance gate; no runtime secrets or production DB."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/market_intelligence"
PW = "mcr.microsoft.com/playwright:v1.55.1-noble"


def browser_mounts(modules):
    # Sibling mounts keep ESM's parent-directory resolution without requiring
    # Docker to mkdir node_modules inside the read-only source mount.
    return ['-w', '/harness/source', '-v', f'{SOURCE}:/harness/source:ro',
            '-v', f'{modules}:/harness/node_modules:ro']


def installer_options(directory):
    # The caller must own temporary files so cleanup works on non-root CI.
    return ['--user', f'{os.getuid()}:{os.getgid()}',
            '-e', 'npm_config_cache=/tmp/bee-npm-cache', '-v', f'{directory}:/tools']


def run(*args, timeout=300, capture=False):
    return subprocess.run(["docker", *map(str,args)],check=True,timeout=timeout,
                          text=True,capture_output=capture)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True,help='Already-built Researcher candidate image')
    parser.add_argument('--node-modules',type=Path,help='Optional pinned Playwright installation')
    parser.add_argument('--artifacts',type=Path,help='Optional directory for synthetic UI screenshots')
    args=parser.parse_args()
    suffix=uuid.uuid4().hex[:12];net='bee-news-chat-test-'+suffix
    names={k:'bee-news-chat-'+k+'-'+suffix for k in ('pg','redis','app','startup')}
    containers=[];network=False
    with tempfile.TemporaryDirectory(prefix='bee-news-chat-browser-') as tools:
        try:
            modules=args.node_modules.resolve() if args.node_modules else Path(tools)/'node_modules'
            if not args.node_modules:
                run('run','--rm','--entrypoint','npm',*installer_options(tools),PW,'install','--prefix','/tools','--ignore-scripts','--no-audit','--no-fund','playwright@1.55.1','@axe-core/playwright@4.11.0')
            run('network','create','--internal',net,capture=True);network=True
            run('run','-d','--name',names['pg'],'--network',net,'-e','POSTGRES_DB=news_chat_test','-e','POSTGRES_USER=news_chat_test','-e','POSTGRES_PASSWORD=synthetic-chat-database-fixture','postgres:17.10-alpine',capture=True);containers.append(names['pg'])
            run('run','-d','--name',names['redis'],'--network',net,'redis:7.4.9-alpine','redis-server','--requirepass','synthetic-chat-redis-fixture',capture=True);containers.append(names['redis'])
            for attempt in range(60):
                ready=subprocess.run(['docker','exec',names['pg'],'pg_isready','-U','news_chat_test','-d','news_chat_test'],capture_output=True)
                if ready.returncode==0:break
                if attempt==59:raise RuntimeError('Synthetic PostgreSQL did not become ready')
                time.sleep(.5)
            env={
                'POSTGRES_HOST':names['pg'],'POSTGRES_DB':'news_chat_test','POSTGRES_USER':'news_chat_test','POSTGRES_PASSWORD':'synthetic-chat-database-fixture',
                'REDIS_HOST':names['redis'],'REDIS_PASSWORD':'synthetic-chat-redis-fixture','ENVIRONMENT':'test','ADMIN_COOKIE_SECURE':'false',
                'SCHEDULER_ENABLED':'false','TELEGRAM_POLLING_ENABLED':'false','NEWS_CHAT_ENABLED':'true','CSP_STRICT':'true',
                'OPENAI_API_KEY':'synthetic-fixture-not-real','NEWS_CHAT_ANTHROPIC_KEY':'synthetic-fixture-not-real','NEWS_CHAT_GOOGLE_KEY':'synthetic-fixture-not-real',
                'OWNER_EMAIL':'chat-owner@gmail.com','DOMAIN':names['app'],
                'DEPLOYMENT_DRAIN_ENABLED':'true',
            }
            # Runtime, fixture, SQL tests and assets come from the candidate
            # itself. A host-source bind must never hide a stale/broken image.
            common=['--network',net,'-w','/app']
            for key,value in env.items():common.extend(['-e',f'MARKET_INTELLIGENCE_{key}={value}'])
            run('run','--rm','--entrypoint','alembic',*common,args.image,'upgrade','head')
            # Exercise the ACTUAL image CMD in production mode. UI fixtures
            # override that CMD and otherwise hide broken startup preflights.
            run('run','--rm','--entrypoint','python',*common,args.image,'scripts/seed_runtime_boot_sql.py')
            run('exec',names['redis'],'redis-cli','-a','synthetic-chat-redis-fixture','ACL','SETUSER',
                'startup-fixture','on','>synthetic-startup-redis-fixture','~*','+@all',capture=True)
            startup=dict(env)
            startup.update({'ENVIRONMENT':'production','ADMIN_COOKIE_SECURE':'true','POSTGRES_USER':'startup_fixture',
                'POSTGRES_PASSWORD':'synthetic-startup-database-fixture','REDIS_USERNAME':'startup-fixture',
                'REDIS_PASSWORD':'synthetic-startup-redis-fixture','NEWS_CHAT_ENABLED':'false',
                'OPENAI_API_KEY':'','NEWS_CHAT_ANTHROPIC_KEY':'','NEWS_CHAT_GOOGLE_KEY':'',
                'CSRF_SIGNING_SECRET':'synthetic-csrf-startup-secret-at-least-32',
                'MFA_ENCRYPTION_SECRET':'synthetic-encryption-startup-secret-at-least-32',
                'GOOGLE_CLIENT_ID':'synthetic-startup.apps.googleusercontent.com',
                'GOOGLE_CLIENT_SECRET':'synthetic-startup-google-client-secret',
                'GOOGLE_REDIRECT_URI':'https://startup-fixture.invalid/auth/google/callback',
                'DOMAIN':'startup-fixture.invalid','ADMIN_BOOTSTRAP_USERNAME':'chat-owner',
                'ADMIN_BOOTSTRAP_PASSWORD':'synthetic violet herons cross mountain lakes'})
            startup_options=['--network',net,'--read-only','--tmpfs','/tmp:size=32m,mode=1777',
                '--cap-drop','ALL','--security-opt','no-new-privileges:true']
            for key,value in startup.items():startup_options.extend(['-e',f'MARKET_INTELLIGENCE_{key}={value}'])
            run('run','-d','--name',names['startup'],*startup_options,args.image,capture=True)
            containers.append(names['startup'])
            probe="import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8010/health',timeout=2); assert r.status==200; assert json.load(r)['status']=='healthy'"
            for attempt in range(60):
                check=subprocess.run(['docker','exec',names['startup'],'python','-c',probe],capture_output=True)
                if check.returncode==0:break
                state=run('inspect','--format','{{.State.Running}}',names['startup'],capture=True).stdout.strip()
                if state!='true' or attempt==59:
                    # Every value in this disposable fixture is synthetic.
                    diagnostics=run('logs','--tail','60',names['startup'],capture=True)
                    raise RuntimeError('Actual startup CMD failed: '+diagnostics.stdout+diagnostics.stderr)
                time.sleep(.5)
            run('stop','--time','30',names['startup'],capture=True)
            print('Actual production startup CMD passed with restricted PostgreSQL/Redis identities, OAuth prerequisites and 0045 schema.')
            run('run','-d','--name',names['app'],'--entrypoint','python',*common,args.image,'scripts/news_chat_fixture.py',capture=True);containers.append(names['app'])
            artifacts=[]
            if args.artifacts:
                output=args.artifacts.resolve();output.mkdir(parents=True,exist_ok=True)
                artifacts=['-v',f'{output}:/artifacts','-e','BEE_CHAT_ARTIFACT_DIR=/artifacts']
            # Loopback provides a trustworthy browser context for native
            # clipboard APIs. It still has no host ports or Internet route.
            run('run','--rm','--entrypoint','node','--network','container:'+names['app'],*browser_mounts(modules),*artifacts,
                '-e','MARKET_INTELLIGENCE_ENVIRONMENT=test','-e','BEE_CHAT_TEST_URL=http://127.0.0.1:8010',PW,'scripts/verify_news_chat.mjs')
            # The new optional surface must not break the existing Reader
            # settings, focus trap, text direction or notification preferences.
            run('run','--rm','--entrypoint','node','--network',net,*browser_mounts(modules),
                '-e',f'BEE_USER_URL=http://{names["app"]}:8010/user','-e','MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME=chat-owner',
                '-e','MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD=synthetic violet herons cross mountain lakes',PW,'scripts/verify_user_portal.mjs')
            run('run','--rm','--entrypoint','python',*common,args.image,'scripts/verify_news_chat_sql.py')
            run('run','--rm','--entrypoint','python',*common,args.image,'scripts/verify_job_recovery_sql.py')
            # The modularized Admin document must keep real modal hit tests,
            # ticket conversations, locale rendering and keyboard semantics.
            for script in ('verify_admin_support.mjs', 'verify_admin_catalog_viewports.mjs',
                           'verify_admin_locales.mjs', 'verify_admin_accessibility.mjs'):
                run('run','--rm','--entrypoint','node','--network',net,*browser_mounts(modules),
                    '-e',f'BEE_ADMIN_URL=http://{names["app"]}:8010/admin',
                    '-e','MARKET_INTELLIGENCE_ENVIRONMENT=test',
                    '-e','MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME=chat-owner',
                    '-e','MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD=synthetic violet herons cross mountain lakes',
                    PW,'scripts/'+script,timeout=360)
            print('Isolated news-chat acceptance gate passed; no live credentials or calls.')
        finally:
            # Explicit IDs created in this invocation only. Never prune Docker.
            for name in reversed(containers):
                # Include only anonymous volumes belonging to this test's
                # exact container, never shared/named production volumes.
                subprocess.run(['docker','rm','-f','-v',name],capture_output=True,timeout=30)
            if network:subprocess.run(['docker','network','rm',net],capture_output=True,timeout=30)


if __name__=='__main__':main()
