"""Bounded private WAV files; independent versioned AEAD keyring."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import wave
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import get_settings

MAX_BYTES=25_000_000
RATE=16000


def wav(pcm):
    if not pcm or len(pcm)%2 or len(pcm)+44>MAX_BYTES:raise ValueError('invalid_pcm')
    out=io.BytesIO()
    with wave.open(out,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(RATE);f.writeframes(pcm)
    return out.getvalue()


def pcm(data):
    with wave.open(io.BytesIO(data),'rb') as f:
        if f.getnchannels()!=1 or f.getsampwidth()!=2 or f.getframerate()!=RATE or f.getcomptype()!='NONE':
            raise ValueError('invalid_wav')
        if f.getnframes()*2+44>MAX_BYTES:raise ValueError('audio_too_large')
        result=f.readframes(f.getnframes())
        if len(result)!=f.getnframes()*2:raise ValueError('invalid_wav')
    if not result or len(result)%2:raise ValueError('invalid_wav')
    return result


class Store:
    def __init__(self,settings=None):
        s=settings or get_settings()
        self.root=Path(s.news_voice_storage_path).resolve()
        report=Path(getattr(s,'report_storage_path','/var/lib/bee-researcher/report')).resolve()
        if self.root==report or report in self.root.parents or self.root in report.parents:
            raise ValueError('independent_voice_storage_required')
        path=Path(s.news_voice_keyring_file)
        if not s.news_voice_keyring_file or path.is_symlink() or path.stat().st_mode&0o077:
            raise ValueError('private_voice_keyring_required')
        if path.stat().st_size>16000:raise ValueError('invalid_keyring')
        data=json.loads(path.read_text())
        self.active=data['active']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',self.active):raise ValueError('invalid_keyring')
        self.keys={k:base64.b64decode(v,validate=True) for k,v in data['keys'].items()}
        if (not 1<=len(self.keys)<=32 or self.active not in self.keys or
                any(not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',k) for k in self.keys) or
                any(len(k)!=32 for k in self.keys.values())):raise ValueError('invalid_keyring')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.root.stat().st_mode&0o077:raise ValueError('private_voice_storage_required')

    def path(self,key):
        if not re.fullmatch(r'[0-9a-f]{32}',key):raise ValueError('invalid_object')
        return self.root/(key+'.aead')

    @staticmethod
    def aad(asset):return f'bee-reader-voice:1:{asset.user_id}:{asset.assistant_id}:{asset.id}'.encode()

    def write(self,asset,data):
        if len(data)>MAX_BYTES:raise ValueError('audio_too_large')
        key=asset.id.hex
        path=self.path(key)
        nonce=secrets.token_bytes(12)
        encrypted=AESGCM(self.keys[self.active]).encrypt(nonce,data,self.aad(asset))
        envelope=b'BRV1'+bytes([len(self.active)])+self.active.encode()+nonce+encrypted
        pending=path.with_suffix('.pending')
        fd=os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'wb') as f:f.write(envelope);f.flush();os.fsync(f.fileno())
            os.replace(pending,path)
            d=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(d)
            finally:os.close(d)
        finally:
            pending.unlink(missing_ok=True)
        return key,hashlib.sha256(data).hexdigest()

    def read(self,asset):
        fd=os.open(self.path(asset.object_key),os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as f:data=f.read(MAX_BYTES+256)
        if data[:4]!=b'BRV1' or len(data)>MAX_BYTES+128:raise ValueError('invalid_audio_object')
        n=data[4];key_id=data[5:5+n].decode('ascii');nonce=data[5+n:17+n]
        clear=AESGCM(self.keys[key_id]).decrypt(nonce,data[17+n:],self.aad(asset))
        if len(clear)!=asset.byte_count or hashlib.sha256(clear).hexdigest()!=asset.sha256:raise ValueError('audio_integrity_failed')
        return clear

    def remove(self,key):
        self.path(key).unlink(missing_ok=True)
        self.path(key).with_suffix('.pending').unlink(missing_ok=True)
