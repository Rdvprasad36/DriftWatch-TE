"""Suite loader: reads YAML scenario files, validates schemas, computes stable hashes.

The hash is SHA-256 over the canonical JSON of all scenario files in a suite,
sorted by filename to ensure stability across machines and file orderings (FR1).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import yaml

from driftwatch.schema.models import Scenario, SuiteManifest

logger = logging.getLogger(__name__)


def _canonical_json(obj: object) -> str:
    """Produce deterministic JSON for hashing.

    Keys are sorted, no trailing whitespace, consistent separators.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _compute_suite_hash(suite_dir: Path) -> str:
    """Compute SHA-256 over all files in a suite directory.

    Files are sorted by name for cross-platform stability.
    The hash covers both YAML scenario files and any referenced payload files.
    """
    hasher = hashlib.sha256()

    all_files = sorted(suite_dir.rglob("*"), key=lambda p: p.as_posix())
    for file_path in all_files:
        if file_path.is_file():
            # Include relative path in hash so renames are detected
            rel = file_path.relative_to(suite_dir).as_posix()
            hasher.update(rel.encode("utf-8"))
            hasher.update(file_path.read_bytes())

    return hasher.hexdigest()


def _load_scenario_file(path: Path) -> list[Scenario]:
    """Load and validate one YAML scenario file.

    A file may contain a single scenario dict or a list of scenarios.
    """
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        return []

    if isinstance(raw, dict):
        raw_list: list[dict[str, object]] = [raw]
    elif isinstance(raw, list):
        raw_list = raw
    else:
        msg = f"Expected dict or list in {path}, got {type(raw).__name__}"
        raise ValueError(msg)

    scenarios: list[Scenario] = []
    for item in raw_list:
        scenario = Scenario.model_validate(item)
        scenarios.append(scenario)

    return scenarios


def load_suite(suite_dir: Path) -> SuiteManifest:
    """Load all scenarios from a suite directory and compute its hash.

    Args:
        suite_dir: Path to the suite directory containing YAML files.

    Returns:
        SuiteManifest with validated scenarios and a stable SHA-256 hash.

    Raises:
        FileNotFoundError: If suite_dir does not exist.
        ValueError: If any scenario file is invalid.
    """
    if not suite_dir.is_dir():
        msg = f"Suite directory does not exist: {suite_dir}"
        raise FileNotFoundError(msg)

    yaml_files = sorted(suite_dir.glob("*.yaml"), key=lambda p: p.name)
    yml_files = sorted(suite_dir.glob("*.yml"), key=lambda p: p.name)
    all_yaml = sorted(set(yaml_files) | set(yml_files), key=lambda p: p.name)

    if not all_yaml:
        msg = f"No YAML files found in suite directory: {suite_dir}"
        raise ValueError(msg)

    scenarios: list[Scenario] = []
    for yaml_path in all_yaml:
        loaded = _load_scenario_file(yaml_path)
        scenarios.extend(loaded)
        logger.debug("Loaded %d scenarios from %s", len(loaded), yaml_path.name)

    suite_hash = _compute_suite_hash(suite_dir)
    suite_name = suite_dir.name

    logger.info("Suite '%s': %d scenarios, hash=%s", suite_name, len(scenarios), suite_hash[:16])

    return SuiteManifest(
        name=suite_name,
        scenarios=scenarios,
        suite_hash=suite_hash,
    )


def load_all_suites(suites_root: Path) -> dict[str, SuiteManifest]:
    """Load all suites from the suites root directory.

    Args:
        suites_root: Path containing suite subdirectories (e.g. suites/).

    Returns:
        Dict mapping suite name to SuiteManifest.
    """
    if not suites_root.is_dir():
        msg = f"Suites root does not exist: {suites_root}"
        raise FileNotFoundError(msg)

    manifests: dict[str, SuiteManifest] = {}
    for child in sorted(suites_root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            try:
                manifest = load_suite(child)
                manifests[manifest.name] = manifest
            except (ValueError, FileNotFoundError) as e:
                logger.warning("Skipping suite '%s': %s", child.name, e)

    return manifests
