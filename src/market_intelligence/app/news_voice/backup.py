"""Streaming, authenticated disaster-recovery bundle with a separate key.

The recovery key is kept outside the application volume. Neither ciphertext
audio nor the encrypted provider credential needs conversion to plaintext.
Restore authenticates the entire bundle before extracting any file.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import tarfile
import tempfile
from types import SimpleNamespace
import uuid
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from app.config import get_settings
from app.news_voice.storage import Store, wav

AAD = b'bee-researcher:voice-backup:1'
MAX_BUNDLE = 4_000_000_000


def private_file(path):
    path = Path(path)
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise ValueError('private regular file required')
    return path


def recovery_key(path):
    data = private_file(path).read_bytes()
    if len(data) != 32:
        raise ValueError('independent 256-bit recovery key required')
    return data


class EncryptedWriter:
    def __init__(self, output, key):
        nonce = secrets.token_bytes(12)
        self.output = output
        output.write(b'BRB1' + nonce)
        self.encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        self.encryptor.authenticate_additional_data(AAD)
        self.count = 0

    def write(self, data):
        self.count += len(data)
        if self.count > MAX_BUNDLE:
            raise ValueError('backup limit exceeded')
        self.output.write(self.encryptor.update(data))
        return len(data)

    def finish(self):
        self.output.write(self.encryptor.finalize() + self.encryptor.tag)


def member(archive, name, data):
    item = tarfile.TarInfo(name)
    item.size = len(data)
    item.mode = 0o600
    archive.addfile(item, io.BytesIO(data))


def create(destination, key_path, database_dump=None):
    settings = get_settings()
    store = Store(settings)
    key = recovery_key(key_path)
    if key in store.keys.values():
        raise ValueError('recovery key must be independent')
    destination = Path(destination)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with tempfile.TemporaryDirectory(prefix='bee-voice-backup-') as scratch, os.fdopen(descriptor, 'wb') as output:
            writer = EncryptedWriter(output, key)
            probe = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), assistant_id=uuid.uuid4())
            probe_settings = SimpleNamespace(news_voice_storage_path=scratch + '/state',
                news_voice_keyring_file=settings.news_voice_keyring_file)
            test_store = Store(probe_settings)
            data = wav(b'\x00\x10' * 16000)
            probe.object_key, probe.sha256 = test_store.write(probe, data)
            probe.byte_count = len(data)
            keyring = private_file(settings.news_voice_keyring_file).read_bytes()
            count = 0
            with tarfile.open(fileobj=writer, mode='w|') as archive:
                member(archive, 'keyring.json', keyring)
                for path in sorted(store.root.rglob('*')):
                    if path.is_dir() and not path.is_symlink():
                        continue
                    relative = path.relative_to(store.root)
                    if len(relative.parts) > 2 or path.suffix not in ('.aead', '.lock'):
                        # In-progress .pending files are not committed objects.
                        if path.suffix == '.pending':
                            continue
                        raise ValueError('unexpected voice storage entry')
                    private_file(path)
                    archive.add(path, arcname='state/' + relative.as_posix(), recursive=False)
                    count += 1
                member(archive, 'state/' + probe.object_key + '.aead', test_store.path(probe.object_key).read_bytes())
                manifest = {'at':datetime.now(timezone.utc).isoformat(), 'files':count,
                    'probe':{k:str(v) if isinstance(v, uuid.UUID) else v for k,v in vars(probe).items()}}
                member(archive, 'manifest.json', json.dumps(manifest).encode())
                if database_dump:
                    archive.add(private_file(database_dump), arcname='database.dump', recursive=False)
            # Reject a concurrent keyring rotation rather than mix generations.
            if private_file(settings.news_voice_keyring_file).read_bytes() != keyring:
                raise ValueError('keyring changed during backup')
            writer.finish()
            output.flush()
            os.fsync(output.fileno())
        return {'backup_created':True, 'state_files':count, 'database_included':bool(database_dump),
            'independent_recovery_key':True, 'plaintext_audio_exported':False}
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def restore(source, key_path, directory):
    source = private_file(source)
    if not 32 <= source.stat().st_size <= MAX_BUNDLE + 32:
        raise ValueError('invalid backup size')
    directory = Path(directory)
    if directory.exists() or directory.is_symlink():
        raise ValueError('restore requires a new isolated directory')
    with tempfile.TemporaryFile() as clear, source.open('rb') as encrypted:
        header = encrypted.read(16)
        if header[:4] != b'BRB1':
            raise ValueError('invalid backup')
        encrypted.seek(-16, os.SEEK_END)
        tag = encrypted.read(16)
        decryptor = Cipher(algorithms.AES(recovery_key(key_path)), modes.GCM(header[4:], tag)).decryptor()
        decryptor.authenticate_additional_data(AAD)
        remaining = source.stat().st_size - 32
        encrypted.seek(16)
        while remaining:
            chunk = encrypted.read(min(1_048_576, remaining))
            if not chunk:
                raise ValueError('truncated backup')
            remaining -= len(chunk)
            clear.write(decryptor.update(chunk))
        clear.write(decryptor.finalize())  # authentication precedes extraction
        clear.seek(0)
        directory.mkdir(mode=0o700)
        try:
            names = set()
            with tarfile.open(fileobj=clear, mode='r|') as archive:
                for item in archive:
                    name = Path(item.name)
                    allowed = item.name in ('keyring.json', 'manifest.json', 'database.dump') or (
                        len(name.parts) in (2,3) and name.parts[0] == 'state' and
                        name.suffix in ('.aead', '.lock') and all(p not in ('.','..') for p in name.parts))
                    if not allowed or not item.isfile() or name.is_absolute() or item.name in names or item.size > MAX_BUNDLE:
                        raise ValueError('invalid archive member')
                    names.add(item.name)
                    target = directory / name
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, 'wb') as output, archive.extractfile(item) as input_file:
                        shutil.copyfileobj(input_file, output, 1_048_576)
            manifest = json.loads((directory / 'manifest.json').read_text())
            probe = SimpleNamespace(**manifest['probe'])
            for field in ('id', 'user_id', 'assistant_id'):
                setattr(probe, field, uuid.UUID(getattr(probe, field)))
            restored = Store(SimpleNamespace(news_voice_storage_path=str(directory / 'state'),
                news_voice_keyring_file=str(directory / 'keyring.json')))
            data = restored.read(probe)
            if hashlib.sha256(data).hexdigest() != probe.sha256 or data != wav(b'\x00\x10' * 16000):
                raise ValueError('restore probe failed')
            restored.remove(probe.object_key)
            return {'authenticated_restore':True, 'wav_roundtrip_verified':True,
                'state_files':manifest['files'], 'database_included':(directory / 'database.dump').exists(),
                'live_state_overwritten':False}
        except BaseException:
            shutil.rmtree(directory)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'restore'])
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--recovery-key', required=True)
    parser.add_argument('--database-dump')
    parser.add_argument('--directory')
    args = parser.parse_args()
    try:
        result = create(args.bundle, args.recovery_key, args.database_dump) if args.action == 'create' else restore(args.bundle, args.recovery_key, args.directory)
        print(json.dumps(result))
    except Exception as exc:
        allowed={'private regular file required','independent 256-bit recovery key required','recovery key must be independent','unexpected voice storage entry','keyring changed during backup','restore requires a new isolated directory','invalid archive member'}
        code=str(exc) if isinstance(exc,ValueError) and str(exc) in allowed else type(exc).__name__
        print(json.dumps({'backup_error':code}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
