"""DriftWatch-TE CLI.

Commands (design.md §6):
  driftwatch freeze   — compute and lock suite hashes
  driftwatch verify   — fail if suite hash changed
  driftwatch run      — execute a weekly trial run
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from driftwatch.providers.registry import ProviderRegistry

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
        click.echo(
            f"ERROR — missing suites: {', '.join(result.missing_on_disk)}",
            err=True,
        )
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


# ---------------------------------------------------------------------------
# driftwatch run
# ---------------------------------------------------------------------------


def _build_fake_provider_registry() -> ProviderRegistry:
    """Build a ProviderRegistry with an infinite FakeProvider.

    The infinite variant resets its index on exhaustion so the
    orchestrator can run arbitrarily many jobs without running out
    of scripted responses.
    """
    from driftwatch.providers.base import (
        ParsedToolCall,
        ProviderResponse,
    )
    from driftwatch.providers.fake import (
        FAKE_FINGERPRINT,
        FAKE_MODEL_ID,
        FakeProvider,
    )
    from driftwatch.providers.registry import ProviderRegistry

    class _InfiniteFakeProvider(FakeProvider):
        """FakeProvider that cycles responses instead of exhausting."""

        async def complete(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            model: str,
            temperature: float,
            max_tokens: int | None = None,
        ) -> ProviderResponse:
            if self._index >= len(self._responses):
                self._index = 0
            return await super().complete(
                messages, tools, model, temperature, max_tokens
            )

    responses = [
        ProviderResponse(
            requested_model=FAKE_MODEL_ID,
            returned_model=FAKE_MODEL_ID,
            fingerprint=FAKE_FINGERPRINT,
            content=None,
            tool_calls=[
                ParsedToolCall(
                    id="call_fake_0",
                    name="lookup_order",
                    arguments={"order_id": "1042"},
                )
            ],
            tokens_in=20,
            tokens_out=8,
            latency_ms=1.0,
            http_status=200,
            redacted_headers={"x-request-id": "fake-req-run"},
        ),
        ProviderResponse(
            requested_model=FAKE_MODEL_ID,
            returned_model=FAKE_MODEL_ID,
            fingerprint=FAKE_FINGERPRINT,
            content="Order 1042 is being processed.",
            tool_calls=[],
            tokens_in=20,
            tokens_out=6,
            latency_ms=1.0,
            http_status=200,
            redacted_headers={"x-request-id": "fake-req-run"},
        ),
    ]

    registry = ProviderRegistry()
    registry.register("fake", _InfiniteFakeProvider(responses=responses * 10))
    return registry


@cli.command()
@click.option("--week", required=True, help="ISO week date, e.g. 2026-10-19.")
@click.option(
    "--suites", required=True, help="Comma-separated suite names to run."
)
@click.option(
    "--models", required=True, help="Comma-separated model aliases."
)
@click.option("--trials", default=5, type=int, help="Trials per scenario.")
@click.option(
    "--results-dir",
    default="weekly",
    help="Root directory for result bundles.",
)
@click.option(
    "--suite-root",
    default="suites",
    help="Root directory containing suite subdirectories.",
)
@click.option(
    "--concurrency",
    default=4,
    type=int,
    help="Max simultaneous LLM calls.",
)
def run(
    week: str,
    suites: str,
    models: str,
    trials: int,
    results_dir: str,
    suite_root: str,
    concurrency: int,
) -> None:
    """Execute a weekly trial run (FR2, FR7).

    Loads requested suites, expands jobs, runs them with bounded
    concurrency, writes NDJSON results, and finalizes the bundle.
    """
    from driftwatch.orchestrator.jobs import expand_jobs
    from driftwatch.orchestrator.runner import run_jobs
    from driftwatch.orchestrator.writer import RunWriter
    from driftwatch.suites.loader import load_suite

    suite_root_path = Path(suite_root)
    requested = [s.strip() for s in suites.split(",") if s.strip()]
    model_list = [m.strip() for m in models.split(",") if m.strip()]

    # Load requested suites
    loaded_suites = []
    for name in requested:
        suite_dir = suite_root_path / name
        if not suite_dir.is_dir():
            click.echo(f"ERROR: suite '{name}' not found in {suite_root_path}", err=True)
            sys.exit(EXIT_HARNESS_ERROR)
        try:
            loaded_suites.append(load_suite(suite_dir))
        except (ValueError, FileNotFoundError) as exc:
            click.echo(f"ERROR loading suite '{name}': {exc}", err=True)
            sys.exit(EXIT_HARNESS_ERROR)

    # Build provider registry
    if model_list == ["fake"]:
        registry = _build_fake_provider_registry()
    else:
        # Real providers: build from env (for future use)
        from driftwatch.providers.registry import ProviderRegistry

        registry = ProviderRegistry()
        click.echo(
            "WARNING: non-fake models require env-based provider setup.",
            err=True,
        )

    # Expand jobs
    jobs = expand_jobs(loaded_suites, model_list, trials)
    if not jobs:
        click.echo("No jobs to run.")
        sys.exit(EXIT_OK)

    # Set up writer and run
    run_dir = Path(results_dir) / week
    writer = RunWriter(run_dir=run_dir, week=week, planned=len(jobs))

    try:
        summary = asyncio.run(
            run_jobs(
                jobs,
                provider_registry=registry,
                suite_root=suite_root_path,
                writer=writer,
                concurrency=concurrency,
            )
        )
    except Exception as exc:
        click.echo(f"ERROR: run failed: {exc}", err=True)
        sys.exit(EXIT_HARNESS_ERROR)

    # Finalize writer and convert to Parquet bundle (FR7)
    try:
        from driftwatch.storage.bundle import finalize_bundle

        writer.finalize(allow_overwrite=True)
        finalize_bundle(run_dir, week=week, allow_overwrite=True)
    except Exception as exc:
        click.echo(f"ERROR finalizing: {exc}", err=True)
        sys.exit(EXIT_HARNESS_ERROR)

    click.echo(
        f"Run complete: {summary.completed} completed, "
        f"{summary.skipped} skipped, {summary.errors} errors."
    )

    if summary.errors > 0:
        sys.exit(EXIT_PARTIAL)
    else:
        sys.exit(EXIT_OK)



# ---------------------------------------------------------------------------
# driftwatch summarize
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--week", required=True, help="ISO week date, e.g. 2026-10-19.")
@click.option(
    "--results-dir",
    default="weekly",
    help="Root directory containing weekly run bundles.",
)
@click.option(
    "--output-dir",
    default="results/summary",
    help="Output directory for summary JSON files.",
)
def summarize(week: str, results_dir: str, output_dir: str) -> None:
    """Generate a summary JSON for a weekly run (FR7).

    Reads trials.parquet from the run bundle and writes a compact
    summary to results/summary/<week>.json for the dashboard.
    """
    from driftwatch.storage.summary import write_summary

    run_dir = Path(results_dir) / week
    if not run_dir.is_dir():
        click.echo(
            f"ERROR: run directory '{run_dir}' not found.", err=True
        )
        sys.exit(EXIT_HARNESS_ERROR)

    parquet_path = run_dir / "trials.parquet"
    if not parquet_path.exists():
        click.echo(
            f"ERROR: trials.parquet not found in '{run_dir}'. "
            "Run `driftwatch run` first.",
            err=True,
        )
        sys.exit(EXIT_HARNESS_ERROR)

    try:
        path = write_summary(
            run_dir, week=week, output_dir=Path(output_dir)
        )
        click.echo(f"Summary written: {path}")
        sys.exit(EXIT_OK)
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_HARNESS_ERROR)


# ---------------------------------------------------------------------------
# driftwatch canary
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--week", required=True, help="ISO week date, e.g. 2026-10-19.")
@click.option(
    "--models", required=True, help="Comma-separated model aliases."
)
@click.option(
    "--suite-dir",
    default="suites/canary",
    help="Path to canary suite directory.",
)
@click.option(
    "--results-dir",
    default="weekly",
    help="Root directory for result bundles.",
)
def canary(week: str, models: str, suite_dir: str, results_dir: str) -> None:
    """Execute canary prompts at temperature 0.0 (FR5).

    Detects underlying model changes by recording deterministic output hashes.
    Saves output to weekly/<week>/canary.json.
    """
    from driftwatch.canary.runner import (
        load_canary_prompts,
        run_canaries,
        write_canary_bundle,
    )

    suite_path = Path(suite_dir)
    if not suite_path.is_dir():
        click.echo(f"ERROR: canary suite directory '{suite_path}' not found.", err=True)
        sys.exit(EXIT_HARNESS_ERROR)

    try:
        prompts = load_canary_prompts(suite_path)
    except Exception as exc:
        click.echo(f"ERROR loading canary suite: {exc}", err=True)
        sys.exit(EXIT_HARNESS_ERROR)

    model_list = [m.strip() for m in models.split(",") if m.strip()]

    if model_list == ["fake"]:
        registry = _build_fake_provider_registry()
    else:
        from driftwatch.providers.registry import ProviderRegistry

        registry = ProviderRegistry()
        click.echo(
            "WARNING: non-fake models require env-based provider setup.",
            err=True,
        )

    run_dir = Path(results_dir) / week

    try:
        results = asyncio.run(
            run_canaries(
                prompts,
                provider_registry=registry,
                model_aliases=model_list,
            )
        )
        out_path = write_canary_bundle(results, run_dir, week=week)
        click.echo(f"Canary bundle written: {out_path} ({len(results)} prompt(s))")
        sys.exit(EXIT_OK)
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(EXIT_HARNESS_ERROR)


if __name__ == "__main__":
    cli()
