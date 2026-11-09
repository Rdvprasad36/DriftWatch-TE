"""Run a tiny live pilot to verify Telugu/Tenglish output and predicates behave.

Runs:
- 2 trials per scenario
- 2 scenarios per class (e.g. 2 en, 2 te, 2 te-Latn across attack classes)
- Each provider that is available in registry (or fake if no external API configured)
- Results written to temporary non-committed directory tmp/pilot/
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from driftwatch.orchestrator.jobs import expand_jobs
from driftwatch.orchestrator.runner import run_jobs
from driftwatch.orchestrator.writer import RunWriter
from driftwatch.providers.registry import build_from_env
from driftwatch.suites.loader import load_suite


def main():
    pilot_dir = Path("tmp_pilot")
    if pilot_dir.exists():
        shutil.rmtree(pilot_dir)
    pilot_dir.mkdir(parents=True, exist_ok=True)

    suite = load_suite(Path("suites/attacks_v1"))

    # Select 2 scenarios per class across languages (including Telugu and Tenglish)
    selected_scenarios = []
    # Pick sample scenarios: 2 te, 2 te-Latn, 2 en
    for lang in ["te", "te-Latn", "en"]:
        matching = [s for s in suite.scenarios if str(s.language) == lang]
        selected_scenarios.extend(matching[:2])

    print(f"Selected {len(selected_scenarios)} scenarios for pilot:")
    for s in selected_scenarios:
        print(f"  - {s.id} ({s.language}, channel={s.channel}, class={s.attack_class})")

    from driftwatch.cli.main import _build_fake_provider_registry

    reg = _build_fake_provider_registry()

    # Check live models
    try:
        env_reg = build_from_env()
        for alias in ["google", "groq"]:
            if alias in env_reg:
                reg.register(alias, env_reg.get(alias))
    except Exception as exc:
        print(f"Env notice: {exc}")

    models_to_test = [m for m in ["google", "fake"] if m in reg][:2]
    print(f"Selected pilot models: {models_to_test}")

    # Build mini manifest
    from driftwatch.schema.models import SuiteManifest

    mini_manifest = SuiteManifest(
        name="attacks_v1",
        version="pilot",
        scenarios=selected_scenarios,
        suite_hash="pilot_hash",
    )

    jobs = expand_jobs(
        suites=[mini_manifest],
        model_aliases=models_to_test,
        trials=2,
    )
    print(f"Running {len(jobs)} pilot trial jobs...")

    writer = RunWriter(pilot_dir, week="2026-11-06", planned=len(jobs))
    summary = asyncio.run(
        run_jobs(
            jobs=jobs,
            provider_registry=reg,
            suite_root=Path("suites"),
            writer=writer,
            concurrency=1,
        )
    )
    writer.finalize(allow_overwrite=True)

    print(f"\nPilot finished: completed={summary.completed}, errors={summary.errors}")

    # Check that Telugu and Tenglish responses were evaluated properly
    ndjson_path = pilot_dir / "trials.ndjson"
    if ndjson_path.exists():
        records = [
            json.loads(line)
            for line in ndjson_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for rec in records:
            print(
                f"Trial {rec['job_id']}: lang={rec['language']}, atk_succ={rec['attack_success']}, task_succ={rec['task_success']}, steps={rec['steps']}, error={rec['error_type']}"
            )

    print("\nPilot data safely contained in tmp_pilot/ (not committed).")


if __name__ == "__main__":
    main()
