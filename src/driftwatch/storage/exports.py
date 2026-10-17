"""Export utilities for DriftWatch-TE trial records and provider events.

Implements Item 2 of the data contract:
- results/exports/records.csv
- results/exports/records.jsonl
- results/exports/schema.json
- results/events.json
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from driftwatch.schema.contracts import SCHEMA_VERSION, ExportRowSchema
from driftwatch.storage.bundle import _get_git_sha
from driftwatch.storage.parquet import load_parquet_rows
from driftwatch.storage.summary import _infer_origin, update_summary_index, write_summary

logger = logging.getLogger(__name__)

EXPORT_COLUMNS: list[str] = [
    "trial_id",
    "scenario_id",
    "run_week",
    "timestamp_utc",
    "model_alias",
    "requested_model",
    "returned_model_id",
    "suite",
    "suite_hash",
    "attack_class",
    "channel",
    "language",
    "origin",
    "trial_index",
    "tool_calls",
    "attack_success",
    "task_success",
    "steps",
    "stop_reason",
    "error_type",
    "http_errors",
    "tokens_in",
    "tokens_out",
    "latency_ms",
    "git_sha",
]

SECRET_KEYWORDS = ("api_key", "bearer", "authorization", "secret", "token", "password")


def _sanitize_no_secrets(value: Any) -> None:
    """Ensure no API keys, tokens or secrets appear in text representations."""
    str_val = str(value).lower()
    for kw in ("bearer ", "authorization:"):
        if kw in str_val:
            msg = f"Potential secret or credential pattern detected: '{kw}'"
            raise ValueError(msg)


def _infer_attack_class(scenario_id: str, suite: str) -> str:
    """Infer attack classification category from scenario ID or suite."""
    scen = scenario_id.lower()
    if "ctrl" in scen or "control" in suite.lower():
        return "control"
    if "canary" in scen or "canary" in suite.lower():
        return "canary"
    if "refund" in scen:
        return "refund_override"
    if "discount" in scen:
        return "discount_exploit"
    if "cancel" in scen:
        return "order_cancel"
    if "review" in scen:
        return "review_manipulation"
    return "general_injection"


def build_export_row(row: dict[str, Any], default_git_sha: str) -> dict[str, Any]:
    """Convert a raw trial dictionary into a sanitized ExportRow dict."""
    scenario_id = str(row.get("scenario_id", ""))
    suite = str(row.get("suite", ""))
    model_alias = str(row.get("model_alias", ""))
    trial_idx = int(row.get("trial", 0))
    week = str(row.get("week", ""))

    # trial_id uniquely identifying the execution
    trial_id = str(
        row.get("trial_id")
        or row.get("job_id")
        or f"{suite}:{scenario_id}:{model_alias}:{trial_idx}"
    )

    # origin: native or machine
    origin = _infer_origin(suite)

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

    export_row = {
        "trial_id": trial_id,
        "scenario_id": scenario_id,
        "run_week": week,
        "timestamp_utc": str(
            row.get("timestamp_utc") or row.get("finalized_at") or f"{week}T00:00:00Z"
        ),
        "model_alias": model_alias,
        "requested_model": str(row.get("requested_model") or model_alias),
        "returned_model_id": str(row.get("returned_model_id", "")),
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
        "error_type": str(err) if err is not None else None,
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
        weekly_root: Path to weekly/ directory with run folders.
        results_root: Path to results/ output directory.
        events_file: Path to events/provider_events.json.
        repo_root: Root repo path.

    Returns:
        Mapping of output artifact names to written file paths.
    """
    results_root.mkdir(parents=True, exist_ok=True)
    exports_dir = results_root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    summary_dir = results_root / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    git_sha = _get_git_sha()
    all_rows: list[dict[str, Any]] = []

    # 1. Scan all weekly bundles
    if weekly_root.is_dir():
        for run_dir in sorted(weekly_root.iterdir()):
            if not run_dir.is_dir():
                continue
            week_str = run_dir.name
            parquet_file = run_dir / "trials.parquet"
            ndjson_file = run_dir / "trials.ndjson"

            rows: list[dict[str, Any]] = []
            if parquet_file.exists():
                rows = load_parquet_rows(parquet_file)
            elif ndjson_file.exists():
                rows = [
                    json.loads(line)
                    for line in ndjson_file.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]

            if rows:
                # Also ensure summary JSON exists for this week
                try:
                    write_summary(
                        run_dir, week=week_str, output_dir=summary_dir, repo_root=repo_root
                    )
                except Exception as exc:
                    logger.warning("Could not write weekly summary for %s: %s", week_str, exc)

                for r in rows:
                    if "week" not in r:
                        r["week"] = week_str
                    all_rows.append(build_export_row(r, default_git_sha=git_sha))

    # 2. Write results/exports/records.csv
    csv_path = exports_dir / "records.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)
    logger.info("Wrote %d records to %s", len(all_rows), csv_path)

    # 3. Write results/exports/records.jsonl
    jsonl_path = exports_dir / "records.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info("Wrote %s", jsonl_path)

    # 4. Write results/exports/schema.json
    schema_path = exports_dir / "schema.json"
    pydantic_schema = ExportRowSchema.model_json_schema()
    schema_wrapper = {
        "schema_version": SCHEMA_VERSION,
        "title": "DriftWatch-TE Trial Records Schema",
        "description": "Schema definition for per-trial records exported by DriftWatch-TE.",
        "columns": EXPORT_COLUMNS,
        "json_schema": pydantic_schema,
    }
    schema_path.write_text(json.dumps(schema_wrapper, indent=2), encoding="utf-8")
    logger.info("Wrote %s", schema_path)

    # 5. Write results/events.json
    events_path = results_root / "events.json"
    src_events = events_file or (
        Path("events/provider_events.json")
        if Path("events/provider_events.json").exists()
        else None
    )
    event_list = []
    if src_events and src_events.is_file():
        try:
            event_list = json.loads(src_events.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read provider events file %s: %s", src_events, exc)

    events_payload = {
        "schema_version": SCHEMA_VERSION,
        "exported_at_utc": datetime.now(UTC).isoformat(),
        "events": event_list,
    }
    events_path.write_text(json.dumps(events_payload, indent=2), encoding="utf-8")
    logger.info("Wrote %s with %d events", events_path, len(event_list))

    # 6. Update summary index
    index_path = update_summary_index(summary_dir, repo_root=repo_root)

    return {
        "records_csv": csv_path,
        "records_jsonl": jsonl_path,
        "records_schema": schema_path,
        "events": events_path,
        "summary_index": index_path,
    }
