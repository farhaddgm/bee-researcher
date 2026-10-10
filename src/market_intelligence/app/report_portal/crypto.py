"""Tenant/purpose-bound authenticated encryption; no plaintext fallback."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
import os
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from app.config import get_settings


def keyring() -> list[bytes]:
    settings = get_settings()
    secret = settings.report_encryption_secret
    if settings.report_encryption_secret_file:
        try:
            from pydantic import SecretStr

            secret = SecretStr(
                Path(settings.report_encryption_secret_file).read_text().strip()
            )
        except OSError:
            raise HTTPException(503, "report_encryption_unavailable") from None
    if not secret or len(secret.get_secret_value()) < 32:
        raise HTTPException(503, "report_encryption_unavailable")
    values = [secret.get_secret_value()]
    if settings.report_previous_encryption_secrets:
        try:
            previous = json.loads(
                settings.report_previous_encryption_secrets.get_secret_value()
            )
            if (
                not isinstance(previous, list)
                or len(previous) > 8
                or any(not isinstance(v, str) or len(v) < 32 for v in previous)
            ):
                raise ValueError()
            values.extend(previous)
        except (TypeError, ValueError):
            raise HTTPException(503, "report_encryption_unavailable") from None
    return [hashlib.sha256(v.encode()).digest() for v in values]


def encrypt(business_id: uuid.UUID, scope: str, payload: dict) -> str:
    master = keyring()[0]
    kid = hashlib.sha256(master).hexdigest()[:16]
    key = hmac.new(master, b"report-v1:" + business_id.bytes, hashlib.sha256).digest()
    aad = f"report-v1:{business_id}:{scope}:{kid}".encode()
    nonce = os.urandom(12)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ciphertext = AESGCM(key).encrypt(nonce, data, aad)
    return kid + "." + base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt(business_id: uuid.UUID, scope: str, ciphertext: str) -> dict:
    try:
        kid, encoded = ciphertext.split(".", 1)
        master = next(k for k in keyring() if hashlib.sha256(k).hexdigest()[:16] == kid)
        key = hmac.new(
            master, b"report-v1:" + business_id.bytes, hashlib.sha256
        ).digest()
        data = base64.b64decode(encoded, altchars=b"-_", validate=True)
        aad = f"report-v1:{business_id}:{scope}:{kid}".encode()
        result = json.loads(AESGCM(key).decrypt(data[:12], data[12:], aad))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except HTTPException:
        raise
    except Exception:
        # No exception message or ciphertext is sent to UI/logs.
        raise HTTPException(503, "report_encryption_unavailable") from None
