"""Retain the previous application with compatibility for versioned hashes.

No schema downgrade: the additive security journal is a permanent floor.
Patch before loading routes so imports in both portals see the same verifier.
"""
import runpy
import os
from urllib.parse import quote
import uvicorn

from app.config import Settings
from app import admin
from app.password_security import check_password, hash_password

admin._check_password = check_password
admin._hash_password = hash_password

# The previous settings model predates named Redis users. Preserve its default
# behavior, but also support the isolated ACL during rollback verification.
_previous_redis_url = Settings.redis_url.fget
def _redis_url(settings):
    username = os.environ.get("MARKET_INTELLIGENCE_REDIS_USERNAME")
    if not username:
        return _previous_redis_url(settings)
    password = quote(settings.redis_password.get_secret_value(), safe="")
    return f"redis://{quote(username, safe='')}:{password}@{settings.redis_host}:{settings.redis_port}/{settings.redis_database}"
Settings.redis_url = property(_redis_url)

if __name__ == "__main__":
    runpy.run_module("app.auth_deployment", run_name="__main__")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8010,
                access_log=False, proxy_headers=False)
