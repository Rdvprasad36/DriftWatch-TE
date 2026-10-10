"""Payload loader for DriftWatch-TE attack suites.

Payloads are plain-text files stored inside frozen suite directories.
They are loaded by the orchestrator before each trial and passed to the
:class:`~driftwatch.attacks.injector.AttackInjector`.

Security invariants (AGENTS.md rules 1, 9):
- Payloads are *read*, never written or generated at runtime.
- ``payload_ref`` is relative to the suite directory only; path traversal
  outside the suite root is rejected with :class:`ValueError`.
- Only ``suites/<suite_name>/`` paths may be referenced; the guard prevents
  access to world files, source code, secrets or anything else in the repo.

Usage::

    from pathlib import Path
    from driftwatch.attacks.loader import load_payload

    suite_dir = Path("suites/attacks_v1")
    payload = load_payload("payloads/refund_override_en_01.txt", suite_dir)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_payload(payload_ref: str, suite_dir: Path) -> str:
    """Load and return the payload text from *suite_dir* / *payload_ref*.

    Args:
        payload_ref: Relative path to the payload file, e.g.
            ``"payloads/refund_override_en_01.txt"``.  Must not escape
            *suite_dir* (path traversal is rejected).
        suite_dir: Absolute or relative path to the suite root directory,
            e.g. ``Path("suites/attacks_v1")``.

    Returns:
        The payload text exactly as stored (no stripping or normalisation).

    Raises:
        ValueError: If *payload_ref* resolves outside *suite_dir* (path
            traversal attempt, AGENTS.md rule 9).
        FileNotFoundError: If the resolved file does not exist.
    """
    suite_root = suite_dir.resolve()
    # Join then resolve: this collapses any ../ components
    target = (suite_dir / payload_ref).resolve()

    # Guard: resolved target must be strictly inside suite_root
    try:
        target.relative_to(suite_root)
    except ValueError:
        msg = (
            f"Path traversal detected: '{payload_ref}' resolves outside "
            f"suite directory '{suite_root}'."
        )
        raise ValueError(msg) from None

    if not target.exists():
        msg = f"Payload file not found: '{target}' (payload_ref='{payload_ref}')."
        raise FileNotFoundError(msg)

    text = target.read_text(encoding="utf-8")
    logger.debug(
        "Loaded payload '%s' (%d chars) from suite '%s'.", payload_ref, len(text), suite_dir.name
    )
    return text
