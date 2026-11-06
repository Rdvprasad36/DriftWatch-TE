"""Tests for storage: Parquet conversion, bundle management, summary, HF upload.

All tests are offline — no real Hugging Face API calls.
Satisfies AGENTS.md testing requirements:
  "bundles are immutable (writes to an existing week fail unless --force-new-version)."
FR7 (immutable weekly result bundles pushed to HF Datasets, summaries in git).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_ROWS: list[dict[str, Any]] = [
    {
        "job_id": "canary:s01:fake:0",
        "suite": "canary",
        "suite_hash": "abc123",
        "week": "2026-10-19",
        "scenario_id": "s01",
        "language": "en",
        "channel": "tool_output",
        "model_alias": "fake",
        "returned_model_id": "fake-v1",
        "fingerprint": None,
        "trial": 0,
        "temperature": 0.0,
        "attack_success": False,
        "task_success": True,
        "steps": 2,
        "tokens_in": 40,
        "tokens_out": 16,
        "latency_ms": 2.0,
        "http_errors": 0,
        "error_type": None,
    },
    {
        "job_id": "canary:s02:fake:0",
        "suite": "canary",
        "suite_hash": "abc123",
        "week": "2026-10-19",
        "scenario_id": "s02",
        "language": "te",
        "channel": "tool_description",
        "model_alias": "fake",
        "returned_model_id": "fake-v1",
        "fingerprint": "fp-xyz",
        "trial": 0,
        "temperature": 0.0,
        "attack_success": True,
        "task_success": False,
        "steps": 4,
        "tokens_in": 80,
        "tokens_out": 32,
        "latency_ms": 4.5,
        "http_errors": 1,
        "error_type": None,
    },
    {
        "job_id": "attacks_v1:a01:groq:0",
        "suite": "attacks_v1",
        "suite_hash": "def456",
        "week": "2026-10-19",
        "scenario_id": "a01",
        "language": "te-en",
        "channel": "tool_output",
        "model_alias": "groq",
        "returned_model_id": "llama-3.3-70b",
        "fingerprint": None,
        "trial": 0,
        "temperature": 0.7,
        "attack_success": True,
        "task_success": False,
        "steps": 6,
        "tokens_in": 120,
        "tokens_out": 48,
        "latency_ms": 8.0,
        "http_errors": 0,
        "error_type": None,
    },
]


def _write_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows as NDJSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Parquet round-trip
# ---------------------------------------------------------------------------


class TestParquetConversion:
    def test_ndjson_to_parquet_creates_file(self, tmp_path: Path) -> None:
        """NDJSON -> Parquet conversion produces a readable Parquet file."""
        from driftwatch.storage.parquet import ndjson_to_parquet

        ndjson_path = tmp_path / "trials.ndjson"
        parquet_path = tmp_path / "trials.parquet"
        _write_ndjson(ndjson_path, SAMPLE_ROWS)

        count = ndjson_to_parquet(ndjson_path, parquet_path)

        assert parquet_path.exists()
        assert count == len(SAMPLE_ROWS)

    def test_parquet_round_trip_preserves_data(
        self, tmp_path: Path
    ) -> None:
        """Data survives NDJSON -> Parquet -> read-back."""
        from driftwatch.storage.parquet import (
            load_parquet_rows,
            ndjson_to_parquet,
        )

        ndjson_path = tmp_path / "trials.ndjson"
        parquet_path = tmp_path / "trials.parquet"
        _write_ndjson(ndjson_path, SAMPLE_ROWS)
        ndjson_to_parquet(ndjson_path, parquet_path)

        rows = load_parquet_rows(parquet_path)

        assert len(rows) == len(SAMPLE_ROWS)
        # Check key fields survive
        assert rows[0]["scenario_id"] == "s01"
        assert rows[0]["attack_success"] is False
        assert rows[1]["language"] == "te"
        assert rows[1]["attack_success"] is True
        assert rows[2]["model_alias"] == "groq"
        assert rows[2]["temperature"] == pytest.approx(0.7)

    def test_parquet_preserves_none_fingerprint(
        self, tmp_path: Path
    ) -> None:
        """Nullable fields (fingerprint) round-trip as None."""
        from driftwatch.storage.parquet import (
            load_parquet_rows,
            ndjson_to_parquet,
        )

        ndjson_path = tmp_path / "trials.ndjson"
        parquet_path = tmp_path / "trials.parquet"
        _write_ndjson(ndjson_path, SAMPLE_ROWS)
        ndjson_to_parquet(ndjson_path, parquet_path)

        rows = load_parquet_rows(parquet_path)
        assert rows[0]["fingerprint"] is None
        assert rows[1]["fingerprint"] == "fp-xyz"

    def test_empty_ndjson_produces_empty_parquet(
        self, tmp_path: Path
    ) -> None:
        """Empty NDJSON file -> Parquet with 0 rows."""
        from driftwatch.storage.parquet import (
            load_parquet_rows,
            ndjson_to_parquet,
        )

        ndjson_path = tmp_path / "trials.ndjson"
        parquet_path = tmp_path / "trials.parquet"
        ndjson_path.write_text("", encoding="utf-8")

        count = ndjson_to_parquet(ndjson_path, parquet_path)
        assert count == 0
        rows = load_parquet_rows(parquet_path)
        assert rows == []


# ---------------------------------------------------------------------------
# Bundle finalization (Parquet conversion + immutability)
# ---------------------------------------------------------------------------


class TestBundleFinalize:
    def test_finalize_creates_parquet_and_meta(
        self, tmp_path: Path
    ) -> None:
        """finalize_bundle converts NDJSON to Parquet and writes meta."""
        from driftwatch.storage.bundle import finalize_bundle

        run_dir = tmp_path / "weekly" / "2026-10-19"
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)

        meta = finalize_bundle(run_dir, week="2026-10-19")

        assert (run_dir / "trials.parquet").exists()
        assert (run_dir / "meta.json").exists()
        assert meta["row_count"] == len(SAMPLE_ROWS)

    def test_finalize_refuses_overwrite(self, tmp_path: Path) -> None:
        """Overwriting an existing Parquet bundle raises FileExistsError."""
        from driftwatch.storage.bundle import finalize_bundle

        run_dir = tmp_path / "weekly" / "2026-10-19"
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)
        finalize_bundle(run_dir, week="2026-10-19")

        # Write a new NDJSON (simulating re-run)
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)

        with pytest.raises(FileExistsError, match="already exists"):
            finalize_bundle(run_dir, week="2026-10-19")

    def test_finalize_allows_overwrite_with_flag(
        self, tmp_path: Path
    ) -> None:
        """allow_overwrite=True permits re-finalization."""
        from driftwatch.storage.bundle import finalize_bundle

        run_dir = tmp_path / "weekly" / "2026-10-19"
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)
        finalize_bundle(run_dir, week="2026-10-19")

        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)
        meta = finalize_bundle(
            run_dir, week="2026-10-19", allow_overwrite=True
        )
        assert meta["row_count"] == len(SAMPLE_ROWS)

    def test_meta_json_has_required_fields(self, tmp_path: Path) -> None:
        """meta.json must contain week, row_count, git_sha, sdk_versions."""
        from driftwatch.storage.bundle import finalize_bundle

        run_dir = tmp_path / "weekly" / "2026-10-19"
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)
        finalize_bundle(run_dir, week="2026-10-19")

        meta = json.loads((run_dir / "meta.json").read_text())
        assert meta["week"] == "2026-10-19"
        assert "row_count" in meta
        assert "git_sha" in meta
        assert "sdk_versions" in meta
        assert "finalized_at" in meta


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_per_model_asr(self, tmp_path: Path) -> None:
        """Summary computes per-model ASR from Parquet data."""
        from driftwatch.storage.parquet import ndjson_to_parquet
        from driftwatch.storage.summary import generate_summary

        run_dir = tmp_path / "weekly" / "2026-10-19"
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)
        ndjson_to_parquet(
            run_dir / "trials.ndjson", run_dir / "trials.parquet"
        )

        summary = generate_summary(run_dir, week="2026-10-19")

        assert summary["week"] == "2026-10-19"
        assert "models" in summary
        # "fake" model: 1 attack_success out of 2 rows -> ASR 0.5
        fake_model = summary["models"]["fake"]
        assert fake_model["total_trials"] == 2
        assert fake_model["attack_successes"] == 1
        assert fake_model["asr"] == pytest.approx(0.5)

    def test_summary_per_language(self, tmp_path: Path) -> None:
        """Summary includes per-language breakdown."""
        from driftwatch.storage.parquet import ndjson_to_parquet
        from driftwatch.storage.summary import generate_summary

        run_dir = tmp_path / "weekly" / "2026-10-19"
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)
        ndjson_to_parquet(
            run_dir / "trials.ndjson", run_dir / "trials.parquet"
        )

        summary = generate_summary(run_dir, week="2026-10-19")

        assert "languages" in summary
        assert "en" in summary["languages"]
        assert "te" in summary["languages"]
        assert "te-en" in summary["languages"]

    def test_write_summary_creates_file(self, tmp_path: Path) -> None:
        """write_summary writes JSON to results/summary/<week>.json."""
        from driftwatch.storage.parquet import ndjson_to_parquet
        from driftwatch.storage.summary import write_summary

        run_dir = tmp_path / "weekly" / "2026-10-19"
        output_dir = tmp_path / "results" / "summary"
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)
        ndjson_to_parquet(
            run_dir / "trials.ndjson", run_dir / "trials.parquet"
        )

        path = write_summary(
            run_dir, week="2026-10-19", output_dir=output_dir
        )

        assert path.exists()
        assert path.name == "2026-10-19.json"
        data = json.loads(path.read_text())
        assert data["week"] == "2026-10-19"


# ---------------------------------------------------------------------------
# Hugging Face upload (mocked)
# ---------------------------------------------------------------------------


class TestHFUpload:
    def test_upload_calls_hf_api(self, tmp_path: Path) -> None:
        """upload_bundle calls HfApi.upload_folder with correct args."""
        from driftwatch.storage.hf_upload import upload_bundle

        run_dir = tmp_path / "weekly" / "2026-10-19"
        run_dir.mkdir(parents=True)
        (run_dir / "trials.parquet").write_text("fake parquet")
        (run_dir / "meta.json").write_text("{}")

        mock_api = MagicMock()
        with patch(
            "driftwatch.storage.hf_upload.HfApi", return_value=mock_api
        ):
            upload_bundle(
                run_dir,
                repo_id="user/driftwatch-data",
                week="2026-10-19",
                token="fake-token",
            )

        mock_api.upload_folder.assert_called_once()
        call_kwargs = mock_api.upload_folder.call_args
        assert call_kwargs.kwargs["repo_id"] == "user/driftwatch-data"
        assert "2026-10-19" in call_kwargs.kwargs["path_in_repo"]

    def test_upload_raises_without_token(self, tmp_path: Path) -> None:
        """upload_bundle raises ValueError if no token is provided."""
        from driftwatch.storage.hf_upload import upload_bundle

        run_dir = tmp_path / "weekly" / "2026-10-19"
        run_dir.mkdir(parents=True)

        with pytest.raises(ValueError, match="HF_TOKEN"):
            upload_bundle(
                run_dir,
                repo_id="user/driftwatch-data",
                week="2026-10-19",
                token=None,
            )

    def test_upload_raises_if_no_parquet(self, tmp_path: Path) -> None:
        """upload_bundle raises FileNotFoundError if Parquet missing."""
        from driftwatch.storage.hf_upload import upload_bundle

        run_dir = tmp_path / "weekly" / "2026-10-19"
        run_dir.mkdir(parents=True)

        with pytest.raises(FileNotFoundError, match="trials.parquet"):
            upload_bundle(
                run_dir,
                repo_id="user/driftwatch-data",
                week="2026-10-19",
                token="fake-token",
            )


# ---------------------------------------------------------------------------
# CLI: driftwatch summarize
# ---------------------------------------------------------------------------


class TestDriftwatchSummarizeCLI:
    def test_summarize_command_smoke(self, tmp_path: Path) -> None:
        """driftwatch summarize produces summary JSON."""
        from click.testing import CliRunner

        from driftwatch.cli.main import cli
        from driftwatch.storage.parquet import ndjson_to_parquet

        run_dir = tmp_path / "weekly" / "2026-10-19"
        _write_ndjson(run_dir / "trials.ndjson", SAMPLE_ROWS)
        ndjson_to_parquet(
            run_dir / "trials.ndjson", run_dir / "trials.parquet"
        )
        # Also create meta.json so the bundle looks complete
        (run_dir / "meta.json").write_text(
            json.dumps({"week": "2026-10-19"})
        )

        output_dir = tmp_path / "results" / "summary"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "summarize",
                "--week", "2026-10-19",
                "--results-dir", str(tmp_path / "weekly"),
                "--output-dir", str(output_dir),
            ],
        )

        assert result.exit_code == 0, (
            f"CLI exited with {result.exit_code}:\n{result.output}"
        )
        assert (output_dir / "weekly" / "2026-10-19.json").exists()
        assert (output_dir / "index.json").exists()

    def test_summarize_missing_week_exits_2(
        self, tmp_path: Path
    ) -> None:
        """Missing week directory -> exit code 2."""
        from click.testing import CliRunner

        from driftwatch.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "summarize",
                "--week", "2099-01-01",
                "--results-dir", str(tmp_path / "weekly"),
                "--output-dir", str(tmp_path / "out"),
            ],
        )
        assert result.exit_code == 2

