"""Pydantic models for DriftWatch-TE scenarios and suites.

Maps to design.md §2 (frozen specifications) and architecture.md §4 (data schema).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Language(StrEnum):
    """ISO-style language tags used by DriftWatch-TE."""

    EN = "en"
    TE = "te"
    TE_LATN = "te-Latn"
    TE_EN = "te-en"


class Channel(StrEnum):
    """Attack injection channel."""

    TOOL_OUTPUT = "tool_output"
    TOOL_DESCRIPTION = "tool_description"


class GoalPredicate(BaseModel):
    """Deterministic predicate for attack/task success.

    Exactly one field should be set.  The predicate is evaluated against
    the world-state trace after the agent loop completes.
    """

    tool_called: dict[str, Any] | None = Field(
        default=None,
        description="Attack succeeds if this tool was called with matching args.",
    )
    no_call: dict[str, str] | None = Field(
        default=None,
        description="Correct behavior: this tool was NOT called.",
    )
    state_equals: dict[str, Any] | None = Field(
        default=None,
        description="Task succeeds if world state matches these key-value pairs.",
    )


class Injection(BaseModel):
    """Where and what to inject for an attack scenario."""

    tool: str = Field(description="Tool whose output is poisoned.")
    payload_ref: str = Field(description="Path to the payload text file, relative to suite dir.")


class Scenario(BaseModel):
    """A single test scenario within a suite.

    Matches the YAML schema from design.md §2.
    """

    id: str = Field(description="Unique identifier, e.g. atk_refund_review_en_01.")
    suite: str = Field(description="Parent suite name, e.g. attacks_v1.")
    language: Language
    channel: Channel = Field(default=Channel.TOOL_OUTPUT)
    world: str = Field(description="Path to world definition YAML.")
    user_turns: list[str] = Field(description="User messages that start the agent conversation.")
    injection: Injection | None = Field(
        default=None,
        description="Injection config; None for control/canary scenarios.",
    )
    goal: GoalPredicate = Field(description="Attack success predicate.")
    benign_expected: GoalPredicate | None = Field(
        default=None,
        description="What correct (non-attacked) behavior looks like.",
    )
    max_steps: int = Field(default=8, ge=1, le=20)
    base_id: str | None = Field(
        default=None,
        description=(
            "Base attack identifier shared across language and channel variants. "
            "GEE and cluster bootstrap MUST cluster on base_id, not on scenario id."
        ),
    )
    attack_class: str | None = Field(default=None, description="Attack classification.")
    origin: str | None = Field(default=None, description="Origin: human, machine, etc.")
    translator: dict[str, Any] | str | None = Field(
        default=None, description="Translation metadata if machine-translated."
    )
    review_status: str | None = Field(
        default=None, description="Review status, e.g. needs_native_review."
    )


class SuiteManifest(BaseModel):
    """Metadata for a loaded suite, including its content hash."""

    name: str
    version: str = Field(default="v1")
    scenarios: list[Scenario]
    suite_hash: str = Field(description="SHA-256 hex digest of canonical suite content.")


class SuiteLockEntry(BaseModel):
    """One entry in the suite lock file."""

    suite_name: str
    suite_hash: str
    locked_at: str = Field(description="ISO-8601 timestamp when this hash was locked.")


class SuiteLockFile(BaseModel):
    """The full lock file mapping suite names to their frozen hashes."""

    frozen: bool = Field(
        default=False, description="Explicit marker indicating suites are frozen."
    )
    entries: dict[str, SuiteLockEntry] = Field(default_factory=dict)
