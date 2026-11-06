"""Central study configuration loader for DriftWatch-TE.

Reads and validates config/study.yaml, providing strongly typed access to:
  - STUDY_START_DATE
  - planned_weeks
  - models (alias, provider, requested_id)
  - hf_dataset_repo
  - github_repo
  - preregistration_url
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ModelConfig(BaseModel):
    """Configuration for a benchmarked model."""

    alias: str
    provider: str
    requested_id: str
    justification: str | None = None


class StudyConfig(BaseModel):
    """Global configuration for the longitudinal study."""

    study_start_date: str = "2026-11-09"
    planned_weeks: int = 12
    github_repo: str = "https://github.com/Rdvprasad36/DriftWatch-TE"
    hf_dataset_repo: str = "TODO"
    preregistration_url: str = "TODO"
    local_model_digest: str = "baf6a787fdff"
    models: list[ModelConfig] = Field(default_factory=list)


def find_study_config_file(start_path: Path | None = None) -> Path:
    """Find config/study.yaml by looking at start_path and its parents."""
    curr = (start_path or Path.cwd()).resolve()
    for directory in [curr, *curr.parents]:
        candidate = directory / "config" / "study.yaml"
        if candidate.is_file():
            return candidate
    return Path("config/study.yaml")


def load_study_config(config_path: Path | None = None) -> StudyConfig:
    """Load and validate the study configuration.

    If config/study.yaml does not exist, defaults are used.
    """
    path = config_path or find_study_config_file()
    if not path.is_file():
        logger.warning("Study config file '%s' not found; using defaults.", path)
        return StudyConfig()

    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return StudyConfig.model_validate(data)
    except Exception as exc:
        logger.error("Failed to load study config from '%s': %s", path, exc)
        return StudyConfig()

