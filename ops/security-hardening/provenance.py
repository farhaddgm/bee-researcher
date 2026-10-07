"""Build/test locally from a clean commit; no inventory leaves this host."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('release', HERE/'release.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def image_run(arguments, *, test_env=True):
    args = ['docker','run','--rm','--network','none','--memory','1g','--cpus','2','--read-only',
            '--tmpfs','/tmp:size=96m,mode=1777','--cap-drop','ALL','--security-opt','no-new-privileges:true']
    if test_env:
        for key,value in {'ENVIRONMENT':'test','POSTGRES_DB':'assistant_test','POSTGRES_USER':'assistant_test',
            'POSTGRES_PASSWORD':'test-password','REDIS_PASSWORD':'test-password','SCHEDULER_ENABLED':'false',
            'TELEGRAM_POLLING_ENABLED':'false','CSRF_SIGNING_SECRET':'test-only-signing-secret-at-least-32',
            'MFA_ENCRYPTION_SECRET':'test-only-encryption-secret-at-least-32'}.items():
            args += ['-e','MARKET_INTELLIGENCE_'+key+'='+value]
    return r.run(args+['--entrypoint',arguments[0],r.image()]+arguments[1:],timeout=600)


def main():
    os.chdir(r.SOURCE)
    assert not r.run(['git','status','--porcelain']).strip(), 'build requires a clean source commit'
    revision=r.run(['git','rev-parse','HEAD']).strip()
    assert r.inspect('bee-researcher-direct:3.38.2-operational')['Id']==r.OLD_IMAGE
    environment=dict(os.environ);environment['DOCKER_BUILDKIT']='0'
    result=r.run(['docker','build','--network','none','--pull=false','-f','src/market_intelligence/Dockerfile.release',
        '--build-arg','SOURCE_REVISION='+revision,'-t','bee-researcher-direct:3.39.0-security','src/market_intelligence'],env=environment,timeout=600)
    r.write(r.ART/'build.log',result)
    built=r.inspect('bee-researcher-direct:3.39.0-security')
    assert built['Config']['Labels']['org.opencontainers.image.revision']==revision
    assert built['Config']['Labels']['org.opencontainers.image.version']=='3.39.0'
    ident=built['Id']
    r.write(r.ART/'image.json',{'image_id':ident,'revision':revision,'candidate':False,'base_image_id':r.OLD_IMAGE})
    result=r.run(['docker','build','--network','none','--pull=false','-f','src/market_intelligence/Dockerfile.rollback',
        '--build-arg','SOURCE_REVISION='+revision,'-t','bee-researcher-direct:3.38.2-security-rollback','src/market_intelligence'],env=environment,timeout=600)
    r.write(r.ART/'rollback-build.log',result)
    fallback=r.inspect('bee-researcher-direct:3.38.2-security-rollback')
    r.write(r.ART/'rollback-image.json',{'image_id':fallback['Id'],'source_revision':revision,
        'previous_base_image_id':r.OLD_IMAGE,'password_format_compatible':True,'journal_downgrade':False})
    runtime=r.prepared_env();runtime.update({'MARKET_INTELLIGENCE_BUILD_REVISION':revision,'MARKET_INTELLIGENCE_IMAGE_DIGEST':ident})
    r.write(r.PRIVATE/'runtime.json',runtime,private=True);r.env_file(r.PRIVATE/'runtime.env',runtime)
    # Verify every copied source file by reading the image itself. No secrets/config are copied.
    expected={}
    root=r.SOURCE/'src/market_intelligence'
    for name in ['app','tests','scripts','golden','alembic','alembic.ini','VERSION','start-service.sh']:
        path=root/name
        for file in ([path] if path.is_file() else path.rglob('*')):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix not in {'.pyc','.pyo'}:
                expected[str(file.relative_to(root))]=hashlib.sha256(file.read_bytes()).hexdigest()
    program='import pathlib,hashlib,json\npaths='+repr(list(expected))+'\nprint(json.dumps({p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in paths}))'
    actual=json.loads(image_run(['python','-c',program],test_env=False))
    assert actual==expected, 'image/source mismatch'
    r.write(r.ART/'source-files.json',expected)
    tests=image_run(['python','-c',"import unittest,sys; r=unittest.TextTestRunner(stream=sys.stdout).run(unittest.defaultTestLoader.discover('tests')); sys.exit(not r.wasSuccessful())"])
    assert re.search(r"Ran (\d+) tests",tests) and tests.rstrip().endswith('OK')
    count=int(re.search(r"Ran (\d+) tests",tests).group(1))
    r.write(r.ART/'unit-tests.log',tests)
    static=''
    for script in ('check_csp_inline_budget.py','check_i18n_catalog.py'):
        static+=image_run(['python','scripts/'+script])
    r.write(r.ART/'static-checks.log',static)
    r.write(r.ART/'migration.sql',image_run(['alembic','upgrade','head','--sql']))
    r.run(['git','archive','--format=tar','--output='+str(r.ART/'source.tar'),'HEAD'])
    r.run(['git','bundle','create',str(r.ART/'source.bundle'),'HEAD'])
    r.run(['docker','save','--output',str(r.ART/'image.tar'),ident],timeout=600)
    os.chmod(r.ART/'image.tar',0o600)
    cache=r.WORK/'ops/bee-researcher-direct/artifacts/trivy-cache'
    trivy=['docker','run','--rm','--network','none','--memory','2g','-e','TRIVY_SKIP_VERSION_CHECK=true',
        '-v',str(r.ART)+':/release','-v',str(cache)+':/cache','aquasec/trivy:0.75.0',
        '--cache-dir','/cache','image','--input','/release/image.tar','--offline-scan','--skip-db-update','--skip-java-db-update']
    r.run(trivy+['--scanners','vuln,secret','--format','json','--output','/release/trivy-report.json'],timeout=600)
    r.run(trivy+['--scanners','vuln','--format','cyclonedx','--output','/release/sbom.cdx.json'],timeout=600)
    scan=json.loads((r.ART/'trivy-report.json').read_text())
    vulnerabilities=[v for result in scan.get('Results',[]) for v in result.get('Vulnerabilities',[])]
    critical=[v for v in vulnerabilities if v['Severity'] in {'HIGH','CRITICAL'}]
    secret_findings=[v for result in scan.get('Results',[]) for v in result.get('Secrets',[])]
    # Any finding needs explicit local triage before this gate can pass.
    assert not critical, 'high/critical vulnerability gate failed'
    assert not secret_findings, 'secret scan gate requires local review'
    r.write(r.ART/'security-passed.json',{'high_or_critical':0,'secret_findings':0,'offline':True,
        'inventory_uploaded':False,'advisory_database':json.loads((cache/'db/metadata.json').read_text())})
    files=['image.json','rollback-image.json','source-files.json','unit-tests.log','static-checks.log','migration.sql',
        'source.tar','source.bundle','image.tar','trivy-report.json','sbom.cdx.json','security-passed.json']
    hashes={name:hashlib.sha256((r.ART/name).read_bytes()).hexdigest() for name in files}
    manifest={'source_revision':revision,'version':'3.39.0','image_id':ident,'base_image_id':r.OLD_IMAGE,
        'clean_source':True,'unit_tests':count,'source_file_count':len(expected),'files':hashes,
        'inventory_uploaded':False,'source_root':str(r.SOURCE),'build_dockerfile':'Dockerfile.release'}
    r.write(r.ART/'manifest.json',manifest)
    signing=r.WORK/'ops/bee-researcher-direct/artifacts/signing'
    r.run(['openssl','dgst','-sha256','-sign',str(signing/'release-private.pem'),'-out',str(r.ART/'manifest.sig'),str(r.ART/'manifest.json')])
    verified=r.run(['openssl','dgst','-sha256','-verify',str(signing/'release-public.pem'),'-signature',str(r.ART/'manifest.sig'),str(r.ART/'manifest.json')])
    assert 'Verified OK' in verified
    r.write(r.ART/'release-verified.json',{'image_id':ident,'source_revision':revision,'signature_verified':True,
        'unit_tests':count,'source_file_count':len(expected),'offline_scan_passed':True})
    print(f'Final image verified against {len(expected)} source files; {count} tests passed; offline scan and signed provenance passed.')


if __name__=='__main__': main()
