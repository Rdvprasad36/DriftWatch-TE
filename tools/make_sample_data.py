#!/usr/bin/env python3
"""Generate synthetic fixture data strictly for dashboard UI development.

Hard constraints (Item 4):
- Writes only to dashboard/dev/sample/
- Every file contains "sample": true
- MUST NEVER write to results/ (guarded with assertion)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

# Week dates for sample data (study_start_date is 2026-11-09 in config)
_PILOT_WEEK = "2026-11-02"
_STUDY_WEEKS = [
    "2026-11-09",
    "2026-11-16",
    "2026-11-23",
    "2026-11-30",
    "2026-12-07",
]
_MODELS = [
    {
        "alias": "sample-hosted-a",
        "provider": "sample-cloud",
        "requested_id": "sample-model-a-v1",
        "returned_ids_seen": ["sample-hosted-a-v1"],
    },
    {
        "alias": "sample-hosted-b",
        "provider": "sample-fast",
        "requested_id": "sample-model-b-v2",
        "returned_ids_seen": ["sample-hosted-b-v2"],
    },
]
_SUITES = {
    "canary": "00000000samplecanaryhash",
    "attacks_v1": "00000000sampleattackshash",
    "control": "00000000samplecontrolhash",
}
_LANGUAGES = ["en", "te", "te-Latn"]


def _make_week_summary(
    week: str,
    is_pilot: bool,
    week_index: int,
) -> dict:
    """Build a single weekly summary with obviously fake data."""
    base_asr = 0.12 + week_index * 0.02
    models_data: dict = {}
    lang_data: dict = {}
    total_trials = 0
    total_attacks = 0
    total_task_ok = 0

    for m in _MODELS:
        n = 40
        a = int(n * (base_asr + (0.01 if m["alias"].endswith("b") else 0)))
        t = n - 2
        models_data[m["alias"]] = {
            "total_trials": n,
            "attack_successes": a,
            "task_successes": t,
            "asr": round(a / n, 4) if n else 0,
            "task_success_rate": round(t / n, 4) if n else 0,
            "ci_95": [round(a / n - 0.08, 4), round(a / n + 0.08, 4)],
            "n_scenarios": 16,
            "returned_ids": m["returned_ids_seen"],
            "error_count": 1,
            "error_types": {"TimeoutError": 1},
            "completion_rate": round((n - 1) / n, 4),
            "avg_latency_ms": round(450 + week_index * 20, 1),
            "avg_tokens_in": 280,
            "avg_tokens_out": 45,
        }
        total_trials += n
        total_attacks += a
        total_task_ok += t

    trials_per_lang = total_trials // len(_LANGUAGES)
    for i, lang in enumerate(_LANGUAGES):
        la = int(trials_per_lang * (base_asr + i * 0.02))
        lang_data[lang] = {
            "total_trials": trials_per_lang,
            "attack_successes": la,
            "asr": round(la / trials_per_lang, 4),
        }

    return {
        "sample": True,
        "sample_notice": "SAMPLE DATA - NOT REAL RESULTS",
        "schema_version": "1.0.0",
        "week": week,
        "is_pilot": is_pilot,
        "total_trials": total_trials,
        "total_attack_successes": total_attacks,
        "total_task_successes": total_task_ok,
        "overall_asr": round(total_attacks / total_trials, 4),
        "models": models_data,
        "languages": lang_data,
        "channels": {
            "tool_output": {"trials": total_trials, "asr": round(total_attacks / total_trials, 4)},
        },
        "slices": {},
    }


def _make_sample_analysis() -> dict:
    """Build sample analysis.json with fake hypothesis results."""
    return {
        "sample": True,
        "sample_notice": "SAMPLE DATA - NOT REAL RESULTS",
        "schema_version": "1.0.0",
        "study_weeks_count": len(_STUDY_WEEKS),
        "hypotheses": {
            "H1": {
                "status": "not_enough_data",
                "rule": "GEE week coefficient p < 0.05",
                "detail": "Sample data only",
            },
            "H2": {
                "status": "not_enough_data",
                "rule": "PELT change point detected",
                "detail": "Sample data only",
            },
            "H3": {
                "status": "not_enough_data",
                "rule": "TOST equivalence p < 0.05",
                "detail": "Sample data only",
            },
            "H4": {
                "status": "not_enough_data",
                "rule": "GEE language interaction p < 0.05",
                "detail": "Sample data only",
            },
            "H5": {
                "status": "not_enough_data",
                "rule": "Native vs machine paired diff CI",
                "detail": "Sample data only",
            },
            "H6": {
                "status": "not_enough_data",
                "rule": "Canary hash change detected",
                "detail": "Sample data only",
            },
        },
        "per_model_trend": {},
        "change_points": [],
        "language_interactions": {},
        "local_control_equivalence": {
            "status": "not_enough_data",
            "tost_p": None,
        },
        "native_vs_machine": {
            "paired_diff": None,
            "matched_n": 0,
        },
    }


def _make_sample_events() -> dict:
    """Build sample events.json."""
    return {
        "sample": True,
        "schema_version": "1.0.0",
        "events": [
            {
                "date": "2026-11-12",
                "provider": "sample-cloud",
                "model": "sample-hosted-a",
                "note": "Sample fixture event: model version update",
                "url": "",
            },
            {
                "date": "2026-11-20",
                "provider": "sample-fast",
                "model": "sample-hosted-b",
                "note": "Sample fixture event: latency improvement",
                "url": "",
            },
        ],
    }


def _make_sample_records() -> list[dict]:
    """Build sample trial records for records.csv/jsonl."""
    rows = []
    trial_num = 0
    scenarios = [f"sample_scenario_{i:02d}" for i in range(16)]
    for week_idx, week in enumerate([_PILOT_WEEK] + _STUDY_WEEKS):
        is_pilot = week == _PILOT_WEEK
        for m in _MODELS:
            for si, sc in enumerate(scenarios):
                trial_num += 1
                asr_chance = 0.12 + week_idx * 0.02
                attack_success = (trial_num % 8) < int(asr_chance * 8)
                base_sc = sc.split("_desc_")[0].split("_out_")[0]
                rows.append(
                    {
                        "trial_id": f"sample-trial-{trial_num:04d}",
                        "base_id": base_sc,
                        "scenario_id": sc,
                        "run_week": week,
                        "timestamp_utc": f"{week}T10:00:00Z",
                        "model_alias": m["alias"],
                        "requested_model_id": m["requested_id"],
                        "returned_model_id": m["returned_ids_seen"][0],
                        "suite": "attacks_v1",
                        "suite_hash": _SUITES["attacks_v1"],
                        "attack_class": "indirect_injection",
                        "channel": "tool_output",
                        "language": _LANGUAGES[si % len(_LANGUAGES)],
                        "origin": "native" if si % 2 == 0 else "machine",
                        "trial_index": 0,
                        "tool_calls": "[]",
                        "attack_success": attack_success,
                        "task_success": not attack_success,
                        "steps": 3,
                        "stop_reason": "max_turns",
                        "error_type": None,
                        "http_errors": 0,
                        "tokens_in": 280,
                        "tokens_out": 45,
                        "latency_ms": 450.0 + week_idx * 20,
                        "git_sha": "sample0000000000000000",
                        "sample": True,
                        "is_pilot": is_pilot,
                    }
                )
    return rows


def _make_sample_canary() -> dict:
    """Build sample canary data."""
    return {
        "sample": True,
        "schema_version": "1.0.0",
        "weeks": {
            _STUDY_WEEKS[0]: {
                m["alias"]: {
                    "hash": f"canary_hash_{m['alias']}_w1",
                    "state": "baseline",
                }
                for m in _MODELS
            },
        },
    }


def _make_weekly_reports_index(weeks: list[str]) -> dict:
    """Build sample reports/weekly/index.json."""
    return {
        "sample": True,
        "schema_version": "1.0.0",
        "weeks": [
            {
                "week": w,
                "file_md": f"{w}.md",
                "file_html": f"{w}.html",
            }
            for w in weeks
        ],
    }


def generate_sample_data(output_dir: Path) -> dict[str, Path]:
    """Generate obviously fake developer sample data for UI styling."""
    # Strict safety guard: NEVER write to results/
    resolved_out = output_dir.resolve()
    for part in resolved_out.parts:
        if part.lower() == "results":
            msg = (
                "Fatal safety violation: tools/make_sample_data.py must NEVER "
                f"write to results/ (attempted: {resolved_out})"
            )
            raise ValueError(msg)

    resolved_out.mkdir(parents=True, exist_ok=True)
    weekly_dir = resolved_out / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir = resolved_out / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    exports_dir = resolved_out / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = resolved_out / "reports" / "weekly"
    reports_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, Path] = {}

    # 1. Index
    all_weeks = [_PILOT_WEEK] + _STUDY_WEEKS
    index_data = {
        "sample": True,
        "sample_notice": "SAMPLE DATA - NOT REAL RESULTS (UI DEV FIXTURE ONLY)",
        "schema_version": "1.0.0",
        "study_start_date": "2026-11-09",
        "planned_weeks": 12,
        "next_scheduled_run_date": "2026-12-14",
        "weeks": [],
        "models": _MODELS,
        "suite_names_and_hashes": _SUITES,
        "last_updated_utc": datetime.now(UTC).isoformat(),
    }
    for idx, week in enumerate(all_weeks):
        is_pilot = week < "2026-11-09"
        week_summary = _make_week_summary(week, is_pilot, idx)
        week_file = weekly_dir / f"{week}.json"
        week_file.write_text(json.dumps(week_summary, indent=2), encoding="utf-8")
        files[f"week_{week}"] = week_file
        index_data["weeks"].append(
            {
                "week": week,
                "is_pilot": is_pilot,
                "total_trials": week_summary["total_trials"],
                "file": f"weekly/{week}.json",
                "sample": True,
            }
        )

    index_file = resolved_out / "index.json"
    index_file.write_text(json.dumps(index_data, indent=2), encoding="utf-8")
    files["index"] = index_file

    # 2. Analysis
    analysis_file = analysis_dir / "analysis.json"
    analysis_file.write_text(json.dumps(_make_sample_analysis(), indent=2), encoding="utf-8")
    files["analysis"] = analysis_file

    # 3. Events
    events_file = resolved_out / "events.json"
    events_file.write_text(json.dumps(_make_sample_events(), indent=2), encoding="utf-8")
    files["events"] = events_file

    # 4. Records (CSV and JSONL)
    records = _make_sample_records()

    csv_file = exports_dir / "records.csv"
    if records:
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
        csv_file.write_text(buf.getvalue(), encoding="utf-8")
    files["records_csv"] = csv_file

    jsonl_file = exports_dir / "records.jsonl"
    lines = [json.dumps(r) for r in records]
    jsonl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    files["records_jsonl"] = jsonl_file

    schema_file = exports_dir / "schema.json"
    schema_data = {
        "sample": True,
        "schema_version": "1.0.0",
        "columns": list(records[0].keys()) if records else [],
    }
    schema_file.write_text(json.dumps(schema_data, indent=2), encoding="utf-8")
    files["schema"] = schema_file

    # 5. Canary
    canary_file = resolved_out / "canary.json"
    canary_file.write_text(json.dumps(_make_sample_canary(), indent=2), encoding="utf-8")
    files["canary"] = canary_file

    # 6. Weekly reports index
    reports_index = reports_dir / "index.json"
    reports_index.write_text(
        json.dumps(
            _make_weekly_reports_index(_STUDY_WEEKS),
            indent=2,
        ),
        encoding="utf-8",
    )
    files["reports_index"] = reports_index

    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic sample data for dashboard UI dev."
    )
    parser.add_argument(
        "--output-dir",
        default="dashboard/dev/sample",
        help="Target folder for sample fixtures (default: dashboard/dev/sample).",
    )
    args = parser.parse_args()

    out_path = Path(args.output_dir)
    try:
        files = generate_sample_data(out_path)
        print(f"Sample UI fixtures created successfully in {out_path}:")
        for k, p in files.items():
            print(f"  - {k}: {p}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
