"""Verify a Researcher-only keyless release before migration or cutover.

All signature, certificate, transparency log and attestation checks remain
enabled. No runtime credentials, private application data or bypass flags.
"""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess

from deploy import ROOT, save


def documents(raw):
    decoder = json.JSONDecoder()
    items = []
    while raw.strip():
        parsed, used = decoder.raw_decode(raw.lstrip())
        items.extend(parsed if isinstance(parsed, list) else [parsed])
        raw = raw.lstrip()[used:]
    return items


def verify(directory, revision, version, cosign):
    if not re.fullmatch('[0-9a-f]{40}', revision) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Full commit and release version required')
    trace = json.loads((directory / 'market-intelligence-release-trace.json').read_text())
    image = trace['image']
    if trace['commit'] != revision or not re.fullmatch(
        'ghcr.io/farhaddgm/bee-researcher-market-intelligence@sha256:[0-9a-f]{64}', image
    ):
        raise RuntimeError('Trace source/image mismatch')
    digest = image.split('@sha256:')[1]
    claims = [
        '--certificate-identity', 'https://github.com/farhaddgm/bee-researcher/.github/workflows/market-intelligence.yml@refs/heads/main',
        '--certificate-oidc-issuer', 'https://token.actions.githubusercontent.com',
        '--certificate-github-workflow-sha', revision,
        '--certificate-github-workflow-repository', 'farhaddgm/bee-researcher',
        '--certificate-github-workflow-ref', 'refs/heads/main',
        '--certificate-github-workflow-trigger', 'push',
    ]
    verified = {}
    for key, command in [('signature', ['verify']),
        ('build_binding', ['verify-attestation', '--type', 'custom']),
        ('sbom', ['verify-attestation', '--type', 'cyclonedx'])]:
        result = subprocess.run([str(cosign), *command, *claims, image], capture_output=True, text=True, timeout=200)
        if result.returncode:
            raise RuntimeError('Independent ' + key + ' verification failed; do not promote')
        docs = documents(result.stdout)
        if not docs:
            raise RuntimeError('Empty verified evidence')
        if key == 'signature':
            if not any(d.get('critical', {}).get('image', {}).get('docker-manifest-digest') == 'sha256:' + digest for d in docs):
                raise RuntimeError('Signature digest claim mismatch')
        else:
            statements = [json.loads(base64.b64decode(d['payload'])) for d in docs]
            statements = [s for s in statements if any(v.get('digest', {}).get('sha256') == digest for v in s.get('subject', []))]
            if not statements:
                raise RuntimeError('Attestation subject mismatch')
            if key == 'build_binding':
                matches = False
                for statement in statements:
                    predicate = statement.get('predicate', {})
                    data = predicate.get('Data', predicate)
                    data = json.loads(data) if isinstance(data, str) else data
                    matches = matches or (data.get('source_repository') == 'farhaddgm/bee-researcher'
                        and data.get('source_commit') == revision and data.get('image_digest') == 'sha256:' + digest)
                if not matches:
                    raise RuntimeError('Signed source provenance mismatch')
        verified[key] = True
    receipt = {'image': image, 'revision': revision, 'version': version, **verified,
        'repository_workflow_sha_constraints_verified': True,
        'transparency_log_and_certificate_checks_enabled': True, 'verification_bypass_used': False}
    save(ROOT / 'ops/bee-researcher-direct/artifacts' / (version + '-provenance-' + revision + '.json'), receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--cosign', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.revision, args.version, args.cosign)))
