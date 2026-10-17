# DriftWatch-TE

[![CI](https://github.com/driftwatch-te/driftwatch/actions/workflows/ci.yml/badge.svg)](https://github.com/driftwatch-te/driftwatch/actions/workflows/ci.yml)
[![Pages](https://github.com/driftwatch-te/driftwatch/actions/workflows/pages.yml/badge.svg)](https://github.com/driftwatch-te/driftwatch/actions/workflows/pages.yml)
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
git clone https://github.com/driftwatch-te/driftwatch.git
cd driftwatch

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
```

---

## 7. Interactive Dashboard

The results dashboard is deployed to GitHub Pages and can also be viewed locally without running a local web server:

```bash
# Open directly in your browser:
# Open dashboard/index.html in any modern browser
```

The dashboard includes 6 interactive views:
1. **Overview Grid:** Longitudinal ASR time series per model with 95% cluster bootstrap intervals.
2. **Controls & Canary:** Benign task success rates alongside zero-temperature output hash stability.
3. **Language Breakdown:** Disaggregated results across English, Telugu, and Tenglish, comparing native vs. synthetic attack performance.
4. **Change Points & Events:** PELT/CUSUM changepoint markers overlaid with provider changelog entries.
5. **Negative Control:** Pinned local model stability evaluated against $\pm 3\%$ TOST equivalence bands.
6. **Data & Methods:** Methodology, pre-registration details, and Parquet download links.

---

## 8. Responsible Research & Ethics

- **Sandboxed Execution:** All attacks target mock e-commerce tools exclusively (`get_order_status`, `request_refund`, `search_catalog`, `apply_discount`, `cancel_order`). No real external APIs or personal accounts are ever contacted.
- **Header Redaction:** API authorization keys and tokens are scrubbed from all in-memory traces and serialized bundles.
- **Provider Terms:** Evaluations respect free-tier provider rate limits and concurrency constraints. Serious vulnerabilities are disclosed responsibly.

---

## 9. Citation

```bibtex
@misc{driftwatch2026,
  title={DriftWatch-TE: A Longitudinal Study of Security Drift in Hosted LLM Agents with Telugu and Tenglish Attack Sets},
  author={TODO: Author Name(s)},
  year={2026},
  publisher={Zenodo},
  doi={TODO: 10.5281/zenodo.TODO},
  url={https://github.com/TODO:ORG/driftwatch}
}
```

---

## 10. License

This project is licensed under the **Apache License 2.0**. Test suites and datasets are released under **CC-BY 4.0**.

