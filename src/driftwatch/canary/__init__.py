"""Canary prompt runner and output hashing (FR5).

Architecture.md §3.1, §4:
  Canary suite: 20 prompts, temperature 0.
  Output hash, logprobs where offered.
  Canary row: prompt_id, output_hash, top_logprobs_hash, returned_model_id.
"""

from __future__ import annotations

from driftwatch.canary.hashing import (
    compare_canary_runs,
    compute_logprobs_hash,
    compute_output_hash,
)
from driftwatch.canary.runner import (
    CanaryPrompt,
    CanaryResult,
    load_canary_prompts,
    run_canaries,
    write_canary_bundle,
)

__all__ = [
    "CanaryPrompt",
    "CanaryResult",
    "compare_canary_runs",
    "compute_logprobs_hash",
    "compute_output_hash",
    "load_canary_prompts",
    "run_canaries",
    "write_canary_bundle",
]

