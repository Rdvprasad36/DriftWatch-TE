"""Job expansion — builds the flat list of trial jobs from suites.

Each ``Job`` is one (scenario, model, trial_index) tuple.  The orchestrator
runs every job exactly once, writing one result row per job.

Architecture.md §3.6:
  "Expands suites x trials into jobs, runs with bounded concurrency."

Temperature is set per design.md §2 / architecture.md §3.4:
  - canary suites: temperature=0
  - all other suites: temperature=0.7 (configurable via agent_temperature)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from driftwatch.schema.models import Scenario, SuiteManifest

logger = logging.getLogger(__name__)

# Default agent temperature (architecture.md §3.4)
DEFAULT_AGENT_TEMPERATURE: float = 0.7
# Canary suite temperature (design.md §2: temp 0 for canaries)
CANARY_TEMPERATURE: float = 0.0


def make_job_id(suite_name: str, scenario_id: str, model_alias: str, trial: int) -> str:
    """Build a unique, human-readable job ID."""
    return f"{suite_name}:{scenario_id}:{model_alias}:{trial}"


@dataclass
class Job:
    """One unit of work for the orchestrator."""

    job_id: str
    suite_name: str
    suite_hash: str
    scenario: Scenario
    model_alias: str
    trial: int
    temperature: float


def expand_jobs(
    suites: list[SuiteManifest],
    model_aliases: list[str],
    trials: int | dict[str, int] = 5,
    agent_temperature: float = DEFAULT_AGENT_TEMPERATURE,
) -> list[Job]:
    """Expand suites × scenarios × models × trials into a flat job list.

    Args:
        suites: Loaded suite manifests.
        model_aliases: Model aliases to test (e.g. ``["fake"]``).
        trials: Number of trials per (scenario, model) pair, or dict mapping
            suite name to trial count (e.g. from config/study.yaml).
        agent_temperature: Temperature for non-canary suites.

    Returns:
        Flat list of :class:`Job` instances with unique IDs.
    """
    jobs: list[Job] = []
    for suite in suites:
        # Determine trial count for this suite
        suite_trials = trials.get(suite.name, 5) if isinstance(trials, dict) else int(trials)

        # Canary suites always use temperature 0
        temp = CANARY_TEMPERATURE if suite.name.startswith("canary") else agent_temperature
        for scenario in suite.scenarios:
            for alias in model_aliases:
                for trial_idx in range(suite_trials):
                    job_id = make_job_id(suite.name, scenario.id, alias, trial_idx)
                    jobs.append(
                        Job(
                            job_id=job_id,
                            suite_name=suite.name,
                            suite_hash=suite.suite_hash,
                            scenario=scenario,
                            model_alias=alias,
                            trial=trial_idx,
                            temperature=temp,
                        )
                    )
    logger.info(
        "Expanded %d job(s) from %d suite(s) × %d model(s).",
        len(jobs),
        len(suites),
        len(model_aliases),
    )
    return jobs
