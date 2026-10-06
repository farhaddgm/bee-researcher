"""Real PostgreSQL/API/OIDC integration. Only synthetic, isolated environments.

Google's network boundary is replaced, not its state/PKCE/signature verification.
No real Google, Telegram, AI or Contenter credentials are accepted by this test.
"""
import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr
from sqlalchemy import delete, select

from app import admin, google_auth, main
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AdminSession, AdminUser, AssistantMember, AssistantWorkspace


async def run():
    cfg = get_settings()
    if (cfg.environment != "test" or cfg.postgres_db != "assistant_test" or cfg.openai_ready
            or cfg.telegram_ready or cfg.google_login_ready or cfg.scheduler_enabled):
        raise RuntimeError("Refusing a live database or configured external providers")
    suffix = uuid.uuid4().hex[:12]
    ids, project_ids = [], [uuid.uuid4(), uuid.uuid4()]
    owner_email = f"authowner{suffix}@gmail.com"
    password = "synthetic-fixture-password"
    local = cfg.model_copy(update={"owner_email": owner_email, "admin_cookie_secure": False,
        "google_client_id": "synthetic.apps.googleusercontent.com", "google_client_secret": SecretStr("synthetic-only"),
        "google_redirect_uri": "http://auth-app/auth/google/callback", "domain": None, "legacy_domain": None})
    transport = httpx.ASGITransport(app=main.app)
    def client():
        return httpx.AsyncClient(transport=transport, base_url="http://auth-app", follow_redirects=False)
    async def request(c, method, path, body=None, *, status=200, csrf=True):
        headers = {"Origin": "http://auth-app"}
        if csrf:
            headers["X-CSRF-Token"] = c.cookies.get(admin.CSRF_COOKIE) or ""
        r = await c.request(method, path, json=body, headers=headers)
        assert r.status_code == status, (method, path, r.status_code, status, r.text[:400])
        return r
    async def password_login(c, email, *, reader=False, status=200, value=password):
        return await request(c, "POST", "/user/api/login" if reader else "/admin/api/login",
                             {"email": email, "password": value}, status=status)
    async def create(c, **fields):
        body = {"email": f"member{uuid.uuid4().hex[:12]}@gmail.com", "display_name": "Synthetic account",
            "assistant_ids": [str(project_ids[0])], "login_method": "both", "password": password, **fields}
        item = (await request(c, "POST", "/admin/api/accounts", body)).json()
        ids.append(uuid.UUID(item["id"]))
        assert "password_hash" not in item and "google_sub" not in item
        return item
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "synthetic-test-key"
    finish = google_auth.finish_flow
    async def oidc_finish(settings, *, flow, **kwargs):
        identity = oidc_finish.identity
        claims = {"iss": "https://accounts.google.com", "aud": local.google_client_id, "iat": int(time.time()),
            "exp": int(time.time()) + 300, "sub": identity[1], "email": identity[0], "email_verified": True,
            "nonce": flow["nonce"], "name": "Synthetic Google account"}
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": jwk["kid"]})
        def provider(r):
            if str(r.url) == google_auth.TOKEN_URL:
                values = parse_qs(r.content.decode())
                assert values["code_verifier"][0] == flow["verifier"]
                assert values["client_id"][0] == local.google_client_id
                return httpx.Response(200, json={"id_token": token})
            assert str(r.url) == google_auth.JWKS_URL
            return httpx.Response(200, json={"keys": [jwk]})
        return await finish(settings, flow=flow, transport=httpx.MockTransport(provider), **kwargs)
    async def google_login(c, email, sub, *, reader=False, error=None, wrong_state=False):
        oidc_finish.identity = (email, sub)
        portal = "user" if reader else "admin"
        start = await request(c, "GET", f"/auth/google/start?portal={portal}&redirectTo=/{portal}?view=account", status=302)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        assert "code_challenge" in start.headers["location"]
        r = await request(c, "GET", "/auth/google/callback?code=synthetic-code&state=" + ("wrong" if wrong_state else state), status=302)
        if error:
            assert f"login_error={error}" in r.headers["location"], r.headers["location"]
        else:
            assert "login_error" not in r.headers["location"], r.headers["location"]
            assert r.headers["location"].startswith("/" + portal)
        assert google_auth.FLOW_COOKIE not in c.cookies
        return r
    try:
        async with SessionLocal() as s:
            owner = AdminUser(id=uuid.uuid4(), username="auth-" + suffix, email=owner_email, display_name="Synthetic owner",
                role="admin", login_method="both", password_hash=admin._hash_password(password), preferences={})
            ids.append(owner.id)
            s.add(owner)
            s.add_all([AssistantWorkspace(id=aid, name="Synthetic account project", slug="auth-" + str(aid), status="active",
                business_name="", config={"active_business_id": None}) for aid in project_ids])
            await s.commit()
        google_auth._JWKS_CACHE.update(keys=[], until=0.0)
        with patch.object(main, "settings", local), patch.object(admin, "get_settings", return_value=local), patch.object(google_auth, "finish_flow", oidc_finish):
            async with client() as owner_client, client() as member_client:
                await password_login(owner_client, owner_email)
                me = (await request(owner_client, "GET", "/admin/api/me")).json()
                assert me["is_owner"] and me["role"] == "owner"
                assert "Max-Age=2592000" in (await request(owner_client, "GET", "/admin/api/me")).headers["set-cookie"]
                await request(owner_client, "POST", "/admin/api/accounts", {"email": "blocked@gmail.com", "display_name": "Blocked"}, status=403, csrf=False)
                await request(owner_client, "PATCH", f"/admin/api/accounts/{owner.id}", {"active": False}, status=403)
                await request(owner_client, "DELETE", f"/admin/api/accounts/{owner.id}", status=403)
                item = await create(owner_client)
                path = "/admin/api/accounts/" + item["id"]
                await password_login(member_client, item["email"], reader=True, status=403)
                await password_login(member_client, item["email"])
                await request(member_client, "PATCH", path, {"display_name": "Self-service name"})
                await request(member_client, "PATCH", path, {"role": "admin"}, status=403)
                await request(member_client, "POST", "/admin/api/accounts", {"email": "denied@gmail.com", "display_name": "Denied"}, status=403)
                await request(owner_client, "PATCH", path, {"user_portal_access": True})
                await request(member_client, "GET", "/admin/api/me", status=401)
                await password_login(member_client, item["email"])
                await password_login(member_client, item["email"], reader=True)
                user_token = member_client.cookies.get(admin.USER_SESSION_COOKIE)
                admin_token = member_client.cookies.get(admin.COOKIE)
                available = (await request(member_client, "GET", "/user/api/assistants")).json()
                assert {x["id"] for x in available["assistants"]} == {str(project_ids[0])}
                access = (await request(member_client, "GET", "/user/api/me")).json()
                assert access["user_portal_access"] and not access["user_feedback_access"]
                for resolve, token in ((admin.current_admin, user_token), (admin.current_reader, admin_token)):
                    try:
                        await resolve(token)
                    except main.HTTPException as exc:
                        assert exc.status_code == 401
                    else:
                        raise AssertionError("Portal token isolation failed")
                async with SessionLocal() as s:
                    sessions = (await s.execute(select(AdminSession).where(AdminSession.user_id == uuid.UUID(item["id"])))).scalars().all()
                    assert {x.portal for x in sessions} == {"admin", "user"}
                    for row in sessions:
                        if row.portal == "admin":
                            assert (row.expires_at - datetime.now(timezone.utc)).days >= 29
                        else:
                            assert row.expires_at <= admin._reader_nightly_expiry(row.created_at)
                await request(owner_client, "PATCH", path, {"user_feedback_access": True})
                for endpoint in ("/admin/api/me", "/user/api/me"):
                    await request(member_client, "GET", endpoint, status=401)
                # Real OIDC authorization-code -> RS256 -> allowlist -> portal cookie.
                await google_login(member_client, item["email"], "synthetic-member")
                assert (await request(member_client, "GET", "/admin/api/me")).json()["id"] == item["id"]
                await google_login(member_client, item["email"], "synthetic-member", reader=True)
                # Re-grant merges, never duplicates or unbinds a verified subject.
                granted = (await request(owner_client, "POST", "/admin/api/owner/google-access", {"email": item["email"], "login_method": "both"})).json()
                assert granted["id"] == item["id"] and granted["linked"]
                await google_login(member_client, item["email"], "wrong-subject", error="not_allowed")
                await google_login(member_client, "unlisted@gmail.com", "synthetic-unlisted", error="not_allowed")
                await google_login(member_client, item["email"], "synthetic-member", wrong_state=True, error="expired")
                await request(owner_client, "PATCH", path, {"login_method": "google"})
                await password_login(member_client, item["email"], status=401)
                await request(owner_client, "PATCH", path, {"password": password}, status=422)
                await request(owner_client, "PUT", "/admin/api/users/" + item["id"] + "/password", {"new_password": password}, status=422)
                await google_login(member_client, item["email"], "synthetic-member")
                await request(owner_client, "PATCH", path, {"active": False})
                await request(member_client, "GET", "/admin/api/me", status=401)
                await google_login(member_client, item["email"], "synthetic-member", error="inactive")
                await request(owner_client, "PATCH", path, {"active": True, "login_method": "both", "password": "password"})
                await password_login(member_client, item["email"], value="password")
                await password_login(member_client, item["email"], value="password", reader=True)
                # Admin logout must not close the independent User session.
                await request(member_client, "POST", "/admin/api/logout")
                await request(member_client, "GET", "/user/api/me")
                async with SessionLocal() as s:
                    row = await s.scalar(select(AdminSession).where(AdminSession.token_hash == hashlib.sha256(member_client.cookies.get(admin.USER_SESSION_COOKIE).encode()).hexdigest()))
                    row.created_at = datetime.now(timezone.utc) - timedelta(days=2)
                    row.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                    await s.commit()
                await request(member_client, "GET", "/user/api/me", status=401)
                await request(owner_client, "DELETE", "/admin/api/owner/google-access/" + item["id"])
                async with SessionLocal() as s:
                    row = await s.get(AdminUser, uuid.UUID(item["id"]))
                    assert row.email == item["email"] and row.login_method == "password" and row.google_sub is None
                await google_login(member_client, item["email"], "synthetic-member", error="not_allowed")
                await request(owner_client, "DELETE", path)
                ids.remove(uuid.UUID(item["id"]))
                # A project administrator may neither promote itself nor add Google grants.
                manager = await create(owner_client, login_method="password", role="admin")
                await password_login(member_client, manager["email"])
                await request(member_client, "POST", "/admin/api/accounts", {"email": "googledenied@gmail.com", "display_name": "Denied", "assistant_ids": [str(project_ids[0])]}, status=403)
                await request(member_client, "PATCH", "/admin/api/accounts/" + manager["id"], {"assistant_ids": [str(project_ids[1])]}, status=403)
                listing = (await request(member_client, "GET", "/admin/api/accounts")).json()
                assert not listing["can_manage_google"]
                google_only = await create(owner_client, login_method="google", password=None)
                await request(owner_client, "DELETE", "/admin/api/owner/google-access/" + google_only["id"])
                await password_login(member_client, google_only["email"], status=401)
        print("Account integration passed: real SQL/API, signed Google OIDC+PKCE/state, merged allowlist, method rules, self-service, roles/project ACL, User/feedback grants, immediate dual-portal revocation, independent logout, 30-day Admin and fixed 02:00 User expiry.")
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(AdminSession).where(AdminSession.user_id.in_(ids)))
            await s.execute(delete(AssistantMember).where(AssistantMember.user_id.in_(ids)))
            await s.execute(delete(AdminUser).where(AdminUser.id.in_(ids)))
            await s.execute(delete(AssistantWorkspace).where(AssistantWorkspace.id.in_(project_ids)))
            await s.commit()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
