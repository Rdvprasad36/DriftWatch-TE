"""Tests for the CLI commands (freeze, verify).

Uses Click's test runner for offline testing.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from driftwatch.cli.main import EXIT_HASH_MISMATCH, EXIT_OK, cli


class TestFreezeCommand:
    def test_freeze_succeeds(self, tmp_suites_dir: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])
        assert result.exit_code == EXIT_OK
        assert "Locked" in result.output

    def test_freeze_idempotent(self, tmp_suites_dir: Path) -> None:
        runner = CliRunner()
        runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])
        result = runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])
        assert result.exit_code == EXIT_OK

    def test_freeze_detects_tampering(self, tmp_suites_dir: Path) -> None:
        runner = CliRunner()
        runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])

        # Tamper
        payload = tmp_suites_dir / "attacks_v1" / "payloads" / "refund_override_en_01.txt"
        payload.write_text("TAMPERED", encoding="utf-8")

        result = runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])
        assert result.exit_code == EXIT_HASH_MISMATCH


class TestVerifyCommand:
    def test_verify_passes(self, tmp_suites_dir: Path) -> None:
        runner = CliRunner()
        runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])
        result = runner.invoke(cli, ["verify", "--suites-dir", str(tmp_suites_dir)])
        assert result.exit_code == EXIT_OK
        assert "verified" in result.output.lower()

    def test_verify_fails_on_tamper(self, tmp_suites_dir: Path) -> None:
        runner = CliRunner()
        runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])

        # Tamper
        scenario = tmp_suites_dir / "attacks_v1" / "scenario_01.yaml"
        content = scenario.read_text(encoding="utf-8")
        scenario.write_text(content + "\n# evil edit", encoding="utf-8")

        result = runner.invoke(cli, ["verify", "--suites-dir", str(tmp_suites_dir)])
        assert result.exit_code == EXIT_HASH_MISMATCH
        assert "mismatch" in result.output.lower()

    def test_verify_unfrozen_skips_enforcement_and_exits_zero(self, tmp_suites_dir: Path) -> None:
        """When SUITE_LOCK.json contains 'frozen': false, verify skips enforcement and exits 0."""
        import json

        runner = CliRunner()
        runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])

        # Mark lock explicitly unfrozen
        lock_file = tmp_suites_dir / "SUITE_LOCK.json"
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        data["frozen"] = False
        lock_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Tamper a scenario file to create an intentional hash mismatch
        scenario = tmp_suites_dir / "attacks_v1" / "scenario_01.yaml"
        scenario.write_text(
            scenario.read_text(encoding="utf-8") + "\n# unfrozen edit", encoding="utf-8"
        )

        result = runner.invoke(cli, ["verify", "--suites-dir", str(tmp_suites_dir)])
        assert result.exit_code == EXIT_OK
        assert "suites not frozen, hash enforcement skipped" in result.output

    def test_verify_frozen_strictly_enforces_hashes(self, tmp_suites_dir: Path) -> None:
        """When SUITE_LOCK.json contains 'frozen': true, verify fails on any hash mismatch."""
        import json

        runner = CliRunner()
        runner.invoke(cli, ["freeze", "--suites-dir", str(tmp_suites_dir)])

        # Ensure lock explicitly marked frozen: true
        lock_file = tmp_suites_dir / "SUITE_LOCK.json"
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        data["frozen"] = True
        lock_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Tamper a scenario file
        scenario = tmp_suites_dir / "attacks_v1" / "scenario_01.yaml"
        scenario.write_text(
            scenario.read_text(encoding="utf-8") + "\n# frozen edit", encoding="utf-8"
        )

        result = runner.invoke(cli, ["verify", "--suites-dir", str(tmp_suites_dir)])
        assert result.exit_code == EXIT_HASH_MISMATCH
        assert "mismatch" in result.output.lower()
