"""Bundle finalization for DriftWatch-TE.

Converts the NDJSON staging output from the orchestrator into an immutable
weekly result bundle:

    weekly/<week>/
        trials.ndjson          # source (kept for debugging)
        trials.parquet         # columnar format for analysis
        meta.json              # run metadata + git SHA + SDK versions

Immutability (AGENTS.md rule 2 / FR7):
  ``finalize_bundle()`` refuses to overwrite an existing ``trials.parquet``
  unless ``allow_overwrite=True``.

Design.md §2:
  "Result bundle: ``weekly/2026-10-19/{trials.parquet, canary.json, meta.json}``"
  ``meta.json`` holds git SHA, suite hashes, library versions, start/end time.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from driftwatch.storage.parquet import ndjson_to_parquet

logger = logging.getLogger(__name__)


def _get_git_sha() -> str:
    """Return the current git HEAD SHA, or 'unknown' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _get_sdk_versions() -> dict[str, str]:
    """Collect versions of key dependencies for reproducibility (FR3)."""
    versions: dict[str, str] = {}

    import sys

    versions["python"] = sys.version.split()[0]

    for pkg_name in ("pydantic", "httpx", "pyarrow", "pyyaml", "click"):
        try:
            from importlib.metadata import version

            versions[pkg_name] = version(pkg_name)
        except Exception:  # noqa: BLE001
            versions[pkg_name] = "unknown"

    return versions


def finalize_bundle(
    run_dir: Path,
    *,
    week: str,
    allow_overwrite: bool = False,
) -> dict[str, Any]:
    """Convert NDJSON to Parquet and write meta.json.

    Args:
        run_dir: Directory containing ``trials.ndjson``
            (e.g. ``weekly/2026-10-19``).
        week: ISO date string for this run.
        allow_overwrite: If True, overwrite existing ``trials.parquet``.
            Otherwise raise :class:`FileExistsError` (AGENTS.md rule 2).

    Returns:
        The meta dict that was written to ``meta.json``.

    Raises:
        FileExistsError: If ``trials.parquet`` exists and
            *allow_overwrite* is False.
        FileNotFoundError: If ``trials.ndjson`` does not exist.
    """
    ndjson_path = run_dir / "trials.ndjson"
    parquet_path = run_dir / "trials.parquet"
    meta_path = run_dir / "meta.json"

    if not ndjson_path.exists():
        msg = f"NDJSON file not found: {ndjson_path}"
        raise FileNotFoundError(msg)

    if parquet_path.exists() and not allow_overwrite:
        msg = (
            f"Bundle already exists: '{parquet_path}'. "
            "Use --force-new-version to overwrite."
        )
        raise FileExistsError(msg)

    # Convert NDJSON → Parquet
    row_count = ndjson_to_parquet(ndjson_path, parquet_path)

    # Build meta.json
    meta: dict[str, Any] = {
        "week": week,
        "row_count": row_count,
        "git_sha": _get_git_sha(),
        "sdk_versions": _get_sdk_versions(),
        "finalized_at": datetime.now(UTC).isoformat(),
    }

    # Merge with existing meta.json if present (orchestrator may have
    # written planned_jobs, completed_jobs, etc.)
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
            existing.update(meta)
            meta = existing
        except json.JSONDecodeError:
            logger.warning("Existing meta.json is invalid; overwriting.")

    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "Finalized bundle: %d rows → %s, meta → %s",
        row_count,
        parquet_path.name,
        meta_path.name,
    )
    return meta

