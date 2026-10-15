"""Summary generation for DriftWatch-TE weekly bundles.

Architecture.md §3.7:
  "Summaries: small JSON/CSV in git (results/summary/), so the dashboard
   builds without raw data."

Reads a finalized ``trials.parquet`` bundle and produces a compact summary
with per-model and per-language ASR, task success rates, and trial counts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from driftwatch.storage.parquet import load_parquet_rows

logger = logging.getLogger(__name__)


def generate_summary(
    run_dir: Path,
    *,
    week: str,
) -> dict[str, Any]:
    """Generate a summary dict from a finalized Parquet bundle.

    Args:
        run_dir: Directory containing ``trials.parquet``.
        week: ISO date string for the run week.

    Returns:
        Summary dict with per-model and per-language breakdowns.

    Raises:
        FileNotFoundError: If ``trials.parquet`` is missing.
    """
    parquet_path = run_dir / "trials.parquet"
    rows = load_parquet_rows(parquet_path)

    total = len(rows)
    total_attacks = sum(1 for r in rows if r.get("attack_success"))
    total_task = sum(1 for r in rows if r.get("task_success"))

    # Per-model breakdown
    models: dict[str, dict[str, Any]] = {}
    for row in rows:
        alias = str(row.get("model_alias", "unknown"))
        if alias not in models:
            models[alias] = {
                "total_trials": 0,
                "attack_successes": 0,
                "task_successes": 0,
            }
        models[alias]["total_trials"] += 1
        if row.get("attack_success"):
            models[alias]["attack_successes"] += 1
        if row.get("task_success"):
            models[alias]["task_successes"] += 1

    for stats in models.values():
        n = stats["total_trials"]
        stats["asr"] = stats["attack_successes"] / n if n > 0 else 0.0
        stats["task_success_rate"] = (
            stats["task_successes"] / n if n > 0 else 0.0
        )

    # Per-language breakdown
    languages: dict[str, dict[str, Any]] = {}
    for row in rows:
        lang = str(row.get("language", "unknown"))
        if lang not in languages:
            languages[lang] = {
                "total_trials": 0,
                "attack_successes": 0,
            }
        languages[lang]["total_trials"] += 1
        if row.get("attack_success"):
            languages[lang]["attack_successes"] += 1

    for stats in languages.values():
        n = stats["total_trials"]
        stats["asr"] = stats["attack_successes"] / n if n > 0 else 0.0

    summary: dict[str, Any] = {
        "week": week,
        "total_trials": total,
        "total_attack_successes": total_attacks,
        "total_task_successes": total_task,
        "overall_asr": total_attacks / total if total > 0 else 0.0,
        "models": models,
        "languages": languages,
    }

    logger.info(
        "Generated summary for week %s: %d trials, overall ASR=%.3f",
        week,
        total,
        summary["overall_asr"],
    )
    return summary


def write_summary(
    run_dir: Path,
    *,
    week: str,
    output_dir: Path,
) -> Path:
    """Generate and write a summary JSON file.

    Args:
        run_dir: Directory containing ``trials.parquet``.
        week: ISO date string for the run week.
        output_dir: Directory for output (e.g. ``results/summary/``).
            Created if it doesn't exist.

    Returns:
        Path to the written JSON file.
    """
    summary = generate_summary(run_dir, week=week)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{week}.json"
    output_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("Wrote summary: %s", output_path)
    return output_path

