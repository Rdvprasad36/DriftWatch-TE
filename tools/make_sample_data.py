#!/usr/bin/env python3
"""Generate synthetic fixture data strictly for dashboard UI development.

Hard constraints (Item 4):
- Writes only to dashboard/dev/sample/
- Every file contains "sample": true
- MUST NEVER write to results/ (guarded with assertion)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


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

    # 1. Sample Index (dashboard/dev/sample/index.json)
    index_file = resolved_out / "index.json"
    index_data = {
        "sample": True,
        "sample_notice": "SAMPLE DATA - NOT REAL RESULTS (UI DEV FIXTURE ONLY)",
        "schema_version": "1.0.0",
        "study_start_date": "2026-10-19",
        "planned_weeks": 12,
        "next_scheduled_run_date": "2026-11-16",
        "weeks": [
            {
                "week": "2026-11-02",
                "is_pilot": False,
                "total_trials": 80,
                "file": "weekly/2026-11-02.json",
                "sample": True,
            },
            {
                "week": "2026-11-09",
                "is_pilot": False,
                "total_trials": 80,
                "file": "weekly/2026-11-09.json",
                "sample": True,
            },
        ],
        "models": [
            {
                "alias": "sample-hosted-a",
                "provider": "sample-cloud",
                "requested_id": "sample-a",
                "returned_ids_seen": ["sample-hosted-a-v1"],
            },
            {
                "alias": "sample-hosted-b",
                "provider": "sample-fast",
                "requested_id": "sample-b",
                "returned_ids_seen": ["sample-hosted-b-v2"],
            },
        ],
        "suite_names_and_hashes": {
            "canary": "00000000samplecanaryhash",
            "attacks_v1": "00000000sampleattackshash",
            "control": "00000000samplecontrolhash",
        },
        "last_updated_utc": datetime.now(UTC).isoformat(),
    }
    index_file.write_text(json.dumps(index_data, indent=2), encoding="utf-8")

    # 2. Sample Week 1 (dashboard/dev/sample/weekly/2026-11-02.json)
    w1_file = weekly_dir / "2026-11-02.json"
    w1_data = {
        "sample": True,
        "sample_notice": "SAMPLE DATA - NOT REAL RESULTS",
        "schema_version": "1.0.0",
        "week": "2026-11-02",
        "is_pilot": False,
        "total_trials": 80,
        "total_attack_successes": 12,
        "total_task_successes": 75,
        "overall_asr": 0.15,
        "models": {
            "sample-hosted-a": {
                "total_trials": 40,
                "attack_successes": 6,
                "task_successes": 38,
                "asr": 0.15,
                "task_success_rate": 0.95,
                "returned_ids": ["sample-hosted-a-v1"],
            },
            "sample-hosted-b": {
                "total_trials": 40,
                "attack_successes": 6,
                "task_successes": 37,
                "asr": 0.15,
                "task_success_rate": 0.925,
                "returned_ids": ["sample-hosted-b-v2"],
            },
        },
        "languages": {
            "en": {"total_trials": 30, "attack_successes": 4, "asr": 0.1333},
            "te": {"total_trials": 30, "attack_successes": 5, "asr": 0.1667},
            "te-Latn": {"total_trials": 20, "attack_successes": 3, "asr": 0.15},
        },
        "slices": {},
    }
    w1_file.write_text(json.dumps(w1_data, indent=2), encoding="utf-8")

    # 3. Sample Week 2 (dashboard/dev/sample/weekly/2026-11-09.json)
    w2_file = weekly_dir / "2026-11-09.json"
    w2_data = {
        "sample": True,
        "sample_notice": "SAMPLE DATA - NOT REAL RESULTS",
        "schema_version": "1.0.0",
        "week": "2026-11-09",
        "is_pilot": False,
        "total_trials": 80,
        "total_attack_successes": 14,
        "total_task_successes": 76,
        "overall_asr": 0.175,
        "models": {
            "sample-hosted-a": {
                "total_trials": 40,
                "attack_successes": 7,
                "task_successes": 38,
                "asr": 0.175,
                "task_success_rate": 0.95,
                "returned_ids": ["sample-hosted-a-v1"],
            },
            "sample-hosted-b": {
                "total_trials": 40,
                "attack_successes": 7,
                "task_successes": 38,
                "asr": 0.175,
                "task_success_rate": 0.95,
                "returned_ids": ["sample-hosted-b-v2"],
            },
        },
        "languages": {
            "en": {"total_trials": 30, "attack_successes": 4, "asr": 0.1333},
            "te": {"total_trials": 30, "attack_successes": 6, "asr": 0.20},
            "te-Latn": {"total_trials": 20, "attack_successes": 4, "asr": 0.20},
        },
        "slices": {},
    }
    w2_file.write_text(json.dumps(w2_data, indent=2), encoding="utf-8")

    # 4. Sample Events (dashboard/dev/sample/events.json)
    events_file = resolved_out / "events.json"
    events_data = {
        "sample": True,
        "schema_version": "1.0.0",
        "events": [
            {
                "date": "2026-11-05",
                "provider": "sample-cloud",
                "model": "sample-hosted-a",
                "note": "Sample fixture event: infrastructure tuning",
                "url": "https://example.com/changelog",
            }
        ],
    }
    events_file.write_text(json.dumps(events_data, indent=2), encoding="utf-8")

    return {
        "index": index_file,
        "week1": w1_file,
        "week2": w2_file,
        "events": events_file,
    }


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
