"""Atomic result writer for DriftWatch-TE.

Results are written to a staging file (``trials.ndjson.staging``) as NDJSON
(one JSON object per line).  When the run completes, the staging file is
atomically renamed to ``trials.ndjson`` and a ``meta.json`` summary is written.

Immutability guarantee (AGENTS.md rule 2 / FR7):
  - ``finalize()`` refuses to overwrite an existing ``trials.ndjson`` unless
    ``allow_overwrite=True`` (``--force-new-version`` in the CLI).
  - If the process crashes mid-run, the staging file preserves completed rows
    for resume.

Storage layout (design.md §2, architecture.md §3.7):
    weekly/<week>/
        trials.ndjson          # final (renamed from staging)
        trials.ndjson.staging  # in-progress (for resume)
        meta.json              # run metadata (after finalize)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from driftwatch.agent.trial import TrialResult
from driftwatch.orchestrator.jobs import Job

logger = logging.getLogger(__name__)


class RunWriter:
    """Accumulates trial results and writes them atomically.

    Args:
        run_dir: Directory for this run (e.g. ``weekly/2026-10-19``).
            Created if it doesn't exist.
        week: ISO date string for this run (e.g. ``"2026-10-19"``).
        planned: Total number of planned jobs (for meta.json).
    """

    def __init__(self, run_dir: Path, week: str, planned: int) -> None:
        self._run_dir = run_dir
        self._week = week
        self._planned = planned
        self._completed = 0
        self._errors = 0
        self._start_time = datetime.now(UTC).isoformat()

        # Ensure directory exists
        self._run_dir.mkdir(parents=True, exist_ok=True)

        # Paths
        self._staging_path = self._run_dir / "trials.ndjson.staging"
        self._final_path = self._run_dir / "trials.ndjson"
        self._meta_path = self._run_dir / "meta.json"

        # Lock for concurrent writes
        self._write_lock = asyncio.Lock()

    async def append(self, job: Job, result: TrialResult) -> None:
        """Append one result row to the staging file.

        Thread-safe via asyncio.Lock.  The row includes both the
        TrialResult columns and the job-level context (suite, hash, week).
        """
        record = result.as_record()
        # Add orchestrator-level columns
        record["job_id"] = job.job_id
        record["base_id"] = getattr(job.scenario, "base_id", None) or job.scenario.id
        record["suite"] = job.suite_name
        record["suite_hash"] = job.suite_hash
        record["week"] = self._week

        line = json.dumps(record, ensure_ascii=False, sort_keys=True)

        async with self._write_lock:
            with open(self._staging_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._completed += 1
            if result.error_type is not None:
                self._errors += 1

        logger.debug("Wrote result for job '%s'.", job.job_id)

    def completed_job_ids(self) -> set[str]:
        """Return job IDs already in the staging file (for resume).

        Reads the existing staging file if it exists and extracts job_id
        from each NDJSON line.  Invalid lines are skipped with a warning.
        """
        ids: set[str] = set()
        if not self._staging_path.exists():
            return ids

        for line_num, line in enumerate(
            self._staging_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                jid = row.get("job_id")
                if jid:
                    ids.add(jid)
            except json.JSONDecodeError:
                logger.warning(
                    "Skipping invalid NDJSON at line %d in %s",
                    line_num,
                    self._staging_path,
                )
        logger.info("Found %d completed job(s) in staging file for resume.", len(ids))
        return ids

    def finalize(self, *, allow_overwrite: bool = False) -> None:
        """Rename staging to final and write meta.json.

        Args:
            allow_overwrite: If True, overwrite an existing ``trials.ndjson``.
                Otherwise raise :class:`FileExistsError` (AGENTS.md rule 2).
        """
        if self._final_path.exists() and not allow_overwrite:
            msg = (
                f"Bundle already exists: '{self._final_path}'. "
                "Use --force-new-version to overwrite."
            )
            raise FileExistsError(msg)

        # Rename staging → final (atomic on most filesystems)
        if self._staging_path.exists():
            if self._final_path.exists():
                self._final_path.unlink()
            self._staging_path.rename(self._final_path)
            logger.info(
                "Finalized: %s → %s",
                self._staging_path.name,
                self._final_path.name,
            )

        # Write meta.json
        meta: dict[str, Any] = {
            "week": self._week,
            "planned_jobs": self._planned,
            "completed_jobs": self._completed,
            "error_jobs": self._errors,
            "start_time": self._start_time,
            "end_time": datetime.now(UTC).isoformat(),
        }
        self._meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Wrote %s.", self._meta_path)
