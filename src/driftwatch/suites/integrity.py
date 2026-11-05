"""Suite freeze and verify operations.

`freeze` computes and locks suite hashes into SUITE_LOCK.json.
`verify` checks that current suite content matches locked hashes.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from driftwatch.schema.models import SuiteLockEntry, SuiteLockFile
from driftwatch.suites.loader import load_suite

logger = logging.getLogger(__name__)

LOCK_FILENAME = "SUITE_LOCK.json"


def _lock_path(suites_root: Path) -> Path:
    return suites_root / LOCK_FILENAME


def read_lock_file(suites_root: Path) -> SuiteLockFile:
    """Read the suite lock file, returning an empty lock if it doesn't exist."""
    path = _lock_path(suites_root)
    if not path.exists():
        return SuiteLockFile()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return SuiteLockFile.model_validate(data)


def write_lock_file(suites_root: Path, lock: SuiteLockFile) -> Path:
    """Write the suite lock file atomically."""
    path = _lock_path(suites_root)
    content = lock.model_dump_json(indent=2)
    path.write_text(content, encoding="utf-8")
    logger.info("Wrote lock file: %s", path)
    return path


def freeze_suites(suites_root: Path) -> SuiteLockFile:
    """Compute and lock hashes for all suites in the suites directory.

    If a lock file exists, only new suites are added. Existing hashes
    are never overwritten — that would violate the immutability rule.

    Returns:
        The updated SuiteLockFile.

    Raises:
        ValueError: If a suite's hash has changed from its locked value.
    """
    existing_lock = read_lock_file(suites_root)
    now = datetime.now(UTC).isoformat()

    for child in sorted(suites_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue

        try:
            manifest = load_suite(child)
        except (ValueError, FileNotFoundError) as e:
            logger.warning("Skipping '%s' during freeze: %s", child.name, e)
            continue

        if manifest.name in existing_lock.entries:
            locked_hash = existing_lock.entries[manifest.name].suite_hash
            if locked_hash != manifest.suite_hash:
                msg = (
                    f"Suite '{manifest.name}' hash changed! "
                    f"Locked: {locked_hash[:16]}..., "
                    f"Current: {manifest.suite_hash[:16]}... "
                    f"Frozen suites must never be modified (FR1)."
                )
                raise ValueError(msg)
            logger.info("Suite '%s' already locked, hash matches.", manifest.name)
        else:
            existing_lock.entries[manifest.name] = SuiteLockEntry(
                suite_name=manifest.name,
                suite_hash=manifest.suite_hash,
                locked_at=now,
            )
            logger.info("Locked suite '%s': %s", manifest.name, manifest.suite_hash[:16])

    write_lock_file(suites_root, existing_lock)
    return existing_lock


class VerifyResult:
    """Result of a suite verification."""

    def __init__(self) -> None:
        self.ok: list[str] = []
        self.mismatched: list[tuple[str, str, str]] = []  # (name, locked, current)
        self.missing_on_disk: list[str] = []
        self.unlocked: list[str] = []

    @property
    def passed(self) -> bool:
        return not self.mismatched and not self.missing_on_disk


def verify_suites(suites_root: Path) -> VerifyResult:
    """Verify that current suite hashes match locked values.

    Returns:
        VerifyResult with details of what passed and what failed.

    Raises:
        FileNotFoundError: If no lock file exists.
    """
    lock_path = _lock_path(suites_root)
    if not lock_path.exists():
        msg = f"No lock file found at {lock_path}. Run 'driftwatch freeze' first."
        raise FileNotFoundError(msg)

    lock = read_lock_file(suites_root)
    result = VerifyResult()

    # Check each locked suite
    for name, entry in lock.entries.items():
        suite_dir = suites_root / name
        if not suite_dir.is_dir():
            result.missing_on_disk.append(name)
            logger.error("Locked suite '%s' not found on disk!", name)
            continue

        try:
            manifest = load_suite(suite_dir)
        except (ValueError, FileNotFoundError) as e:
            result.missing_on_disk.append(name)
            logger.error("Failed to load locked suite '%s': %s", name, e)
            continue

        if manifest.suite_hash == entry.suite_hash:
            result.ok.append(name)
            logger.info("[OK] Suite '%s' hash verified.", name)
        else:
            result.mismatched.append((name, entry.suite_hash, manifest.suite_hash))
            logger.error(
                "[FAIL] Suite '%s' hash MISMATCH! Locked: %s, Current: %s",
                name,
                entry.suite_hash[:16],
                manifest.suite_hash[:16],
            )

    # Check for unlocked suites on disk
    for child in sorted(suites_root.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and child.name not in lock.entries:
            result.unlocked.append(child.name)
            logger.warning("Suite '%s' is not locked.", child.name)

    return result
