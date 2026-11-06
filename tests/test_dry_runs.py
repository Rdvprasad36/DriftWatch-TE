"""Tests for Step 10: 2 dry runs and suite freeze (FR1, FR5).

Validates:
1. End-to-end execution of 2 dry runs (Dry Run 1, Dry Run 2) across weeks.
2. Stability of canary hashes and metric outputs across dry runs under control conditions.
3. Suite freeze operation: generates suites/SUITE_LOCK.json with SHA-256 hashes.
4. Suite verification: passes when clean, detects tampering/mismatch with exit code 3.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from driftwatch.canary.hashing import compare_canary_runs
from driftwatch.cli.main import cli
from driftwatch.suites.integrity import freeze_suites, verify_suites


class TestDryRunsPipeline:
    def test_two_dry_runs_produce_valid_bundles_and_stable_canaries(
        self, tmp_path: Path
    ) -> None:
        """Simulate two consecutive weekly dry runs (design.md §4.7 / prd.md §9).

        Dry Run 1 (week 2026-10-05) and Dry Run 2 (week 2026-10-12)
        must both complete cleanly and demonstrate zero canary drift.
        """
        runner = CliRunner()
        results_dir = tmp_path / "weekly"
        summary_dir = tmp_path / "results" / "summary"

        weeks = ["2026-10-05", "2026-10-12"]

        for week in weeks:
            # 1. Run canary prompts
            canary_res = runner.invoke(
                cli,
                [
                    "canary",
                    "--week", week,
                    "--models", "fake",
                    "--suite-dir", "suites/canary",
                    "--results-dir", str(results_dir),
                ],
            )
            assert canary_res.exit_code == 0, f"Canary run failed: {canary_res.output}"

            # 2. Run scenario trials
            run_res = runner.invoke(
                cli,
                [
                    "run",
                    "--week", week,
                    "--suites", "canary",
                    "--models", "fake",
                    "--trials", "2",
                    "--results-dir", str(results_dir),
                    "--suite-root", "suites",
                ],
            )
            assert run_res.exit_code == 0, f"Trial run failed: {run_res.output}"

            # 3. Summarize run
            summary_res = runner.invoke(
                cli,
                [
                    "summarize",
                    "--week", week,
                    "--results-dir", str(results_dir),
                    "--output-dir", str(summary_dir),
                ],
            )
            assert summary_res.exit_code == 0, f"Summarize failed: {summary_res.output}"

            # Verify bundle contents
            week_dir = results_dir / week
            assert (week_dir / "canary.json").exists()
            assert (week_dir / "trials.parquet").exists()
            assert (week_dir / "meta.json").exists()
            assert (summary_dir / "weekly" / f"{week}.json").exists()
            assert (summary_dir / "index.json").exists()

        # Compare canary hashes between Dry Run 1 and Dry Run 2
        canary1_data = json.loads((results_dir / weeks[0] / "canary.json").read_text())
        canary2_data = json.loads((results_dir / weeks[1] / "canary.json").read_text())

        drift_report = compare_canary_runs(
            canary1_data["results"], canary2_data["results"]
        )
        assert (
            drift_report["changed_count"] == 0
        ), "No drift expected under controlled FakeProvider"
        assert drift_report["drift_detected"] is False


class TestSuiteFreezeAndVerify:
    def test_freeze_creates_suite_lock_file(self, tmp_path: Path) -> None:
        """freeze_suites creates SUITE_LOCK.json containing SHA-256 hashes."""
        suite_dir = tmp_path / "suites"
        canary_dir = suite_dir / "canary"
        canary_dir.mkdir(parents=True)
        (canary_dir / "test.yaml").write_text(
            "- id: s01\n  suite: canary\n  language: en\n  channel: tool_output\n"
            "  world: worlds/shop_v1.yaml\n  user_turns: ['Hi']\n  goal: {no_call: {tool: x}}\n",
            encoding="utf-8",
        )

        lock = freeze_suites(suite_dir)
        lock_file = suite_dir / "SUITE_LOCK.json"

        assert lock_file.exists()
        assert "canary" in lock.entries
        assert len(lock.entries["canary"].suite_hash) == 64

    def test_verify_passes_on_unmodified_suites(self, tmp_path: Path) -> None:
        """verify_suites succeeds when files match locked hashes."""
        suite_dir = tmp_path / "suites"
        canary_dir = suite_dir / "canary"
        canary_dir.mkdir(parents=True)
        (canary_dir / "test.yaml").write_text(
            "- id: s01\n  suite: canary\n  language: en\n  channel: tool_output\n"
            "  world: worlds/shop_v1.yaml\n  user_turns: ['Hi']\n  goal: {no_call: {tool: x}}\n",
            encoding="utf-8",
        )

        freeze_suites(suite_dir)
        result = verify_suites(suite_dir)

        assert result.passed is True
        assert "canary" in result.ok
        assert len(result.mismatched) == 0

    def test_verify_fails_on_tampered_suite(self, tmp_path: Path) -> None:
        """verify_suites flags hash mismatch if suite content was modified (FR1)."""
        suite_dir = tmp_path / "suites"
        canary_dir = suite_dir / "canary"
        canary_dir.mkdir(parents=True)
        yaml_file = canary_dir / "test.yaml"
        yaml_file.write_text(
            "- id: s01\n  suite: canary\n  language: en\n  channel: tool_output\n"
            "  world: worlds/shop_v1.yaml\n  user_turns: ['Hi']\n  goal: {no_call: {tool: x}}\n",
            encoding="utf-8",
        )

        freeze_suites(suite_dir)

        # Tamper with suite file
        yaml_file.write_text(
            "- id: s01\n"
            "  suite: canary\n"
            "  language: en\n"
            "  channel: tool_output\n"
            "  world: worlds/shop_v1.yaml\n"
            "  user_turns: ['TAMPERED']\n"
            "  goal: {no_call: {tool: x}}\n",
            encoding="utf-8",
        )

        result = verify_suites(suite_dir)
        assert result.passed is False
        assert len(result.mismatched) == 1
        assert result.mismatched[0][0] == "canary"
