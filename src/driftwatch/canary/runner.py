"""Canary runner for DriftWatch-TE.

Executes canary prompts at temperature 0.0 to detect underlying model changes.
Architecture.md §3.1, §4.
FR5 (Canary prompts at temperature 0, output hashes, logprobs where offered).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from driftwatch.canary.hashing import compute_output_hash
from driftwatch.providers.registry import ProviderRegistry
from driftwatch.suites.loader import load_suite

logger = logging.getLogger(__name__)


@dataclass
class CanaryPrompt:
    """A single canary prompt."""

    prompt_id: str
    prompt: str


@dataclass
class CanaryResult:
    """Result of running one canary prompt against a model.

    Maps to architecture.md §4:
      prompt_id, output_hash, top_logprobs_hash, returned_model_id
    """

    prompt_id: str
    model_alias: str
    returned_model_id: str
    output_text: str
    output_hash: str
    top_logprobs_hash: str | None = None
    latency_ms: float = 0.0
    error: str | None = None

    def as_record(self) -> dict[str, Any]:
        """Convert to dict matching the canary row schema (architecture.md §4)."""
        return {
            "prompt_id": self.prompt_id,
            "model_alias": self.model_alias,
            "returned_model_id": self.returned_model_id,
            "output_hash": self.output_hash,
            "top_logprobs_hash": self.top_logprobs_hash,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def load_canary_prompts(suite_dir: Path) -> list[CanaryPrompt]:
    """Load canary prompts from a canary suite directory.

    Reads scenario YAMLs and extracts prompt_id = scenario.id
    and prompt = scenario.user_turns[0].
    """
    manifest = load_suite(suite_dir)
    prompts: list[CanaryPrompt] = []
    for scenario in manifest.scenarios:
        prompt_text = (
            scenario.user_turns[0] if scenario.user_turns else "Ping."
        )
        prompts.append(CanaryPrompt(prompt_id=scenario.id, prompt=prompt_text))
    return prompts


async def run_canaries(
    prompts: list[CanaryPrompt],
    *,
    provider_registry: ProviderRegistry,
    model_aliases: list[str],
) -> list[CanaryResult]:
    """Execute all canary prompts across model aliases at temperature 0.0.

    Args:
        prompts: List of canary prompts to execute.
        provider_registry: Registry containing model providers.
        model_aliases: List of model aliases to test.

    Returns:
        List of CanaryResult instances.
    """
    results: list[CanaryResult] = []

    for alias in model_aliases:
        try:
            provider = provider_registry.get(alias)
        except KeyError as exc:
            for p in prompts:
                results.append(
                    CanaryResult(
                        prompt_id=p.prompt_id,
                        model_alias=alias,
                        returned_model_id=alias,
                        output_text="",
                        output_hash="",
                        top_logprobs_hash=None,
                        latency_ms=0.0,
                        error=f"unknown_model:{exc}",
                    )
                )
            continue

        for p in prompts:
            messages = [{"role": "user", "content": p.prompt}]
            try:
                # Canary prompts always run at temperature 0.0 (FR5)
                resp = await provider.complete(
                    messages=messages,
                    tools=[],
                    model=alias,
                    temperature=0.0,
                )
                if not resp.ok:
                    results.append(
                        CanaryResult(
                            prompt_id=p.prompt_id,
                            model_alias=alias,
                            returned_model_id=resp.returned_model,
                            output_text="",
                            output_hash="",
                            top_logprobs_hash=None,
                            latency_ms=resp.latency_ms,
                            error=resp.error or f"HTTP {resp.http_status}",
                        )
                    )
                else:
                    text = resp.content or ""
                    h = compute_output_hash(text)
                    results.append(
                        CanaryResult(
                            prompt_id=p.prompt_id,
                            model_alias=alias,
                            returned_model_id=resp.returned_model,
                            output_text=text,
                            output_hash=h,
                            top_logprobs_hash=None,
                            latency_ms=resp.latency_ms,
                            error=None,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Unexpected canary error for '%s' on '%s': %s",
                    p.prompt_id,
                    alias,
                    exc,
                )
                results.append(
                    CanaryResult(
                        prompt_id=p.prompt_id,
                        model_alias=alias,
                        returned_model_id=alias,
                        output_text="",
                        output_hash="",
                        top_logprobs_hash=None,
                        latency_ms=0.0,
                        error=f"unexpected:{type(exc).__name__}:{exc}",
                    )
                )

    return results


def write_canary_bundle(
    results: list[CanaryResult],
    run_dir: Path,
    *,
    week: str,
) -> Path:
    """Save canary results to weekly/<week>/canary.json.

    Args:
        results: List of CanaryResult objects.
        run_dir: Run directory for weekly results.
        week: ISO week string.

    Returns:
        Path to written canary.json.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "canary.json"

    data = {
        "week": week,
        "results": [r.as_record() for r in results],
    }

    out_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote canary bundle: %s (%d results)", out_path, len(results))
    return out_path
