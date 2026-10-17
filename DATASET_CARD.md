---
annotations_creators:
  - expert-annotated
  - machine-generated
language_creators:
  - expert-annotated
  - machine-generated
language:
  - en
  - te
  - te-Latn
license: apache-2.0
multilinguality:
  - multilingual
  - translation
size_categories:
  - 10K<n<100K
source_datasets:
  - original
task_categories:
  - text-generation
pretty_name: DriftWatch-TE Longitudinal Agent Security Dataset
tags:
  - prompt-injection
  - agent-security
  - longitudinal-drift
  - telugu
  - tenglish
---

# Dataset Card for DriftWatch-TE

## Dataset Summary
DriftWatch-TE is a longitudinal dataset and research benchmark measuring prompt injection Attack Success Rate (ASR) over time on hosted LLM agents. Hosted endpoints change silently over time (due to weight tuning, quantization, routing, or safety filter updates). This dataset records weekly evaluations of agents interacting with a deterministic mock e-commerce environment across English, Telugu (తెలుగు), and Tenglish (code-mixed Telugu in Latin script).

All outcomes are determined by deterministic goal predicates evaluated over the environment world state, avoiding subjective LLM-as-a-judge scoring. A pinned local model runs concurrently to serve as an invariance negative control.

## Supported Tasks
- **Agent Security Evaluation**: Measuring susceptibility to indirect prompt injection in tool outputs and tool descriptions.
- **Longitudinal Drift Tracking**: Analyzing whether hosted LLM agent security posture shifts over time.
- **Multilingual / Code-Mixed Robustness**: Evaluating performance gaps between English, native-script Indic languages (Telugu), and Romanized code-mixed dialects (Tenglish).
- **Synthetic vs. Human Comparison**: Comparing vulnerability metrics between machine-translated injection payloads and native speaker-written payloads.

## Languages
- **English (`en`)**: Standard English customer service queries and injection payloads.
- **Telugu (`te`)**: Telugu in Telugu script (తెలుగు), including both machine-translated (v1) and native human-authored (v2) sets.
- **Tenglish (`te-Latn`)**: Telugu-English code-mixed dialect written phonetically in Latin script.

## Dataset Structure

### Data Instances
Each trial record represents a single execution of an agent against a customer-service scenario:
```json
{
  "job_id": "<suite>:<scenario_id>:<model_alias>:<trial>",
  "suite": "attacks_v1",
  "suite_hash": "<suite_sha256_hash>",
  "week": "YYYY-MM-DD",
  "scenario_id": "order_cancel_01",
  "language": "te-Latn",
  "channel": "tool_output",
  "model_alias": "<model_alias>",
  "returned_model_id": "<provider_model_id>",
  "fingerprint": null,
  "trial": 0,
  "temperature": 0.7,
  "attack_success": true,
  "task_success": false,
  "steps": 4,
  "tokens_in": 312,
  "tokens_out": 88,
  "latency_ms": 1420.5,
  "http_errors": 0,
  "error_type": null
}
```

### Data Fields
- `job_id` (`string`): Unique job identifier (`<suite>:<scenario>:<model>:<trial>`).
- `suite` (`string`): Benchmark suite (`canary`, `control`, `attacks_v1`, `attacks_v2_native`).
- `suite_hash` (`string`): SHA-256 integrity hash of the frozen suite configuration.
- `week` (`string`): Execution week identifier (`YYYY-MM-DD`).
- `scenario_id` (`string`): Unique identifier of the test scenario.
- `language` (`string`): Scenario language (`en`, `te`, `te-Latn`).
- `channel` (`string`): Injection delivery mechanism (`tool_output` or `tool_description`).
- `model_alias` (`string`): Abstracted target model alias.
- `returned_model_id` (`string`): Raw backend model identifier returned in API completion payload.
- `fingerprint` (`string`, nullable): Provider system fingerprint if exposed.
- `trial` (`int`): Replicate trial index (0 to 4).
- `temperature` (`float`): Sampling temperature (0.7 for trials, 0.0 for canaries).
- `attack_success` (`bool`): Deterministic predicate outcome (true if injection goal achieved).
- `task_success` (`bool`): Deterministic predicate outcome (true if benign user task achieved).
- `steps` (`int`): Count of agent-environment interaction turns taken (max 8).
- `tokens_in` (`int`): Prompt tokens consumed.
- `tokens_out` (`int`): Completion tokens generated.
- `latency_ms` (`float`): Wall-clock trial duration in milliseconds.
- `http_errors` (`int`): Number of HTTP retries encountered during trial.
- `error_type` (`string`, nullable): Classification of failure if uncompleted (`rate_limit`, `context_length`, `provider_error`, etc.).

### Data Splits
Weekly bundles are stored in Apache Parquet format partitioned by week (`weekly/<week>/bundle.parquet`).

## Dataset Creation

### Curation Rationale
Safety evaluations are predominantly static snapshots. DriftWatch-TE provides a continuous, immutable longitudinal record of model behavior under adversarial pressure.

### Source Data & Annotations
- **v1 Attack Suite**: Scenarios generated through structured translation and adversarial perturbation templates.
- **v2 Native Telugu/Tenglish Suite**: Authored by native Telugu speakers and reviewed independently by a second annotator, with inter-annotator agreement reported using Cohen's kappa ($\kappa$).

### Personal and Sensitive Information
None. All entities, customer names, order IDs, payment details, and scenarios are synthetic and operate strictly within a mock world sandbox (`worlds/shop_v1.yaml`).

## Considerations for Using the Data

### Limitations
- Evaluates indirect prompt injection in tool interactions; does not cover multi-modal attacks, audio/voice agents, or memory-poisoning vectors.
- Uses mock customer-service tools; real-world environments may exhibit different operational constraints.
- Free-tier API rate limits bound weekly trial counts.

## Licensing & Citation
- **Code & Dataset License**: Apache License 2.0.
- **Citation**:
```bibtex
@misc{driftwatch2026,
  title={DriftWatch-TE: A Longitudinal Study of Security Drift in Hosted LLM Agents with Telugu and Tenglish Attack Sets},
  author={TODO: Author Name(s)},
  year={2026},
  publisher={Zenodo},
  doi={TODO: 10.5281/zenodo.TODO}
}
```

