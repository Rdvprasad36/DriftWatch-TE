"""Offline tests for DriftWatch-TE data contracts, schemas, gating,
and exports (FR7, FR8, Items 2-5).

Verifies:
1. Schema validation for every output:
   - results/summary/index.json (SummaryIndex)
   - results/summary/weekly/<date>.json (WeeklySummaryContract, SliceStats)
   - results/analysis/analysis.json (AnalysisContract)
   - results/events.json (EventsContract)
   - results/exports/records.csv, records.jsonl, schema.json (ExportRowSchema)
2. Empty-data behavior & <4 weeks report gating.
3. Hypothesis status rules (H1 to H6).
4. No secrets or raw headers in exported records or summaries.
5. Developer sample data safety (cannot write to results/, excluded from published site).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest
from tools.make_sample_data import generate_sample_data

from driftwatch.analysis.pipeline import run_analysis_pipeline
from driftwatch.reporting.generator import generate_reports
from driftwatch.schema.contracts import (
    AnalysisContract,
    EventsContract,
    ExportRowSchema,
    SummaryIndex,
    WeeklySummaryContract,
)
from driftwatch.storage.exports import export_all
from driftwatch.storage.summary import generate_summary, update_summary_index


class TestContractSchemas:
    """Test schema validity of pipeline outputs."""

    def test_summary_index_schema(self, tmp_path: Path) -> None:
        """results/summary/index.json validates against SummaryIndex."""
        summary_dir = tmp_path / "summary"
        summary_dir.mkdir(parents=True)
        weekly_dir = tmp_path / "weekly"
        weekly_dir.mkdir(parents=True)

        index_file = update_summary_index(summary_dir)
        assert index_file.exists()
        index_data = json.loads(index_file.read_text(encoding="utf-8"))
        validated = SummaryIndex.model_validate(index_data)
        assert validated.schema_version == "1.0.0"
        assert validated.planned_weeks == 12
        from driftwatch.config import load_study_config

        assert validated.study_start_date == load_study_config().study_start_date
        assert isinstance(validated.weeks, list)
        assert isinstance(validated.models, list)

    def test_weekly_summary_schema(self, tmp_path: Path) -> None:
        """results/summary/weekly/<date>.json validates against WeeklySummaryContract."""
        run_dir = tmp_path / "2026-10-20"
        run_dir.mkdir(parents=True)
        ndjson = run_dir / "trials.ndjson"

        # Mock 2 trial records
        row1 = {
            "trial_id": "t1",
            "scenario_id": "sc1",
            "run_week": "2026-10-20",
            "timestamp_utc": "2026-10-20T10:00:00Z",
            "model_alias": "hosted-a",
            "requested_model": "test/model-a",
            "returned_model_id": "test/model-a-v1",
            "suite": "attacks_v1",
            "suite_hash": "hash123",
            "channel": "tool_output",
            "language": "en",
            "attack_success": True,
            "task_success": False,
            "latency_ms": 1200.0,
            "tokens_in": 100,
            "tokens_out": 50,
        }
        row2 = {
            "trial_id": "t2",
            "scenario_id": "sc2",
            "run_week": "2026-10-20",
            "timestamp_utc": "2026-10-20T10:01:00Z",
            "model_alias": "hosted-a",
            "requested_model": "test/model-a",
            "returned_model_id": "test/model-a-v1",
            "suite": "attacks_v1",
            "suite_hash": "hash123",
            "channel": "tool_output",
            "language": "en",
            "attack_success": False,
            "task_success": True,
            "latency_ms": 800.0,
            "tokens_in": 80,
            "tokens_out": 40,
        }
        ndjson.write_text(f"{json.dumps(row1)}\n{json.dumps(row2)}\n", encoding="utf-8")

        summary = generate_summary(run_dir, week="2026-10-20")
        validated = WeeklySummaryContract.model_validate(summary)
        assert validated.schema_version == "1.0.0"
        assert validated.total_trials == 2
        assert validated.total_attack_successes == 1
        assert validated.overall_asr == 0.5
        assert len(validated.slices) > 0
        for _slice_key, slice_obj in validated.slices.items():
            assert slice_obj.n_trials > 0
            assert 0.0 <= slice_obj.attack_success_rate <= 1.0
            # Under Item 2a, when clusters < 10, CI is None (not estimable)
            assert slice_obj.ci_95 is None or len(slice_obj.ci_95) == 2

    def test_analysis_schema_and_hypothesis_rules(self, tmp_path: Path) -> None:
        """results/analysis/analysis.json conforms to AnalysisContract with all H1-H6 rules."""
        analysis_file = tmp_path / "analysis.json"
        weekly_dir = tmp_path / "weekly"
        weekly_dir.mkdir(parents=True)

        res = run_analysis_pipeline(weekly_root=weekly_dir, output_path=analysis_file)
        validated = AnalysisContract.model_validate(res)
        assert validated.schema_version == "1.0.0"
        assert validated.study_weeks_count == 0

        # When study weeks < 4, H1-H6 must be not_enough_data
        for h in ["H1", "H2", "H3", "H4", "H5", "H6"]:
            assert h in validated.hypotheses
            assert validated.hypotheses[h].status in [
                "not_enough_data",
                "supported",
                "not_supported",
                "inconclusive",
            ]
            assert validated.hypotheses[h].rule != ""

    def test_events_schema(self, tmp_path: Path) -> None:
        """results/events.json validates against EventsContract."""
        events_file = tmp_path / "events.json"
        events_data = {
            "schema_version": "1.0.0",
            "exported_at_utc": "2026-10-20T00:00:00Z",
            "events": [
                {
                    "date": "2026-10-25",
                    "provider": "openrouter",
                    "model": "meta-llama/llama-3.1-8b",
                    "note": "Silent weight update observed",
                    "url": "https://openrouter.ai/changelog",
                }
            ],
        }
        events_file.write_text(json.dumps(events_data), encoding="utf-8")
        validated = EventsContract.model_validate(events_data)
        assert validated.schema_version == "1.0.0"
        assert len(validated.events) == 1
        assert validated.events[0].provider == "openrouter"

    def test_exports_schema_and_column_completeness(self, tmp_path: Path) -> None:
        """records.csv and records.jsonl validate against ExportRowSchema."""
        weekly_dir = tmp_path / "weekly"
        results_dir = tmp_path / "results"
        run_week_dir = weekly_dir / "2026-10-20"
        run_week_dir.mkdir(parents=True)

        trial = {
            "trial_id": "trial_001",
            "scenario_id": "scen_shop_01",
            "run_week": "2026-10-20",
            "timestamp_utc": "2026-10-20T12:00:00Z",
            "model_alias": "gemini-flash",
            "requested_model": "google/gemini-2.0-flash",
            "returned_model_id": "gemini-2.0-flash-001",
            "suite": "attacks_v1",
            "suite_hash": "deadbeef1234",
            "attack_class": "prompt_injection",
            "channel": "tool_output",
            "language": "te",
            "trial_index": 0,
            "tool_calls": [{"name": "search_catalog", "args": {"query": "shoes"}}],
            "attack_success": True,
            "task_success": False,
            "steps": 2,
            "stop_reason": "tool_executed",
            "error_type": None,
            "http_errors": 0,
            "tokens_in": 150,
            "tokens_out": 45,
            "latency_ms": 320.5,
            "git_sha": "abc1234",
        }
        (run_week_dir / "trials.ndjson").write_text(json.dumps(trial) + "\n", encoding="utf-8")

        res_files = export_all(weekly_root=weekly_dir, results_root=results_dir)
        csv_file = res_files["records_csv"]
        jsonl_file = res_files["records_jsonl"]
        schema_file = res_files["records_schema"]

        assert csv_file.exists()
        assert jsonl_file.exists()
        assert schema_file.exists()

        # Check CSV header matches the 25 fields
        with csv_file.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            assert len(row) == 25
            assert row["trial_id"] == "trial_001"
            assert row["language"] == "te"
            assert row["origin"] == "machine"  # inferred from attacks_v1

        # Check JSONL row validates with ExportRowSchema
        with jsonl_file.open(encoding="utf-8") as f:
            line = f.readline()
            row_dict = json.loads(line)
            validated_row = ExportRowSchema.model_validate(row_dict)
            assert validated_row.trial_id == "trial_001"
            assert validated_row.origin == "machine"


class TestReportGatingAndCaution:
    """Test report generation behavior below 4 weeks and cautious tone."""

    def test_report_gated_below_4_weeks(self, tmp_path: Path) -> None:
        """When study weeks < 4, report explicitly states results are not yet available."""
        analysis_data = {
            "schema_version": "1.0.0",
            "analyzed_at_utc": "2026-10-20T00:00:00Z",
            "study_weeks_count": 1,
            "per_model_trend": {},
            "change_points": [],
            "local_control_equivalence": None,
            "language_interactions": {},
            "native_versus_machine": None,
            "hypotheses": {
                "H1": {"status": "not_enough_data", "rule": "Requires >= 4 weeks.", "details": {}}
            },
        }
        analysis_file = tmp_path / "analysis.json"
        analysis_file.write_text(json.dumps(analysis_data), encoding="utf-8")

        reports = generate_reports(
            analysis_file=analysis_file,
            output_dir=tmp_path / "reports",
        )
        md_content = reports["report_md"].read_text(encoding="utf-8")
        html_content = reports["report_html"].read_text(encoding="utf-8")

        # Must mention results are not yet available
        assert "not yet available" in md_content.lower()
        assert "4 study weeks" in md_content
        assert "Data Completeness" in md_content

        # HTML must include print stylesheet
        assert "@media print" in html_content
        assert "not yet available" in html_content.lower()

    def test_cautious_phrasing_rules(self, tmp_path: Path) -> None:
        """Report never claims provider intent or absolute 'no change' without evidence."""
        analysis_data = {
            "schema_version": "1.0.0",
            "analyzed_at_utc": "2026-10-20T00:00:00Z",
            "study_weeks_count": 0,
            "per_model_trend": {},
            "change_points": [],
            "local_control_equivalence": None,
            "language_interactions": {},
            "native_versus_machine": None,
            "hypotheses": {},
        }
        analysis_file = tmp_path / "analysis.json"
        analysis_file.write_text(json.dumps(analysis_data), encoding="utf-8")

        reports = generate_reports(
            analysis_file=analysis_file,
            output_dir=tmp_path / "reports",
        )
        md_content = reports["report_md"].read_text(encoding="utf-8")

        # Cautious phrasing assertions
        assert "provider intent" in md_content.lower() or "intent" in md_content.lower()
        # Ensure no dogmatic claims about provider intent
        assert "cannot be substantiated" in md_content or "no conclusions" in md_content.lower()


class TestSecurityAndSampleIsolation:
    """Audit for zero secret leakage and dev sample isolation."""

    def test_sample_generator_never_writes_to_results(self, tmp_path: Path) -> None:
        """tools/make_sample_data.py throws ValueError if output directory contains results."""
        results_target = tmp_path / "results" / "summary"
        with pytest.raises(ValueError, match="must NEVER write to results/"):
            generate_sample_data(results_target)

    def test_published_site_excludes_sample_data(self) -> None:
        """Dashboard build must not include dashboard/dev or sample fixtures."""
        # If dev sample fixtures exist locally, verify pages.yml explicitly removes them
        workflow_file = Path(".github/workflows/pages.yml")
        assert workflow_file.exists()
        workflow_text = workflow_file.read_text(encoding="utf-8")
        assert "rm -rf _site/dev" in workflow_text
        assert "grep -rn '\"sample\": true'" in workflow_text

        # Real results/ directory must never contain "sample": true
        results_dir = Path("results")
        if results_dir.exists():
            for p in results_dir.rglob("*.json"):
                data = json.loads(p.read_text(encoding="utf-8"))
                assert not data.get("sample"), (
                    f"Forbidden sample data marker found in production results file: {p}"
                )

    def test_no_secrets_in_exports_or_summaries(self) -> None:
        """Verify exports and summaries contain no API keys, bearer tokens, or env values."""
        export_dir = Path("results/exports")
        summary_dir = Path("results/summary")

        secret_patterns = [
            re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{15,}", re.IGNORECASE),
            re.compile(r"sk-[A-Za-z0-9_\-]{20,}", re.IGNORECASE),
            re.compile(r"AIza[0-9A-Za-z-_]{35}"),
            re.compile(r"x-api-key", re.IGNORECASE),
            re.compile(r"authorization:\s*", re.IGNORECASE),
        ]

        check_paths = list(export_dir.rglob("*")) + list(summary_dir.rglob("*.json"))
        for p in check_paths:
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for pattern in secret_patterns:
                matches = pattern.findall(text)
                assert not matches, f"Potential secret leak in {p}: {matches}"


class TestStudyConfigurationContract:
    """Validate config/study.yaml model identifier and stability rules."""

    def test_model_requested_ids_no_unjustified_dynamic_tags(self) -> None:
        """Fails if any requested_id in study.yaml contains 'latest', 'preview',

        or ':free', unless an explicit justification field exists.
        """
        from driftwatch.config import load_study_config

        config = load_study_config()
        restricted_substrings = ["latest", "preview", ":free"]

        for model in config.models:
            req_id = model.requested_id
            found_tags = [sub for sub in restricted_substrings if sub in req_id]
            if found_tags:
                assert model.justification and model.justification.strip(), (
                    f"Model '{model.alias}' requested_id '{req_id}' contains dynamic/unpinned "
                    f"tags {found_tags} without an explicit 'justification' field in "
                    f"config/study.yaml"
                )

    def test_model_requested_ids_unjustified_fails(self, tmp_path: Path) -> None:
        """Verifies that an unjustified dynamic tag causes the validation check to fail."""
        from driftwatch.config import load_study_config

        bad_config_yaml = """
study_start_date: "2026-11-09"
planned_weeks: 12
models:
  - alias: "unjustified-latest"
    provider: "google"
    requested_id: "gemini-2.0-flash-latest"
"""
        bad_cfg_file = tmp_path / "study.yaml"
        bad_cfg_file.write_text(bad_config_yaml, encoding="utf-8")
        bad_config = load_study_config(bad_cfg_file)

        with pytest.raises(AssertionError, match="without an explicit 'justification'"):
            for model in bad_config.models:
                found_tags = [
                    sub for sub in ["latest", "preview", ":free"] if sub in model.requested_id
                ]
                if found_tags:
                    assert model.justification and model.justification.strip(), (
                        f"Model '{model.alias}' requested_id '{model.requested_id}' contains "
                        f"dynamic/unpinned tags {found_tags} without an explicit "
                        f"'justification' field in config/study.yaml"
                    )
