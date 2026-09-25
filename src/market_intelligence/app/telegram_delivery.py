from __future__ import annotations

import hashlib
import html
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.security_controls import redact_sensitive_text


TELEGRAM_MESSAGE_LIMIT = 4096
PRODUCT_MESSAGE_LIMIT = 1200
SAFE_MESSAGE_LIMIT = PRODUCT_MESSAGE_LIMIT
MESSAGE_TEMPLATE_VERSION = "mi-020-v1.1.9"


def _normalize_message_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _fa_digits(value: str | int) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _escaped_text(value: str, limit: int) -> str:
    """Escape user/model text without cutting an HTML entity."""
    if limit <= 0:
        return ""
    normalized = _fa_digits(_normalize_message_text(value))
    escaped = html.escape(normalized, quote=False)
    if len(escaped) <= limit:
        return escaped
    if limit == 1:
        return "…"
    parts: list[str] = []
    used = 0
    for character in normalized:
        encoded = html.escape(character, quote=False)
        if used + len(encoded) + 1 > limit:
            break
        parts.append(encoded)
        used += len(encoded)
    return "".join(parts).rstrip() + "…"


def _bounded_prose(value: str, limit: int) -> str:
    """Keep complete sentences within a field budget."""
    normalized = _fa_digits(_normalize_message_text(value))
    escaped = html.escape(normalized, quote=False)
    if len(escaped) <= limit:
        return escaped
    candidate = normalized[: max(1, limit - 1)]
    cut = max(candidate.rfind(mark) for mark in (".", "؟", "!", "؛"))
    if cut > 20:
        return html.escape(candidate[: cut + 1].rstrip(), quote=False)
    words = candidate.rsplit(" ", 1)
    return html.escape(words[0].rstrip(), quote=False) if len(words) > 1 else ""


def _clean_summary(value: str) -> str:
    """Remove legacy presentation labels that must not appear in the final card."""
    cleaned = _normalize_message_text(value)
    cleaned = re.sub(r"^(?:📰\s*|خلاصه(?:\s+خبر)?\s*:\s*)+", "", cleaned)
    return cleaned.strip()


def _jalali_date(value: str | None) -> str:
    """Render an ISO timestamp as the requested Persian calendar date."""
    if not value:
        return "نامشخص"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            # Article timestamps in the product pipeline are stored as Tehran-local
            # wall time when the source does not provide an offset.
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Tehran"))
        local = parsed.astimezone(ZoneInfo("Asia/Tehran"))
        gy, gm, gd = local.year, local.month, local.day
        gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
        gy2 = gy + 1 if gm > 2 else gy
        days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + gdm[gm - 1]
        jy = -1595 + 33 * (days // 12053)
        days %= 12053
        jy += 4 * (days // 1461)
        days %= 1461
        if days > 365:
            jy += (days - 1) // 365
            days = (days - 1) % 365
        jm = days // 31 + 1 if days < 186 else (days - 186) // 30 + 7
        jd = days % 31 + 1 if days < 186 else (days - 186) % 30 + 1
        months = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
        weekdays = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]
        return f"{weekdays[local.weekday()]} {_fa_digits(jd)} {months[jm - 1]} {_fa_digits(jy)} - {_fa_digits(local.strftime('%H:%M'))}"
    except (TypeError, ValueError, IndexError):
        return "نامشخص"


def split_message(text: str, limit: int = SAFE_MESSAGE_LIMIT) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def render_analysis_message(
    *,
    headline: str,
    summary: str,
    business_connection: str,
    opportunity: str,
    risk: str,
    action: str,
    confidence: float,
    source_name: str,
    source_url: str,
    published_at: str | None,
    incomplete: bool,
    template_blocks: list[dict[str, object]] | None = None,
    business_name: str = "داتین",
) -> str:
    del confidence, action, incomplete
    escaped_url = html.escape(source_url.strip(), quote=True)
    try:
        publication = datetime.fromisoformat(published_at) if published_at else None
        if publication and publication.tzinfo is None:
            publication = publication.replace(tzinfo=timezone.utc)
        publication_date = _jalali_date(published_at)
    except ValueError:
        publication_date = "نامشخص"

    headline_text = _normalize_message_text(headline)
    business_label = _normalize_message_text(business_name) or "داتین"
    source_text = _normalize_message_text(source_name)
    summary_text = _clean_summary(summary)
    risks: list[str] = []
    if _normalize_message_text(opportunity):
        risks.append(f"○ فرصت: {_normalize_message_text(opportunity)}")
    if _normalize_message_text(risk):
        risks.append(f"○ ریسک: {_normalize_message_text(risk)}")
    def build(summary_limit: int, connection_limit: int, opportunity_limit: int) -> str:
        opportunity_block = ""
        if risks:
            opportunity_block = "\n\n🔍 <b>فرصت و ریسک:</b>\n" + "\n".join(
                _bounded_prose(item, opportunity_limit // len(risks)) for item in risks
            )
        message = (
            f"📢 <b>{_bounded_prose(headline_text, 150)}</b>\n\n"
            f"{_bounded_prose(summary_text, summary_limit)}\n\n"
            f"🔗 مطالعه بیشتر: <a href=\"{escaped_url}\">{_escaped_text(source_text, 120)}</a>\n"
            f"{publication_date}\n\n"
            f"💡 <b>ارتباط با {html.escape(business_label, quote=False)}:</b>\n{_bounded_prose(business_connection, connection_limit)}"
            f"{opportunity_block}"
        )
        return message

    if template_blocks:
        # Owner templates are deliberately a small, server-validated block
        # vocabulary. Rendering is text-only and keeps Telegram HTML escaped.
        defaults = {"title": 150, "summary": 350, "business_connection": 300, "opportunity": 250, "risk": 250, "source": 120, "source_url": 120, "published_at": 80, "feedback": 80, "footer": 80}
        def block_limit(block: dict[str, object], block_type: str) -> int:
            raw_value = block.get("max_chars")
            if not isinstance(raw_value, (str, int, float)):
                return defaults[block_type]
            try:
                value = int(raw_value)
            except (TypeError, ValueError, OverflowError):
                return defaults[block_type]
            return min(max(value, 20), 1200) if value else defaults[block_type]

        def block_emoji(block: dict[str, object], fallback: str) -> str:
            return html.escape(str(block.get("emoji") or fallback).strip(), quote=False)

        def heading(emoji: str, label: str, body: str) -> str:
            return f"{emoji + ' ' if emoji else ''}<b>{label}</b>{body}"

        values = {
            "title": lambda b: f"{block_emoji(b, '📢')} <b>{_bounded_prose(headline_text, block_limit(b, 'title'))}</b>",
            # Image blocks are rendered by TelegramClient as sendPhoto; they
            # intentionally add no raw URL or HTML to the message body.
            "image": lambda b: "",
            "summary": lambda b: f"{block_emoji(b, '') + ' ' if block_emoji(b, '') else ''}{_bounded_prose(summary_text, block_limit(b, 'summary'))}",
            "business_connection": lambda b: f"{block_emoji(b, '💡')} <b>ارتباط با {html.escape(business_label, quote=False)}:</b>\n{_bounded_prose(business_connection, block_limit(b, 'business_connection'))}",
            "opportunity": lambda b: f"{block_emoji(b, '🔍')} <b>فرصت:</b> {_bounded_prose(opportunity, block_limit(b, 'opportunity'))}",
            "risk": lambda b: f"{block_emoji(b, '⚠️')} <b>ریسک:</b> {_bounded_prose(risk, block_limit(b, 'risk'))}",
            "source": lambda b: f"{block_emoji(b, '🔗')} <b>منبع:</b> <a href=\"{escaped_url}\">{_escaped_text(source_text, block_limit(b, 'source'))}</a>",
            "published_at": lambda b: f"{block_emoji(b, '🕒')} {publication_date}" if block_emoji(b, '🕒') else publication_date,
            "source_url": lambda b: f"<a href=\"{escaped_url}\">{_escaped_text(source_text, block_limit(b, 'source_url'))}</a>",
            # TelegramClient adds the actual inline buttons for the feedback
            # channel. This block is a useful cue in preview/observer layouts.
            "feedback": lambda b: f"{block_emoji(b, '🗳')} <b>بازخورد:</b> مرتبط / نامرتبط",
            "footer": lambda b: f"{block_emoji(b, '') + ' ' if block_emoji(b, '') else ''}Bee Researcher",
        }
        parts = []
        for block in template_blocks:
            if not isinstance(block, dict) or not block.get("visible", True):
                continue
            renderer = values.get(str(block.get("type")))
            if renderer:
                parts.append(str(renderer(block)))
        # Treat each block as a bounded paragraph.  Normalize model/template
        # whitespace before joining so an owner cannot accidentally create a
        # tall message with multiple blank lines between blocks.
        normalized_parts = [re.sub(r"\n{3,}", "\n\n", part).strip() for part in parts if part.strip()]
        custom = "\n\n".join(normalized_parts)
        if len(custom) > PRODUCT_MESSAGE_LIMIT:
            # Keep the owner-selected order while trimming only generated prose
            # in a predictable way; links and headings remain intact.
            custom = custom[:PRODUCT_MESSAGE_LIMIT].rsplit(" ", 1)[0].rstrip()
        if not custom:
            raise AssertionError("MI template rendered an empty message")
        return custom

    message = build(350, 300, 250)
    if len(message) > PRODUCT_MESSAGE_LIMIT:
        # Keep every required structural field and trim only model-generated prose.
        message = build(260, 220, 160)
    if len(message) > PRODUCT_MESSAGE_LIMIT:
        message = build(180, 160, 80)
    if len(message) > PRODUCT_MESSAGE_LIMIT:
        raise AssertionError("MI-014 renderer exceeded its 1200-character message limit")
    return message


@dataclass(frozen=True, slots=True)
class TelegramPermissionStatus:
    ready: bool
    bot_username: str | None
    member_status: str | None
    can_post: bool
    can_edit: bool
    can_delete: bool
    error: str | None = None


class TelegramClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    @property
    def configured(self) -> bool:
        return self.settings.telegram_ready

    @property
    def channel_hash(self) -> str | None:
        if self.settings.telegram_channel_id is None:
            return None
        return hashlib.sha256(
            self.settings.telegram_channel_id.encode("utf-8")
        ).hexdigest()

    def _api_url(self, method: str) -> str:
        if self.settings.telegram_bot_token is None:
            raise RuntimeError("Telegram bot token is not configured")
        token = self.settings.telegram_bot_token.get_secret_value()
        return f"https://api.telegram.org/bot{token}/{method}"

    async def _call(self, method: str, payload: dict[str, object]) -> Any:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40), transport=self.transport) as client:
            response = await client.post(self._api_url(method), json=payload)
            response.raise_for_status()
            body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description', 'unknown')}")
        return body.get("result")

    async def check_permissions(self) -> TelegramPermissionStatus:
        if not self.configured:
            return TelegramPermissionStatus(
                ready=False,
                bot_username=None,
                member_status=None,
                can_post=False,
                can_edit=False,
                can_delete=False,
                error="dedicated bot token or numeric private channel id is missing",
            )
        try:
            identity = await self._call("getMe", {})
            if not str(self.settings.telegram_channel_id).startswith("-100"):
                # A private chat does not expose channel-admin permissions.
                # getChat confirms that the user has started the bot and that
                # Telegram can resolve the configured destination.
                await self._call("getChat", {"chat_id": self.settings.telegram_channel_id})
                return TelegramPermissionStatus(
                    ready=True,
                    bot_username=identity.get("username"),
                    member_status="private_chat",
                    can_post=True,
                    can_edit=True,
                    can_delete=True,
                )
            member = await self._call(
                "getChatMember",
                {
                    "chat_id": self.settings.telegram_channel_id,
                    "user_id": identity["id"],
                },
            )
            status = str(member.get("status") or "")
            can_post = status == "creator" or bool(member.get("can_post_messages"))
            can_edit = status == "creator" or bool(member.get("can_edit_messages"))
            can_delete = status == "creator" or bool(member.get("can_delete_messages"))
            return TelegramPermissionStatus(
                ready=can_post,
                bot_username=identity.get("username"),
                member_status=status,
                can_post=can_post,
                can_edit=can_edit,
                can_delete=can_delete,
            )
        except Exception as exc:
            return TelegramPermissionStatus(
                ready=False,
                bot_username=None,
                member_status=None,
                can_post=False,
                can_edit=False,
                can_delete=False,
                error=redact_sensitive_text(f"{type(exc).__name__}: {exc}", limit=500),
            )

    async def send_analysis(
        self,
        text: str,
        *,
        analysis_id: uuid.UUID,
        channel_id: str | None = None,
        include_feedback_buttons: bool = True,
        silent: bool = False,
        image_url: str | None = None,
        message_limit: int = SAFE_MESSAGE_LIMIT,
    ) -> list[int]:
        if not self.configured:
            raise RuntimeError("Telegram delivery is not configured")
        try:
            effective_limit = min(max(int(message_limit), 20), TELEGRAM_MESSAGE_LIMIT)
        except (TypeError, ValueError):
            effective_limit = SAFE_MESSAGE_LIMIT
        chunks = split_message(text, limit=effective_limit)
        message_ids: list[int] = []
        for index, chunk in enumerate(chunks):
            reply_markup = None
            if include_feedback_buttons and index == len(chunks) - 1:
                reply_markup = {
                    "inline_keyboard": [
                        [
                            {"text": "مرتبط", "callback_data": f"mi:up:{analysis_id}"},
                            {"text": "نامرتبط", "callback_data": f"mi:down:{analysis_id}"},
                        ]
                    ]
                }
            # Telegram captions are limited to 1024 characters. If the first
            # chunk is longer, send the image separately and retain the full
            # text in the following message instead of truncating the news.
            if index == 0 and image_url:
                photo_payload: dict[str, object] = {
                    "chat_id": channel_id or self.settings.telegram_channel_id,
                    "photo": image_url,
                    "parse_mode": "HTML",
                    "disable_notification": bool(silent),
                }
                if len(chunk) <= 1024:
                    photo_payload["caption"] = chunk
                    if reply_markup is not None:
                        photo_payload["reply_markup"] = reply_markup
                result = await self._call("sendPhoto", photo_payload)
                message_ids.append(int(result["message_id"]))
                if len(chunk) <= 1024:
                    continue
            payload: dict[str, object] = {
                "chat_id": channel_id or self.settings.telegram_channel_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": bool(silent),
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            result = await self._call("sendMessage", payload)
            message_ids.append(int(result["message_id"]))
        return message_ids

    async def edit_message(self, message_id: int, text: str) -> None:
        if len(text) > PRODUCT_MESSAGE_LIMIT:
            raise ValueError("edited Telegram message must fit the 2000-character contract")
        await self._call(
            "editMessageText",
            {
                "chat_id": self.settings.telegram_channel_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )

    async def delete_messages(self, message_ids: list[int]) -> None:
        for message_id in message_ids:
            await self._call(
                "deleteMessage",
                {
                    "chat_id": self.settings.telegram_channel_id,
                    "message_id": message_id,
                },
            )

    async def get_updates(self, offset: int | None = None) -> list[dict[str, object]]:
        if not self.configured:
            return []
        payload: dict[str, object] = {
            "timeout": 25,
            # Bee CFO's typed /why command is accepted only in an authorised
            # private chat. Keeping message updates here avoids a second bot
            # polling loop and does not alter normal channel publication.
            "allowed_updates": ["callback_query", "message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload)
        return list(result or [])

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        await self._call(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text},
        )
