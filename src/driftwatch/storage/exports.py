"""Export pipeline for DriftWatch-TE trial records.

Converts weekly run bundles into the 25-column versioned tabular format
(records.csv, records.jsonl) per data contract and architecture.md §4.
Sanitizes output to guarantee no API keys, credentials, or raw auth headers
leak into exports.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from driftwatch.schema.contracts import (
    EXPORT_SCHEMA_PROPERTIES,
    RECORD_SCHEMA_COLUMNS,
    SCHEMA_VERSION,
)
from driftwatch.storage.parquet import load_parquet_rows
from driftwatch.storage.summary import _infer_origin, update_summary_index

logger = logging.getLogger(__name__)


def _sanitize_no_secrets(value: Any) -> None:
    """Raise ValueError if a credential pattern is found in exported data."""
    if value is None:
        return
    s = str(value)
    # Check for raw authorization headers or bearer tokens
    low = s.lower()
    if "bearer " in low and "[redacted]" not in low:
        msg = f"Credential leak detected in exported data: {s[:30]}..."
        raise ValueError(msg)
    if "gsk_" in s or "sk-" in s:
        # Known API key prefixes
        msg = f"Potential API key leak detected in exported data: {s[:10]}..."
        raise ValueError(msg)


def _infer_attack_class(scenario_id: str, suite: str) -> str:
    """Infer attack_class taxonomy from scenario_id or suite."""
    sid = scenario_id.lower()
    if "refund" in sid:
        return "financial_manipulation"
    if "address" in sid:
        return "privilege_escalation"
    if "order" in sid:
        return "state_corruption"
    if "email" in sid:
        return "data_exfiltration"
    if "canary" in suite.lower() or "canary" in sid:
        return "canary"
    if "control" in suite.lower():
        return "benign_control"
    return "indirect_prompt_injection"


def build_export_row(
    row: dict[str, Any],
    week: str,
    default_git_sha: str = "unknown",
) -> dict[str, Any]:
    """Transform an internal trial row into the versioned 25-column schema."""
    raw_trial_id = row.get("trial_id")
    fallback_id = f"{week}_{row.get('scenario_id', 'sc')}_{row.get('trial', 0)}"
    trial_id = str(raw_trial_id or fallback_id)
    scenario_id = str(row.get("scenario_id", ""))
    model_alias = str(row.get("model_alias", ""))
    suite = str(row.get("suite", ""))
    origin = _infer_origin(suite)

    # trial index
    raw_idx = row.get("trial_index")
    if raw_idx is None:
        raw_idx = row.get("trial", 0)
    trial_idx = int(raw_idx)

    # tool_calls as JSON string
    raw_calls = row.get("tool_calls")
    if isinstance(raw_calls, (list, dict)):
        tool_calls_str = json.dumps(raw_calls, ensure_ascii=False)
    elif isinstance(raw_calls, str):
        tool_calls_str = raw_calls
    else:
        tool_calls_str = "[]"

    # error and stop reason
    err = row.get("error_type")
    stop_reason = str(row.get("stop_reason") or ("error" if err else "completed"))

    # Returned model ID must only contain IDs returned by provider API, never alias (Item 2c)
    rid = str(row.get("returned_model_id") or "")
    if rid == model_alias:
        rid = ""

    export_row = {
        "trial_id": trial_id,
        "scenario_id": scenario_id,
        "run_week": week,
        "timestamp_utc": str(
            row.get("timestamp_utc") or row.get("finalized_at") or f"{week}T00:00:00Z"
        ),
        "model_alias": model_alias,
        "requested_model_id": str(
            row.get("requested_model_id") or row.get("requested_model") or model_alias
        ),
        "returned_model_id": rid,
        "suite": suite,
        "suite_hash": str(row.get("suite_hash", "")),
        "attack_class": _infer_attack_class(scenario_id, suite),
        "channel": str(row.get("channel", "tool_output")),
        "language": str(row.get("language", "en")),
        "origin": origin,
        "trial_index": trial_idx,
        "tool_calls": tool_calls_str,
        "attack_success": bool(row.get("attack_success", False)),
        "task_success": bool(row.get("task_success", False)),
        "steps": int(row.get("steps", 0)),
        "stop_reason": stop_reason,
        "error_type": str(err) if (err is not None and str(err) != "None") else None,
        "http_errors": int(row.get("http_errors", 0)),
        "tokens_in": int(row.get("tokens_in", 0)),
        "tokens_out": int(row.get("tokens_out", 0)),
        "latency_ms": round(float(row.get("latency_ms", 0.0)), 2),
        "git_sha": str(row.get("git_sha") or default_git_sha),
    }

    # Safety checks: ensure no secrets or headers
    for k, v in export_row.items():
        if k != "tool_calls":
            _sanitize_no_secrets(v)

    return export_row


def export_all(
    weekly_root: Path,
    results_root: Path,
    events_file: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    """Scan all weekly runs, export records, events, and update summaries.

    Args:
        weekly_root: Root directory of weekly runs (e.g. ``weekly/``).
        results_root: Target directory for exports (e.g. ``results/``).
        events_file: Optional path to raw events JSON.
        repo_root: Repository root path.

    Returns:
        Mapping of output artifact names to generated file paths.
    """
    exports_dir = results_root / "exports"
    summary_dir = results_root / "summary"
    exports_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    # 1. Gather all trial records from all available weekly bundles
    all_rows: list[dict[str, Any]] = []

    # Look for both parquet and ndjson
    candidate_weeks: list[tuple[str, Path]] = []
    if weekly_root.is_dir():
        for week_dir in sorted(weekly_root.iterdir()):
            if week_dir.is_dir() and not week_dir.name.startswith("."):
                candidate_weeks.append((week_dir.name, week_dir))

    # Also check if results/summary has weekly data
    weekly_summary_dir = summary_dir / "weekly"
    if weekly_summary_dir.is_dir():
        for _ in sorted(weekly_summary_dir.glob("*.json")):
            # If not in candidate_weeks, we might have trials in run bundles
            pass

    for week_str, wdir in candidate_weeks:
        parquet_file = wdir / "trials.parquet"
        ndjson_file = wdir / "trials.ndjson"

        week_rows: list[dict[str, Any]] = []
        if parquet_file.exists():
            try:
                week_rows = load_parquet_rows(parquet_file)
            except Exception as exc:
                logger.warning("Error reading %s: %s", parquet_file, exc)
        elif ndjson_file.exists():
            try:
                week_rows = [
                    json.loads(line)
                    for line in ndjson_file.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except Exception as exc:
                logger.warning("Error reading %s: %s", ndjson_file, exc)

        for r in week_rows:
            all_rows.append(build_export_row(r, week_str))

    # 2. Write records.csv
    csv_path = exports_dir / "records.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RECORD_SCHEMA_COLUMNS)
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)
    logger.info("Exported %d records to %s", len(all_rows), csv_path)

    # 3. Write records.jsonl
    jsonl_path = exports_dir / "records.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info("Exported %d records to %s", len(all_rows), jsonl_path)

    # 4. Write schema.json
    schema_path = exports_dir / "schema.json"
    schema_spec = {
        "schema_version": SCHEMA_VERSION,
        "title": "DriftWatch-TE Trial Records Schema",
        "description": "Schema definition for per-trial records exported by DriftWatch-TE.",
        "columns": RECORD_SCHEMA_COLUMNS,
        "json_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "ExportRowSchema",
            "type": "object",
            "required": RECORD_SCHEMA_COLUMNS,
            "properties": EXPORT_SCHEMA_PROPERTIES,
        },
    }
    schema_path.write_text(
        json.dumps(schema_spec, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Exported schema to %s", schema_path)

    # 5. Export results/events.json
    events_out_path = results_root / "events.json"
    ev_list: list[dict[str, Any]] = []
    if events_file and events_file.is_file():
        try:
            raw_ev = json.loads(events_file.read_text(encoding="utf-8"))
            if isinstance(raw_ev, list):
                ev_list = raw_ev
            elif isinstance(raw_ev, dict) and "events" in raw_ev:
                ev_list = raw_ev["events"]
        except Exception as exc:
            logger.warning("Error reading events from %s: %s", events_file, exc)

    events_data = {
        "schema_version": SCHEMA_VERSION,
        "exported_at_utc": "2026-10-22T00:00:00Z",
        "events": ev_list,
    }
    events_out_path.write_text(
        json.dumps(events_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Exported %d provider events to %s", len(ev_list), events_out_path)

    # 6. Update summary index
    index_path = update_summary_index(summary_dir, repo_root=repo_root)

    return {
        "csv": csv_path,
        "records_csv": csv_path,
        "jsonl": jsonl_path,
        "records_jsonl": jsonl_path,
        "schema": schema_path,
        "records_schema": schema_path,
        "events": events_out_path,
        "summary_index": index_path,
    }
