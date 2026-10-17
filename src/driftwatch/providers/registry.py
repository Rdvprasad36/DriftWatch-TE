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
from pathlib import Path

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


def load_dotenv_if_present(env_path: Path | None = None) -> None:
    """Load .env file into os.environ if present, without logging or printing values."""
    path = env_path or Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


def build_openai_compat_from_env(
    alias: str,
    base_url: str,
    api_key_env: str,
    *,
    default_model: str | None = None,
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
        default_model: Default backend model identifier if alias is requested.
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
        default_model=default_model,
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        timeout=timeout,
    )


def build_from_env() -> ProviderRegistry:
    """Build ProviderRegistry populated from environment variables (FR3, FR6).

    Loads .env if present. Maps hosted aliases (groq, google, openrouter)
    and local model endpoint according to environment configuration.
    """
    load_dotenv_if_present()
    registry = ProviderRegistry()

    # Always register fake for offline smoke tests
    registry.register("fake", FakeProvider(responses=[]))

    # Groq (openai/gpt-oss-20b or llama model)
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key:
        groq_model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
        groq_p = OpenAICompatProvider(
            base_url="https://api.groq.com/openai",
            api_key=groq_key,
            default_model=groq_model,
        )
        registry.register("groq", groq_p)
        registry.register("groq-llama3", groq_p)

    # Google AI Studio
    google_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if google_key:
        google_model = os.environ.get("GOOGLE_MODEL", "gemini-flash-latest")
        google_p = OpenAICompatProvider(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key=google_key,
            default_model=google_model,
        )
        registry.register("google", google_p)

    # OpenRouter
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if or_key:
        or_model = os.environ.get("OPENROUTER_MODEL", "dots-studio/dots-3-note-preview:free")
        or_p = OpenAICompatProvider(
            base_url="https://openrouter.ai/api",
            api_key=or_key,
            default_model=or_model,
        )
        registry.register("openrouter", or_p)

    # Local model
    local_url = os.environ.get("LOCAL_MODEL_URL", "").strip()
    if local_url:
        local_model = os.environ.get("LOCAL_MODEL", "llama3.2:1b")
        local_p = OpenAICompatProvider(
            base_url=local_url,
            api_key="ollama",
            default_model=local_model,
        )
        registry.register("local", local_p)

    return registry


def build_fake_registry() -> ProviderRegistry:
    """Return a ProviderRegistry pre-loaded with a no-op FakeProvider.

    Useful for offline smoke tests of the orchestrator and CLI.
    """
    registry = ProviderRegistry()
    registry.register("fake", FakeProvider(responses=[]))
    return registry
