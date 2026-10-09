"""Reproducible isolated chat acceptance gate; no runtime secrets or production DB."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/market_intelligence"
PW = "mcr.microsoft.com/playwright:v1.55.1-noble"


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
    names={k:'bee-news-chat-'+k+'-'+suffix for k in ('pg','redis','app')}
    containers=[];network=False
    with tempfile.TemporaryDirectory(prefix='bee-news-chat-browser-') as tools:
        try:
            modules=args.node_modules.resolve() if args.node_modules else Path(tools)/'node_modules'
            if not args.node_modules:
                run('run','--rm','--entrypoint','npm','-v',f'{tools}:/tools',PW,'install','--prefix','/tools','--ignore-scripts','--no-audit','--no-fund','playwright@1.55.1','@axe-core/playwright@4.11.0')
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
            run('run','-d','--name',names['app'],'--entrypoint','python',*common,args.image,'scripts/news_chat_fixture.py',capture=True);containers.append(names['app'])
            artifacts=[]
            if args.artifacts:
                output=args.artifacts.resolve();output.mkdir(parents=True,exist_ok=True)
                artifacts=['-v',f'{output}:/artifacts','-e','BEE_CHAT_ARTIFACT_DIR=/artifacts']
            # Loopback provides a trustworthy browser context for native
            # clipboard APIs. It still has no host ports or Internet route.
            run('run','--rm','--entrypoint','node','--network','container:'+names['app'],'-w','/app','-v',f'{SOURCE}:/app:ro','-v',f'{modules}:/app/node_modules:ro',*artifacts,
                '-e','MARKET_INTELLIGENCE_ENVIRONMENT=test','-e','BEE_CHAT_TEST_URL=http://127.0.0.1:8010',PW,'scripts/verify_news_chat.mjs')
            # The new optional surface must not break the existing Reader
            # settings, focus trap, text direction or notification preferences.
            run('run','--rm','--entrypoint','node','--network',net,'-w','/app','-v',f'{SOURCE}:/app:ro','-v',f'{modules}:/app/node_modules:ro',
                '-e',f'BEE_USER_URL=http://{names["app"]}:8010/user','-e','MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_USERNAME=chat-owner',
                '-e','MARKET_INTELLIGENCE_ADMIN_BOOTSTRAP_PASSWORD=synthetic violet herons cross mountain lakes',PW,'scripts/verify_user_portal.mjs')
            run('run','--rm','--entrypoint','python',*common,args.image,'scripts/verify_news_chat_sql.py')
            run('run','--rm','--entrypoint','python',*common,args.image,'scripts/verify_job_recovery_sql.py')
            # The modularized Admin document must keep real modal hit tests,
            # ticket conversations, locale rendering and keyboard semantics.
            for script in ('verify_admin_support.mjs', 'verify_admin_catalog_viewports.mjs',
                           'verify_admin_locales.mjs', 'verify_admin_accessibility.mjs'):
                run('run','--rm','--entrypoint','node','--network',net,'-w','/app',
                    '-v',f'{SOURCE}:/app:ro','-v',f'{modules}:/app/node_modules:ro',
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
