"""OpenAI-compatible HTTP provider client.

Implements ``BaseProvider`` against any endpoint that speaks the
OpenAI Chat Completions API (e.g. Groq, Google AI Studio, OpenRouter,
local Ollama).

Captures (architecture.md §3.5 / FR3):
  - Requested model id vs returned model id (from response body)
  - ``system_fingerprint`` field (when present)
  - Latency (wall-clock, ``time.monotonic``)
  - Token counts (prompt + completion)
  - HTTP status and selected response headers (auth redacted)
  - HTTP errors — always recorded, never silently dropped (AGENTS.md rule 7)

Retry policy (AGENTS.md free-tier handling):
  - Retry on HTTP 429, 500, 502, 503, 504
  - Exponential backoff with uniform jitter: ``min(base * 2^n + U(0, base), max)``
  - Configurable ``max_retries``, ``base_delay``, ``max_delay``
  - Set ``base_delay=0.0`` in tests to skip real sleeps
"""

from __future__ import annotations

import asyncio
import json as json_module
import logging
import random
import time
from typing import Any

import httpx

from driftwatch.providers.base import (
    BaseProvider,
    ParsedToolCall,
    ProviderResponse,
    redact_headers,
)

logger = logging.getLogger(__name__)

# Headers worth capturing from the response (informational, non-secret)
_CAPTURE_RESPONSE_HEADERS: tuple[str, ...] = (
    "x-request-id",
    "cf-ray",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "retry-after",
)

# HTTP status codes that are worth retrying
_RETRIABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class OpenAICompatProvider(BaseProvider):
    """OpenAI-compatible HTTP provider.

    Args:
        base_url: API base URL, e.g. ``https://api.groq.com/openai``.
        api_key: Provider API key — sourced from an env var, never hard-coded.
        max_retries: Number of retry attempts after the first failure (default 3).
        timeout: Per-request HTTP timeout in seconds (default 30).
        base_delay: Backoff base delay in seconds (set to 0.0 in tests).
        max_delay: Maximum backoff cap in seconds (default 60).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        max_retries: int = 3,
        timeout: float = 30.0,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        default_model: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # Keep the key private — redact before saving
        self._api_key = api_key
        self._max_retries = max_retries
        self._timeout = timeout
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._default_model = default_model

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Send a chat-completion request with retry on transient errors.

        Never raises. Returns a ProviderResponse with ``error`` set on failure.
        """
        target_model = self._default_model or model
        body: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        last_status: int | None = None
        last_error: str | None = None
        last_exc_class: str | None = None
        latency_ms: float = 0.0

        for attempt in range(self._max_retries + 1):
            t0 = time.monotonic()
            try:
                http_resp = await self._post("/v1/chat/completions", body)
            except httpx.RequestError as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                last_exc_class = type(exc).__name__
                last_error = f"{last_exc_class}: {exc}"
                logger.warning("Network error on attempt %d: %s", attempt, last_error)
                break  # network errors are not retried (may be config issue)

            latency_ms = (time.monotonic() - t0) * 1000
            last_status = http_resp.status_code

            if http_resp.status_code in _RETRIABLE_STATUS:
                delay = self._backoff(attempt)
                logger.warning(
                    "HTTP %d on attempt %d/%d, retrying in %.2fs",
                    http_resp.status_code,
                    attempt + 1,
                    self._max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            # Success or non-retriable HTTP error
            return self._parse_response(http_resp, model, latency_ms)

        # All attempts exhausted
        fallback_err = f"HTTPStatusError_{last_status}" if last_status else "RequestError"
        err_type = last_exc_class or fallback_err
        return ProviderResponse(
            requested_model=model,
            returned_model="",
            fingerprint=None,
            content=None,
            tool_calls=[],
            tokens_in=0,
            tokens_out=0,
            latency_ms=latency_ms,
            http_status=last_status,
            redacted_headers=self._safe_request_headers(),
            error=last_error or f"Max retries exceeded (last HTTP {last_status})",
            error_type=err_type,
        )

    # ------------------------------------------------------------------
    # Private helpers (small methods -> easy to mock in tests)
    # ------------------------------------------------------------------

    async def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        """Make one HTTP POST — isolated here so tests can mock it."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
        ) as client:
            return await client.post(path, json=body)

    def _parse_response(
        self, resp: httpx.Response, model: str, latency_ms: float
    ) -> ProviderResponse:
        """Parse an httpx.Response into a ProviderResponse."""
        captured: dict[str, str] = {}
        for name in _CAPTURE_RESPONSE_HEADERS:
            val = resp.headers.get(name)
            if val is not None:
                captured[name] = val
        rh = redact_headers(captured)

        if resp.status_code != 200:
            return ProviderResponse(
                requested_model=model,
                returned_model="",
                fingerprint=None,
                content=None,
                tool_calls=[],
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                http_status=resp.status_code,
                redacted_headers=rh,
                error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                error_type=f"HTTPStatusError_{resp.status_code}",
            )

        try:
            data: dict[str, Any] = resp.json()
        except Exception as exc:
            return ProviderResponse(
                requested_model=model,
                returned_model="",
                fingerprint=None,
                content=None,
                tool_calls=[],
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                http_status=resp.status_code,
                redacted_headers=rh,
                error=f"JSON parse error: {exc}",
                error_type=type(exc).__name__,
            )

        # Only use returned model id if returned by the provider API (Item 2c)
        returned_model: str = str(data.get("model") or "")
        fingerprint: str | None = data.get("system_fingerprint")
        usage: dict[str, Any] = data.get("usage") or {}
        tokens_in: int = int(usage.get("prompt_tokens") or 0)
        tokens_out: int = int(usage.get("completion_tokens") or 0)

        choices: list[dict[str, Any]] = data.get("choices") or []
        choice: dict[str, Any] = choices[0] if choices else {}
        message: dict[str, Any] = choice.get("message") or {}
        content: str | None = message.get("content")

        # Parse tool calls
        raw_tool_calls: list[dict[str, Any]] = message.get("tool_calls") or []
        tool_calls: list[ParsedToolCall] = []
        for tc in raw_tool_calls:
            fn: dict[str, Any] = tc.get("function") or {}
            tc_name: str = fn.get("name") or ""
            raw_args: str = fn.get("arguments") or "{}"
            try:
                args: dict[str, Any] = json_module.loads(raw_args)
            except json_module.JSONDecodeError:
                args = {}
                logger.warning("Could not parse tool_call arguments JSON for '%s'", tc_name)
            tool_calls.append(ParsedToolCall(id=tc.get("id") or "", name=tc_name, arguments=args))

        return ProviderResponse(
            requested_model=model,
            returned_model=returned_model,
            fingerprint=fingerprint,
            content=content,
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            http_status=resp.status_code,
            redacted_headers=rh,
            error=None,
            error_type=None,
        )

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff with uniform jitter."""
        base: float = self._base_delay * (2**attempt)
        jitter: float = random.uniform(0, self._base_delay)  # noqa: S311 (not crypto)
        return float(min(base + jitter, self._max_delay))

    def _safe_request_headers(self) -> dict[str, str]:
        """Return request headers with auth redacted (for error ProviderResponse)."""
        return redact_headers({"Authorization": f"Bearer {self._api_key}"})
