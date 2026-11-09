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
import os
from pathlib import Path

from huggingface_hub import HfApi

logger = logging.getLogger(__name__)


def upload_bundle(
    run_dir: Path | None = None,
    *,
    repo_id: str,
    week: str,
    token: str | None = None,
    repo_type: str = "dataset",
    is_dry_run: bool = False,
    weekly_run_dir: Path | None = None,
) -> str:
    """Upload a weekly or dry-run bundle directory to Hugging Face Datasets.

    Args:
        run_dir: Directory containing ``trials.parquet`` and ``meta.json``.
        repo_id: HF repo ID (e.g. ``"rdvprasad36/driftwatch-te-data"``).
        week: ISO date string used as subdirectory on HF.
        token: HF API token. If ``None``, reads from ``HF_TOKEN`` env var.
        repo_type: HF repo type (default ``"dataset"``).
        is_dry_run: If True, uploads to ``dryrun/<week>/``; otherwise ``weekly/<week>/``.
        weekly_run_dir: Alias for *run_dir*.

    Returns:
        URL string from the upload response.

    Raises:
        ValueError: If neither *run_dir* nor *weekly_run_dir* is provided,
            or if *token* is empty/unset.
        FileNotFoundError: If ``trials.parquet`` does not exist in target dir.
    """
    target_dir = run_dir if run_dir is not None else weekly_run_dir
    if target_dir is None:
        msg = "run_dir (or weekly_run_dir) must be provided."
        raise ValueError(msg)

    if token is None:
        token = os.environ.get("HF_TOKEN")

    if not token:
        msg = "HF_TOKEN is required for upload. Set the HF_TOKEN environment variable."
        raise ValueError(msg)

    parquet_path = target_dir / "trials.parquet"
    if not parquet_path.exists():
        msg = f"trials.parquet not found in {target_dir}"
        raise FileNotFoundError(msg)

    api = HfApi(token=token)

    prefix = "dryrun" if is_dry_run else "weekly"
    path_in_repo = f"{prefix}/{week}"

    logger.info(
        "Uploading %s → %s/%s",
        target_dir,
        repo_id,
        path_in_repo,
    )

    api.upload_folder(
        folder_path=str(target_dir),
        repo_id=repo_id,
        path_in_repo=path_in_repo,
        repo_type=repo_type,
    )

    url = f"https://huggingface.co/datasets/{repo_id}/tree/main/{path_in_repo}"
    logger.info("Upload complete: %s", url)
    return url


upload_weekly_bundle = upload_bundle
