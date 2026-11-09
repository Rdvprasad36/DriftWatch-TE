"""Tests for ProviderResponse, ParsedToolCall, redact_headers, and FakeProvider.

All tests run offline — no real HTTP calls.
"""

from __future__ import annotations

import pytest

from driftwatch.providers.base import ParsedToolCall, ProviderResponse, redact_headers
from driftwatch.providers.fake import FakeProvider, FakeProviderExhausted

# ---------------------------------------------------------------------------
# redact_headers
# ---------------------------------------------------------------------------


class TestRedactHeaders:
    def test_authorization_redacted(self) -> None:
        result = redact_headers({"Authorization": "Bearer sk-secret123"})
        assert result["Authorization"] == "[REDACTED]"

    def test_case_insensitive_redaction(self) -> None:
        result = redact_headers({"AUTHORIZATION": "Bearer sk-secret"})
        assert result["AUTHORIZATION"] == "[REDACTED]"

    def test_x_api_key_redacted(self) -> None:
        result = redact_headers({"x-api-key": "gsk_secret"})
        assert result["x-api-key"] == "[REDACTED]"

    def test_x_goog_api_key_redacted(self) -> None:
        result = redact_headers({"x-goog-api-key": "AIza-secret"})
        assert result["x-goog-api-key"] == "[REDACTED]"

    def test_api_key_header_redacted(self) -> None:
        result = redact_headers({"api-key": "secret"})
        assert result["api-key"] == "[REDACTED]"

    def test_non_secret_header_preserved(self) -> None:
        result = redact_headers({"content-type": "application/json"})
        assert result["content-type"] == "application/json"

    def test_x_request_id_preserved(self) -> None:
        result = redact_headers({"x-request-id": "req-abc-123"})
        assert result["x-request-id"] == "req-abc-123"

    def test_mixed_headers(self) -> None:
        headers = {
            "Authorization": "Bearer secret",
            "content-type": "application/json",
            "x-request-id": "req-001",
            "x-api-key": "another-secret",
        }
        result = redact_headers(headers)
        assert result["Authorization"] == "[REDACTED]"
        assert result["x-api-key"] == "[REDACTED]"
        assert result["content-type"] == "application/json"
        assert result["x-request-id"] == "req-001"

    def test_returns_copy_not_mutate(self) -> None:
        original = {"Authorization": "secret"}
        result = redact_headers(original)
        assert original["Authorization"] == "secret"  # original unchanged
        assert result["Authorization"] == "[REDACTED]"

    def test_empty_headers(self) -> None:
        assert redact_headers({}) == {}


# ---------------------------------------------------------------------------
# ProviderResponse
# ---------------------------------------------------------------------------


class TestProviderResponse:
    def test_ok_when_http_200_no_error(self) -> None:
        resp = ProviderResponse(
            requested_model="m",
            returned_model="m",
            fingerprint=None,
            content="hello",
            http_status=200,
        )
        assert resp.ok is True

    def test_not_ok_when_error_set(self) -> None:
        resp = ProviderResponse(
            requested_model="m",
            returned_model="m",
            fingerprint=None,
            content=None,
            http_status=200,
            error="Something went wrong",
        )
        assert resp.ok is False

    def test_not_ok_when_http_429(self) -> None:
        resp = ProviderResponse(
            requested_model="m",
            returned_model="m",
            fingerprint=None,
            content=None,
            http_status=429,
            error="Rate limited",
        )
        assert resp.ok is False

    def test_default_tool_calls_empty(self) -> None:
        resp = ProviderResponse(
            requested_model="m",
            returned_model="m",
            fingerprint=None,
            content="hi",
            http_status=200,
        )
        assert resp.tool_calls == []

    def test_default_redacted_headers_empty(self) -> None:
        resp = ProviderResponse(
            requested_model="m",
            returned_model="m",
            fingerprint=None,
            content="hi",
            http_status=200,
        )
        assert resp.redacted_headers == {}

    def test_returned_model_differs_from_requested(self) -> None:
        """FR3: returned model id may differ from requested (provider may silently swap)."""
        resp = ProviderResponse(
            requested_model="llama3-70b",
            returned_model="llama3-70b-8192",  # provider returned a versioned ID
            fingerprint="fp-abc",
            content="Hello",
            http_status=200,
        )
        assert resp.requested_model != resp.returned_model
        assert resp.fingerprint == "fp-abc"


class TestParsedToolCall:
    def test_fields(self) -> None:
        tc = ParsedToolCall(id="call_0", name="lookup_order", arguments={"order_id": "1042"})
        assert tc.id == "call_0"
        assert tc.name == "lookup_order"
        assert tc.arguments["order_id"] == "1042"


# ---------------------------------------------------------------------------
# FakeProvider
# ---------------------------------------------------------------------------


class TestFakeProvider:
    @pytest.mark.asyncio
    async def test_returns_scripted_responses_in_order(self) -> None:
        r1 = FakeProvider.make_tool_response("lookup_order", {"order_id": "1042"})
        r2 = FakeProvider.make_text_response("Done.")
        provider = FakeProvider(responses=[r1, r2])

        out1 = await provider.complete([], [], "fake", 0.0)
        out2 = await provider.complete([], [], "fake", 0.0)

        assert out1.tool_calls[0].name == "lookup_order"
        assert out2.content == "Done."

    @pytest.mark.asyncio
    async def test_raises_when_exhausted(self) -> None:
        provider = FakeProvider(responses=[FakeProvider.make_text_response("Hi")])
        await provider.complete([], [], "fake", 0.0)
        with pytest.raises(FakeProviderExhausted):
            await provider.complete([], [], "fake", 0.0)

    @pytest.mark.asyncio
    async def test_call_count_incremented(self) -> None:
        provider = FakeProvider(
            responses=[
                FakeProvider.make_text_response("a"),
                FakeProvider.make_text_response("b"),
            ]
        )
        await provider.complete([], [], "fake", 0.0)
        await provider.complete([], [], "fake", 0.0)
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_call_log_records_inputs(self) -> None:
        provider = FakeProvider(responses=[FakeProvider.make_text_response("ok")])
        msgs = [{"role": "user", "content": "hello"}]
        tools = [{"type": "function", "function": {"name": "ping"}}]
        await provider.complete(msgs, tools, "my-model", 0.7)

        assert len(provider.call_log) == 1
        entry = provider.call_log[0]
        assert entry["model"] == "my-model"
        assert entry["temperature"] == 0.7
        assert entry["messages"] == msgs

    def test_make_tool_response_fields(self) -> None:
        resp = FakeProvider.make_tool_response(
            "issue_refund", {"order_id": "1042", "account": "9981"}
        )
        assert resp.ok is True
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "issue_refund"
        assert resp.tool_calls[0].arguments["account"] == "9981"
        assert resp.content is None

    def test_make_text_response_fields(self) -> None:
        resp = FakeProvider.make_text_response("Order is refundable.")
        assert resp.ok is True
        assert resp.content == "Order is refundable."
        assert resp.tool_calls == []

    def test_make_error_response_fields(self) -> None:
        resp = FakeProvider.make_error_response("Provider unavailable", http_status=503)
        assert resp.ok is False
        assert resp.error == "Provider unavailable"
        assert resp.http_status == 503

    def test_for_vulnerable_attack_sequence(self) -> None:
        """Verify the vulnerable scenario factory builds the right response sequence."""
        provider = FakeProvider.for_vulnerable_attack(
            attack_tool="issue_refund",
            attack_args={"order_id": "1042", "account": "9981"},
        )
        assert len(provider._responses) == 3
        assert provider._responses[0].tool_calls[0].name == "read_reviews"
        assert provider._responses[1].tool_calls[0].name == "issue_refund"
        assert provider._responses[1].tool_calls[0].arguments["account"] == "9981"
        assert provider._responses[2].content is not None

    def test_for_robust_task_sequence(self) -> None:
        """Verify the robust scenario factory never includes attack tool calls."""
        provider = FakeProvider.for_robust_task(
            legitimate_tool="lookup_order",
            legitimate_args={"order_id": "1042"},
        )
        assert len(provider._responses) == 2
        tool_names = [tc.name for r in provider._responses for tc in r.tool_calls]
        assert "issue_refund" not in tool_names
        assert "lookup_order" in tool_names

    @pytest.mark.asyncio
    async def test_empty_provider_raises_immediately(self) -> None:
        provider = FakeProvider(responses=[])
        with pytest.raises(FakeProviderExhausted):
            await provider.complete([], [], "fake", 0.0)
