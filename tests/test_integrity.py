"""Tests for suite freeze and verify operations.

Tests the integrity module: freezing hashes, verifying against lock file,
detecting modifications to frozen suites (FR1).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from driftwatch.schema.models import SuiteLockEntry, SuiteLockFile
from driftwatch.suites.integrity import (
    LOCK_FILENAME,
    VerifyResult,
    freeze_suites,
    read_lock_file,
    verify_suites,
    write_lock_file,
)
from driftwatch.suites.loader import load_suite


class TestFreezeSuites:
    def test_freeze_creates_lock_file(self, tmp_suites_dir: Path) -> None:
        lock = freeze_suites(tmp_suites_dir)
        lock_path = tmp_suites_dir / LOCK_FILENAME
        assert lock_path.exists()
        assert "attacks_v1" in lock.entries

    def test_freeze_is_idempotent(self, tmp_suites_dir: Path) -> None:
        lock1 = freeze_suites(tmp_suites_dir)
        lock2 = freeze_suites(tmp_suites_dir)
        assert lock1.entries["attacks_v1"].suite_hash == lock2.entries["attacks_v1"].suite_hash

    def test_freeze_detects_tampering(self, tmp_suites_dir: Path) -> None:
        """Once frozen, modifying suite content must raise an error (FR1)."""
        freeze_suites(tmp_suites_dir)

        # Tamper with a file
        payload = tmp_suites_dir / "attacks_v1" / "payloads" / "refund_override_en_01.txt"
        payload.write_text("TAMPERED", encoding="utf-8")

        with pytest.raises(ValueError, match="hash changed"):
            freeze_suites(tmp_suites_dir)

    def test_freeze_adds_new_suites(self, tmp_suites_multi: Path) -> None:
        # First freeze with only one suite
        lock1 = freeze_suites(tmp_suites_multi)
        assert len(lock1.entries) == 2  # attacks_v1 and control

    def test_lock_file_has_timestamps(self, tmp_suites_dir: Path) -> None:
        lock = freeze_suites(tmp_suites_dir)
        entry = lock.entries["attacks_v1"]
        assert entry.locked_at  # non-empty ISO timestamp


class TestVerifySuites:
    def test_verify_passes_on_unchanged(self, tmp_suites_dir: Path) -> None:
        freeze_suites(tmp_suites_dir)
        result = verify_suites(tmp_suites_dir)
        assert result.passed
        assert "attacks_v1" in result.ok

    def test_verify_fails_on_tampered_content(self, tmp_suites_dir: Path) -> None:
        freeze_suites(tmp_suites_dir)

        # Tamper
        scenario = tmp_suites_dir / "attacks_v1" / "scenario_01.yaml"
        content = scenario.read_text(encoding="utf-8")
        scenario.write_text(content + "\n# tampered", encoding="utf-8")

        result = verify_suites(tmp_suites_dir)
        assert not result.passed
        assert len(result.mismatched) == 1
        assert result.mismatched[0][0] == "attacks_v1"

    def test_verify_fails_on_deleted_suite(self, tmp_suites_dir: Path) -> None:
        freeze_suites(tmp_suites_dir)

        # Delete the suite directory
        import shutil

        shutil.rmtree(tmp_suites_dir / "attacks_v1")

        result = verify_suites(tmp_suites_dir)
        assert not result.passed
        assert "attacks_v1" in result.missing_on_disk

    def test_verify_no_lock_raises(self, tmp_suites_dir: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No lock file"):
            verify_suites(tmp_suites_dir)

    def test_verify_reports_unlocked_suites(self, tmp_suites_multi: Path) -> None:
        # Freeze only attacks_v1 by manually building a partial lock
        manifest = load_suite(tmp_suites_multi / "attacks_v1")
        lock = SuiteLockFile(
            entries={
                "attacks_v1": SuiteLockEntry(
                    suite_name="attacks_v1",
                    suite_hash=manifest.suite_hash,
                    locked_at=datetime.now(UTC).isoformat(),
                )
            }
        )
        write_lock_file(tmp_suites_multi, lock)

        result = verify_suites(tmp_suites_multi)
        assert result.passed  # locked suites are fine
        assert "control" in result.unlocked


class TestReadLockFile:
    def test_read_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        lock = read_lock_file(tmp_path)
        assert len(lock.entries) == 0

    def test_read_written_lock(self, tmp_suites_dir: Path) -> None:
        freeze_suites(tmp_suites_dir)
        lock = read_lock_file(tmp_suites_dir)
        assert "attacks_v1" in lock.entries

    def test_lock_file_is_valid_json(self, tmp_suites_dir: Path) -> None:
        freeze_suites(tmp_suites_dir)
        lock_path = tmp_suites_dir / LOCK_FILENAME
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert "entries" in data


class TestVerifyResult:
    def test_passed_when_all_ok(self) -> None:
        r = VerifyResult()
        r.ok.append("suite_a")
        assert r.passed

    def test_failed_on_mismatch(self) -> None:
        r = VerifyResult()
        r.mismatched.append(("suite_a", "hash1", "hash2"))
        assert not r.passed

    def test_failed_on_missing(self) -> None:
        r = VerifyResult()
        r.missing_on_disk.append("suite_a")
        assert not r.passed
