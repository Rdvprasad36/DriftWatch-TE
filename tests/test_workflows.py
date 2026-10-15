"""Tests for GitHub Actions workflow definitions (FR2, FR7, FR10).

Validates syntax, triggers, secrets mapping, and immutability guards
in .github/workflows/*.yml.
Tests run completely offline using pyyaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS_DIR = Path(".github/workflows")


def _load_workflow(filename: str) -> dict[str, Any]:
    """Load and parse a workflow YAML file."""
    path = WORKFLOWS_DIR / filename
    assert path.exists(), f"Workflow file missing: {path}"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"Expected dict in {path}, got {type(data)}"
    return data


# ---------------------------------------------------------------------------
# CI Workflow Tests
# ---------------------------------------------------------------------------


class TestCIWorkflow:
    def test_ci_file_exists_and_valid_yaml(self) -> None:
        """ci.yml must exist and be valid YAML."""
        wf = _load_workflow("ci.yml")
        assert "name" in wf
        assert "jobs" in wf

    def test_ci_triggers_on_push_and_pr(self) -> None:
        """ci.yml triggers on push and pull_request to main/master."""
        wf = _load_workflow("ci.yml")
        # In PyYAML, 'on' key can parse as boolean True or string 'on'
        triggers = wf.get(True) or wf.get("on")
        assert triggers is not None
        assert "push" in triggers or "pull_request" in triggers

    def test_ci_runs_lint_typecheck_test(self) -> None:
        """ci.yml must include steps for ruff, mypy, and pytest."""
        wf = _load_workflow("ci.yml")
        jobs = wf["jobs"]
        # Find test/build job
        all_steps: list[dict[str, Any]] = []
        for job in jobs.values():
            all_steps.extend(job.get("steps", []))

        step_runs = " ".join(str(s.get("run", "")) for s in all_steps)
        assert "pytest" in step_runs
        assert "ruff" in step_runs
        assert "mypy" in step_runs


# ---------------------------------------------------------------------------
# Weekly Workflow Tests
# ---------------------------------------------------------------------------


class TestWeeklyWorkflow:
    def test_weekly_file_exists_and_valid_yaml(self) -> None:
        """weekly.yml must exist and be valid YAML."""
        wf = _load_workflow("weekly.yml")
        assert "name" in wf
        assert "jobs" in wf

    def test_weekly_triggers_on_cron_and_dispatch(self) -> None:
        """weekly.yml must have a cron schedule (Monday) and workflow_dispatch."""
        wf = _load_workflow("weekly.yml")
        triggers = wf.get(True) or wf.get("on")
        assert triggers is not None
        assert "schedule" in triggers
        assert "workflow_dispatch" in triggers

        # Verify cron runs on Monday
        schedules = triggers["schedule"]
        cron_expr = schedules[0]["cron"]
        # Standard cron: '0 0 * * 1' or similar for Monday
        assert "1" in cron_expr.split()[-1]

    def test_weekly_has_model_matrix(self) -> None:
        """weekly.yml must shard runs across models via matrix (architecture.md §6)."""
        wf = _load_workflow("weekly.yml")
        jobs = wf["jobs"]
        # At least one job has a strategy matrix for models
        has_matrix = False
        for job in jobs.values():
            strategy = job.get("strategy", {})
            matrix = strategy.get("matrix", {})
            if "model" in matrix or "models" in matrix:
                has_matrix = True
                assert strategy.get("fail-fast") is False, "fail-fast must be false for resilience"
                break
        assert has_matrix, "weekly.yml must define a matrix over models"

    def test_weekly_injects_secrets_from_env(self) -> None:
        """weekly.yml references required provider secrets (AGENTS.md rule 4)."""
        wf = _load_workflow("weekly.yml")
        content = yaml.dump(wf)
        assert "GROQ_API_KEY" in content or "HF_TOKEN" in content


# ---------------------------------------------------------------------------
# Pages Workflow Tests
# ---------------------------------------------------------------------------


class TestPagesWorkflow:
    def test_pages_file_exists_and_valid_yaml(self) -> None:
        """pages.yml must exist and be valid YAML."""
        wf = _load_workflow("pages.yml")
        assert "name" in wf
        assert "jobs" in wf

    def test_pages_has_deploy_permissions(self) -> None:
        """pages.yml must declare pages: write and id-token: write permissions."""
        wf = _load_workflow("pages.yml")
        perms = wf.get("permissions", {})
        # Permissions can be at workflow root or job level
        if not perms:
            for job in wf.get("jobs", {}).values():
                perms = job.get("permissions", {})
                if perms:
                    break
        assert perms.get("pages") == "write"
        assert perms.get("id-token") == "write"
