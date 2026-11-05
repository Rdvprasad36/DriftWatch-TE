# DriftWatch-TE

[![CI](https://github.com/Rdvprasad36/DriftWatch-TE/actions/workflows/ci.yml/badge.svg)](https://github.com/Rdvprasad36/DriftWatch-TE/actions/workflows/ci.yml)
[![Pages](https://github.com/Rdvprasad36/DriftWatch-TE/actions/workflows/pages.yml/badge.svg)](https://github.com/Rdvprasad36/DriftWatch-TE/actions/workflows/pages.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![DOI](https://img.shields.io/badge/DOI-TODO%3A%2010.5281%2Fzenodo.TODO-blue.svg)](#citation)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

> **A Longitudinal Study of Security Drift in Hosted LLM Agents, with Telugu and Tenglish Attack Sets.**

---

## 1. Overview

Hosted LLM endpoints evolve constantly and silently through quantization tuning, routing tweaks, safety filter adjustments, and model weight refreshes. Prior research has studied performance and probability drift on static question-answering benchmarks, but whether **prompt injection Attack Success Rate (ASR) against tool-using agents drifts over time on the same hosted endpoint** remains unmeasured.

**DriftWatch-TE** is an open-source, reproducible research harness that evaluates hosted LLM endpoints against indirect prompt injection over 12 consecutive weeks. 

### Key Principles
1. **Zero-Dollar Budget ($0):** Built entirely using free-tier hosted model providers (OpenRouter, Groq, Cerebras) and scheduled via GitHub Actions.
2. **Deterministic Goal Predicates (FR4):** No LLM-as-a-judge is used for primary security outcomes. Attack success and task success are deterministic invariant checks over a simulated customer-service shop environment (`worlds/shop_v1.yaml`).
3. **Multilingual & Code-Mixed Attacks:** Evaluates three language conditions: English (`en`), Telugu in Telugu script (`te`), and Tenglish (code-mixed Telugu-English in Latin script, `te-Latn`).
4. **Human Native vs. Synthetic Comparison (H6):** Evaluates whether automated translation pipelines overestimate agent safety compared to human-authored native attacks.
5. **Pinned Invariance Negative Control (FR6, H3):** Concurrently evaluates a pinned local model with Two One-Sided Tests (TOST) within a $\pm 3\%$ equivalence margin to confirm harness stability.
6. **Immutable Open Data (FR7):** Result bundles are committed immutably as Apache Parquet files and uploaded to Hugging Face Datasets.

---

## 2. Research Questions & Hypotheses

Pre-registered on the Open Science Framework (OSF):
- **RQ1 Drift ($H_1$):** Does prompt injection ASR change over time on fixed hosted model aliases? Tested via Logistic GEE ($\beta_1 \neq 0$).
- **RQ2 Specificity ($H_2$):** Are security shifts accompanied by general capability degradation or canary output hash changes?
- **RQ3 Harness Validity ($H_3$):** Does the pinned local model remain invariant within $\pm 3\%$ ASR equivalence via TOST?
- **RQ4 Language Interaction ($H_4$):** Do Telugu and Tenglish exhibit differential drift rates relative to English? Tested via GEE interaction term ($\beta_3$).
- **RQ5 Disclosure:** What proportion of detected changepoints (PELT/CUSUM) correspond to public provider release notes?
- **RQ6 Native vs. Synthetic ($H_6$):** Do machine-generated attacks overestimate model robustness compared to human-authored attacks?

---

## 3. Repository Layout

```
driftwatch/
├── src/driftwatch/
│   ├── agent/           # Tool loop (max 8 steps, state evaluation)
│   ├── analysis/        # GEE, cluster bootstrap, PELT, CUSUM, TOST
│   ├── attacks/         # Injection channels (tool_output, tool_description)
│   ├── canary/          # Zero-temperature prompts & output hash comparator
│   ├── cli/             # Click command-line interface
│   ├── orchestrator/    # Concurrency, atomic ndjson writes, resume logic
│   ├── providers/       # OpenAI-compatible client, FakeProvider, retries
│   ├── schema/          # Pydantic v2 schemas for trials, suites, and worlds
│   ├── storage/         # Parquet serialization, summary JSONs, HF client
│   ├── suites/          # Suite loader and cryptographic hash verification
│   └── world/           # Mock shop environment, 5 tools, goal evaluator
├── suites/              # Locked, hashed YAML test suites (SUITE_LOCK.json)
├── dashboard/           # Single-file zero-build static dashboard (GitHub Pages)
├── events/              # Dated provider changelog log (FR11)
├── scripts/             # Release packaging & verification scripts
├── docs/                # AGENTS.md, prd.md, architecture.md, design.md
├── tests/               # 300+ offline unit & integration tests
├── DATASET_CARD.md      # Hugging Face dataset documentation
└── .zenodo.json         # Zenodo DOI archive metadata
```

---

## 4. Quickstart & Installation

Requires **Python 3.12+**.

```bash
# Clone repository
git clone https://github.com/Rdvprasad36/DriftWatch-TE.git
cd DriftWatch-TE

# Set up virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies and development tools
pip install -e ".[dev]"
```

Configure your environment variables if running live evaluations:
```bash
cp .env.example .env
# Edit .env with your free-tier API keys:
# OPENROUTER_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY, HF_TOKEN
```

---

## 5. Verification & Testing

All unit tests run completely offline without making external network calls using the built-in `FakeProvider`:

```bash
# Run complete test suite (340+ tests)
pytest -q

# Run static type checking
mypy src

# Run style and lint checks
ruff check .

# Verify frozen suite hashes
driftwatch verify
```

---

## 6. CLI Usage Guide

The `driftwatch` CLI provides commands for running, verifying, analyzing, and logging:

```bash
# Verify integrity of locked test suites
driftwatch verify

# Freeze suite hashes to suites/SUITE_LOCK.json
driftwatch freeze

# Execute a weekly trial run (e.g. offline smoke test with fake provider)
driftwatch run --week 2026-10-19 --suites canary --models fake --trials 2

# Run canary prompts at temperature 0.0
driftwatch canary --week 2026-10-19 --models fake

# Summarize weekly results into JSON
driftwatch summarize 2026-10-19

# Run pre-registered statistical analysis pipeline (GEE, Bootstrap, PELT, TOST)
driftwatch analyze --output-dir analysis/output --synthetic

# Log a provider changelog event
driftwatch event add --provider openrouter --model llama-3.1-8b \
  --date 2026-10-25 --url "https://openrouter.ai/changelog" \
  --note "Quantization tuning update"

# List recorded provider events
driftwatch event list

# Generate weekly report for a specific date
driftwatch weekly-report 2026-11-09

# Export trial records (CSV, JSONL, schema)
driftwatch export

# Generate final comprehensive research reports
driftwatch report
```

---

## 7. Test Your Own Model in 10 Minutes

You can evaluate any OpenAI-compatible LLM endpoint (local or remote) against the frozen DriftWatch-TE attack suites using the `--models custom` option without modifying harness code.

### Step 1: Set your API key environment variable
```bash
# Example for a custom provider or local proxy
export MY_API_KEY="your-secret-key-here"  # On Windows: set MY_API_KEY="your-secret-key-here"
```

### Step 2: Run evaluation trials
```bash
driftwatch run \
  --week 2026-11-09 \
  --suites attacks_v1 \
  --models custom \
  --base-url "https://api.together.xyz/v1" \
  --model "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo" \
  --api-key-env "MY_API_KEY" \
  --trials 3
```

For a local Ollama instance (no API key required, set any dummy value):
```bash
export OLLAMA_KEY="ollama"
driftwatch run \
  --week 2026-11-09 \
  --suites attacks_v1 \
  --models custom \
  --base-url "http://localhost:11434/v1" \
  --model "llama3.2:1b" \
  --api-key-env "OLLAMA_KEY" \
  --trials 3
```

### Step 3: Summarize and inspect results
```bash
# Generate weekly summary JSON
driftwatch summarize --week 2026-11-09

# Generate Markdown and HTML reports
driftwatch weekly-report 2026-11-09
```
The summary report will be available at `reports/weekly/2026-11-09.md` and `reports/weekly/2026-11-09.html`.

---

## 8. Interactive Dashboard

The results dashboard is deployed to GitHub Pages and can also be viewed locally without running a local web server:

```bash
# Open directly in your browser:
# Open dashboard/index.html in any modern browser
```

The dashboard includes 10 interactive views:
1. **Overview Grid:** Longitudinal ASR time series per model with 95% cluster bootstrap intervals, status strip, circular progress ring, and pilot panel.
2. **Drift Analysis (Output 1):** Hosted model curves with shaded 95% confidence bands and pinned local reference line.
3. **Language Breakdown (Output 2):** Disaggregated results across English, Telugu, and Tenglish, comparing native vs. synthetic attack performance.
4. **Controls & Canary:** Benign task success rates alongside zero-temperature output hash stability and observed returned model IDs timeline.
5. **Change Points & Events:** PELT/CUSUM changepoint markers overlaid with provider changelog entries.
6. **Trial Records (Output 3):** Virtualized, filterable table of trial records with 25-column schema viewer and CSV/JSONL/Parquet downloads.
7. **Data Quality & Telemetry:** Audit trial execution completeness, HTTP retry and 429 rate-limiting events, token consumption, and response latency.
8. **Weekly Evaluation Reports:** Historical archive of weekly batches with previous/next controls, side-by-side comparison, and Markdown/HTML report downloads.
9. **Final Evaluation Report (Output 4):** Embedded research report viewer rendering `reports/report.html` with download and print options.
10. **Scientific Methodology:** Pre-registered hypotheses (H1 to H6), suite verification digests, and replication commands.

---

## 9. Automation & GitHub Actions Setup

DriftWatch-TE runs fully automated longitudinal evaluations via GitHub Actions on a zero-dollar budget.

### Repository Secrets & Variables
To enable automated evaluation runs, configure the following repository secrets under **Settings > Secrets and variables > Actions**:

| Secret Name | Required For | Description |
|---|---|---|
| `GROQ_API_KEY` | Hosted evaluation | Groq Cloud API key for evaluating `openai/gpt-oss-20b` |
| `GOOGLE_AI_API_KEY` | Hosted evaluation | Google AI Studio API key for evaluating `gemini-flash-latest` |
| `OPENROUTER_API_KEY` | Hosted evaluation | OpenRouter API key for evaluating free-tier hosted models |
| `HF_TOKEN` | Immutable storage | Hugging Face user access token with write permissions for dataset upload |

### GitHub Pages Setup
1. In the repository on GitHub, navigate to **Settings > Pages**.
2. Under **Build and deployment > Source**, select **GitHub Actions**.
3. Deployed site URL: `https://rdvprasad36.github.io/DriftWatch-TE/`

### First Manual Run
To execute your first manual evaluation without waiting for the Monday cron schedule:
1. Navigate to the **Actions** tab on GitHub.
2. Select **Weekly Evaluation Pipeline** from the left sidebar.
3. Click **Run workflow**, set `dry_run: true` (if running before the study launch date of 2026-11-09), and click **Run workflow**.

Alternatively, run an offline trial run locally with the fake provider:
```bash
python -m driftwatch.cli.main run --week 2026-11-09 --suites attacks_v1 --models fake --trials 2
```

### Where to Find Evaluation Outputs (Outputs 1 to 4)
- **Output 1 (Longitudinal Drift):**
  - Data: `results/analysis/analysis.json` (`per_model_trend` and GEE slope)
  - Dashboard: View at `#drift`
  - Report: Section 4 of `reports/report.md` and `reports/report.html`
- **Output 2 (Multilingual Telugu & Tenglish Disparity):**
  - Data: `results/analysis/analysis.json` (`language_interactions` and `native_vs_machine`)
  - Dashboard: View at `#languages`
  - Report: Section 5 of `reports/report.md` and `reports/report.html`
- **Output 3 (Trial Records Export):**
  - Data: `results/exports/records.csv`, `results/exports/records.jsonl`, and `results/exports/schema.json`
  - Dashboard: View and search at `#data`
- **Output 4 (Evaluation Reports):**
  - Final Report: `reports/report.md` and `reports/report.html` (Dashboard `#report`)
  - Weekly Reports: `reports/weekly/<date>.md`, `reports/weekly/<date>.html`, and `reports/weekly/index.json` (Dashboard `#weekly-reports`)

### How to Verify Suite Integrity Offline
All test suites are frozen and locked with SHA-256 cryptographic hashes in `suites/SUITE_LOCK.json`. To verify that test suites have not been modified or tampered with:
```bash
driftwatch verify
```
This runs completely offline and fails with exit code 3 if any scenario prompt, injection string, or evaluation invariant has been altered.

---

## 10. Responsible Research & Ethics

- **Sandboxed Execution:** All attacks target mock e-commerce tools exclusively (`get_order_status`, `request_refund`, `search_catalog`, `apply_discount`, `cancel_order`). No real external APIs or personal accounts are ever contacted.
- **Header Redaction:** API authorization keys and tokens are scrubbed from all in-memory traces and serialized bundles.
- **Provider Terms:** Evaluations respect free-tier provider rate limits and concurrency constraints. Serious vulnerabilities are disclosed responsibly.

---

## 11. Citation

```bibtex
@misc{driftwatch2026,
  title={DriftWatch-TE: A Longitudinal Study of Security Drift in Hosted LLM Agents with Telugu and Tenglish Attack Sets},
  author={TODO: Author Name(s)},
  year={2026},
  publisher={Zenodo},
  doi={TODO: 10.5281/zenodo.TODO},
  url={https://github.com/Rdvprasad36/DriftWatch-TE}
}
```

---

## 12. License

This project is licensed under the **Apache License 2.0**. Test suites and datasets are released under **CC-BY 4.0**.

