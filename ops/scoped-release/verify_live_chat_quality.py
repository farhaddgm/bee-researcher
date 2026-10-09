"""Bounded synthetic chat QA using only Researcher's existing approved key."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--assistant',type=uuid.UUID,required=True)
    args = parser.parse_args()
    live = json.loads(subprocess.check_output(['docker','inspect','ai-market-intelligence'],text=True))[0]
    allowed = {'OPENAI_API_KEY','ANALYSIS_MODEL','EXTERNAL_ANALYSIS_APPROVED','DEPLOYMENT_DRAIN_ENABLED',
        'ENVIRONMENT','MODEL_INPUT_USD_PER_MILLION_TOKENS','MODEL_OUTPUT_USD_PER_MILLION_TOKENS'}
    values = {}
    for item in live['Config']['Env']:
        if not item.startswith('MARKET_INTELLIGENCE_') or '=' not in item:
            continue
        key,value=item.split('=',1); short=key.removeprefix('MARKET_INTELLIGENCE_')
        if short in allowed or short.startswith(('POSTGRES_','REDIS_')):
            values[key]=value
    # Only existing Researcher credentials; no provisioning, grants or rekeys.
    values.update(MARKET_INTELLIGENCE_SCHEDULER_ENABLED='false',
                  MARKET_INTELLIGENCE_TELEGRAM_POLLING_ENABLED='false',MARKET_INTELLIGENCE_NEWS_CHAT_ENABLED='false')
    if any('\n' in v or '\r' in v for v in values.values()):
        raise RuntimeError('multiline_environment_requires_secret_files')
    with tempfile.TemporaryDirectory(prefix='bee-chat-quality-') as directory:
        env = Path(directory)/'researcher.env'
        descriptor = os.open(env,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as output:
            output.write(''.join(k+'='+v+'\n' for k,v in values.items()))
        # The backend is intentionally internal: a backend-only test cannot
        # reach OpenAI. Reuse the existing service's approved network namespace
        # (no host port, listener, service restart or new egress entitlement).
        result = subprocess.run(['docker','run','--rm','--network','container:ai-market-intelligence',
            '--env-file',str(env),'--read-only','--tmpfs','/tmp:size=32m,mode=1777','--cap-drop','ALL',
            '--security-opt','no-new-privileges:true','--entrypoint','python',args.image,
            'scripts/verify_live_chat_quality.py','--live','--assistant',str(args.assistant)],
            capture_output=True,text=True,timeout=800)
        if result.stdout:
            print(result.stdout.strip())  # Synthetic report answers only.
        if result.returncode:
            # Withhold traceback/runtime values; no credentials in diagnostics.
            raise RuntimeError('chat_quality_evaluation_failed; inspect bounded ledger')


if __name__ == '__main__':
    main()
