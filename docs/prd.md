# PRD: DriftWatch-TE (working name)
**A longitudinal study of security drift in hosted LLM agents, with Telugu/Tenglish attack sets**

> Status: Draft v1 | Created: 8 Oct 2026 | Budget: $0 (free tools only)
> Check that the name is free on GitHub, PyPI and Hugging Face before publishing.

## 1. Summary
Hosted LLM endpoints change over time, often silently. Prior work measures drift in accuracy and output probabilities. This project measures whether **attack success rate (ASR) against tool-using agents changes over time on the same hosted model name**, whether control behavior changes at the same time, and whether providers disclose it. Attacks are presented in English, Telugu and Tenglish (Telugu-English code-mixed), and a native-speaker-written attack set is compared against a machine-generated one.

## 2. Problem and motivation
- Teams pin a model name, run a security review once, then assume the result holds. If behavior changes silently, the review is stale.
- Security evaluations of agents are almost always **one-shot snapshots** (single date, single run).
- Non-English attack sets are mostly machine-generated or machine-translated, so measured robustness may be inflated or misleading.

## 3. Prior work (checked Oct 2026, not exhaustive; re-check before submission)
| Area | Examples found | Relation |
|---|---|---|
| API behavior drift | Chen et al. 2023 (ChatGPT behavior over time), HAPI dataset (Chen et al. 2022), logprob tracking of LLM APIs (arXiv 2512.03816), agent tool-drift taxonomy | Accuracy/behavior drift, not attack success |
| Agent attack benchmarks | AgentDojo, InjecAgent, MCP Security Bench (2510.15994), MCPTox (2508.14925) | Single-time snapshots |
| Multilingual safety | Code-mixed safety failures (2505.14469), phonetic code-mixed red-teaming (2505.14226), MLCL tool-calling robustness (ACL 2026), Tamil/Tanglish injection pilot (2608.15392, small sample) | Mostly Hindi or other languages, mostly not longitudinal |
| Indic tool use | BFCL-Hi, Indic function-calling set, VoiceAgentBench (2510.07978) | Accuracy, not security over time |
| Indic guardrails | DhvaniGuard (synthetic training/eval data, not a paper) | Possible synthetic inflation |

**Claim to defend:** to our knowledge (after literature review) no study tracks agent attack success on hosted models over a multi-week window with Telugu/Tenglish attack sets and a pinned local negative control. **Do not claim "first" without a full search.**

## 4. Research questions and hypotheses (pre-register on OSF before data collection)
- **RQ1 Drift.** Does ASR on a fixed attack suite change over weeks for each hosted model alias? *H1:* the weekly ASR trend differs from zero for at least one model.
- **RQ2 Specificity.** Is any ASR change specific to security behavior, or does control-task success change too? *H2:* detected change points in ASR coincide with canary-hash or control-task shifts in some cases and not others.
- **RQ3 Harness validity.** Does a pinned local model show no drift? *H3:* local ASR change is within an equivalence margin of +/-3 points (TOST).
- **RQ4 Language.** Does ASR, and its drift, differ across English, Telugu and Tenglish? *H4:* language x time interaction.
- **RQ5 Disclosure.** What fraction of detected change points correspond to a public provider announcement? (descriptive)
- **RQ6 Native vs synthetic.** Do guardrails/agents score differently on native-written vs machine-generated Telugu/Tenglish attacks? *H6:* synthetic sets overestimate robustness.
Null results are reported with intervals and equivalence tests.

## 5. Scope
**In:** a mock customer-support agent world, 3 hosted free-tier models, 1 pinned local model, weekly automated runs, frozen attack suite v1, native suite v2, analysis, dashboard, dataset, preprint.
**Out:** real-world accounts, voice/audio, memory attacks, defense research, paid APIs.

## 6. Functional requirements
| ID | Requirement | Priority |
|---|---|---|
| FR1 | Frozen, hashed suites (canary, control, attacks v1) never modified after launch | P0 |
| FR2 | Weekly scheduled run via GitHub Actions, resumable, logs failures | P0 |
| FR3 | Record exact model id, provider headers, fingerprint if available, timestamps, SDK versions | P0 |
| FR4 | Deterministic goal predicates for ASR (no LLM judge for the primary metric) | P0 |
| FR5 | Canary prompts at temperature 0, output hashes, logprobs where offered | P0 |
| FR6 | Pinned local model control | P0 |
| FR7 | Immutable weekly result bundles pushed to Hugging Face Datasets, summaries in git | P0 |
| FR8 | Analysis notebook/scripts: GEE, change-point, TOST, multiple-comparison correction | P0 |
| FR9 | Native Telugu/Tenglish attack set (v2) with second-annotator validation | P1 |
| FR10 | Static dashboard with time series and intervals | P1 |
| FR11 | Provider changelog log (manual, dated) | P1 |
| FR12 | Release: dataset card, code, DOI (Zenodo) | P1 |

## 7. Non-functional
- **Cost $0.** Fit within free-tier quotas (verify current limits at the start; they change).
- **Reproducibility:** each result carries suite hash, git SHA, model id, date.
- **Ethics and ToS:** attacks run only against mock tools; read each provider's terms on automated testing before starting; no real personal data.
- **Integrity:** pre-registered analysis; deviations documented.

## 8. Success metrics
| Metric | Target |
|---|---|
| Weekly runs completed | 12 of 12 (stretch 16) |
| Suites | canary 20, control 40, attacks v1 about 120 scenario variants, native v2 about 40 |
| Models | 3 hosted + 1 local |
| Native set validation | second annotator agreement (Cohen's kappa) reported |
| Outputs | OSF preregistration, dataset on HF, repo with DOI, arXiv preprint |

## 9. Timeline (today is 8 Oct 2026)
| Dates | Phase | Deliverables |
|---|---|---|
| 8 to 18 Oct | **Phase 0: setup** | Literature review, preregistration draft, ToS check, repo, harness v0, 2 dry runs, **freeze suites v1 by 18 Oct** |
| Mon 19 Oct | **Run 1** | Weekly runs every Monday from this date |
| 19 Oct to 15 Nov | Build native set | Write 40 Telugu/Tenglish attacks, 2nd annotator review 16 to 29 Nov |
| Mon 30 Nov | Suite v2 starts | Native set joins weekly runs (about 6 runs by 4 Jan) |
| Mon 4 Jan 2027 | **Run 12** | Primary 12-week window closes |
| 5 Jan to 31 Jan | Analysis | Run preregistered analysis, figures |
| 1 Feb to 14 Feb | Write | Full draft, dataset card |
| About 14 Feb | **Release** | arXiv preprint v1, dataset, DOI |
| Feb to Apr | Optional extension | Continue weekly runs to 16+ weeks, collect feedback |
| Spring 2027 | **Submit** | Next ACL Rolling Review cycle or a relevant workshop (confirm exact dates on the ARR and workshop pages) |

**Why not the 4 Jan 2027 ARR deadline (ACL 2027):** the 12-week window ends the same day, leaving no time to analyze or write. NAACL 2027's ARR deadline (12 Oct 2026) is also too early. Confirm future dates yourself because they change.

## 10. Risks
| Risk | Mitigation |
|---|---|
| No drift observed | Report null with equivalence tests; add second change source (quantization levels of one local model) |
| Free-tier limits or model removals | Start with 5 trials per scenario; keep model-id log; fallback model list defined up front |
| Scheduled workflow disabled or delayed | Weekly manual check, alert on missed run, rerun same-day |
| Provider ToS issue | Read terms in Phase 0; use only mock tools; drop provider if disallowed |
| Small native set | State limits, report intervals, release data |
| Scooped | Longitudinal data cannot be sped up; release the dataset early |
| Analysis flexibility | Pre-register, freeze analysis code before Run 12 |
