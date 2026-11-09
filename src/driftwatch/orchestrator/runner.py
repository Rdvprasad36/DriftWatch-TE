"""Async job runner with bounded concurrency.

Architecture.md §3.6:
  "Runs with bounded concurrency to respect quotas, writes each result
   atomically, resumes after failure."

AGENTS.md rule 7: "Never silently drop errors."
  - Provider errors → ``TrialResult.error_type`` set, row written.
  - Unknown model alias → caught, error row written, run continues.

Design choices held constant (AGENTS.md rule 6):
  - Concurrency, run hour, system prompt — changes require documentation.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from driftwatch.agent.loop import AgentLoop
from driftwatch.agent.trial import TrialResult
from driftwatch.attacks.injector import AttackInjector
from driftwatch.attacks.loader import load_payload
from driftwatch.orchestrator.jobs import Job
from driftwatch.orchestrator.writer import RunWriter
from driftwatch.providers.registry import ProviderRegistry
from driftwatch.world.evaluator import GoalEvaluator
from driftwatch.world.state import load_world
from driftwatch.world.tools import build_default_registry

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    """Summary of an orchestrator run."""

    week: str = ""
    planned: int = 0
    completed: int = 0
    skipped: int = 0
    errors: int = 0


async def run_jobs(
    jobs: list[Job],
    *,
    provider_registry: ProviderRegistry,
    suite_root: Path,
    writer: RunWriter,
    concurrency: int = 4,
) -> RunSummary:
    """Execute all *jobs* with bounded concurrency.

    Args:
        jobs: Flat list of jobs from :func:`expand_jobs`.
        provider_registry: Maps model aliases to providers.
        suite_root: Root directory containing suites (e.g. ``Path("suites")``).
        writer: :class:`RunWriter` for staging output.
        concurrency: Max simultaneous LLM calls (``asyncio.Semaphore``).

    Returns:
        :class:`RunSummary` with counts.
    """
    # Determine already-completed jobs (for resume)
    completed_ids = writer.completed_job_ids()

    summary = RunSummary(
        week=writer._week,
        planned=len(jobs),
    )

    semaphore = asyncio.Semaphore(concurrency)
    injector = AttackInjector()
    evaluator = GoalEvaluator()

    async def run_one(job: Job) -> None:
        """Execute a single job, guarded by the semaphore."""
        if job.job_id in completed_ids:
            summary.skipped += 1
            logger.info("Skipping completed job '%s'.", job.job_id)
            return

        async with semaphore:
            result = await _execute_job(
                job,
                provider_registry=provider_registry,
                suite_root=suite_root,
                injector=injector,
                evaluator=evaluator,
            )
            await writer.append(job, result)
            summary.completed += 1
            if result.error_type is not None:
                summary.errors += 1

    # Launch all jobs concurrently (semaphore limits parallelism)
    tasks = [asyncio.create_task(run_one(job)) for job in jobs]
    await asyncio.gather(*tasks)

    logger.info(
        "Run complete: %d planned, %d completed, %d skipped, %d errors.",
        summary.planned,
        summary.completed,
        summary.skipped,
        summary.errors,
    )
    return summary


async def _execute_job(
    job: Job,
    *,
    provider_registry: ProviderRegistry,
    suite_root: Path,
    injector: AttackInjector,
    evaluator: GoalEvaluator,
) -> TrialResult:
    """Execute one job and return a TrialResult.

    Never raises — all errors are captured in ``TrialResult.error_type``
    (AGENTS.md rule 7).
    """
    scenario = job.scenario

    try:
        # Resolve provider
        try:
            provider = provider_registry.get(job.model_alias)
        except KeyError as exc:
            return _error_result(job, f"unknown_model:{exc}")

        # Load world state (fresh per trial)
        world_state = load_world(Path(scenario.world)).fresh_copy()

        # Build a fresh tool registry per trial
        # (tool_description injection mutates the registry)
        tool_registry = build_default_registry()

        # Load and apply injection if present
        payload: str | None = None
        if scenario.injection is not None:
            suite_dir = suite_root / scenario.suite
            payload = load_payload(scenario.injection.payload_ref, suite_dir)
            injector.inject(
                channel=scenario.channel,
                injection=scenario.injection,
                payload=payload,
                world_state=world_state,
                tool_registry=tool_registry,
            )

        # Run the agent loop
        loop = AgentLoop(
            provider=provider,
            tool_registry=tool_registry,
            evaluator=evaluator,
        )
        result = await loop.run(
            scenario,
            world_state,
            model_alias=job.model_alias,
            temperature=job.temperature,
            trial=job.trial,
            payload=payload,
        )
        return result

    except Exception as exc:
        # Catch-all: never let a single job crash the orchestrator
        logger.error("Unexpected error in job '%s': %s", job.job_id, exc, exc_info=True)
        return _error_result(job, f"unexpected:{type(exc).__name__}:{exc}")


def _error_result(job: Job, error_type: str) -> TrialResult:
    """Build a TrialResult representing a harness error."""
    return TrialResult(
        scenario_id=job.scenario.id,
        language=str(job.scenario.language.value),
        channel=str(job.scenario.channel.value),
        model_alias=job.model_alias,
        returned_model_id="",
        fingerprint=None,
        attack_success=False,
        task_success=False,
        exposed=False,
        trial=job.trial,
        temperature=job.temperature,
        steps=0,
        error_type=error_type,
    )
