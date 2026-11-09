"""Hashing utilities for canary outputs and logprobs.

FR5 (Canary prompts at temperature 0, output hashes, logprobs where offered).
Design.md §4.7 (Canary analysis: output hash stability across weeks).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_output_hash(text: str) -> str:
    """Compute deterministic SHA-256 hex digest of model output text.

    Whitespace is stripped so trivial trailing newlines don't trigger
    false drift alerts.
    """
    normalized = text.strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def compute_logprobs_hash(logprobs: Any) -> str | None:
    """Compute deterministic SHA-256 hash of logprobs structure if present.

    Returns None if *logprobs* is None, empty, or unparseable.
    """
    if not logprobs:
        return None

    try:
        canonical_json = json.dumps(
            logprobs, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not hash logprobs: %s", exc)
        return None


def compare_canary_runs(
    baseline: list[dict[str, Any]], current: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare two sets of canary records to detect model drift (design.md §4.7).

    Args:
        baseline: Canary records from week 1 or baseline run.
        current: Canary records from current weekly run.

    Returns:
        Dict summarizing comparison:
        - total_compared: Number of matched (prompt_id, model_alias) pairs
        - changed_count: Number of prompts where output_hash changed
        - drift_detected: True if changed_count > 0
        - changes: List of change detail dicts
    """
    baseline_map: dict[tuple[str, str], dict[str, Any]] = {
        (str(row["prompt_id"]), str(row.get("model_alias", ""))): row for row in baseline
    }

    changes: list[dict[str, Any]] = []
    total_compared = 0

    for curr_row in current:
        key = (str(curr_row["prompt_id"]), str(curr_row.get("model_alias", "")))
        if key not in baseline_map:
            continue

        total_compared += 1
        base_row = baseline_map[key]
        base_hash = base_row.get("output_hash", "")
        curr_hash = curr_row.get("output_hash", "")

        if base_hash != curr_hash:
            changes.append(
                {
                    "prompt_id": key[0],
                    "model_alias": key[1],
                    "baseline_hash": base_hash,
                    "current_hash": curr_hash,
                    "baseline_model_id": base_row.get("returned_model_id"),
                    "current_model_id": curr_row.get("returned_model_id"),
                }
            )

    drift_detected = len(changes) > 0
    return {
        "total_compared": total_compared,
        "changed_count": len(changes),
        "drift_detected": drift_detected,
        "changes": changes,
    }
