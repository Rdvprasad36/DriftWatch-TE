"""Tests for canary runner and hashing (FR5).

All tests are offline — FakeProvider supplies scripted responses.
No real LLM APIs.

Satisfies FR5 (Canary prompts at temperature 0, output hashes, logprobs where offered).
Architecture.md §3.1, §4:
  Canary row: prompt_id, output_hash, top_logprobs_hash, returned_model_id.
Design.md §4.7 (Canary analysis: compare output hash to week 1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from driftwatch.canary.hashing import (
    compare_canary_runs,
    compute_logprobs_hash,
    compute_output_hash,
)
from driftwatch.canary.runner import (
    CanaryPrompt,
    CanaryResult,
    load_canary_prompts,
    run_canaries,
    write_canary_bundle,
)
from driftwatch.cli.main import cli
from driftwatch.providers.fake import FakeProvider
from driftwatch.providers.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fake_registry(
    responses: list[Any] | None = None,
    returned_model_id: str = "fake-model-v1",
) -> ProviderRegistry:
    """Build a ProviderRegistry with a FakeProvider."""
    resp_list = responses or [
        FakeProvider.make_text_response(
            "Canary output response 1.", model=returned_model_id
        ),
        FakeProvider.make_text_response(
            "Canary output response 2.", model=returned_model_id
        ),
    ]
    provider = FakeProvider(
        responses=resp_list, returned_model_id=returned_model_id
    )
    registry = ProviderRegistry()
    registry.register("fake", provider)
    return registry


# ---------------------------------------------------------------------------
# Canary Hashing Tests
# ---------------------------------------------------------------------------


class TestCanaryHashing:
    def test_output_hash_is_stable_sha256(self) -> None:
        """Same output text always produces identical SHA-256 hex digest."""
        text = "Order 1042 status: shipped."
        h1 = compute_output_hash(text)
        h2 = compute_output_hash(text)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 is 64 hex chars
        assert all(c in "0123456789abcdef" for c in h1)

    def test_output_hash_normalizes_whitespace(self) -> None:
        """Trailing whitespace and newlines are stripped before hashing."""
        text_clean = "Model response text"
        text_padded = "  Model response text\n\n  "
        assert compute_output_hash(text_clean) == compute_output_hash(text_padded)

    def test_output_hash_differs_on_content_change(self) -> None:
        """Different text produces different hashes."""
        h1 = compute_output_hash("Response version A")
        h2 = compute_output_hash("Response version B")
        assert h1 != h2

    def test_logprobs_hash_none_when_empty(self) -> None:
        """compute_logprobs_hash returns None when logprobs is None or empty."""
        assert compute_logprobs_hash(None) is None
        assert compute_logprobs_hash([]) is None
        assert compute_logprobs_hash({}) is None

    def test_logprobs_hash_computed_when_present(self) -> None:
        """Structured logprobs data produces deterministic SHA-256 hash."""
        logprobs = [{"token": "hello", "logprob": -0.05, "top_logprobs": []}]
        h = compute_logprobs_hash(logprobs)
        assert h is not None
        assert len(h) == 64

    def test_logprobs_hash_deterministic_dict_ordering(self) -> None:
        """Dict key ordering does not affect logprobs hash."""
        lp1 = {"b": 2, "a": 1}
        lp2 = {"a": 1, "b": 2}
        assert compute_logprobs_hash(lp1) == compute_logprobs_hash(lp2)


# ---------------------------------------------------------------------------
# Canary Runner Tests
# ---------------------------------------------------------------------------


class TestCanaryRunner:
    async def test_canary_runs_at_temperature_zero(self) -> None:
        """Canary execution must always use temperature=0.0 (FR5 / design.md §2)."""
        provider = FakeProvider(
            responses=[FakeProvider.make_text_response("Canary answer.")]
        )
        registry = ProviderRegistry()
        registry.register("fake", provider)

        prompts = [CanaryPrompt(prompt_id="canary_01", prompt="Ping test.")]
        results = await run_canaries(
            prompts, provider_registry=registry, model_aliases=["fake"]
        )

        assert len(results) == 1
        assert results[0].prompt_id == "canary_01"
        assert results[0].output_text == "Canary answer."
        assert len(results[0].output_hash) == 64
        # Verify provider received temperature=0.0
        assert len(provider.call_log) == 1
        assert provider.call_log[0]["temperature"] == 0.0

    async def test_canary_records_returned_model_id(self) -> None:
        """Records returned_model_id from provider response (FR3, FR5)."""
        registry = make_fake_registry(returned_model_id="gpt-4o-2026-10")
        prompts = [CanaryPrompt(prompt_id="c01", prompt="Hello")]
        results = await run_canaries(
            prompts, provider_registry=registry, model_aliases=["fake"]
        )

        assert results[0].returned_model_id == "gpt-4o-2026-10"
        assert results[0].model_alias == "fake"

    async def test_canary_captures_provider_error(self) -> None:
        """Provider error is recorded in result, never raised (AGENTS.md rule 7)."""
        error_resp = FakeProvider.make_error_response("Rate limit 429", http_status=429)
        provider = FakeProvider(responses=[error_resp])
        registry = ProviderRegistry()
        registry.register("fake", provider)

        prompts = [CanaryPrompt(prompt_id="c01", prompt="Hello")]
        results = await run_canaries(
            prompts, provider_registry=registry, model_aliases=["fake"]
        )

        assert len(results) == 1
        assert results[0].error is not None
        assert "429" in results[0].error
        assert results[0].output_hash == ""

    async def test_canary_unknown_model_alias(self) -> None:
        """Unregistered model alias logs error, does not raise."""
        registry = ProviderRegistry()  # empty
        prompts = [CanaryPrompt(prompt_id="c01", prompt="Hello")]
        results = await run_canaries(
            prompts, provider_registry=registry, model_aliases=["missing_model"]
        )

        assert len(results) == 1
        assert results[0].error is not None
        assert "unknown_model" in results[0].error

    def test_canary_result_as_record_schema(self) -> None:
        """as_record matches architecture.md §4:
        prompt_id, output_hash, top_logprobs_hash, returned_model_id.
        """
        res = CanaryResult(
            prompt_id="c01",
            model_alias="fake",
            returned_model_id="fake-v1",
            output_text="Answer text",
            output_hash="abc" * 21 + "a",
            top_logprobs_hash=None,
            latency_ms=12.5,
            error=None,
        )
        rec = res.as_record()
        assert rec["prompt_id"] == "c01"
        assert rec["model_alias"] == "fake"
        assert rec["returned_model_id"] == "fake-v1"
        assert rec["output_hash"] == res.output_hash
        assert rec["top_logprobs_hash"] is None
        assert rec["latency_ms"] == 12.5
        assert rec["error"] is None

    def test_load_canary_prompts_from_suite(self, tmp_path: Path) -> None:
        """Loads canary prompts from a suite YAML file or directory."""
        suite_dir = tmp_path / "canary"
        suite_dir.mkdir()
        yaml_content = """
- id: prompt_1
  suite: canary
  language: en
  channel: tool_output
  world: worlds/shop_v1.yaml
  user_turns:
    - "Canary question 1"
  goal:
    no_call: {tool: issue_refund}
- id: prompt_2
  suite: canary
  language: en
  channel: tool_output
  world: worlds/shop_v1.yaml
  user_turns:
    - "Canary question 2"
  goal:
    no_call: {tool: issue_refund}
"""
        (suite_dir / "canary.yaml").write_text(yaml_content, encoding="utf-8")
        prompts = load_canary_prompts(suite_dir)
        assert len(prompts) == 2
        assert prompts[0].prompt_id == "prompt_1"
        assert prompts[0].prompt == "Canary question 1"
        assert prompts[1].prompt_id == "prompt_2"
        assert prompts[1].prompt == "Canary question 2"


# ---------------------------------------------------------------------------
# Canary Bundle & Comparison Tests
# ---------------------------------------------------------------------------


class TestCanaryBundle:
    def test_write_canary_bundle(self, tmp_path: Path) -> None:
        """write_canary_bundle writes valid canary.json in run dir."""
        run_dir = tmp_path / "weekly" / "2026-10-19"
        results = [
            CanaryResult(
                prompt_id="c01",
                model_alias="fake",
                returned_model_id="fake-v1",
                output_text="Done",
                output_hash=compute_output_hash("Done"),
                top_logprobs_hash=None,
                latency_ms=5.0,
            )
        ]
        out_path = write_canary_bundle(results, run_dir, week="2026-10-19")
        assert out_path.exists()
        assert out_path.name == "canary.json"

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["week"] == "2026-10-19"
        assert len(data["results"]) == 1
        assert data["results"][0]["prompt_id"] == "c01"
        assert data["results"][0]["output_hash"] == compute_output_hash("Done")

    def test_compare_canary_runs_detects_no_drift(self) -> None:
        """Identical runs report 0 hash changes."""
        h = compute_output_hash("Test")
        baseline = [
            {"prompt_id": "c01", "model_alias": "fake", "output_hash": h}
        ]
        current = [
            {"prompt_id": "c01", "model_alias": "fake", "output_hash": h}
        ]
        report = compare_canary_runs(baseline, current)
        assert report["total_compared"] == 1
        assert report["changed_count"] == 0
        assert report["drift_detected"] is False

    def test_compare_canary_runs_detects_drift(self) -> None:
        """Hash mismatch flags model drift (design.md §4.7)."""
        h1 = compute_output_hash("Test 1")
        h2 = compute_output_hash("Test 2")
        baseline = [
            {"prompt_id": "c01", "model_alias": "fake", "output_hash": h1}
        ]
        current = [
            {"prompt_id": "c01", "model_alias": "fake", "output_hash": h2}
        ]
        report = compare_canary_runs(baseline, current)
        assert report["total_compared"] == 1
        assert report["changed_count"] == 1
        assert report["drift_detected"] is True
        assert len(report["changes"]) == 1
        assert report["changes"][0]["prompt_id"] == "c01"
        assert report["changes"][0]["baseline_hash"] == h1
        assert report["changes"][0]["current_hash"] == h2


# ---------------------------------------------------------------------------
# CLI Canary Command Tests
# ---------------------------------------------------------------------------


class TestDriftwatchCanaryCLI:
    def test_canary_cli_smoke(self, tmp_path: Path) -> None:
        """driftwatch canary smoke test runs canary prompts and writes canary.json."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "canary",
                "--week", "2026-10-19",
                "--models", "fake",
                "--suite-dir", "suites/canary",
                "--results-dir", str(tmp_path / "weekly"),
            ],
        )
        assert result.exit_code == 0, f"CLI error: {result.output}"
        canary_file = tmp_path / "weekly" / "2026-10-19" / "canary.json"
        assert canary_file.exists()
        data = json.loads(canary_file.read_text(encoding="utf-8"))
        assert data["week"] == "2026-10-19"
        assert len(data["results"]) >= 1

    def test_canary_cli_missing_suite_exits_2(self, tmp_path: Path) -> None:
        """Missing canary suite directory exits with code 2."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "canary",
                "--week", "2026-10-19",
                "--models", "fake",
                "--suite-dir", "suites/nonexistent_canary_dir",
                "--results-dir", str(tmp_path / "weekly"),
            ],
        )
        assert result.exit_code == 2
