"""Retain the previous application with compatibility for versioned hashes.

No schema downgrade: the additive security journal is a permanent floor.
Patch before loading routes so imports in both portals see the same verifier.
"""
import runpy
import uvicorn

from app import admin
from app.password_security import check_password, hash_password

admin._check_password = check_password
admin._hash_password = hash_password

if __name__ == "__main__":
    runpy.run_module("app.auth_deployment", run_name="__main__")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8010,
                access_log=False, proxy_headers=False)
