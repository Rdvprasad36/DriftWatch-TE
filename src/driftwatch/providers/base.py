"""Provider abstractions for DriftWatch-TE.

``ProviderResponse`` carries everything needed for one row of the result schema
(architecture.md §4): requested model id, returned model id, fingerprint,
content, tool calls, token counts, latency, HTTP status, redacted headers.

Header redaction (AGENTS.md rule 4): credential headers are replaced with
``[REDACTED]`` before the response is stored anywhere — never logged raw.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Headers that contain credentials. Values are redacted before persisting.
# (AGENTS.md rule 4: "No secrets in the repo, logs or traces.")
_SECRET_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "authorization",
        "x-api-key",
        "api-key",
        "x-goog-api-key",
        "x-auth-token",
        "bearer",
    }
)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of *headers* with credential values replaced by ``[REDACTED]``.

    Comparison is case-insensitive. All other headers pass through unchanged.
    """
    return {
        k: "[REDACTED]" if k.lower() in _SECRET_HEADER_NAMES else v for k, v in headers.items()
    }


@dataclass
class ParsedToolCall:
    """A single function call extracted from an LLM response."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderResponse:
    """One LLM completion result, with all metadata needed for FR3.

    Maps to architecture.md §4 columns: returned_model_id, fingerprint,
    tokens_in, tokens_out, latency_ms, http_errors.
    """

    # Model tracking (FR3)
    requested_model: str
    returned_model: str  # from response body — may differ from requested_model
    fingerprint: str | None  # system_fingerprint field, if present

    # Response content
    content: str | None  # text completion, or None when tool_calls present
    tool_calls: list[ParsedToolCall] = field(default_factory=list)

    # Cost / latency
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0

    # HTTP metadata (FR3)
    http_status: int | None = None
    redacted_headers: dict[str, str] = field(default_factory=dict)

    # Error capture (AGENTS.md rule 7: never silently drop errors)
    error: str | None = None
    error_type: str | None = None

    @property
    def ok(self) -> bool:
        """True if the response is usable (no error, HTTP 200)."""
        return self.error is None and self.http_status == 200


class BaseProvider(ABC):
    """Abstract base class for all LLM providers.

    All I/O is async; retries and header redaction are provider responsibilities.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Send a chat-completion request and return a structured response.

        Must never raise on HTTP/network errors — return a ProviderResponse
        with ``error`` set instead (AGENTS.md rule 7).
        """
