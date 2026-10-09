"""Native provider protocols, fixed hosts, no tools or automatic paid retries."""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_CEILING
from urllib.parse import quote

import httpx
from app.config import Settings
from app.news_chat.schemas import ModelSpec


class ProviderError(Exception):
    def __init__(self, code="provider_failed"):
        self.code = code
        super().__init__(code)


def configured(settings: Settings, provider: str) -> bool:
    return bool({"openai": settings.openai_api_key, "anthropic": settings.news_chat_anthropic_key,
                 "google": settings.news_chat_google_key}.get(provider))


def cost(model: ModelSpec, usage: dict) -> Decimal | None:
    if not all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")):
        return None
    # Conservative: cache hits count at the normal input price. Anthropic cache
    # creation can cost more; its adapter folds that surcharge into input_tokens.
    return ((Decimal(usage["input_tokens"]) * model.input_usd +
             Decimal(usage["output_tokens"]) * model.output_usd) / Decimal(1_000_000)).quantize(Decimal("0.00000001"), rounding=ROUND_CEILING)


async def stream(settings: Settings, model: ModelSpec, messages: list, *, transport=None):
    key = {"openai": settings.openai_api_key, "anthropic": settings.news_chat_anthropic_key,
           "google": settings.news_chat_google_key}[model.provider]
    if key is None:
        raise ProviderError("provider_unconfigured")
    secret = key.get_secret_value()
    system, turns = messages[0]["content"], messages[1:]
    if model.provider == "openai":
        url = "https://api.openai.com/v1/responses"
        headers = {"Authorization": "Bearer " + secret}
        body = {"model": model.model_id, "instructions": system, "input": turns,
                "max_output_tokens": model.max_output_tokens, "store": False, "stream": True}
    elif model.provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": secret, "anthropic-version": "2023-06-01"}
        body = {"model": model.model_id, "system": system, "messages": turns,
                "max_tokens": model.max_output_tokens, "stream": True}
    else:
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(model.model_id, safe="") + ":streamGenerateContent?alt=sse"
        headers = {"x-goog-api-key": secret}
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [
            {"role": "model" if t["role"] == "assistant" else "user", "parts": [{"text": t["content"]}]} for t in turns],
            "generationConfig": {"maxOutputTokens": model.max_output_tokens}}
    usage, terminal = {}, False
    timeout = httpx.Timeout(settings.news_chat_timeout_seconds, connect=10)
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=False) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    code = {401: "provider_credentials", 403: "provider_credentials", 404: "model_unavailable",
                            429: "provider_rate_limited"}.get(response.status_code, "provider_failed")
                    raise ProviderError(code)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except (ValueError, TypeError):
                        raise ProviderError("provider_invalid_response") from None
                    if not isinstance(event, dict) or event.get("error"):
                        raise ProviderError("provider_failed")
                    if model.provider == "openai":
                        kind = event.get("type")
                        if kind == "response.output_text.delta":
                            yield {"text": str(event.get("delta", ""))}
                        elif kind == "response.completed":
                            data = event.get("response", {}).get("usage") or {}
                            usage = {"input_tokens": data.get("input_tokens"), "output_tokens": data.get("output_tokens")}
                            terminal = True
                        elif kind in {"response.failed", "response.incomplete", "error", "response.refusal.delta"}:
                            raise ProviderError("provider_incomplete")
                    elif model.provider == "anthropic":
                        kind = event.get("type")
                        if kind == "message_start":
                            data = event.get("message", {}).get("usage") or {}
                            usage["input_tokens"] = int(data.get("input_tokens", 0)) + int(data.get("cache_read_input_tokens", 0)) + 2 * int(data.get("cache_creation_input_tokens", 0))
                        elif kind == "content_block_delta" and event.get("delta", {}).get("type") == "text_delta":
                            yield {"text": str(event["delta"].get("text", ""))}
                        elif kind == "message_delta":
                            usage["output_tokens"] = event.get("usage", {}).get("output_tokens")
                            if event.get("delta", {}).get("stop_reason") not in {"end_turn", None}:
                                raise ProviderError("provider_incomplete")
                        elif kind == "message_stop":
                            terminal = True
                    else:
                        data = event.get("usageMetadata") or {}
                        if data:
                            usage = {"input_tokens": data.get("promptTokenCount"),
                                     "output_tokens": int(data.get("candidatesTokenCount", 0)) + int(data.get("thoughtsTokenCount", 0))}
                        for candidate in event.get("candidates", []):
                            for part in candidate.get("content", {}).get("parts", []):
                                if not part.get("thought") and part.get("text"):
                                    yield {"text": str(part["text"])}
                            if candidate.get("finishReason"):
                                if candidate["finishReason"] != "STOP":
                                    raise ProviderError("provider_incomplete")
                                terminal = True
        if not terminal:
            raise ProviderError("generation_unknown")
        yield {"usage": usage, "done": True}
    except httpx.TimeoutException:
        raise ProviderError("generation_unknown") from None
    except httpx.HTTPError:
        raise ProviderError("generation_unknown") from None
