"""Provider registry — maps model alias strings to BaseProvider instances.

Usage::

    registry = ProviderRegistry()
    registry.register("fake", FakeProvider(responses=[...]))
    registry.register("groq-llama3", OpenAICompatProvider(...))

    provider = registry.get("groq-llama3")
    response = await provider.complete(...)

The registry also handles ``build_from_env()`` for setting up real providers
from environment variables (AGENTS.md rule 4: keys come from env vars only).
"""

from __future__ import annotations

import logging
import os

from driftwatch.providers.base import BaseProvider
from driftwatch.providers.fake import FakeProvider
from driftwatch.providers.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Maps model alias strings to :class:`BaseProvider` instances.

    A single registry is shared across an orchestrator run.
    """

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}

    def register(self, alias: str, provider: BaseProvider) -> None:
        """Register a provider under *alias*."""
        if alias in self._providers:
            logger.warning("Overwriting existing provider for alias '%s'.", alias)
        self._providers[alias] = provider
        logger.debug("Registered provider '%s': %s", alias, type(provider).__name__)

    def get(self, alias: str) -> BaseProvider:
        """Return the provider for *alias*.

        Raises:
            KeyError: If the alias is not registered.
        """
        if alias not in self._providers:
            available = ", ".join(sorted(self._providers)) or "<none>"
            msg = f"Unknown provider alias '{alias}'. Available: {available}"
            raise KeyError(msg)
        return self._providers[alias]

    def aliases(self) -> list[str]:
        """Return all registered alias names."""
        return list(self._providers.keys())

    def __contains__(self, alias: str) -> bool:
        return alias in self._providers


# ---------------------------------------------------------------------------
# Environment-based provider builders
# ---------------------------------------------------------------------------


def build_openai_compat_from_env(
    alias: str,
    base_url: str,
    api_key_env: str,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    timeout: float = 30.0,
) -> OpenAICompatProvider:
    """Build an :class:`OpenAICompatProvider` from an environment variable.

    Args:
        alias: Human-readable alias (used only for logging).
        base_url: Provider base URL.
        api_key_env: Name of the environment variable that holds the API key.
        max_retries, base_delay, max_delay, timeout: Passed to provider.

    Raises:
        ValueError: If the env var is not set or empty.
    """
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        msg = f"Provider '{alias}': environment variable '{api_key_env}' is not set."
        raise ValueError(msg)
    return OpenAICompatProvider(
        base_url=base_url,
        api_key=api_key,
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        timeout=timeout,
    )


def build_fake_registry() -> ProviderRegistry:
    """Return a ProviderRegistry pre-loaded with a no-op FakeProvider.

    Useful for offline smoke tests of the orchestrator and CLI.
    """
    registry = ProviderRegistry()
    registry.register("fake", FakeProvider(responses=[]))
    return registry

