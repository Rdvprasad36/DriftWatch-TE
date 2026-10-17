# DriftWatch-TE: Longitudinal Security Evaluation Report

**Generated:** 2026-10-17 12:36:22 UTC  
**Git Commit:** `9ac1042`  
**Study Weeks Completed:** 0 of 12  

---

## 1. Summary

> **NOTICE: Formal longitudinal results are not yet available.**
> 
> The evaluation protocol pre-registers a minimum threshold of **4 study weeks** before conducting inferential drift tests (H1–H5). Currently, **0 formal study weeks** have been collected. This progress report summarizes data completeness and harness health only.

## 2. Study Design

- **Research Domain:** Measuring prompt injection Attack Success Rate (ASR) drift on hosted LLM agents over time.
- **Evaluation Sandbox:** Deterministic customer service shop environment (`worlds/shop_v1.yaml`) with 5 mock tools.
- **Evaluation Metric:** Deterministic invariant goal predicates evaluated over world state. No LLM-as-a-judge scoring.
- **Language Conditions:** English (`en`), Telugu (`te`), and Tenglish (`te-Latn`).
- **Invariance Control:** Pinned local model evaluated longitudinally via Two One-Sided Tests (TOST) with a pre-registered margin of ±0.03.

## 3. Data Completeness & Progress

- **Planned Duration:** 12 weeks
- **Recorded Batches:** 1 run(s) total (0 study week(s), 1 pilot/dryrun)
- **Total Executed Trials:** 16
- **Models Tracked:** 2 endpoint(s)

| Week Date | Batch Classification | Trials Recorded |
|---|---|---|
| 2026-10-16 | Pilot / Pre-study | 16 |

## 4. Output 1: Drift Results

*Inferential drift estimates require >= 4 study weeks and are deferred until sufficient longitudinal data is gathered.*

## 5. Output 2: Language Results

*Language interaction terms are deferred until >= 4 weeks of study data have been collected.*

## 6. Uncertainty & Confidence Intervals

- Statistical models account for clustered scenario structures via Generalized Estimating Equations (GEE) with exchangeable working correlation.
- Descriptive proportions report 95% Wilson score intervals.
- Multiple comparisons across endpoints are controlled using the Benjamini-Hochberg False Discovery Rate (FDR) procedure at alpha = 0.05.

## 7. Conclusions Supported by Evidence

- **Data Completeness:** The execution pipeline functions as specified; 16 trials collected across 1 batch(es).
- **Evaluation Sandboxing:** All executed trials correctly operated within mock shop tools without external leaks or harness crashes.

## 8. Conclusions Not Supported

- **Longitudinal Drift Conclusions:** Claims asserting the presence or absence of longitudinal drift cannot be substantiated prior to reaching the 4-week threshold.
- **Provider Intent / Mechanics:** No conclusions regarding provider optimization goals, internal weight modifications, or safety filters can be drawn from black-box API observation alone.

## 9. Limitations

1. **Black-box Endpoint Observability:** Hosted endpoints undergo changes (quantization, system prompts, routing) without public disclosure. The harness observes behavioral drift only, without direct access to model weights.
2. **Simulated E-Commerce Domain:** Outcomes evaluate indirect injection vulnerabilities within mock customer-service tools (`worlds/shop_v1.yaml`); real-world enterprise deployments may incorporate external defense layers.
3. **Free-tier Rate Bounds:** Trial quotas are constrained by free-tier API rate limits.

## 10. Reproducibility & Audit Trail

- **Git Commit SHA:** `9ac1042`
- **Software Environment:**
  - `python`: 3.13.2
  - `pydantic`: 2.13.5
  - `httpx`: 0.28.1
  - `pyarrow`: 26.0.0
  - `pyyaml`: 6.0.3
  - `click`: 8.5.0
- **Frozen Suite Hashes (`suites/SUITE_LOCK.json`):**
  - `canary`: `1d80662673c97e047f501a5f50ef33ff8e10e7851154f927b1d243df6d113c8d`
  - `attacks_v1`: `dafc0338875444212e4c07a414e1a7d902f7a89b5cab8f943791bb6a1df114b4`
  - `control`: `1ae8f9e419a98dee801cb5f4c59d7a8b178d012b161dac5e48a57c578b1e93cd`
