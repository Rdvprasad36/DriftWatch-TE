"""Data contracts and schemas for DriftWatch-TE outputs.

All JSON artifacts are versioned with a ``schema_version`` field.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

SCHEMA_VERSION: str = "1.0.0"


# ---------------------------------------------------------------------------
# 1. results/summary/index.json
# ---------------------------------------------------------------------------


class ModelSummaryInfo(BaseModel):
    """Metadata for an evaluated model endpoint."""

    alias: str
    provider: str
    requested_id: str
    returned_ids_seen: list[str] = Field(default_factory=list)


class WeekIndexEntry(BaseModel):
    """Entry describing one weekly run bundle."""

    week: str
    is_pilot: bool = False
    total_trials: int = 0
    file: str


class SummaryIndex(BaseModel):
    """Data contract for results/summary/index.json."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    study_start_date: str
    planned_weeks: int = 12
    next_scheduled_run_date: str
    github_repo: str = "https://github.com/Rdvprasad36/DriftWatch-TE"
    hf_dataset_repo: str = "TODO"
    preregistration_url: str = "TODO"
    weeks: list[WeekIndexEntry] = Field(default_factory=list)
    models: list[ModelSummaryInfo] = Field(default_factory=list)
    suite_names_and_hashes: dict[str, str] = Field(default_factory=dict)
    last_updated_utc: str


# ---------------------------------------------------------------------------
# 2. results/summary/weekly/<date>.json
# ---------------------------------------------------------------------------


class SliceStats(BaseModel):
    """Metrics for one disaggregated slice of trials."""

    n_trials: int
    n_scenarios: int
    attack_success_rate: float
    task_success_rate: float
    ci_95: list[float] | None = Field(
        default=None,
        description="[lower, upper] 95% CI or None if not estimable (< 10 clusters)",
    )
    error_rate: float
    completion_rate: float
    mean_latency: float
    mean_tokens: float


class WeeklySummaryContract(BaseModel):
    """Data contract for results/summary/weekly/<date>.json."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    week: str
    is_pilot: bool
    total_trials: int
    total_attack_successes: int
    total_task_successes: int
    overall_asr: float
    # Detailed dimensional breakdowns:
    slices: dict[str, SliceStats] = Field(
        default_factory=dict, description="Keyed by <model>|<language>|<channel>|<suite>|<origin>"
    )
    # Aggregates for high-level dashboard display:
    models: dict[str, dict[str, Any]] = Field(default_factory=dict)
    languages: dict[str, dict[str, Any]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 3. results/analysis/analysis.json
# ---------------------------------------------------------------------------


class TrendTestResult(BaseModel):
    """Per-model longitudinal trend test result."""

    estimate: float
    interval: list[float] = Field(description="[lower, upper] 95% CI")
    p_value: float
    adjusted_p: float


class ChangePointRecord(BaseModel):
    """Detected change-point specification."""

    week: str
    method: Literal["PELT", "CUSUM"]
    shift: float
    interval: list[float] = Field(description="[lower, upper] CI of the shift")


class LocalControlEquivalence(BaseModel):
    """Negative control TOST equivalence test."""

    is_equivalent: bool
    margin: float = 0.03
    mean_diff: float
    ci_90: list[float] = Field(description="90% CI for two one-sided tests")
    p_value: float


class LanguageInteractionResult(BaseModel):
    """GEE language interaction term."""

    estimate: float
    odds_ratio: float
    p_value: float


class NativeVsMachineResult(BaseModel):
    """Paired difference between native and machine-translated attacks."""

    n_matched_scenarios: int
    mean_diff: float
    interval: list[float] = Field(description="[lower, upper] 95% CI")
    p_value: float


HypothesisStatusType = Literal["not_enough_data", "supported", "not_supported", "inconclusive"]


class HypothesisEvaluation(BaseModel):
    """Evaluation result for one pre-registered hypothesis."""

    status: HypothesisStatusType
    rule: str
    details: dict[str, Any] = Field(default_factory=dict)


class AnalysisContract(BaseModel):
    """Data contract for results/analysis/analysis.json."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    analyzed_at_utc: str
    study_weeks_count: int
    per_model_trend: dict[str, TrendTestResult] = Field(default_factory=dict)
    change_points: list[ChangePointRecord] = Field(default_factory=list)
    local_control_equivalence: LocalControlEquivalence | None = None
    language_interactions: dict[str, LanguageInteractionResult] = Field(default_factory=dict)
    native_versus_machine: NativeVsMachineResult | None = None
    hypotheses: dict[str, HypothesisEvaluation] = Field(default_factory=dict)
    # Optional descriptive summary fields
    overall_mean_asr: float | None = None
    gee_coefficients: dict[str, float] | None = None
    tost_equivalence: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# 4. results/events.json
# ---------------------------------------------------------------------------


class ProviderEventRecord(BaseModel):
    """A single provider changelog event."""

    provider: str
    model: str
    date: str
    url: str = ""
    note: str


class EventsContract(BaseModel):
    """Data contract for results/events.json."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    events: list[ProviderEventRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5. results/exports/schema.json
# ---------------------------------------------------------------------------


class ExportRowSchema(BaseModel):
    """Specification of the 25 trial record columns."""

    trial_id: str
    scenario_id: str
    run_week: str
    timestamp_utc: str
    model_alias: str
    requested_model_id: str = Field(
        validation_alias=AliasChoices("requested_model_id", "requested_model")
    )
    returned_model_id: str
    suite: str
    suite_hash: str
    attack_class: str
    channel: str
    language: str
    origin: Literal["native", "machine"]
    trial_index: int
    tool_calls: str = Field(
        description="JSON-encoded string of tool calls: [{'name': ..., 'arguments': ...}]"
    )
    attack_success: bool
    task_success: bool
    steps: int
    stop_reason: str
    error_type: str | None
    http_errors: int
    tokens_in: int
    tokens_out: int
    latency_ms: float
    git_sha: str


RECORD_SCHEMA_COLUMNS: list[str] = list(ExportRowSchema.model_fields.keys())
EXPORT_SCHEMA_PROPERTIES: dict[str, Any] = (
    ExportRowSchema.model_json_schema().get("properties", {})
)

