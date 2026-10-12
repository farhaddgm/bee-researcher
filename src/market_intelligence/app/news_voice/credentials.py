"""Owner-managed, write-only provider credential on the shared private volume.

No plaintext key in SQL, policy JSON, environment updates or API responses.
The existing versioned voice keyring supplies a purpose-separated AES-GCM key.
All workers read the same atomic file, so rotations do not require a restart.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
import secrets
import stat
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.news_voice.storage import Store

AAD = b'bee-researcher:elevenlabs-credential:1'


class CredentialError(Exception):
    def __init__(self, code='voice_credential_unavailable'):
        self.code = code
        super().__init__(code)


class Credentials:
    def __init__(self, settings=None):
        self.store = Store(settings or get_settings())
        self.root = self.store.root / 'credentials'
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_mode & 0o077:
            raise CredentialError()
        self.path = self.root / 'elevenlabs.aead'

    def cipher(self, kid):
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=AAD).derive(self.store.keys[kid])
        return AESGCM(derived)

    def read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        try:
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4096:
                    raise CredentialError()
                blob = stream.read(4097)
            if len(blob) < 34 or blob[:4] != b'BRK1':
                raise CredentialError()
            length = blob[4]
            kid = blob[5:5+length].decode('ascii')
            value = json.loads(self.cipher(kid).decrypt(blob[5+length:17+length], blob[17+length:], AAD))
            if set(value) != {'key', 'revision', 'updated_at'} or not isinstance(value['key'], str):
                raise CredentialError()
            uuid.UUID(hex=value['revision'])
            datetime.fromisoformat(value['updated_at'])
            if value['key'] and not valid_key(value['key']):
                raise CredentialError()
            return value
        except Exception:
            # Never propagate a crypto/JSON error, file path or secret.
            raise CredentialError() from None

    @contextmanager
    def lock(self):
        fd = os.open(self.root / 'update.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise CredentialError()
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def update(self, key, expected_revision):
        if key and not valid_key(key):
            raise CredentialError('voice_key_invalid')
        with self.lock():
            old = self.read()
            if expected_revision != (old['revision'] if old else 'server'):
                raise CredentialError('revision_conflict')
            value = {'key': key, 'revision': uuid.uuid4().hex, 'updated_at': datetime.now(timezone.utc).isoformat()}
            kid = self.store.active
            nonce = secrets.token_bytes(12)
            blob = b'BRK1' + bytes([len(kid)]) + kid.encode() + nonce + self.cipher(kid).encrypt(
                nonce, json.dumps(value).encode(), AAD)
            pending = self.root / (uuid.uuid4().hex + '.pending')
            fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(blob)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(pending, self.path)
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                pending.unlink(missing_ok=True)
        return metadata(value)


def valid_key(value):
    return isinstance(value, str) and 16 <= len(value) <= 500 and all(33 <= ord(c) <= 126 for c in value)


def metadata(value):
    return {'configured': bool(value['key']), 'source': 'owner' if value['key'] else 'disabled',
            'revision': value['revision'], 'updated_at': value['updated_at'], 'editable': True}


def managed(settings=None):
    settings = settings or get_settings()
    if not settings.news_voice_keyring_file:
        return None
    try:
        return Credentials(settings).read()
    except Exception:
        raise CredentialError() from None


def status():
    from app.news_voice.providers import key, VoiceError
    try:
        store = Credentials()
        value = store.read()
        if value is not None:
            return metadata(value)
        try:
            key()
            configured = True
        except VoiceError:
            configured = False
        return {'configured': configured, 'source': 'server' if configured else 'missing',
                'revision': 'server', 'updated_at': None, 'editable': True}
    except Exception:
        return {'configured': False, 'source': 'unavailable', 'revision': 'unavailable',
                'updated_at': None, 'editable': False}
