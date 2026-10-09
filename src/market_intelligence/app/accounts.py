"""Unified account directory. Identity, project membership and portal grants
are independent; all credential changes revoke both portals atomically.
No Contenter credentials, tables or sessions are shared.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, cast

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.password_security import validate_new_password
from app import admin
from app.database import SessionLocal
from app.google_auth import is_gmail, normalize_email
from app.models import AdminSession, AdminUser, AssistantMember, AssistantWorkspace

Role = Literal["admin", "assistant_admin", "editor", "analyst", "viewer"]
Method = Literal["password", "google", "both"]


def valid_email(value: str) -> str:
    email = normalize_email(value)
    if not re.fullmatch(r"[^@\s/\\]+@[a-z0-9.-]+\.[a-z]{2,63}", email):
        raise ValueError("invalid email address")
    return email


class AccountCreate(BaseModel):
    email: str = Field(min_length=6, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    username: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]{3,128}$")
    role: Role = "viewer"
    login_method: Method = "google"
    password: str | None = Field(default=None, min_length=8, max_length=128)
    assistant_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    user_portal_access: bool = False
    user_feedback_access: bool = False
    news_chat_access: bool = False

    _password_policy = field_validator("password")(validate_new_password)
    _email = field_validator("email")(valid_email)

    @model_validator(mode="after")
    def check_method(self):
        if self.login_method != "password" and not is_gmail(self.email):
            raise ValueError("Google sign-in requires Gmail")
        if self.login_method == "google" and self.password:
            raise ValueError("Google-only accounts have no internal password")
        if self.login_method != "google" and not self.password:
            raise ValueError("a password is required")
        if not self.display_name.strip():
            raise ValueError("name cannot be blank")
        return self


class AccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    # May attach an address once to an old username-only account (owner only).
    email: str | None = Field(default=None, min_length=6, max_length=320)
    role: Role | None = None
    active: bool | None = None
    login_method: Method | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    _password_policy = field_validator("password")(validate_new_password)

    current_password: str | None = Field(default=None, min_length=8, max_length=256)
    assistant_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    user_portal_access: bool | None = None
    user_feedback_access: bool | None = None
    news_chat_access: bool | None = None

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        return valid_email(value) if value is not None else None

    @field_validator("display_name")
    @classmethod
    def name_valid(cls, value):
        if value is not None and not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip() if value else value


def public_account(item: AdminUser, actor: AdminUser | None = None) -> dict:
    own = bool(actor and item.id == actor.id)
    owner = admin.is_owner(item)
    return {"id": str(item.id), "username": item.username, "email": item.email,
            "display_name": item.display_name or item.username, "role": admin.effective_user_role(item),
            "stored_role": item.role, "is_owner": owner, "active": item.active,
            "login_method": item.login_method, "has_password": bool(item.password_hash),
            "google_linked": bool(item.google_sub),
            "last_login_at": item.last_login_at.isoformat() if item.last_login_at else None,
            "created_at": item.created_at.isoformat(),
            "can_manage": bool(actor and not own and (admin.is_owner(actor) or
                (not owner and admin.role_rank(item) < admin.role_rank(actor) and actor.role in {"admin", "assistant_admin"}))),
            **admin.user_portal_access_payload(item)}


async def list_accounts(actor: AdminUser, *, q: str = "", page: int = 1, page_size: int = 20) -> dict:
    # Existing project and role visibility is authoritative, not a new global directory.
    visible = await admin.list_admin_users(actor)
    visible_users = cast(list[dict[str, Any]], visible["users"])
    ids = [uuid.UUID(item["id"]) for item in visible_users]
    async with SessionLocal() as s:
        manage_scope = await admin._project_admin_scope_ids(s, actor)
        rows = (await s.execute(select(AdminUser).where(AdminUser.id.in_(ids)).order_by(AdminUser.created_at.desc()))).scalars().all()
        needle = q.strip().casefold()
        rows = [r for r in rows if not needle or any(needle in str(v or "").casefold() for v in (r.username, r.email, r.display_name))]
        total = len(rows)
        selected = rows[(page - 1) * page_size:page * page_size]
        members = (await s.execute(select(AssistantMember).where(AssistantMember.user_id.in_([r.id for r in selected])))).scalars().all()
    visible_members = {item["id"]: item["project_access"] for item in visible_users}
    accounts = []
    for row in selected:
        account = public_account(row, actor)
        all_projects = {m.assistant_id for m in members if m.user_id == row.id}
        if manage_scope is not None and (not all_projects or not all_projects.issubset(manage_scope)):
            account["can_manage"] = False
        account["assistant_ids"] = [str(m.assistant_id) for m in members if m.user_id == row.id
            and any(str(m.assistant_id) == p["assistant_id"] for p in visible_members.get(str(row.id), []))]
        accounts.append(account)
    return {"accounts": accounts, "total": total, "page": page, "page_size": page_size,
            "can_create": admin.is_owner(actor) or actor.role in {"admin", "assistant_admin"},
            "can_manage_google": admin.is_owner(actor)}


async def _memberships(s, item, ids, actor):
    scope = await admin._project_admin_scope_ids(s, actor)
    selected = set(ids)
    if scope is not None and not selected.issubset(scope):
        raise HTTPException(403, "selected projects are outside your project scope")
    if item.role in {"admin", "assistant_admin"} and not selected and not admin.is_owner(item):
        raise HTTPException(422, "an admin user must have at least one project assignment")
    found = set((await s.execute(select(AssistantWorkspace.id).where(AssistantWorkspace.id.in_(selected), AssistantWorkspace.deleted_at.is_(None)))).scalars().all())
    if found != selected:
        raise HTTPException(404, "one or more selected projects do not exist")
    rows = (await s.execute(select(AssistantMember).where(AssistantMember.user_id == item.id))).scalars().all()
    role = "admin" if item.role in {"admin", "assistant_admin"} else "editor" if item.role == "editor" else "viewer"
    known = {m.assistant_id for m in rows}
    for m in rows:
        if scope is not None and m.assistant_id not in scope:
            continue
        if m.assistant_id not in selected:
            await s.delete(m)
        else:
            m.role = role
    for aid in selected - known:
        s.add(AssistantMember(user_id=item.id, assistant_id=aid, role=role))


def _portal(item, enabled, feedback, actor):
    if enabled is None and feedback is None:
        return
    if not (admin.is_owner(actor) or actor.role == "admin"):
        raise HTTPException(403, "owner or global admin role required")
    current = admin.user_portal_access_payload(item)
    enabled = current["user_portal_access"] if enabled is None else enabled
    feedback = current["user_feedback_access"] if feedback is None else feedback
    if not enabled and (admin.is_owner(item) or item.role == "admin"):
        raise HTTPException(422, "owner and admin accounts always have User-service access")
    if feedback and not enabled:
        raise HTTPException(422, "feedback access requires User-service access")
    item.preferences = {**(item.preferences or {}), "user_portal_access": {"enabled": enabled, "feedback_enabled": feedback}}


async def create_account(payload: AccountCreate, actor: AdminUser) -> dict:
    if not (admin.is_owner(actor) or actor.role in {"admin", "assistant_admin"}):
        raise HTTPException(403, "project admin role required")
    if payload.email == admin.owner_email():
        raise HTTPException(403, "the owner address is reserved")
    if payload.login_method != "password" and not admin.is_owner(actor):
        raise HTTPException(403, "only the owner can grant Google sign-in")
    if not admin.is_owner(actor) and admin._ROLE_RANK[payload.role] >= admin.role_rank(actor):
        raise HTTPException(403, "cannot grant an equal or higher role")
    async with SessionLocal() as s:
        if await s.scalar(select(AdminUser.id).where(AdminUser.email == payload.email)):
            raise HTTPException(409, "email already belongs to an account")
        item = AdminUser(id=uuid.uuid4(), username=(payload.username or await admin._unique_username(s, payload.email.split("@", 1)[0])).lower(),
            email=payload.email, display_name=payload.display_name.strip(), role=payload.role, login_method=payload.login_method,
            password_hash=await admin.hash_password_async(payload.password) if payload.password else None, active=True, preferences={})
        s.add(item)
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(409, "email or username already belongs to an account") from None
        await _memberships(s, item, payload.assistant_ids, actor)
        if payload.user_portal_access or payload.user_feedback_access:
            _portal(item, payload.user_portal_access or item.role == "admin", payload.user_feedback_access, actor)
        if payload.news_chat_access:
            if not admin.is_owner(actor):
                raise HTTPException(403, "owner_required")
            if not admin.user_portal_access_allowed(item):
                raise HTTPException(422, "user_portal_required")
            item.preferences = {**(item.preferences or {}), "news_chat_enabled": True}
        try:
            await s.commit()
        except IntegrityError:
            raise HTTPException(409, "email or username already belongs to an account") from None
    await admin._audit(actor.id, "account.create", details={"user_id": str(item.id), "method": item.login_method})
    return public_account(item, actor)


async def update_account(uid: uuid.UUID, payload: AccountUpdate, actor: AdminUser) -> dict:
    own = uid == actor.id
    if not own and not (admin.is_owner(actor) or actor.role in {"admin", "assistant_admin"}):
        raise HTTPException(403, "project admin role required")
    async with SessionLocal() as s:
        item = await s.get(AdminUser, uid, with_for_update=True)
        if item is None:
            raise HTTPException(404, "account not found")
        if not own:
            await admin._ensure_user_manage_scope(s, uid, actor)
        admin.ensure_can_manage_account(actor, item)
        if own and any(v is not None for v in (payload.role, payload.active, payload.assistant_ids, payload.user_portal_access, payload.user_feedback_access, payload.news_chat_access)):
            raise HTTPException(403, "self-service cannot change privileges")
        if admin.is_owner(item) and (payload.active is False or payload.role is not None):
            raise HTTPException(403, "the owner account is protected")
        if payload.role is not None and not admin.is_owner(actor) and admin._ROLE_RANK[payload.role] >= admin.role_rank(actor):
            raise HTTPException(403, "cannot grant an equal or higher role")
        if payload.email and payload.email != item.email:
            if item.email or not admin.is_owner(actor) or payload.email == admin.owner_email():
                raise HTTPException(403, "account email cannot be changed")
            item.email = payload.email
        method = payload.login_method or item.login_method
        if method != item.login_method and not admin.is_owner(actor):
            raise HTTPException(403, "only the owner can change sign-in methods")
        if method != "password" and not is_gmail(item.email or ""):
            raise HTTPException(422, "Google sign-in requires Gmail")
        if payload.password:
            if method == "google":
                raise HTTPException(422, "Google-only accounts have no internal password")
            if own and not await admin.check_password_async(payload.current_password or "", item.password_hash):
                raise HTTPException(401, "current password is incorrect")
            item.password_hash = await admin.hash_password_async(payload.password)
        if method == "google":
            item.password_hash = None
        elif not item.password_hash:
            raise HTTPException(422, "a password is required")
        if method == "password":
            item.google_sub = None
        item.login_method = method
        if payload.display_name:
            item.display_name = payload.display_name
        if payload.role:
            item.role = payload.role
        if payload.active is not None:
            item.active = payload.active
        _portal(item, payload.user_portal_access, payload.user_feedback_access, actor)
        if payload.news_chat_access is not None:
            if not admin.is_owner(actor):
                raise HTTPException(403, "owner_required")
            if payload.news_chat_access and not admin.user_portal_access_allowed(item):
                raise HTTPException(422, "user_portal_required")
            item.preferences = {**(item.preferences or {}), "news_chat_enabled": payload.news_chat_access}
        if payload.assistant_ids is not None:
            await _memberships(s, item, payload.assistant_ids, actor)
        elif payload.role is not None:
            scope = await admin._project_admin_scope_ids(s, actor)
            current = (await s.execute(select(AssistantMember.assistant_id).where(AssistantMember.user_id == uid))).scalars().all()
            await _memberships(s, item, [aid for aid in current if scope is None or aid in scope], actor)
        # No JWT grace period: all credentials and privileges change in the same transaction.
        if any(v is not None for v in (payload.password, payload.login_method, payload.active, payload.role, payload.email, payload.assistant_ids, payload.user_portal_access, payload.user_feedback_access, payload.news_chat_access)):
            await s.execute(delete(AdminSession).where(AdminSession.user_id == uid))
        try:
            await s.commit()
        except IntegrityError:
            raise HTTPException(409, "email already belongs to an account") from None
    await admin._audit(actor.id, "account.update", details={"user_id": str(uid), "fields": sorted(payload.model_fields_set - {"password", "current_password"})})
    return public_account(item, actor)


async def remove_account(uid: uuid.UUID, actor: AdminUser) -> dict:
    if uid == actor.id:
        raise HTTPException(403, "you cannot delete yourself")
    if not (admin.is_owner(actor) or actor.role == "admin"):
        raise HTTPException(403, "admin role required")
    async with SessionLocal() as s:
        item = await s.get(AdminUser, uid, with_for_update=True)
        if item is None:
            raise HTTPException(404, "account not found")
        await admin._ensure_user_manage_scope(s, uid, actor)
        admin.ensure_can_manage_account(actor, item)
        if admin.is_owner(item):
            raise HTTPException(403, "the owner account cannot be deleted")
        await s.execute(delete(AdminSession).where(AdminSession.user_id == uid))
        await s.execute(delete(AssistantMember).where(AssistantMember.user_id == uid))
        await s.delete(item)
        await s.commit()
    await admin._audit(actor.id, "account.delete", details={"user_id": str(uid)})
    return {"status": "deleted"}
