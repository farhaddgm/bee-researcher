"""Required isolated Report SQL/browser acceptance for an actual candidate image."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from verify_news_chat import run, PW, installer_options


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--node-modules',type=Path)
    parser.add_argument('--artifacts',type=Path)
    args=parser.parse_args()
    suffix=uuid.uuid4().hex[:10]
    names={k:'bee-report-'+k+'-'+suffix for k in ('pg','redis','app')}
    net='bee-report-net-'+suffix
    created=[]
    network=False
    with tempfile.TemporaryDirectory(prefix='bee-report-harness-') as directory:
        try:
            state=Path(directory)/'state';state.mkdir();state.chmod(0o777)
            run('network','create','--internal',net,capture=True);network=True
            run('run','-d','--name',names['pg'],'--network',net,'-e','POSTGRES_DB=report_test','-e','POSTGRES_USER=report_test',
                '-e','POSTGRES_PASSWORD=synthetic-report-db','postgres:17.10-alpine',capture=True);created.append(names['pg'])
            run('run','-d','--name',names['redis'],'--network',net,'redis:7.4.9-alpine','redis-server','--requirepass','synthetic-report-redis',capture=True);created.append(names['redis'])
            for attempt in range(60):
                probe=subprocess.run(['docker','exec',names['pg'],'pg_isready','-U','report_test'],capture_output=True)
                if probe.returncode==0:break
                if attempt==59:raise RuntimeError('Isolated PostgreSQL not ready')
                time.sleep(.5)
            env={'ENVIRONMENT':'test','POSTGRES_HOST':names['pg'],'POSTGRES_DB':'report_test','POSTGRES_USER':'report_test','POSTGRES_PASSWORD':'synthetic-report-db',
                'REDIS_HOST':names['redis'],'REDIS_PASSWORD':'synthetic-report-redis','ADMIN_COOKIE_SECURE':'false','SCHEDULER_ENABLED':'false','TELEGRAM_POLLING_ENABLED':'false',
                'REPORT_PORTAL_ENABLED':'true','REPORT_ENCRYPTION_SECRET':'synthetic-key-only-for-isolated-report-tests',
                'REPORT_DELETION_REGISTRY_FILE':'/report-state/deletions.log','OPENAI_API_KEY':'synthetic-provider-only','EXTERNAL_ANALYSIS_APPROVED':'true',
                'OWNER_EMAIL':'report-owner@gmail.com','CSRF_SIGNING_SECRET':'synthetic-signing-key-only-for-report-tests','CSP_STRICT':'true'}
            common=['--network',net,'-v',str(state)+':/report-state']
            for k,v in env.items():common.extend(['-e','MARKET_INTELLIGENCE_'+k+'='+v])
            run('run','--rm',*common,args.image,'alembic','upgrade','0045_news_chat')
            run('exec',names['pg'],'psql','-U','report_test','-d','report_test','-v','ON_ERROR_STOP=1','-c',
                "CREATE ROLE bee_researcher_runtime LOGIN PASSWORD 'synthetic-runtime-db'; GRANT USAGE ON SCHEMA market_intelligence TO bee_researcher_runtime; GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA market_intelligence TO bee_researcher_runtime; GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA market_intelligence TO bee_researcher_runtime; REVOKE UPDATE,DELETE,TRUNCATE ON market_intelligence.security_events FROM bee_researcher_runtime;")
            run('run','--rm',*common,args.image,'alembic','upgrade','head')
            common.extend(['-e','MARKET_INTELLIGENCE_POSTGRES_USER=bee_researcher_runtime','-e','MARKET_INTELLIGENCE_POSTGRES_PASSWORD=synthetic-runtime-db'])
            run('run','--rm',*common,args.image,'python','-c',"import asyncio; from app.config import get_settings; from app.runtime_permissions import check_runtime_permissions; get_settings().environment='production'; asyncio.run(check_runtime_permissions()); print('Restricted runtime and append-only Report ledgers verified')")
            sql=run('run','--rm',*common,args.image,'python','-m','scripts.verify_report_portal',capture=True)
            print(sql.stdout.strip())
            run('run','-d','--name',names['app'],*common,args.image,'uvicorn','scripts.report_test_server:app','--host','0.0.0.0','--port','8010','--no-access-log',capture=True);created.append(names['app'])
            for attempt in range(60):
                probe=subprocess.run(['docker','exec',names['app'],'python','-c',"import urllib.request; urllib.request.urlopen('http://localhost:8010/_report_fixture',timeout=2)"],capture_output=True)
                if probe.returncode==0:break
                if attempt==59:raise RuntimeError('Isolated Report app not ready')
                time.sleep(.5)
            modules=args.node_modules.resolve() if args.node_modules else Path(directory)/'node_modules'
            if not args.node_modules:
                run('run','--rm','--entrypoint','npm',*installer_options(directory),PW,'install','--prefix','/tools','--ignore-scripts','--no-audit','--no-fund','playwright@1.55.1','@axe-core/playwright@4.11.0')
            source=Path(directory)/'source';source.mkdir()
            run('cp',names['app']+':/app/scripts/verify_report_browser.mjs',source/'verify_report_browser.mjs')
            artifacts=[]
            if args.artifacts:
                args.artifacts.mkdir(parents=True,exist_ok=True)
                artifacts=['-v',str(args.artifacts.resolve())+':/artifacts','-e','REPORT_ARTIFACT_DIR=/artifacts']
            run('run','--rm','--network',net,*artifacts,'-e','REPORT_TEST_URL=http://'+names['app']+':8010','-w','/harness/source',
                '-v',str(source)+':/harness/source:ro','-v',str(modules)+':/harness/node_modules:ro',PW,'node','verify_report_browser.mjs')
            print(json.dumps({'status':'passed','image':args.image,'external_network':False}))
        finally:
            for name in reversed(created):subprocess.run(['docker','rm','-f',name],capture_output=True)
            if network:subprocess.run(['docker','network','rm',net],capture_output=True)


if __name__=='__main__':main()
