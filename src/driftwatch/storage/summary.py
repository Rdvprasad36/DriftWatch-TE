"""Summary generation for DriftWatch-TE weekly bundles.

Data Contract (architecture.md §3.7 / Item 2):
  - results/summary/index.json: study metadata, models, suite hashes, weeks list.
  - results/summary/weekly/<date>.json: disaggregated metrics per model, language,
    channel, suite and origin (native or machine).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from driftwatch.analysis.bootstrap import cluster_bootstrap_ci
from driftwatch.config import load_study_config
from driftwatch.schema.contracts import SCHEMA_VERSION
from driftwatch.storage.parquet import load_parquet_rows

logger = logging.getLogger(__name__)

_cfg = load_study_config()
STUDY_START_DATE = _cfg.study_start_date


def _infer_origin(suite: str) -> str:
    """Infer whether suite is native or machine-translated."""
    suite_lower = suite.lower()
    if "native" in suite_lower or "v2" in suite_lower:
        return "native"
    return "machine"


def compute_slice_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute required metrics for a subset of trial rows."""
    n_trials = len(rows)
    if n_trials == 0:
        return {
            "n_trials": 0,
            "n_scenarios": 0,
            "attack_success_rate": 0.0,
            "task_success_rate": 0.0,
            "ci_95": None,
            "error_rate": 0.0,
            "completion_rate": 0.0,
            "mean_latency": 0.0,
            "mean_tokens": 0.0,
        }

    scenarios = set(r.get("scenario_id") for r in rows if r.get("scenario_id"))
    atk_count = sum(1 for r in rows if r.get("attack_success"))
    task_count = sum(1 for r in rows if r.get("task_success"))
    err_count = sum(1 for r in rows if r.get("error_type"))

    # Latency and tokens
    latencies = [float(r.get("latency_ms", 0.0)) for r in rows]
    tokens = [int(r.get("tokens_in", 0) or 0) + int(r.get("tokens_out", 0) or 0) for r in rows]

    asr = round(atk_count / n_trials, 4)
    # Cluster bootstrap requires >= 10 scenario clusters (Item 2a)
    if len(scenarios) >= 10:
        df = pd.DataFrame(rows)
        _mean, ci_low, ci_high = cluster_bootstrap_ci(
            df,
            metric_col="attack_success",
            cluster_col="scenario_id",
            min_clusters=10,
        )
        if ci_low is not None and ci_high is not None:
            ci_95: list[float] | None = [round(ci_low, 4), round(ci_high, 4)]
        else:
            ci_95 = None
    else:
        ci_95 = None

    return {
        "n_trials": n_trials,
        "n_scenarios": len(scenarios),
        "attack_success_rate": asr,
        "task_success_rate": round(task_count / n_trials, 4),
        "ci_95": ci_95,
        "error_rate": round(err_count / n_trials, 4),
        "completion_rate": round((n_trials - err_count) / n_trials, 4),
        "mean_latency": round(sum(latencies) / n_trials, 2),
        "mean_tokens": round(sum(tokens) / n_trials, 1),
    }


def generate_summary(
    run_dir: Path,
    *,
    week: str,
) -> dict[str, Any]:
    """Generate a summary dict conforming to the data contract.

    Args:
        run_dir: Directory containing ``trials.parquet`` or ``trials.ndjson``.
        week: ISO date string for the run week.

    Returns:
        Summary dict versioned with schema_version and broken down by slice.
    """
    parquet_path = run_dir / "trials.parquet"
    ndjson_path = run_dir / "trials.ndjson"

    if parquet_path.exists():
        rows = load_parquet_rows(parquet_path)
    elif ndjson_path.exists():
        rows = [
            json.loads(line)
            for line in ndjson_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        msg = f"No trial bundle found in '{run_dir}'"
        raise FileNotFoundError(msg)

    total = len(rows)
    total_attacks = sum(1 for r in rows if r.get("attack_success"))
    total_task = sum(1 for r in rows if r.get("task_success"))

    cfg = load_study_config()
    is_pilot = week < cfg.study_start_date or "dryrun" in week.lower()

    # Detailed dimensional slices
    slices_data: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        m = str(r.get("model_alias", "unknown"))
        lang = str(r.get("language", "unknown"))
        ch = str(r.get("channel", "unknown"))
        ste = str(r.get("suite", "unknown"))
        orig = _infer_origin(ste)
        key = f"{m}|{lang}|{ch}|{ste}|{orig}"
        if key not in slices_data:
            slices_data[key] = []
        slices_data[key].append(r)

    slices: dict[str, dict[str, Any]] = {
        k: compute_slice_stats(slice_rows) for k, slice_rows in slices_data.items()
    }

    # Model-level aggregate
    models: dict[str, dict[str, Any]] = {}
    for r in rows:
        alias = str(r.get("model_alias", "unknown"))
        if alias not in models:
            models[alias] = {
                "total_trials": 0,
                "attack_successes": 0,
                "task_successes": 0,
                "returned_ids": set(),
            }
        models[alias]["total_trials"] += 1
        if r.get("attack_success"):
            models[alias]["attack_successes"] += 1
        if r.get("task_success"):
            models[alias]["task_successes"] += 1
        rid = r.get("returned_model_id")
        if rid and str(rid) != alias:
            models[alias]["returned_ids"].add(str(rid))

    for stats in models.values():
        n = stats["total_trials"]
        stats["asr"] = round(stats["attack_successes"] / n, 4) if n > 0 else None
        stats["task_success_rate"] = round(stats["task_successes"] / n, 4) if n > 0 else None
        stats["returned_ids"] = sorted(list(stats["returned_ids"]))

    # Language-level aggregate
    languages: dict[str, dict[str, Any]] = {}
    for r in rows:
        lang = str(r.get("language", "unknown"))
        if lang not in languages:
            languages[lang] = {
                "total_trials": 0,
                "attack_successes": 0,
            }
        languages[lang]["total_trials"] += 1
        if r.get("attack_success"):
            languages[lang]["attack_successes"] += 1

    for stats in languages.values():
        n = stats["total_trials"]
        stats["asr"] = round(stats["attack_successes"] / n, 4) if n > 0 else None

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "week": week,
        "is_pilot": is_pilot,
        "total_trials": total,
        "total_attack_successes": total_attacks,
        "total_task_successes": total_task,
        "overall_asr": round(total_attacks / total, 4) if total > 0 else 0.0,
        "slices": slices,
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


def update_summary_index(output_dir: Path, repo_root: Path | None = None) -> Path:
    """Regenerate results/summary/index.json according to data contract."""
    output_dir.mkdir(parents=True, exist_ok=True)
    weekly_dir = output_dir / "weekly"
    root = repo_root or Path.cwd()
    cfg = load_study_config(root / "config" / "study.yaml")

    # Collect all weekly summary files
    weeks_entries: list[dict[str, Any]] = []
    models_seen: dict[str, dict[str, Any]] = {}

    # Seed models from config/study.yaml
    for m in cfg.models:
        models_seen[m.alias] = {
            "alias": m.alias,
            "provider": m.provider,
            "requested_id": m.requested_id,
            "returned_ids_seen": set(),
        }

    candidate_files: list[Path] = []
    if weekly_dir.is_dir():
        candidate_files.extend(weekly_dir.glob("*.json"))
    # Also check root of output_dir
    for f in output_dir.glob("*.json"):
        if f.name not in ("index.json", "manifest.json") and f not in candidate_files:
            candidate_files.append(f)

    # De-duplicate by stem (week date)
    weeks_by_date: dict[str, Path] = {}
    for f in candidate_files:
        weeks_by_date[f.stem] = f

    sorted_dates = sorted(weeks_by_date.keys())
    latest_date = None

    for date_str in sorted_dates:
        f = weeks_by_date[date_str]
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            is_pilot = data.get("is_pilot", date_str < cfg.study_start_date)
            total_trials = data.get("total_trials", 0)

            weeks_entries.append(
                {
                    "week": date_str,
                    "is_pilot": is_pilot,
                    "total_trials": total_trials,
                    "file": f"weekly/{date_str}.json",
                }
            )

            if not is_pilot:
                latest_date = date_str

            # Accumulate model info
            for alias, m_info in data.get("models", {}).items():
                if alias not in models_seen:
                    models_seen[alias] = {
                        "alias": alias,
                        "provider": alias.split("/")[0] if "/" in alias else alias,
                        "requested_id": alias,
                        "returned_ids_seen": set(),
                    }
                for rid in m_info.get("returned_ids", []):
                    # Only record returned IDs returned by API, never alias (Item 2c)
                    if rid and rid != alias:
                        models_seen[alias]["returned_ids_seen"].add(rid)
        except Exception as exc:
            logger.warning("Error reading summary %s: %s", f, exc)

    # Next scheduled run date (Monday following latest week or start date)
    if latest_date:
        try:
            cur = datetime.strptime(latest_date, "%Y-%m-%d").replace(tzinfo=UTC)
            nxt = cur + timedelta(days=7)
            next_run_date = nxt.strftime("%Y-%m-%d")
        except Exception:
            next_run_date = cfg.study_start_date
    else:
        next_run_date = cfg.study_start_date

    # Load suite hashes from SUITE_LOCK.json
    suite_hashes: dict[str, str] = {}
    lock_file = root / "suites" / "SUITE_LOCK.json"
    if lock_file.is_file():
        try:
            lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
            for s_name, s_info in lock_data.get("entries", {}).items():
                suite_hashes[s_name] = s_info.get("suite_hash", "")
        except Exception as exc:
            logger.warning("Could not read SUITE_LOCK.json: %s", exc)

    models_list = [
        {
            "alias": m["alias"],
            "provider": m["provider"],
            "requested_id": m["requested_id"],
            "returned_ids_seen": sorted(list(m["returned_ids_seen"])),
        }
        for m in models_seen.values()
    ]

    index_data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "study_start_date": cfg.study_start_date,
        "planned_weeks": cfg.planned_weeks,
        "next_scheduled_run_date": next_run_date,
        "github_repo": cfg.github_repo,
        "hf_dataset_repo": cfg.hf_dataset_repo,
        "preregistration_url": cfg.preregistration_url,
        "weeks": weeks_entries,
        "models": models_list,
        "suite_names_and_hashes": suite_hashes,
        "last_updated_utc": datetime.now(UTC).isoformat(),
    }

    index_path = output_dir / "index.json"
    index_path.write_text(
        json.dumps(index_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Updated summary index at %s", index_path)
    return index_path


def write_summary(
    run_dir: Path,
    *,
    week: str,
    output_dir: Path,
    repo_root: Path | None = None,
) -> Path:
    """Generate and write a summary JSON file and update the index.

    Args:
        run_dir: Directory containing trials.parquet or trials.ndjson.
        week: ISO date string for the run week.
        output_dir: Directory for output (e.g. ``results/summary/``).
        repo_root: Root repository path.

    Returns:
        Path to the written JSON file.
    """
    summary = generate_summary(run_dir, week=week)
    output_dir.mkdir(parents=True, exist_ok=True)
    weekly_dir = output_dir / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)

    dest = weekly_dir / f"{week}.json"
    dest.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote weekly summary to %s", dest)

    update_summary_index(output_dir, repo_root=repo_root)
    return dest
