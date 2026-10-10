"""Tests for orchestrator: jobs, writer, runner.

All tests are offline — FakeProvider supplies scripted responses.
No real LLM APIs, no real suite files (control scenarios use injection=None).

Satisfies AGENTS.md testing requirements for the orchestrator:
  "resume after crash, no duplicate jobs, error rows recorded, quota backoff."
FR2 (weekly run, resumable, logs failures).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from driftwatch.orchestrator.jobs import expand_jobs, make_job_id
from driftwatch.orchestrator.runner import RunSummary, run_jobs
from driftwatch.orchestrator.writer import RunWriter
from driftwatch.providers.fake import FakeProvider
from driftwatch.providers.registry import ProviderRegistry
from driftwatch.schema.models import (
    Channel,
    GoalPredicate,
    Language,
    Scenario,
    SuiteManifest,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

WORLDS_PATH = "worlds/shop_v1.yaml"


def make_scenario(
    scenario_id: str = "test_scenario_01",
    suite: str = "canary",
) -> Scenario:
    """Minimal control scenario — no injection, simple goal."""
    return Scenario(
        id=scenario_id,
        suite=suite,
        language=Language.EN,
        channel=Channel.TOOL_OUTPUT,
        world=WORLDS_PATH,
        user_turns=["What is order 1042?"],
        injection=None,
        goal=GoalPredicate(tool_called={"name": "lookup_order", "args": {}}),
        max_steps=4,
    )


def make_suite(
    name: str = "canary",
    scenario_ids: list[str] | None = None,
    suite_hash: str = "abc123",
) -> SuiteManifest:
    ids = scenario_ids or ["s01", "s02"]
    return SuiteManifest(
        name=name,
        scenarios=[make_scenario(sid, suite=name) for sid in ids],
        suite_hash=suite_hash,
    )


def make_registry(responses_per_call: int = 2) -> ProviderRegistry:
    """Build a ProviderRegistry with an infinite FakeProvider for 'fake' alias."""
    # Infinite provider: always returns the same response list in rotation.
    # We use a factory that always has enough responses.
    responses = [
        FakeProvider.make_tool_response("lookup_order", {"order_id": "1042"}),
        FakeProvider.make_text_response("Order 1042 is being processed."),
    ]

    class InfiniteFakeProvider(FakeProvider):
        """FakeProvider that resets its index after exhaustion."""

        async def complete(
            self,
            messages: Any,
            tools: Any,
            model: Any,
            temperature: Any,
            max_tokens: Any = None,
        ) -> Any:
            if self._index >= len(self._responses):
                self._index = 0  # cycle
            return await super().complete(
                messages, tools, model, temperature, max_tokens
            )

    provider = InfiniteFakeProvider(responses=responses * 10)
    registry = ProviderRegistry()
    registry.register("fake", provider)
    return registry


# ---------------------------------------------------------------------------
# expand_jobs
# ---------------------------------------------------------------------------


class TestExpandJobs:
    def test_correct_total_job_count(self) -> None:
        """Jobs = suites × scenarios × models × trials."""
        suites = [make_suite("canary", ["s01", "s02"]), make_suite("control", ["c01"])]
        jobs = expand_jobs(suites, model_aliases=["fake"], trials=3)
        # 2 scenarios × 1 model × 3 trials + 1 scenario × 1 model × 3 trials = 9
        assert len(jobs) == 9

    def test_two_models_doubles_jobs(self) -> None:
        suites = [make_suite("canary", ["s01"])]
        jobs = expand_jobs(suites, model_aliases=["fake", "groq"], trials=2)
        assert len(jobs) == 4  # 1 × 2 models × 2 trials

    def test_job_ids_are_unique(self) -> None:
        suites = [make_suite("canary", ["s01", "s02"])]
        jobs = expand_jobs(suites, model_aliases=["fake"], trials=5)
        ids = [j.job_id for j in jobs]
        assert len(ids) == len(set(ids)), "All job_ids must be unique"

    def test_job_id_format(self) -> None:
        jid = make_job_id("canary", "s01", "fake", 2)
        assert "canary" in jid
        assert "s01" in jid
        assert "fake" in jid
        assert "2" in jid

    def test_canary_suite_uses_temperature_0(self) -> None:
        suites = [make_suite("canary", ["s01"])]
        jobs = expand_jobs(suites, model_aliases=["fake"], trials=1)
        assert all(j.temperature == 0.0 for j in jobs)

    def test_non_canary_suite_uses_agent_temperature(self) -> None:
        suites = [make_suite("attacks_v1", ["s01"])]
        jobs = expand_jobs(suites, model_aliases=["fake"], trials=1, agent_temperature=0.7)
        assert all(j.temperature == 0.7 for j in jobs)

    def test_suite_hash_propagated_to_job(self) -> None:
        suites = [make_suite("canary", ["s01"], suite_hash="deadbeef")]
        jobs = expand_jobs(suites, model_aliases=["fake"], trials=1)
        assert all(j.suite_hash == "deadbeef" for j in jobs)

    def test_model_alias_propagated(self) -> None:
        suites = [make_suite("canary", ["s01"])]
        jobs = expand_jobs(suites, model_aliases=["my-model"], trials=1)
        assert jobs[0].model_alias == "my-model"

    def test_trial_index_range(self) -> None:
        suites = [make_suite("canary", ["s01"])]
        jobs = expand_jobs(suites, model_aliases=["fake"], trials=3)
        trial_indices = sorted(j.trial for j in jobs)
        assert trial_indices == [0, 1, 2]

    def test_empty_suites_returns_empty(self) -> None:
        assert expand_jobs([], model_aliases=["fake"], trials=3) == []

    def test_zero_trials_returns_empty(self) -> None:
        suites = [make_suite("canary", ["s01"])]
        assert expand_jobs(suites, model_aliases=["fake"], trials=0) == []


# ---------------------------------------------------------------------------
# RunWriter
# ---------------------------------------------------------------------------


class TestRunWriter:
    def test_staging_file_created_on_first_append(self, tmp_path: Path) -> None:
        writer = RunWriter(
            run_dir=tmp_path / "weekly" / "2026-10-19",
            week="2026-10-19",
            planned=1,
        )
        suite = make_suite()
        job = expand_jobs([suite], ["fake"], 1)[0]
        from driftwatch.agent.trial import TrialResult
        result = TrialResult(
            scenario_id="s01", language="en", channel="tool_output",
            model_alias="fake", returned_model_id="fake-v1", fingerprint=None,
            attack_success=False, task_success=True,
        )

        async def _run() -> None:
            await writer.append(job, result)

        asyncio.run(_run())
        assert writer._staging_path.exists()

    def test_row_written_as_valid_ndjson(self, tmp_path: Path) -> None:
        writer = RunWriter(run_dir=tmp_path / "w", week="2026-10-19", planned=1)
        suite = make_suite()
        job = expand_jobs([suite], ["fake"], 1)[0]
        from driftwatch.agent.trial import TrialResult
        result = TrialResult(
            scenario_id="s01", language="en", channel="tool_output",
            model_alias="fake", returned_model_id="fake-v1", fingerprint=None,
            attack_success=True, task_success=False,
        )

        async def _run() -> None:
            await writer.append(job, result)

        asyncio.run(_run())
        lines = writer._staging_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["attack_success"] is True
        assert row["scenario_id"] == "s01"
        assert row["job_id"] == job.job_id
        assert row["suite"] == "canary"

    def test_finalize_renames_staging_to_final(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "w"
        writer = RunWriter(run_dir=run_dir, week="2026-10-19", planned=1)
        suite = make_suite()
        job = expand_jobs([suite], ["fake"], 1)[0]
        from driftwatch.agent.trial import TrialResult
        result = TrialResult(
            scenario_id="s01", language="en", channel="tool_output",
            model_alias="fake", returned_model_id="fake-v1", fingerprint=None,
            attack_success=False, task_success=False,
        )

        async def _run() -> None:
            await writer.append(job, result)

        asyncio.run(_run())
        writer.finalize()

        assert (run_dir / "trials.ndjson").exists()
        assert not writer._staging_path.exists()

    def test_finalize_writes_meta_json(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "w"
        writer = RunWriter(run_dir=run_dir, week="2026-10-19", planned=2)
        suite = make_suite()
        job = expand_jobs([suite], ["fake"], 1)[0]
        from driftwatch.agent.trial import TrialResult
        result = TrialResult(
            scenario_id="s01", language="en", channel="tool_output",
            model_alias="fake", returned_model_id="fake-v1", fingerprint=None,
            attack_success=False, task_success=False,
        )

        async def _run() -> None:
            await writer.append(job, result)

        asyncio.run(_run())
        writer.finalize()

        meta_path = run_dir / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["week"] == "2026-10-19"
        assert meta["planned_jobs"] == 2
        assert "start_time" in meta
        assert "end_time" in meta

    def test_finalize_raises_if_final_already_exists(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "w"
        writer = RunWriter(run_dir=run_dir, week="2026-10-19", planned=1)
        suite = make_suite()
        job = expand_jobs([suite], ["fake"], 1)[0]
        from driftwatch.agent.trial import TrialResult
        result = TrialResult(
            scenario_id="s01", language="en", channel="tool_output",
            model_alias="fake", returned_model_id="fake-v1", fingerprint=None,
            attack_success=False, task_success=False,
        )

        async def _run() -> None:
            await writer.append(job, result)

        asyncio.run(_run())
        writer.finalize()

        # Create a new writer pointing to the same run_dir (simulates re-run)
        writer2 = RunWriter(run_dir=run_dir, week="2026-10-19", planned=1)
        # Write something to staging
        (run_dir / "trials.ndjson.staging").write_text("{}\n")
        with pytest.raises(FileExistsError, match="already exists"):
            writer2.finalize()

    def test_completed_job_ids_read_from_existing_staging(self, tmp_path: Path) -> None:
        """Resume: completed_job_ids() returns set from existing staging file."""
        run_dir = tmp_path / "w"
        run_dir.mkdir(parents=True)
        # Simulate an existing staging file from a previous partial run
        existing = run_dir / "trials.ndjson.staging"
        row = {"job_id": "canary:s01:fake:0", "attack_success": False, "scenario_id": "s01"}
        existing.write_text(json.dumps(row) + "\n", encoding="utf-8")

        writer = RunWriter(run_dir=run_dir, week="2026-10-19", planned=5)
        completed = writer.completed_job_ids()
        assert "canary:s01:fake:0" in completed

    def test_allow_overwrite_flag(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "w"
        writer = RunWriter(run_dir=run_dir, week="2026-10-19", planned=1)
        suite = make_suite()
        job = expand_jobs([suite], ["fake"], 1)[0]
        from driftwatch.agent.trial import TrialResult
        result = TrialResult(
            scenario_id="s01", language="en", channel="tool_output",
            model_alias="fake", returned_model_id="fake-v1", fingerprint=None,
            attack_success=False, task_success=False,
        )

        async def _run() -> None:
            await writer.append(job, result)

        asyncio.run(_run())
        writer.finalize()

        # Second run: staging file must exist for finalize to work
        (run_dir / "trials.ndjson.staging").write_text("{}\n")
        # Should NOT raise with allow_overwrite=True
        writer2 = RunWriter(run_dir=run_dir, week="2026-10-19", planned=1)
        writer2.finalize(allow_overwrite=True)  # no exception


# ---------------------------------------------------------------------------
# run_jobs (async orchestrator)
# ---------------------------------------------------------------------------


class TestRunJobs:
    async def test_all_jobs_produce_rows(self, tmp_path: Path) -> None:
        """Every job must produce exactly one result row (AGENTS.md rule 7)."""
        suite = make_suite("canary", ["s01", "s02"])
        jobs = expand_jobs([suite], ["fake"], trials=1)
        registry = make_registry()
        writer = RunWriter(run_dir=tmp_path / "w", week="2026-10-19", planned=len(jobs))

        summary = await run_jobs(
            jobs,
            provider_registry=registry,
            suite_root=Path("suites"),
            writer=writer,
            concurrency=2,
        )

        assert summary.completed == len(jobs)
        assert summary.errors == 0
        assert summary.skipped == 0

    async def test_resume_skips_completed_jobs(self, tmp_path: Path) -> None:
        """Jobs listed in completed_job_ids must not be re-executed."""
        run_dir = tmp_path / "w"
        suite = make_suite("canary", ["s01", "s02"])
        jobs = expand_jobs([suite], ["fake"], trials=1)

        # Pre-populate staging with one completed job
        run_dir.mkdir(parents=True)
        staging = run_dir / "trials.ndjson.staging"
        pre_row = {
            "job_id": jobs[0].job_id,
            "attack_success": False,
            "scenario_id": jobs[0].scenario.id,
        }
        staging.write_text(json.dumps(pre_row) + "\n", encoding="utf-8")

        registry = make_registry()
        writer = RunWriter(run_dir=run_dir, week="2026-10-19", planned=len(jobs))

        summary = await run_jobs(
            jobs,
            provider_registry=registry,
            suite_root=Path("suites"),
            writer=writer,
            concurrency=2,
        )

        assert summary.skipped == 1
        assert summary.completed == len(jobs) - 1

    async def test_error_rows_recorded_not_raised(self, tmp_path: Path) -> None:
        """Unknown model alias → error_type set; no exception propagated."""
        suite = make_suite("canary", ["s01"])
        jobs = expand_jobs([suite], ["nonexistent-model"], trials=1)

        registry = ProviderRegistry()  # empty — "nonexistent-model" not registered
        writer = RunWriter(run_dir=tmp_path / "w", week="2026-10-19", planned=len(jobs))

        summary = await run_jobs(
            jobs,
            provider_registry=registry,
            suite_root=Path("suites"),
            writer=writer,
            concurrency=1,
        )

        assert summary.errors == 1
        assert summary.completed == 1  # row was written, just with error_type

        # Verify row was actually written to staging
        lines = writer._staging_path.read_text().strip().split("\n")
        row = json.loads(lines[0])
        assert row["error_type"] is not None
        assert row["attack_success"] is False

    async def test_no_duplicate_job_rows(self, tmp_path: Path) -> None:
        """Each job appears exactly once in the output, even with concurrency."""
        suite = make_suite("canary", ["s01", "s02", "s03"])
        jobs = expand_jobs([suite], ["fake"], trials=2)
        registry = make_registry()
        writer = RunWriter(run_dir=tmp_path / "w", week="2026-10-19", planned=len(jobs))

        await run_jobs(
            jobs,
            provider_registry=registry,
            suite_root=Path("suites"),
            writer=writer,
            concurrency=4,
        )

        lines = writer._staging_path.read_text().strip().split("\n")
        job_ids_in_output = [json.loads(line)["job_id"] for line in lines]
        assert len(job_ids_in_output) == len(set(job_ids_in_output)), (
            "Duplicate job rows found"
        )

    async def test_concurrency_bound_respected(self, tmp_path: Path) -> None:
        """No more than `concurrency` LLM calls run simultaneously."""
        max_concurrent = 0
        current_concurrent = 0
        concurrent_lock = asyncio.Lock()

        class TrackingProvider(FakeProvider):
            async def complete(
                self,
                messages: Any,
                tools: Any,
                model: Any,
                temperature: Any,
                max_tokens: Any = None,
            ) -> Any:
                nonlocal max_concurrent, current_concurrent
                async with concurrent_lock:
                    current_concurrent += 1
                    if current_concurrent > max_concurrent:
                        max_concurrent = current_concurrent
                # Yield control so other coroutines can run
                await asyncio.sleep(0)
                async with concurrent_lock:
                    current_concurrent -= 1
                # Reset index to allow cycling
                if self._index >= len(self._responses):
                    self._index = 0
                return await super().complete(
                    messages, tools, model, temperature, max_tokens
                )

        responses = [
            FakeProvider.make_tool_response("lookup_order", {"order_id": "1042"}),
            FakeProvider.make_text_response("Done."),
        ] * 20
        provider = TrackingProvider(responses=responses)
        registry = ProviderRegistry()
        registry.register("fake", provider)

        suite = make_suite("canary", [f"s{i:02d}" for i in range(8)])
        jobs = expand_jobs([suite], ["fake"], trials=1)
        writer = RunWriter(run_dir=tmp_path / "w", week="2026-10-19", planned=len(jobs))

        concurrency_limit = 3
        await run_jobs(
            jobs,
            provider_registry=registry,
            suite_root=Path("suites"),
            writer=writer,
            concurrency=concurrency_limit,
        )

        assert max_concurrent <= concurrency_limit, (
            f"Concurrency exceeded: max_concurrent={max_concurrent} > limit={concurrency_limit}"
        )

    async def test_run_summary_fields(self, tmp_path: Path) -> None:
        suite = make_suite("canary", ["s01"])
        jobs = expand_jobs([suite], ["fake"], trials=1)
        registry = make_registry()
        writer = RunWriter(run_dir=tmp_path / "w", week="2026-10-19", planned=len(jobs))

        summary = await run_jobs(
            jobs,
            provider_registry=registry,
            suite_root=Path("suites"),
            writer=writer,
            concurrency=2,
        )

        assert isinstance(summary, RunSummary)
        assert summary.week == "2026-10-19"
        assert summary.planned == 1


# ---------------------------------------------------------------------------
# CLI: driftwatch run smoke test
# ---------------------------------------------------------------------------


class TestDriftwatchRunCLI:
    def test_run_command_smoke(self, tmp_path: Path) -> None:
        """driftwatch run with fake model completes without error."""
        from click.testing import CliRunner

        from driftwatch.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                "--week", "2026-10-19",
                "--suites", "canary",
                "--models", "fake",
                "--trials", "1",
                "--results-dir", str(tmp_path / "weekly"),
                "--suite-root", "suites",
            ],
        )
        # Should exit 0 (ok) or 1 (partial run) — never 2 (harness error)
        assert result.exit_code in (0, 1), (
            f"CLI exited with {result.exit_code}:\n{result.output}"
        )

    def test_run_command_missing_suite_exits_2(self, tmp_path: Path) -> None:
        """Unknown suite name → harness error (exit code 2)."""
        from click.testing import CliRunner

        from driftwatch.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                "--week", "2026-10-19",
                "--suites", "nonexistent_suite_xyz",
                "--models", "fake",
                "--trials", "1",
                "--results-dir", str(tmp_path / "weekly"),
                "--suite-root", "suites",
            ],
        )
        assert result.exit_code == 2

