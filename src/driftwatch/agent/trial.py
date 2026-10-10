"""TrialResult — structured output of one agent trial.

Maps directly to the one-row-per-trial schema in architecture.md §4::

    run_date, week, suite, suite_hash, scenario_id, language, channel,
    model_alias, returned_model_id, fingerprint, trial, temperature,
    task_success, attack_success, steps, tokens_in, tokens_out,
    latency_ms, http_errors, error_type, git_sha, sdk_versions

``TrialResult`` captures the per-trial columns produced by the agent loop.
The orchestrator (step 6) adds run-level columns (week, suite_hash, git_sha…)
before writing to Parquet.

``attack_success`` and ``task_success`` are deterministic predicates evaluated
by ``GoalEvaluator`` — never an LLM judge (AGENTS.md rule 5 / FR4).
``error_type`` is set (not None) whenever the loop ended due to an error
so that errors are always recorded explicitly (AGENTS.md rule 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from driftwatch.providers.base import ProviderResponse
from driftwatch.world.tools import ToolCall


@dataclass
class TrialResult:
    """Output of one scenario × trial execution.

    Columns that map to the Parquet schema (architecture.md §4):
    - scenario_id, language, channel — copied from Scenario
    - model_alias — the requested model alias
    - returned_model_id — model id from the last successful response body
    - fingerprint — system_fingerprint from the last response (or None)
    - trial — 0-based trial index (set by orchestrator)
    - temperature — the temperature used
    - attack_success — True iff the goal predicate fired (FR4)
    - task_success — True iff benign_expected predicate fired (FR4)
    - steps — number of loop iterations executed
    - tokens_in / tokens_out — summed across all LLM calls in this trial
    - latency_ms — total wall-clock ms across all LLM calls
    - http_errors — count of non-200 HTTP responses encountered
    - error_type — None on clean run; short label when loop aborted early
    - tool_trace — ordered list of ToolCall records (for provenance)
    - responses — all ProviderResponses (for debugging; not stored in Parquet)
    """

    # Identity
    scenario_id: str
    language: str
    channel: str
    model_alias: str

    # Model tracking (FR3)
    returned_model_id: str
    fingerprint: str | None

    # Outcome (FR4 — deterministic predicates)
    attack_success: bool
    task_success: bool

    # Execution metadata
    trial: int = 0
    temperature: float = 0.7
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    http_errors: int = 0

    # Error capture (AGENTS.md rule 7)
    error_type: str | None = None

    # Trace (provenance, not in Parquet)
    tool_trace: list[ToolCall] = field(default_factory=list)
    responses: list[ProviderResponse] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True if the trial completed without a harness error."""
        return self.error_type is None

    def as_record(self) -> dict[str, Any]:
        """Flat dict suitable for a Parquet row (drops non-serialisable fields).

        The orchestrator adds run-level columns (week, suite, suite_hash,
        git_sha, sdk_versions) before writing.
        """
        return {
            "scenario_id": self.scenario_id,
            "language": self.language,
            "channel": self.channel,
            "model_alias": self.model_alias,
            "returned_model_id": self.returned_model_id,
            "fingerprint": self.fingerprint,
            "trial": self.trial,
            "temperature": self.temperature,
            "attack_success": self.attack_success,
            "task_success": self.task_success,
            "steps": self.steps,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "http_errors": self.http_errors,
            "error_type": self.error_type,
        }

