"""Versioned password hashes and a bounded off-loop password worker pool."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore
from fastapi import HTTPException

N, R, P = 2**17, 8, 1
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="password")
# Bound pending work as well as active threads, so a login burst cannot keep
# database connections waiting behind an unbounded password queue.
_admission = BoundedSemaphore(4)
_COMMON = frozenset({
    "password", "password123", "password123456789", "123456789012345",
    "1234567890123456", "qwertyuiopasdfgh", "letmein", "admin", "welcome",
    "changeme", "correcthorsebatterystaple", "thisisapassword", "iloveyou",
    "bee-researcher", "beeresearcher", "رمزعبور", "گذرواژه",
})

# Vendored, revision/hash-pinned public blocklist: all comparisons remain local.
_COMMON = _COMMON | frozenset(
    "".join(c for c in unicodedata.normalize("NFKC", line).casefold() if c.isalnum())
    for line in Path(__file__).with_name("common-passwords.txt").read_text(encoding="utf-8").splitlines()
)


def validate_new_password(value: str | None) -> str | None:
    if value is None:
        return value
    if not 15 <= len(value) <= 128:
        raise ValueError("password must contain 15 to 128 characters")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    compact = "".join(c for c in normalized if c.isalnum())
    base = compact.rstrip("0123456789")
    leet = "".join(c for c in normalized.translate(str.maketrans({"0":"o", "1":"i", "3":"e", "4":"a", "5":"s", "7":"t", "@":"a", "$":"s"})) if c.isalnum()).rstrip("0123456789")
    if compact in _COMMON or base in _COMMON or leet in _COMMON or len(set(compact)) < 5:
        raise ValueError("choose an uncommon password or a long passphrase")
    if compact in ("0123456789" * 13, "1234567890" * 13, "abcdefghijklmnopqrstuvwxyz" * 5):
        raise ValueError("choose an uncommon password or a long passphrase")
    return value


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, maxmem=256*1024*1024)
    return f"scrypt$v2${N}${R}${P}${salt.hex()}${digest.hex()}"


def needs_rehash(encoded: str | None) -> bool:
    return not bool(encoded and encoded.startswith(f"scrypt$v2${N}${R}${P}$"))


_DUMMY = hash_password(secrets.token_urlsafe(24))


def check_password(password: str, encoded: str | None) -> bool:
    absent = not encoded
    encoded = encoded or _DUMMY
    try:
        parts = encoded.split("$")
        if len(parts) == 3 and parts[0] == "scrypt":
            n, r, p, salt, expected = 2**14, 8, 1, parts[1], parts[2]
        elif len(parts) == 7 and parts[:2] == ["scrypt", "v2"]:
            n, r, p = map(int, parts[2:5])
            salt, expected = parts[5:]
            if (n, r, p) != (N, R, P):
                return False
        else:
            return False
        if len(password) > 256 or len(salt) != 32 or len(expected) != 128:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=n, r=r, p=p, maxmem=256*1024*1024)
        matched = hmac.compare_digest(actual.hex(), expected)
        # Legacy accounts and absent/modern accounts perform both work factors;
        # failed-login timing does not reveal which hash generation is stored.
        padding_n = N if n == 2**14 else 2**14
        hashlib.scrypt(password.encode(), salt=b"timing-padding!!", n=padding_n, r=R, p=P, maxmem=256*1024*1024)
        return matched and not absent
    except (ValueError, TypeError, AttributeError):
        return False


async def _password_work(function, *args):
    if not _admission.acquire(blocking=False):
        raise HTTPException(503, "authentication temporarily unavailable", headers={"Retry-After": "1"})
    try:
        future = _workers.submit(function, *args)
    except Exception:
        _admission.release()
        raise
    # Release when the actual worker finishes, even if its caller disconnects.
    future.add_done_callback(lambda _: _admission.release())
    return await asyncio.wrap_future(future)


async def hash_password_async(password: str) -> str:
    return await _password_work(hash_password, password)


async def check_password_async(password: str, encoded: str | None) -> bool:
    return await _password_work(check_password, password, encoded)
