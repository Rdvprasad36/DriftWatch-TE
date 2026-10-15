"""Hugging Face Datasets upload for DriftWatch-TE bundles.

Architecture.md §3.7:
  "Raw bundles: Hugging Face Datasets repo (weekly/YYYY-MM-DD/),
   pushed by the workflow with a token."

AGENTS.md rule 4:
  "No secrets in the repo, logs or traces. Keys come from environment
   variables."

Upload is gated behind the ``HF_TOKEN`` environment variable.  Without
a token the function raises ``ValueError`` — no silent fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path

from huggingface_hub import HfApi

logger = logging.getLogger(__name__)


def upload_bundle(
    run_dir: Path,
    *,
    repo_id: str,
    week: str,
    token: str | None = None,
    repo_type: str = "dataset",
) -> str:
    """Upload a weekly bundle directory to Hugging Face Datasets.

    Args:
        run_dir: Directory containing ``trials.parquet`` and ``meta.json``.
        repo_id: HF repo ID (e.g. ``"user/driftwatch-data"``).
        week: ISO date string used as subdirectory on HF.
        token: HF API token.  If ``None``, raises :class:`ValueError`.
        repo_type: HF repo type (default ``"dataset"``).

    Returns:
        URL string from the upload response.

    Raises:
        ValueError: If *token* is ``None`` or empty.
        FileNotFoundError: If ``trials.parquet`` does not exist in *run_dir*.
    """
    if not token:
        msg = (
            "HF_TOKEN is required for upload. "
            "Set the HF_TOKEN environment variable."
        )
        raise ValueError(msg)

    parquet_path = run_dir / "trials.parquet"
    if not parquet_path.exists():
        msg = f"trials.parquet not found in {run_dir}"
        raise FileNotFoundError(msg)

    api = HfApi(token=token)

    path_in_repo = f"weekly/{week}"

    logger.info(
        "Uploading %s → %s/%s",
        run_dir,
        repo_id,
        path_in_repo,
    )

    api.upload_folder(
        folder_path=str(run_dir),
        repo_id=repo_id,
        path_in_repo=path_in_repo,
        repo_type=repo_type,
    )

    url = f"https://huggingface.co/datasets/{repo_id}/tree/main/{path_in_repo}"
    logger.info("Upload complete: %s", url)
    return url

