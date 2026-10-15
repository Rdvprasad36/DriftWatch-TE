#!/usr/bin/env python3
"""Release preparation and validation script (FR12).

Verifies integrity of the release bundle:
1. Suite lock and verification (suites/SUITE_LOCK.json).
2. Zenodo metadata (.zenodo.json).
3. Dataset card (DATASET_CARD.md) and README.md.
4. Dashboard distribution (dashboard/index.html).
5. Packages distribution bundle with SHA-256 checksums.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path

from driftwatch.suites.integrity import verify_suites


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_release(repo_root: Path) -> list[str]:
    """Check all prerequisites for a clean, reproducible release."""
    errors: list[str] = []

    # 1. Verify suite integrity
    suites_dir = repo_root / "suites"
    if not suites_dir.is_dir():
        errors.append("suites/ directory not found.")
    else:
        try:
            res = verify_suites(suites_dir)
            if res.mismatched:
                errors.append(f"Suite hash mismatch: {res.mismatched}")
            if res.missing_on_disk:
                errors.append(f"Missing suites: {res.missing_on_disk}")
        except Exception as exc:
            errors.append(f"Suite verification failed: {exc}")

    # 2. Check documentation files
    for fname in ["README.md", "DATASET_CARD.md", ".zenodo.json", "dashboard/index.html"]:
        fpath = repo_root / fname
        if not fpath.is_file():
            errors.append(f"Required release file missing: {fname}")

    # 3. Validate Zenodo JSON
    zenodo_path = repo_root / ".zenodo.json"
    if zenodo_path.is_file():
        try:
            z_data = json.loads(zenodo_path.read_text(encoding="utf-8"))
            for req in ["title", "description", "creators", "license"]:
                if req not in z_data:
                    errors.append(f".zenodo.json missing key: {req}")
        except Exception as exc:
            errors.append(f"Invalid .zenodo.json: {exc}")

    return errors


def build_release_bundle(repo_root: Path, out_dir: Path) -> Path:
    """Build tar.gz release bundle and checksum file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_name = "driftwatch-te-release.tar.gz"
    bundle_path = out_dir / bundle_name

    included_paths = [
        "src",
        "suites",
        "worlds",
        "dashboard",
        "docs",
        "pyproject.toml",
        "README.md",
        "DATASET_CARD.md",
        ".zenodo.json",
    ]

    with tarfile.open(bundle_path, "w:gz") as tar:
        for item in included_paths:
            p = repo_root / item
            if p.exists():
                tar.add(str(p), arcname=item)

    checksum = compute_sha256(bundle_path)
    checksum_file = out_dir / f"{bundle_name}.sha256"
    checksum_file.write_text(f"{checksum}  {bundle_name}\n", encoding="utf-8")

    return bundle_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and verify DriftWatch-TE release.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Perform verification only.")
    parser.add_argument(
        "--out-dir",
        default="dist",
        help="Output directory for release artifacts.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    print("Verifying release prerequisites...")
    errors = verify_release(repo_root)
    if errors:
        print("ERROR: Release verification failed with the following issues:")
        for err in errors:
            print(f"  - {err}")
        return 1

    if args.dry_run:
        print("Dry-run verification passed! All release prerequisites are satisfied.")
        return 0

    print("Packaging release distribution...")
    bundle_path = build_release_bundle(repo_root, repo_root / args.out_dir)
    print(f"Release bundle created: {bundle_path}")
    print(f"Checksum: {compute_sha256(bundle_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
