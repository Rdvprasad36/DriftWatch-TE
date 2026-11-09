#!/usr/bin/env python3
"""Add base_id field to all attack scenario YAML files in suites/attacks_v1/.

base_id = atk_<NN>_<attack_class> — shared across lang and channel variants.
Safe to run multiple times (idempotent: skips if base_id already present).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ATTACKS_DIR = REPO_ROOT / "suites" / "attacks_v1"

# Pattern: atk_<NN>_<class_words...>_(desc|out)_(en|te|te_latn)
FNAME_RE = re.compile(r"^(atk_\d+_(?P<class>.+?))_(desc|out)_(en|te|te_latn)$")


def derive_base_id(stem: str) -> str | None:
    """Derive base_id from filename stem, e.g. atk_01_unauthorized_refund_desc_en -> atk_01_unauthorized_refund."""
    m = FNAME_RE.match(stem)
    if m:
        return m.group(1)
    return None


def inject_base_id(path: Path, base_id: str) -> bool:
    """Insert base_id line after the 'id:' line. Returns True if file was modified."""
    text = path.read_text(encoding="utf-8")
    if "base_id:" in text:
        return False  # already present

    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if not inserted and line.startswith("id:"):
            new_lines.append(f"base_id: {base_id}\n")
            inserted = True
    if not inserted:
        return False

    path.write_text("".join(new_lines), encoding="utf-8")
    return True


def main() -> None:
    yaml_files = sorted(ATTACKS_DIR.glob("atk_*.yaml"))
    modified = 0
    skipped = 0
    errors = 0
    for yf in yaml_files:
        base_id = derive_base_id(yf.stem)
        if base_id is None:
            print(f"  WARN: cannot derive base_id from {yf.name}")
            errors += 1
            continue
        if inject_base_id(yf, base_id):
            print(f"  + {yf.name}  ->  base_id: {base_id}")
            modified += 1
        else:
            skipped += 1

    print(f"\nDone: {modified} modified, {skipped} already had base_id, {errors} errors.")


if __name__ == "__main__":
    main()
