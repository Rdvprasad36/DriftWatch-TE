"""Tests for OpenAICompatProvider: retry logic, backoff, header capture, parse.

All tests are offline — ``_post`` is mocked so no real HTTP calls are made.
Base delay is set to 0.0 to eliminate real sleeps (AGENTS.md testing rules).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from driftwatch.providers.openai_compat import OpenAICompatProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_httpx_resp(
    status: int,
    body: dict[str, Any],
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a minimal httpx.Response with a JSON body."""
    headers = {"content-type": "application/json"}
    headers.update(extra_headers or {})
    return httpx.Response(status, content=json.dumps(body).encode(), headers=headers)


# A minimal valid OpenAI-style response body
VALID_BODY: dict[str, Any] = {
    "model": "llama3-returned",
    "system_fingerprint": "fp-xyz",
    "choices": [{"message": {"content": "Hello!", "tool_calls": None}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}

# A valid body containing a tool call
TOOL_CALL_BODY: dict[str, Any] = {
    "model": "llama3-returned",
    "system_fingerprint": "fp-xyz",
    "choices": [
        {
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_001",
                        "type": "function",
                        "function": {
                            "name": "lookup_order",
                            "arguments": '{"order_id": "1042"}',
                        },
                    }
                ],
            }
        }
    ],
    "usage": {"prompt_tokens": 15, "completion_tokens": 10},
}


@pytest.fixture
def provider() -> OpenAICompatProvider:
    """Provider with zero delay so tests don't sleep."""
    return OpenAICompatProvider(
        base_url="https://fake.api",
        api_key="sk-test-key",
        max_retries=3,
        base_delay=0.0,
        max_delay=0.0,
    )


# ---------------------------------------------------------------------------
# Retry on retriable HTTP statuses
# ---------------------------------------------------------------------------


class TestRetryBehavior:
    async def test_retries_on_429_then_succeeds(self, provider: OpenAICompatProvider) -> None:
        """Two 429s then a 200 → success, error is None."""
        rate_resp = make_httpx_resp(429, {"error": "rate limited"})
        ok_resp = make_httpx_resp(200, VALID_BODY)
        with patch.object(
            provider, "_post", new=AsyncMock(side_effect=[rate_resp, rate_resp, ok_resp])
        ):
            result = await provider.complete([], [], "llama3", 0.7)

        assert result.error is None
        assert result.http_status == 200
        assert result.returned_model == "llama3-returned"

    async def test_retries_on_500_then_succeeds(self, provider: OpenAICompatProvider) -> None:
        server_err = make_httpx_resp(500, {"error": "internal"})
        ok_resp = make_httpx_resp(200, VALID_BODY)
        with patch.object(
            provider, "_post", new=AsyncMock(side_effect=[server_err, ok_resp])
        ):
            result = await provider.complete([], [], "llama3", 0.7)
        assert result.ok is True

    async def test_retries_on_502_503_504(self, provider: OpenAICompatProvider) -> None:
        for status in (502, 503, 504):
            p = OpenAICompatProvider(
                base_url="https://fake.api",
                api_key="sk-test",
                max_retries=2,
                base_delay=0.0,
                max_delay=0.0,
            )
            err_resp = make_httpx_resp(status, {"error": "gateway"})
            ok_resp = make_httpx_resp(200, VALID_BODY)
            with patch.object(p, "_post", new=AsyncMock(side_effect=[err_resp, ok_resp])):
                result = await p.complete([], [], "m", 0.0)
            assert result.ok is True, f"Expected ok for {status}"

    async def test_max_retries_exhausted_returns_error(
        self, provider: OpenAICompatProvider
    ) -> None:
        """All 4 attempts (1 initial + 3 retries) return 429 → ProviderResponse with error."""
        rate_resp = make_httpx_resp(429, {"error": "rate limited"})
        with patch.object(
            provider,
            "_post",
            new=AsyncMock(side_effect=[rate_resp, rate_resp, rate_resp, rate_resp]),
        ):
            result = await provider.complete([], [], "llama3", 0.7)

        assert result.error is not None
        assert result.ok is False

    async def test_no_retry_on_400(self, provider: OpenAICompatProvider) -> None:
        """HTTP 400 is non-retriable — only one call to _post."""
        bad_resp = make_httpx_resp(400, {"error": "bad request"})
        mock_post = AsyncMock(return_value=bad_resp)
        with patch.object(provider, "_post", new=mock_post):
            result = await provider.complete([], [], "llama3", 0.7)

        mock_post.assert_called_once()
        assert result.http_status == 400
        assert result.error is not None
        assert result.ok is False

    async def test_no_retry_on_401(self, provider: OpenAICompatProvider) -> None:
        """HTTP 401 is non-retriable."""
        unauth_resp = make_httpx_resp(401, {"error": "unauthorized"})
        mock_post = AsyncMock(return_value=unauth_resp)
        with patch.object(provider, "_post", new=mock_post):
            result = await provider.complete([], [], "llama3", 0.7)

        mock_post.assert_called_once()
        assert result.http_status == 401
        assert result.ok is False

    async def test_network_error_returns_error_no_retry(
        self, provider: OpenAICompatProvider
    ) -> None:
        """httpx.RequestError → ProviderResponse with error, no retry (immediate break)."""
        network_err = httpx.ConnectError("Connection refused")
        mock_post = AsyncMock(side_effect=network_err)
        with patch.object(provider, "_post", new=mock_post):
            result = await provider.complete([], [], "llama3", 0.7)

        mock_post.assert_called_once()  # no retry for network errors
        assert result.error is not None
        assert result.error_type == "ConnectError"
        assert "Connection refused" in result.error
        assert result.ok is False


# ---------------------------------------------------------------------------
# _parse_response: content and tool call extraction
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_parses_text_content(self, provider: OpenAICompatProvider) -> None:
        resp = make_httpx_resp(200, VALID_BODY)
        pr = provider._parse_response(resp, "llama3", 42.0)

        assert pr.ok is True
        assert pr.content == "Hello!"
        assert pr.returned_model == "llama3-returned"
        assert pr.fingerprint == "fp-xyz"
        assert pr.tokens_in == 10
        assert pr.tokens_out == 5
        assert pr.latency_ms == 42.0
        assert pr.tool_calls == []

    def test_parses_tool_calls(self, provider: OpenAICompatProvider) -> None:
        resp = make_httpx_resp(200, TOOL_CALL_BODY)
        pr = provider._parse_response(resp, "llama3", 10.0)

        assert pr.ok is True
        assert len(pr.tool_calls) == 1
        tc = pr.tool_calls[0]
        assert tc.id == "call_001"
        assert tc.name == "lookup_order"
        assert tc.arguments == {"order_id": "1042"}

    def test_invalid_json_arguments_graceful_degradation(
        self, provider: OpenAICompatProvider
    ) -> None:
        """Bad JSON in tool arguments → arguments becomes {} (logged, not raised)."""
        bad_args_body: dict[str, Any] = {
            "model": "m",
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "type": "function",
                                "function": {"name": "oops", "arguments": "NOT_JSON"},
                            }
                        ],
                    }
                }
            ],
            "usage": {},
        }
        resp = make_httpx_resp(200, bad_args_body)
        pr = provider._parse_response(resp, "m", 0.0)
        assert pr.ok is True
        assert pr.tool_calls[0].arguments == {}

    def test_non_200_returns_error_response(self, provider: OpenAICompatProvider) -> None:
        resp = make_httpx_resp(403, {"error": "forbidden"})
        pr = provider._parse_response(resp, "m", 0.0)
        assert pr.ok is False
        assert pr.http_status == 403
        assert pr.error is not None
        assert "403" in pr.error

    def test_empty_choices_no_crash(self, provider: OpenAICompatProvider) -> None:
        body: dict[str, Any] = {
            "model": "m",
            "choices": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
        resp = make_httpx_resp(200, body)
        pr = provider._parse_response(resp, "m", 0.0)
        assert pr.ok is True
        assert pr.content is None
        assert pr.tool_calls == []

    def test_missing_usage_defaults_to_zero(self, provider: OpenAICompatProvider) -> None:
        body: dict[str, Any] = {
            "model": "m",
            "choices": [{"message": {"content": "hi"}}],
        }
        resp = make_httpx_resp(200, body)
        pr = provider._parse_response(resp, "m", 0.0)
        assert pr.tokens_in == 0
        assert pr.tokens_out == 0


# ---------------------------------------------------------------------------
# Header capture and redaction
# ---------------------------------------------------------------------------


class TestHeaderCapture:
    def test_response_headers_captured(self, provider: OpenAICompatProvider) -> None:
        extra = {"x-request-id": "req-abc", "cf-ray": "ray-123"}
        resp = make_httpx_resp(200, VALID_BODY, extra_headers=extra)
        pr = provider._parse_response(resp, "m", 0.0)
        assert pr.redacted_headers.get("x-request-id") == "req-abc"
        assert pr.redacted_headers.get("cf-ray") == "ray-123"

    def test_safe_request_headers_redacts_auth(self, provider: OpenAICompatProvider) -> None:
        rh = provider._safe_request_headers()
        assert rh.get("Authorization") == "[REDACTED]"

    def test_safe_request_headers_no_raw_key(self, provider: OpenAICompatProvider) -> None:
        rh = provider._safe_request_headers()
        for v in rh.values():
            assert "sk-test-key" not in v

    def test_rate_limit_header_captured(self, provider: OpenAICompatProvider) -> None:
        extra = {"x-ratelimit-remaining-requests": "42"}
        resp = make_httpx_resp(200, VALID_BODY, extra_headers=extra)
        pr = provider._parse_response(resp, "m", 0.0)
        assert pr.redacted_headers.get("x-ratelimit-remaining-requests") == "42"


# ---------------------------------------------------------------------------
# Model ID tracking (FR3)
# ---------------------------------------------------------------------------


class TestModelTracking:
    async def test_returned_model_captured_from_body(
        self, provider: OpenAICompatProvider
    ) -> None:
        """FR3: returned model id from response body is preserved, even if it differs."""
        body: dict[str, Any] = {**VALID_BODY, "model": "llama3-70b-8192-versioned"}
        resp = make_httpx_resp(200, body)
        with patch.object(provider, "_post", new=AsyncMock(return_value=resp)):
            result = await provider.complete([], [], "llama3-70b", 0.7)

        assert result.requested_model == "llama3-70b"
        assert result.returned_model == "llama3-70b-8192-versioned"

    async def test_fingerprint_captured(self, provider: OpenAICompatProvider) -> None:
        """FR3: system_fingerprint field is captured when present."""
        body: dict[str, Any] = {**VALID_BODY, "system_fingerprint": "fp-unique-123"}
        resp = make_httpx_resp(200, body)
        with patch.object(provider, "_post", new=AsyncMock(return_value=resp)):
            result = await provider.complete([], [], "m", 0.7)

        assert result.fingerprint == "fp-unique-123"

    async def test_fingerprint_none_when_absent(self, provider: OpenAICompatProvider) -> None:
        body: dict[str, Any] = {k: v for k, v in VALID_BODY.items() if k != "system_fingerprint"}
        resp = make_httpx_resp(200, body)
        with patch.object(provider, "_post", new=AsyncMock(return_value=resp)):
            result = await provider.complete([], [], "m", 0.7)

        assert result.fingerprint is None


# ---------------------------------------------------------------------------
# complete(): body construction
# ---------------------------------------------------------------------------


class TestRequestBodyConstruction:
    async def test_tools_included_when_non_empty(self, provider: OpenAICompatProvider) -> None:
        captured_body: list[dict[str, Any]] = []

        async def fake_post(path: str, body: dict[str, Any]) -> httpx.Response:
            captured_body.append(body)
            return make_httpx_resp(200, VALID_BODY)

        with patch.object(provider, "_post", new=fake_post):
            tools = [{"type": "function", "function": {"name": "ping"}}]
            await provider.complete([], tools, "m", 0.7)

        assert "tools" in captured_body[0]
        assert captured_body[0]["tool_choice"] == "auto"

    async def test_tools_omitted_when_empty(self, provider: OpenAICompatProvider) -> None:
        captured_body: list[dict[str, Any]] = []

        async def fake_post(path: str, body: dict[str, Any]) -> httpx.Response:
            captured_body.append(body)
            return make_httpx_resp(200, VALID_BODY)

        with patch.object(provider, "_post", new=fake_post):
            await provider.complete([], [], "m", 0.7)

        assert "tools" not in captured_body[0]
        assert "tool_choice" not in captured_body[0]

    async def test_max_tokens_included_when_set(self, provider: OpenAICompatProvider) -> None:
        captured_body: list[dict[str, Any]] = []

        async def fake_post(path: str, body: dict[str, Any]) -> httpx.Response:
            captured_body.append(body)
            return make_httpx_resp(200, VALID_BODY)

        with patch.object(provider, "_post", new=fake_post):
            await provider.complete([], [], "m", 0.7, max_tokens=512)

        assert captured_body[0]["max_tokens"] == 512

