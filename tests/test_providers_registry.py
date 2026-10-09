"""Tests for ProviderRegistry, build_openai_compat_from_env, build_fake_registry.

All tests are offline — no real HTTP calls.
"""

from __future__ import annotations

import pytest

from driftwatch.providers.fake import FakeProvider
from driftwatch.providers.openai_compat import OpenAICompatProvider
from driftwatch.providers.registry import (
    ProviderRegistry,
    build_fake_registry,
    build_openai_compat_from_env,
)

# ---------------------------------------------------------------------------
# ProviderRegistry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_register_and_get_returns_same_instance(self) -> None:
        registry = ProviderRegistry()
        provider = FakeProvider(responses=[])
        registry.register("fake", provider)
        assert registry.get("fake") is provider

    def test_get_unknown_alias_raises_key_error(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(KeyError, match="Unknown provider alias 'missing'"):
            registry.get("missing")

    def test_key_error_message_lists_available(self) -> None:
        registry = ProviderRegistry()
        registry.register("alpha", FakeProvider(responses=[]))
        registry.register("beta", FakeProvider(responses=[]))
        with pytest.raises(KeyError, match="alpha"):
            registry.get("gamma")

    def test_contains_registered_alias(self) -> None:
        registry = ProviderRegistry()
        registry.register("my-model", FakeProvider(responses=[]))
        assert "my-model" in registry

    def test_not_contains_unregistered_alias(self) -> None:
        registry = ProviderRegistry()
        assert "missing" not in registry

    def test_aliases_returns_all_registered(self) -> None:
        registry = ProviderRegistry()
        registry.register("a", FakeProvider(responses=[]))
        registry.register("b", FakeProvider(responses=[]))
        registry.register("c", FakeProvider(responses=[]))
        assert set(registry.aliases()) == {"a", "b", "c"}

    def test_aliases_empty_when_nothing_registered(self) -> None:
        registry = ProviderRegistry()
        assert registry.aliases() == []

    def test_overwrite_existing_alias_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        registry = ProviderRegistry()
        p1 = FakeProvider(responses=[])
        p2 = FakeProvider(responses=[])
        registry.register("dup", p1)
        with caplog.at_level(logging.WARNING, logger="driftwatch.providers.registry"):
            registry.register("dup", p2)
        assert any("dup" in record.message for record in caplog.records)
        # Second registration wins
        assert registry.get("dup") is p2

    def test_register_multiple_distinct_providers(self) -> None:
        registry = ProviderRegistry()
        fake = FakeProvider(responses=[])
        real = OpenAICompatProvider(
            base_url="https://fake.api", api_key="sk-test", base_delay=0.0, max_delay=0.0
        )
        registry.register("fake", fake)
        registry.register("real", real)
        assert registry.get("fake") is fake
        assert registry.get("real") is real
        assert len(registry.aliases()) == 2


# ---------------------------------------------------------------------------
# build_openai_compat_from_env
# ---------------------------------------------------------------------------


class TestBuildOpenAICompatFromEnv:
    def test_builds_provider_when_env_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_API_KEY", "sk-valid-key")
        provider = build_openai_compat_from_env(
            alias="test-model",
            base_url="https://api.example.com",
            api_key_env="MY_API_KEY",
        )
        assert isinstance(provider, OpenAICompatProvider)

    def test_raises_value_error_when_env_var_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISSING_KEY", raising=False)
        with pytest.raises(ValueError, match="MISSING_KEY"):
            build_openai_compat_from_env(
                alias="test-model",
                base_url="https://api.example.com",
                api_key_env="MISSING_KEY",
            )

    def test_raises_value_error_when_env_var_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EMPTY_KEY", "   ")  # whitespace only
        with pytest.raises(ValueError, match="EMPTY_KEY"):
            build_openai_compat_from_env(
                alias="test-model",
                base_url="https://api.example.com",
                api_key_env="EMPTY_KEY",
            )

    def test_error_message_names_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_KEY_HERE", raising=False)
        with pytest.raises(ValueError, match="my-alias"):
            build_openai_compat_from_env(
                alias="my-alias",
                base_url="https://api.example.com",
                api_key_env="NO_KEY_HERE",
            )

    def test_key_never_logged_raw(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AGENTS.md rule 4: API key must not appear in logs."""
        import logging

        monkeypatch.setenv("SECRET_KEY", "sk-ultra-secret-value")
        with caplog.at_level(logging.DEBUG, logger="driftwatch.providers.registry"):
            build_openai_compat_from_env(
                alias="safe",
                base_url="https://api.example.com",
                api_key_env="SECRET_KEY",
            )
        for record in caplog.records:
            assert "sk-ultra-secret-value" not in record.message

    def test_passes_kwargs_to_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_API_KEY2", "sk-key")
        provider = build_openai_compat_from_env(
            alias="test",
            base_url="https://api.example.com",
            api_key_env="MY_API_KEY2",
            max_retries=5,
            base_delay=2.0,
            max_delay=120.0,
            timeout=45.0,
        )
        assert provider._max_retries == 5
        assert provider._base_delay == 2.0
        assert provider._max_delay == 120.0
        assert provider._timeout == 45.0


# ---------------------------------------------------------------------------
# build_fake_registry
# ---------------------------------------------------------------------------


class TestBuildFakeRegistry:
    def test_returns_registry_with_fake_alias(self) -> None:
        registry = build_fake_registry()
        assert isinstance(registry, ProviderRegistry)
        assert "fake" in registry

    def test_fake_provider_is_fake_provider_instance(self) -> None:
        registry = build_fake_registry()
        provider = registry.get("fake")
        assert isinstance(provider, FakeProvider)

    def test_each_call_returns_independent_registry(self) -> None:
        r1 = build_fake_registry()
        r2 = build_fake_registry()
        assert r1 is not r2
        assert r1.get("fake") is not r2.get("fake")
