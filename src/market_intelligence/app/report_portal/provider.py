"""No tools, retries, provider storage or private request/response logging."""

from decimal import Decimal
import httpx

from app.openai_client import OpenAIClient, OPENAI_BASE_URL, AIProviderError


class PrivateClient(OpenAIClient):
    def __init__(self, settings, *, transport=None, guard):
        super().__init__(settings, transport=transport)
        self.guard = guard
        self.cost = Decimal("0")
        self.usage_complete = True
        self.calls = 0

    async def _post(self, path, payload):
        await self.guard()
        if (
            path != "/responses"
            or payload.get("store") is not False
            or payload.get("tools")
        ):
            raise AIProviderError("private_provider_policy")
        self.calls += 1
        previous_complete = self.usage_complete
        self.usage_complete = False
        try:
            async with httpx.AsyncClient(
                headers=self._headers(), transport=self.transport, timeout=90
            ) as client:
                response = await client.post(OPENAI_BASE_URL + path, json=payload)
                if response.status_code != 200:
                    raise AIProviderError("private_provider_unavailable")
                value = response.json()
                if not isinstance(value, dict):
                    raise AIProviderError("private_provider_invalid")
                usage = value.get("usage")
                if isinstance(usage, dict) and all(
                    isinstance(usage.get(k), int)
                    and not isinstance(usage[k], bool)
                    and usage[k] >= 0
                    for k in ("input_tokens", "output_tokens")
                ):
                    self.cost += Decimal(
                        str(
                            self._estimated_token_cost(
                                usage["input_tokens"], usage["output_tokens"]
                            )
                        )
                    )
                    self.usage_complete = previous_complete
                return value
        except (httpx.HTTPError, ValueError, TypeError):
            raise AIProviderError("private_provider_unavailable") from None
