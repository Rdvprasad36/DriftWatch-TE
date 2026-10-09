# AGENTS.md: Instructions for AI coding agents working on DriftWatch-TE

Read `prd.md`, `architecture.md` and `design.md` first. They are the source of truth. If code and docs disagree, stop and ask or update the docs in the same change.

## What this project is
A research harness that runs the same agent-attack suite against hosted LLM endpoints every week, records results immutably, and analyzes whether attack success changes over time. Research integrity matters more than features. **Everything must run on free tools.**

## Hard rules
1. **Never modify frozen suites** (`suites/`) after `driftwatch freeze` has locked them. CI must fail on a hash mismatch. New scenarios go into a new suite version.
2. **Never edit or delete past result bundles.** Results are append-only.
3. **No paid services or dependencies.** No hard-coded providers; use the provider abstraction.
4. **No secrets in the repo, logs or traces.** Redact auth headers before saving. Keys come from environment variables; document them in `.env.example`.
5. **Primary metric (attack success) must be a deterministic predicate** over world state. Do not use an LLM judge for it.
6. **Do not change prompts, tools, temperature, max steps or concurrency** in the weekly pipeline without a documented, versioned reason, because that would create fake drift.
7. **Never silently drop errors.** Failed jobs are recorded with an error type.
8. **Do not invent results, citations or numbers.** Use `TODO` instead. Cite only papers listed in `prd.md` unless the user provides more.
9. **Attacks only target the mock world.** No code that contacts real accounts or third-party services other than the LLM endpoints.
10. **Respect provider terms.** If unsure whether an action is allowed, ask the user.
11. **Pre-registered analysis is frozen** before Run 12. Do not tune analysis after seeing data. Extra analyses go in an `exploratory/` folder and are labeled exploratory.

## Setup and commands
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest -q                       # offline unit tests with a fake provider
ruff check . && ruff format .
mypy src
driftwatch verify               # suite hashes match locked values
driftwatch run --week 2026-10-19 --suites canary --models fake --trials 2   # smoke test
```
Unit tests must not call real LLM APIs. Use the `FakeProvider` (deterministic and configurable to be "vulnerable" or "robust"). Tests that need a real endpoint use `@pytest.mark.live` and are skipped by default.

## Code conventions
- Python 3.12, full type hints, Pydantic v2 schemas, `async` for I/O.
- Statistics are pure functions with docstrings that cite the method.
- Structured logging, no `print` in library code.
- Small modules matching `architecture.md` section 9.
- Commit messages: conventional commits, referencing the requirement ID (for example `feat(storage): atomic bundle writes (FR7)`).

## Testing requirements
- **Suites:** loader validates schema; hash is stable across machines and file orderings.
- **Agent loop:** with `FakeProvider(vulnerable)` ASR = 1, with `FakeProvider(robust)` ASR = 0, for every attack class and language.
- **Orchestrator:** resume after crash, no duplicate jobs, error rows recorded, quota backoff.
- **Storage:** bundles are immutable (writes to an existing week fail unless `--force-new-version`).
- **Analysis:** test GEE, bootstrap, TOST and change-point functions on synthetic data with known drift (planted step change at known week, planted null).
- Coverage above 90% on `analysis/`, `suites/`, `orchestrator/`.

## Build order (maps to the timeline)
1. `schema/` and `suites/` loader with hashing and `freeze` / `verify`.
2. `world/` mock shop, 5 tools, goal predicates.
3. `providers/` OpenAI-compatible client, `FakeProvider`, header/id capture, retries.
4. `agent/` thin tool loop (8 steps max).
5. `attacks/` injector for both channels.
6. `orchestrator/` jobs, concurrency, resume, atomic writes.
7. `storage/` Parquet bundles, Hugging Face upload, summary JSON.
8. `canary` runner and hashing.
9. GitHub Actions: `ci.yml`, then `weekly.yml` (matrix per model), then `pages.yml`.
10. **Dry runs (2 weeks) before freezing**, then freeze.
11. `analysis/`: GEE, bootstrap, change-point, TOST, plots (develop against synthetic data first).
12. Dashboard, dataset card, release scripts.

## Free-tier handling
- Fixed run hour and bounded concurrency; exponential backoff with jitter on 429/5xx.
- Store the **returned** model id every time. Free models are retired or changed without notice.
- If a model disappears mid-study, log an event, switch to the predefined fallback, and mark a series break. Do not splice series silently.
- Prefer reducing trials per scenario over reducing scenarios, after the power simulation in `design.md` section 4.6.

## Definition of done (per feature)
Requirement ID referenced; tests added and passing; lint and types clean; works offline with `FakeProvider`; docs updated; no new paid dependency; no secret in the diff; no change to frozen suites.

## When unsure
Ask. Research-validity questions (what counts as drift, how to handle missing data, exclusion rules) must be decided by the user and recorded in the preregistration, not guessed.
