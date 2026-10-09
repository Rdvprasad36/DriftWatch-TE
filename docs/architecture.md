# Architecture: DriftWatch-TE

## 1. Principles
1. **Immutability.** Frozen suites, append-only weekly result bundles. Never edit past data.
2. **Same conditions every week.** Same prompts, settings, schedule, SDK versions.
3. **Negative control.** A pinned local model must show no drift, or the harness is suspect.
4. **Deterministic primary metric.** ASR comes from code predicates over world state, not an LLM judge.
5. **Files, not servers.** GitHub Actions schedules, Hugging Face stores, a static site displays. $0.

## 2. System overview
```
                     GitHub Actions (cron, weekly Monday)
                                  |
                 +----------------v-----------------+
                 |   Runner (python -m driftwatch)  |
                 +--+-----------+------------+------+
                    |           |            |
           +--------v--+  +-----v------+  +--v-----------+
           | Suites    |  | Provider   |  | Mock World   |
           | (frozen,  |  | Clients    |  | + Tools      |
           |  hashed)  |  | (OpenAI-   |  | + Attack     |
           | canary    |  | compatible)|  | Injector     |
           | control   |  | hosted x3  |  +--+-----------+
           | attacks v1|  | local x1   |     |
           | native v2 |  +-----+------+     |
           +-----------+        |   tool loop|
                          +-----v------------v----+
                          |   Agent Loop (thin)   |
                          +-----------+-----------+
                                      | trace + outcome
                           +----------v-----------+
                           |  Weekly bundle       |
                           |  trials.parquet      |
                           |  canary.json meta.json|
                           +----+------------+----+
                                |            |
                 +--------------v--+   +-----v-----------------+
                 | Hugging Face    |   | git: summaries only   |
                 | Datasets (raw)  |   | results/summary/*.json|
                 +--------------+--+   +-----+-----------------+
                                |            |
                        +-------v------------v-------+
                        |  Analysis (offline)        |
                        |  GEE, change-point, TOST   |
                        +-------------+--------------+
                                      |
                           GitHub Pages dashboard + paper figures
```

## 3. Components

### 3.1 Suites (frozen)
| Suite | Purpose | Size (initial) | Notes |
|---|---|---|---|
| `canary` | Detect any model change | 20 prompts, temp 0 | Output hash, logprobs if offered |
| `control` | Detect general capability drift | 40 benign agent tasks (EN/TE/Tenglish) | Task success |
| `attacks_v1` | Primary security measure | 20 base attacks x 3 languages x 2 channels = about 120 | EN original; TE and Tenglish machine-translated (IndicTrans2) and spot-checked |
| `attacks_v2_native` | Native-written set | about 40 | Starts later; second-annotator validated |
Each suite file is YAML plus a `SUITE_HASH` (SHA-256 of canonical content) recorded in every result.

### 3.2 Mock world and tools
In-memory fake shop: customers, orders, reviews, refunds. Tools: `lookup_order`, `read_reviews` (untrusted text), `issue_refund`, `send_email`, `update_address`. Each scenario defines a goal predicate, for example "`issue_refund` called with account 9981".

### 3.3 Attack injector
Channels: (a) **tool output** (review text contains payload), (b) **tool description** (poisoned metadata). Payload variants per language. Attack classes follow public taxonomies (AgentDojo, MSB, MCPTox) so results are comparable.

### 3.4 Agent loop
A thin, own implementation: chat-completions with function calling, max 8 steps, fixed system prompt, `temperature=0.7` for agent trials, `temperature=0` for canaries. Using one loop for all models removes framework differences.

### 3.5 Provider clients
OpenAI-compatible HTTP via `httpx`. Records: requested model id, **returned** model id, fingerprint field if present, relevant response headers, latency, token counts, HTTP errors. Retries with backoff; errors are logged as outcomes, never silently dropped.

### 3.6 Orchestrator
Expands suites x trials into jobs, runs with bounded concurrency to respect quotas, writes each result atomically, resumes after failure. Run window is fixed (same start hour weekly). Optional intra-week replicate on a second day to estimate time-of-day effects.

### 3.7 Storage
- **Raw bundles:** Hugging Face Datasets repo (`weekly/YYYY-MM-DD/`), pushed by the workflow with a token.
- **Summaries:** small JSON/CSV in git (`results/summary/`), so the dashboard builds without raw data.
- Raw data is not committed to git because 16 weeks x 4 models of transcripts may exceed repository comfort limits.

### 3.8 Analysis (offline, scripted)
GEE logistic regression (clustered by scenario), change-point detection (PELT via `ruptures`, CUSUM), TOST equivalence for the local control, Benjamini-Hochberg correction, cluster bootstrap CIs. Frozen analysis code (tagged) before Run 12.

### 3.9 Dashboard
Static site built in Actions from summary JSON: ASR over time per model with intervals, control success, canary-hash change markers, language breakdown, provider-announcement markers.

## 4. Data schema (one row per trial)
`run_date, week, suite, suite_hash, scenario_id, language, channel, model_alias, returned_model_id, fingerprint, trial, temperature, task_success, attack_success, steps, tokens_in, tokens_out, latency_ms, http_errors, error_type, git_sha, sdk_versions`
Canary row: `prompt_id, output_hash, top_logprobs_hash (nullable), returned_model_id`.
Provider event log (manual): `date, provider, model, source_url, note`.

## 5. Technology (all free)
| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| HTTP, validation | httpx, Pydantic v2 |
| Local model | Ollama or llama.cpp, quantized small model, pinned weights file hash |
| Hosted models | 3 free-tier OpenAI-compatible endpoints (choose in Phase 0 from Groq, Google AI Studio, OpenRouter free models; **verify limits and ToS**) |
| Translation | IndicTrans2 (free, open) for synthetic sets |
| Storage | Parquet (pyarrow), Hugging Face Datasets, git |
| Stats | NumPy, SciPy, statsmodels, `ruptures`, pandas |
| Scheduling and CI | GitHub Actions (public repo) |
| Dashboard | Static HTML + Plotly or Chart.js on GitHub Pages |
| Preregistration | OSF (free) |
| DOI | Zenodo (free) |
| Paper | LaTeX via Overleaf free tier or local, ACL style files |
| Quality | pytest, ruff, mypy, pre-commit |

## 6. Deployment
- Code: public GitHub repo. Weekly workflow `weekly.yml` (cron Monday), `pages.yml` (dashboard), `ci.yml` (tests).
- Secrets in Actions secrets: provider keys, `HF_TOKEN`.
- **Scheduler caveats (verify):** scheduled workflows can run late, and GitHub disables schedules on inactive public repos after a period, so check weekly and keep repository activity. Each job has a run-time limit, so shard by model using a job matrix.
- Local model control: run on a GitHub runner if a small model fits in time, otherwise on your own machine with a cron job, and commit its bundle manually. Decide in the pilot.
- Backup: also save each bundle to a local drive.

## 7. Failure modes
| Failure | Handling |
|---|---|
| Rate limit or outage | Backoff, partial-run flag, rerun missing jobs same day; analysis treats missing data explicitly |
| Provider deprecates a model | Log event, switch to the predefined fallback, mark series break |
| Workflow missed | Alert (email from Actions failure), manual dispatch |
| Suite accidentally edited | CI fails if `SUITE_HASH` differs from the locked value |
| Secret leak | Never log keys; redact headers before saving |

## 8. Security and ethics
Attacks hit only the fake world. Payloads aim at tool misuse in a mock shop, not at producing harmful content. Check provider terms on automated security testing. Responsibly disclose any serious finding to the provider before publishing details.

## 9. Repository layout
```
driftwatch/
  src/driftwatch/{cli,orchestrator,providers,agent,world,attacks,suites,schema,storage,analysis}/
  suites/{canary,control,attacks_v1,attacks_v2_native}/   # locked, hashed
  results/summary/  dashboard/  analysis/  tests/  docs/
  .github/workflows/{weekly.yml,pages.yml,ci.yml}
  prd.md architecture.md design.md AGENTS.md pyproject.toml README.md
```
