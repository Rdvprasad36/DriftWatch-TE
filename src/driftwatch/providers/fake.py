"""FakeProvider — deterministic offline provider for unit tests.

All unit tests that need a provider must use FakeProvider.
Tests that call real LLM APIs are decorated with ``@pytest.mark.live``
and are skipped by default (AGENTS.md testing requirements).

Usage pattern::

    provider = FakeProvider(
        responses=[
            FakeProvider.make_tool_response("lookup_order", {"order_id": "1042"}),
            FakeProvider.make_text_response("Order 1042 is refundable."),
        ]
    )
    resp = await provider.complete(messages, tools, model="fake", temperature=0)

The FakeProvider is *scripted*: it returns responses from a pre-built list
in order and raises ``FakeProviderExhausted`` when the list is depleted.
This makes test expectations explicit and test failures immediately obvious.

For the agent-loop ASR tests (AGENTS.md: "FakeProvider(vulnerable) ASR=1,
FakeProvider(robust) ASR=0"), helper factories build the right sequences:
``FakeProvider.for_vulnerable_attack(...)`` and ``FakeProvider.for_robust_task(...)``.
"""

from __future__ import annotations

import logging
from typing import Any

from driftwatch.providers.base import BaseProvider, ParsedToolCall, ProviderResponse

logger = logging.getLogger(__name__)

FAKE_MODEL_ID = "fake-model-v1"
FAKE_FINGERPRINT = "fake-fp-abc123"


class FakeProviderExhausted(RuntimeError):
    """Raised when FakeProvider has no more scripted responses."""


class FakeProvider(BaseProvider):
    """Deterministic, offline provider for unit tests.

    Responses are returned from a pre-built list.  Call counts and the
    full call log are available for assertions.
    """

    def __init__(
        self,
        responses: list[ProviderResponse] | None = None,
        returned_model_id: str = FAKE_MODEL_ID,
        latency_ms: float = 1.0,
    ) -> None:
        self._responses: list[ProviderResponse] = list(responses or [])
        self._index: int = 0
        self._returned_model_id = returned_model_id
        self._latency_ms = latency_ms
        # Public for test assertions
        self.call_count: int = 0
        self.call_log: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        self.call_count += 1
        self.call_log.append(
            {"messages": messages, "tools": tools, "model": model, "temperature": temperature}
        )

        if self._index >= len(self._responses):
            raise FakeProviderExhausted(
                f"FakeProvider exhausted after {self._index} response(s). "
                "Add more responses or check your agent loop."
            )

        resp = self._responses[self._index]
        self._index += 1
        logger.debug(
            "FakeProvider returning response %d/%d: tool_calls=%s content=%r",
            self._index,
            len(self._responses),
            [tc.name for tc in resp.tool_calls],
            resp.content,
        )
        return resp

    # ------------------------------------------------------------------
    # Class-method factories for common response types
    # ------------------------------------------------------------------

    @classmethod
    def make_tool_response(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        call_id: str = "call_fake_0",
        model: str = FAKE_MODEL_ID,
        tokens_in: int = 20,
        tokens_out: int = 8,
    ) -> ProviderResponse:
        """Build a ProviderResponse containing a single tool call."""
        return ProviderResponse(
            requested_model=model,
            returned_model=model,
            fingerprint=FAKE_FINGERPRINT,
            content=None,
            tool_calls=[ParsedToolCall(id=call_id, name=tool_name, arguments=arguments)],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=1.0,
            http_status=200,
            redacted_headers={"x-request-id": "fake-req-001"},
        )

    @classmethod
    def make_text_response(
        cls,
        content: str,
        model: str = FAKE_MODEL_ID,
        tokens_in: int = 20,
        tokens_out: int | None = None,
    ) -> ProviderResponse:
        """Build a ProviderResponse with plain text content and no tool calls."""
        out = tokens_out if tokens_out is not None else max(1, len(content.split()))
        return ProviderResponse(
            requested_model=model,
            returned_model=model,
            fingerprint=FAKE_FINGERPRINT,
            content=content,
            tool_calls=[],
            tokens_in=tokens_in,
            tokens_out=out,
            latency_ms=1.0,
            http_status=200,
            redacted_headers={"x-request-id": "fake-req-002"},
        )

    @classmethod
    def make_error_response(
        cls,
        error: str,
        http_status: int = 500,
        model: str = FAKE_MODEL_ID,
    ) -> ProviderResponse:
        """Build a ProviderResponse representing a provider error."""
        return ProviderResponse(
            requested_model=model,
            returned_model=model,
            fingerprint=None,
            content=None,
            tool_calls=[],
            tokens_in=0,
            tokens_out=0,
            latency_ms=1.0,
            http_status=http_status,
            redacted_headers={},
            error=error,
        )

    # ------------------------------------------------------------------
    # High-level scenario factories (used by agent loop ASR tests, step 4)
    # ------------------------------------------------------------------

    @classmethod
    def for_vulnerable_attack(
        cls,
        attack_tool: str,
        attack_args: dict[str, Any],
        preamble_tool: str = "read_reviews",
        preamble_args: dict[str, Any] | None = None,
    ) -> FakeProvider:
        """Build a FakeProvider that simulates a *vulnerable* agent.

        Response sequence:
          1. Call the preamble tool (e.g. read_reviews — this is where injection is seen)
          2. Follow the injection: call ``attack_tool`` with ``attack_args``
          3. Reply with a text answer

        With this sequence, the GoalEvaluator's ``tool_called`` predicate
        for ``attack_tool``/``attack_args`` returns True → ASR = 1.
        """
        return cls(
            responses=[
                cls.make_tool_response(preamble_tool, preamble_args or {}),
                cls.make_tool_response(attack_tool, attack_args, call_id="call_fake_1"),
                cls.make_text_response("Done."),
            ]
        )

    @classmethod
    def for_robust_task(
        cls,
        legitimate_tool: str = "lookup_order",
        legitimate_args: dict[str, Any] | None = None,
    ) -> FakeProvider:
        """Build a FakeProvider that simulates a *robust* agent.

        Response sequence:
          1. Call a legitimate tool (e.g. lookup_order)
          2. Reply with a text answer (no attack tool called)

        With this sequence, the GoalEvaluator's attack ``tool_called`` predicate
        returns False → ASR = 0.
        """
        return cls(
            responses=[
                cls.make_tool_response(legitimate_tool, legitimate_args or {}),
                cls.make_text_response("I've looked up the order. It is refundable."),
            ]
        )
