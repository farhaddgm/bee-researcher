"""Provision NEW private encryption/storage only, never an ElevenLabs API key.

Run with filesystem ownership authority. Never reads application data,
restarts a service, modifies another keyring or overwrites an existing file.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets

ROOT=Path('/opt/ai-assistant/ops/bee-researcher-direct/private')


def provision(directory):
    directory=Path(directory)
    if (directory.is_symlink() or directory.parent.resolve()!=ROOT.resolve()
            or not directory.name.startswith('voice-bootstrap-')):
        raise ValueError('New Researcher voice-bootstrap directory required')
    # Exclusive creation: never rotate, rekey, overwrite or reuse unknown data.
    directory.mkdir(mode=0o700)
    state=directory/'state';state.mkdir(mode=0o700)
    key=directory/'keyring.json'
    value={'active':'v1','keys':{'v1':base64.b64encode(secrets.token_bytes(32)).decode()}}
    descriptor=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as output:
        json.dump(value,output);output.flush();os.fsync(output.fileno())
    for target in (key,state):os.chown(target,10002,10002)
    # Keep the operator able to inspect metadata, not read the service key.
    # Only the key file and state directory themselves are service mounts.
    parent=directory.parent.stat();os.chown(directory,parent.st_uid,parent.st_gid)
    return {'keyring_file':str(key),'state_dir':str(state),'api_key_provisioned':False,
            'other_services_changed':False,'existing_keys_changed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True,type=Path)
    try:print(json.dumps(provision(parser.parse_args().directory)))
    except Exception:
        # Key material and filesystem diagnostics must not enter logs.
        raise SystemExit('Voice bootstrap failed; no existing secret was overwritten.') from None
