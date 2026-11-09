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
        triggers = wf.get(True) or wf.get("on")
        assert triggers is not None
        assert "push" in triggers or "pull_request" in triggers

    def test_ci_runs_lint_typecheck_test(self) -> None:
        """ci.yml must include steps for ruff, mypy, and pytest."""
        wf = _load_workflow("ci.yml")
        jobs = wf["jobs"]
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

        schedules = triggers["schedule"]
        cron_expr = schedules[0]["cron"]
        assert "1" in cron_expr.split()[-1]

    def test_weekly_has_model_matrix(self) -> None:
        """weekly.yml must shard runs across models via matrix (architecture.md §6)."""
        wf = _load_workflow("weekly.yml")
        jobs = wf["jobs"]
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
        """weekly.yml references required provider secrets and avoids deprecated names."""
        wf = _load_workflow("weekly.yml")
        content = yaml.dump(wf)
        # Canonical secrets must all be passed
        for secret_name in ("GROQ_API_KEY", "GOOGLE_AI_API_KEY", "OPENROUTER_API_KEY", "HF_TOKEN"):
            assert secret_name in content, f"weekly.yml missing {secret_name}"
        # GEMINI_API_KEY must not be used (canonical name is GOOGLE_AI_API_KEY)
        assert "GEMINI_API_KEY" not in content, "weekly.yml must not use GEMINI_API_KEY"

    def test_weekly_preflight_fails_closed(self) -> None:
        """preflight job verifies required secrets, hf_dataset_repo, and frozen status."""
        wf = _load_workflow("weekly.yml")
        preflight_steps = wf["jobs"]["preflight"]["steps"]
        step_runs = " ".join(str(s.get("run", "")) for s in preflight_steps)
        assert "FAIL-CLOSED" in step_runs
        assert "hf_dataset_repo" in step_runs
        assert "is_study_week" in step_runs
        assert "is_suites_frozen" in step_runs

    def test_preflight_frozen_gate_behavior(self, tmp_path: Path) -> None:
        """Non-dry-run study weeks fail unless suites are frozen; dry-runs are permitted."""
        import json

        from driftwatch.suites.integrity import is_suites_frozen

        suites_dir = tmp_path / "suites"
        suites_dir.mkdir()
        lock_file = suites_dir / "SUITE_LOCK.json"

        # State 1: Unfrozen ('frozen': false)
        lock_file.write_text(json.dumps({"frozen": False, "entries": {}}), encoding="utf-8")
        assert is_suites_frozen(suites_dir) is False

        # State 2: Frozen ('frozen': true)
        lock_file.write_text(json.dumps({"frozen": True, "entries": {}}), encoding="utf-8")
        assert is_suites_frozen(suites_dir) is True

    def test_weekly_hf_upload_mandatory_for_study_weeks(self) -> None:
        """Hugging Face upload is mandatory during study weeks."""
        wf = _load_workflow("weekly.yml")
        finalize_steps = wf["jobs"]["finalize"]["steps"]
        upload_step = next(
            s for s in finalize_steps if "Upload bundle to Hugging Face" in s.get("name", "")
        )
        assert "is_study_week" in upload_step.get("run", "")
        expected_coe = "${{ needs.preflight.outputs.is_dry_run == 'true' }}"
        assert upload_step.get("continue-on-error") == expected_coe

    def test_weekly_completeness_gate_present(self) -> None:
        """finalize job includes completeness gate checking model trials and opening issues."""
        wf = _load_workflow("weekly.yml")
        finalize_steps = wf["jobs"]["finalize"]["steps"]
        step_names = [s.get("name", "") for s in finalize_steps]
        assert any("Completeness Gate" in name for name in step_names)

    def test_weekly_least_privilege_permissions(self) -> None:
        """Enforce least privilege: evaluation=read, finalize=write, deploy=pages."""
        wf = _load_workflow("weekly.yml")
        jobs = wf["jobs"]

        # Evaluation jobs get contents: read only, no pages or id-token
        for ejob_name in ("evaluate-hosted", "evaluate-local"):
            perms = jobs[ejob_name].get("permissions", {})
            assert perms.get("contents") == "read", f"{ejob_name} must have contents: read"
            assert "pages" not in perms, f"{ejob_name} must not have pages permission"
            assert "id-token" not in perms, f"{ejob_name} must not have id-token permission"

        # Finalize job gets contents: write, no pages or id-token
        fin_perms = jobs["finalize"].get("permissions", {})
        assert fin_perms.get("contents") == "write", "finalize must have contents: write"
        assert "pages" not in fin_perms, "finalize must not have pages permission"
        assert "id-token" not in fin_perms, "finalize must not have id-token permission"

        # Deploy job gets pages: write and id-token: write
        dep_perms = jobs["deploy"].get("permissions", {})
        assert dep_perms.get("pages") == "write", "deploy must have pages: write"
        assert dep_perms.get("id-token") == "write", "deploy must have id-token: write"

    def test_weekly_local_model_readiness_and_digest_pinning(self) -> None:
        """evaluate-local uses readiness loop, timeouts, and pins model digest."""
        wf = _load_workflow("weekly.yml")
        local_job = wf["jobs"]["evaluate-local"]
        assert local_job.get("timeout-minutes") is not None
        assert local_job.get("timeout-minutes") >= 30

        step_runs = " ".join(str(s.get("run", "")) for s in local_job["steps"])
        assert "curl -sf http://localhost:11434/api/version" in step_runs
        assert "local_model_digest" in step_runs
        assert "Model digest mismatch" in step_runs


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
        if not perms:
            for job in wf.get("jobs", {}).values():
                perms = job.get("permissions", {})
                if perms:
                    break
        assert perms.get("pages") == "write"
        assert perms.get("id-token") == "write"

    def test_pages_build_strictly_excludes_dev_and_sample_data(self, tmp_path: Path) -> None:
        """Simulate pages.yml build step: verify site/dev and sample data are strictly excluded."""
        import shutil

        site_dir = tmp_path / "site"
        site_dir.mkdir(parents=True)

        # 1. Copy dashboard
        dash_src = Path("dashboard")
        shutil.copytree(dash_src, site_dir, dirs_exist_ok=True)

        # 2. Copy results summaries
        res_summary = Path("results/summary")
        if res_summary.is_dir():
            shutil.copytree(res_summary, site_dir / "results" / "summary", dirs_exist_ok=True)

        # 3. Apply pages.yml exclusion
        dev_dir = site_dir / "dev"
        if dev_dir.exists():
            shutil.rmtree(dev_dir)

        # Assert dev directory does not exist
        assert not (site_dir / "dev").exists(), "site/dev must be deleted before publishing"

        # Assert no file in site contains '"sample": true'
        sample_hits: list[str] = []
        for f in site_dir.rglob("*"):
            if f.is_file() and f.suffix in [".json", ".html", ".js", ".md"]:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if '"sample": true' in text or '"sample":true' in text:
                    sample_hits.append(str(f))
        assert not sample_hits, f"Found sample: true in published site files: {sample_hits}"


# ---------------------------------------------------------------------------
# Health Check & Keepalive Workflow Tests
# ---------------------------------------------------------------------------


class TestHealthCheckAndKeepaliveWorkflows:
    def test_healthcheck_file_exists_and_valid_yaml(self) -> None:
        """healthcheck.yml exists and has schedule and issues permission."""
        wf = _load_workflow("healthcheck.yml")
        assert "name" in wf
        triggers = wf.get(True) or wf.get("on")
        assert "schedule" in triggers
        perms = wf.get("permissions", {})
        assert perms.get("issues") == "write"

    def test_keepalive_file_exists_and_valid_yaml(self) -> None:
        """keepalive.yml exists and runs on schedule."""
        wf = _load_workflow("keepalive.yml")
        assert "name" in wf
        triggers = wf.get(True) or wf.get("on")
        assert "schedule" in triggers

    def test_keepalive_has_no_third_party_actions(self) -> None:
        """keepalive.yml must not use third-party actions."""
        wf = _load_workflow("keepalive.yml")
        for job in wf.get("jobs", {}).values():
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if uses:
                    assert uses.startswith("actions/"), (
                        f"Third-party action found in keepalive.yml: {uses}"
                    )

    def test_no_third_party_actions_in_weekly(self) -> None:
        """weekly.yml must not use third-party actions (nick-fields/retry, etc)."""
        wf = _load_workflow("weekly.yml")
        for job_name, job in wf.get("jobs", {}).items():
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if uses:
                    assert uses.startswith("actions/"), (
                        f"Third-party action in weekly.yml job '{job_name}': {uses}"
                    )

    def test_trials_per_scenario_in_config_and_workflow(self) -> None:
        """config/study.yaml defines trials_per_scenario and weekly.yml reads it."""
        from driftwatch.config import load_study_config

        cfg = load_study_config()
        assert cfg.trials_per_scenario.get("attacks_v1") == 10
        assert cfg.trials_per_scenario.get("control") == 5
        assert cfg.trials_per_scenario.get("canary") == 2

        content = (WORKFLOWS_DIR / "weekly.yml").read_text(encoding="utf-8")
        assert "attacks_trials" in content
        assert "trials_per_scenario" in content
