"""DriftWatch-TE CLI.

Commands (design.md §6):
  driftwatch freeze   — compute and lock suite hashes
  driftwatch verify   — fail if suite hash changed
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from driftwatch.suites.integrity import freeze_suites, verify_suites

# Exit codes per design.md §6
EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_HARNESS_ERROR = 2
EXIT_HASH_MISMATCH = 3


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """DriftWatch-TE: longitudinal security drift measurement."""
    _setup_logging(verbose)


@cli.command()
@click.option(
    "--suites-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("suites"),
    help="Path to the suites root directory.",
)
def freeze(suites_dir: Path) -> None:
    """Compute and lock suite hashes (FR1).

    Existing locked hashes are never overwritten. If a suite's content
    has changed from its locked hash, this command fails.
    """
    try:
        lock = freeze_suites(suites_dir)
        count = len(lock.entries)
        click.echo(f"Locked {count} suite(s). Lock file written.")
        sys.exit(EXIT_OK)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_HASH_MISMATCH)
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_HARNESS_ERROR)


@cli.command()
@click.option(
    "--suites-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("suites"),
    help="Path to the suites root directory.",
)
def verify(suites_dir: Path) -> None:
    """Verify that suite hashes match locked values (FR1).

    Exit code 3 on mismatch, per design.md §6.
    """
    try:
        result = verify_suites(suites_dir)
    except FileNotFoundError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(EXIT_HARNESS_ERROR)

    if result.ok:
        click.echo(f"Verified: {', '.join(result.ok)}")
    if result.unlocked:
        click.echo(f"Warning — unlocked suites: {', '.join(result.unlocked)}")
    if result.missing_on_disk:
        click.echo(f"ERROR — missing suites: {', '.join(result.missing_on_disk)}", err=True)
    if result.mismatched:
        for name, locked, current in result.mismatched:
            click.echo(
                f"ERROR — hash mismatch for '{name}': "
                f"locked={locked[:16]}..., current={current[:16]}...",
                err=True,
            )

    if result.passed:
        click.echo("All suite hashes verified.")
        sys.exit(EXIT_OK)
    else:
        sys.exit(EXIT_HASH_MISMATCH)
