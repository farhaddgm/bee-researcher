"""Inspect only coarse canary evidence; never export raw production logs."""
import json
from pathlib import Path
import subprocess
import time


def main():
    start=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    result=subprocess.run(['docker','exec','ai-market-intelligence','python',
        'scripts/verify_live_privacy_delivery.py','--live'],capture_output=True,text=True,timeout=120)
    if result.returncode:
        raise RuntimeError('Authenticated canary failed; diagnostics withheld')
    evidence=json.loads(result.stdout)
    marker=evidence.pop('canary_marker')
    logs=subprocess.run(['docker','logs','--since',start,'--tail','1000','ai-market-intelligence'],
        capture_output=True,text=True,timeout=30)
    transcript=logs.stdout+logs.stderr
    assert marker not in transcript,'canary_disclosure'
    assert 'authenticated_client_error kind=action view=unknown action=unknown phase=unknown outcome=unknown route=unknown status=799' in transcript,'canary_not_observed'
    live=json.loads(subprocess.check_output(['docker','inspect','ai-market-intelligence'],text=True))[0]
    checked=0
    for item in live['Config']['Env']:
        if '=' not in item:continue
        key,value=item.split('=',1)
        if key.startswith('MARKET_INTELLIGENCE_') and any(k in key for k in ('SECRET','PASSWORD','TOKEN','API_KEY')) and len(value)>=16:
            checked+=1;assert value not in transcript,'configured_secret_disclosure'
    evidence.update({'sanitized_event_observed':True,'canary_disclosures':0,
        'configured_secret_values_checked':checked,'configured_secret_disclosures':0,
        'native_os_or_telegram_delivery_verified':False,'google_login_verified':False})
    path=Path('/opt/ai-assistant/ops/bee-researcher-direct/artifacts/3.40.0-live-canary.json')
    if path.exists():raise RuntimeError('Existing canary receipt must not be overwritten')
    path.write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence))


if __name__=='__main__':main()
