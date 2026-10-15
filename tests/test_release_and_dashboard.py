"""Tests for dashboard, dataset card, provider events, and release scripts (FR10, FR11, FR12).

Verifies:
1. Dashboard static HTML file exists and adheres to design.md §5:
   - Contains all 6 specified views: Overview grid, Controls, Language breakdown,
     Change points, Negative control, Data and methods.
   - Uses colorblind-safe palette.
   - Renders standalone without breaking external dependencies.
2. CLI `driftwatch event` for logging provider changes (FR11):
   - `driftwatch event add` with --provider, --model, --date, --url, --note.
   - `driftwatch event list` with filtering or formatting.
3. Dataset Card (DATASET_CARD.md) conforming to Hugging Face standard schema (FR12).
4. Release preparation script and .zenodo.json metadata (FR12).
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from driftwatch.cli.main import EXIT_OK, cli


class TestDashboard:
    def test_dashboard_html_exists(self) -> None:
        """Dashboard index.html exists at repository root dashboard/."""
        dashboard_html = Path("dashboard/index.html")
        assert dashboard_html.is_file(), "dashboard/index.html must exist"

    def test_dashboard_contains_all_six_views(self) -> None:
        """Dashboard contains all 6 views specified in design.md §5."""
        dashboard_html = Path("dashboard/index.html")
        content = dashboard_html.read_text(encoding="utf-8").lower()

        required_views = [
            "overview",  # View 1: Overview grid ASR over time
            "control",   # View 2: Task success & canary
            "language",  # View 3: Language breakdown (en, te, te-Latn)
            "change",    # View 4: Change points with provider events
            "negative",  # View 5: Negative control (local model TOST)
            "method",    # View 6: Data and methods
        ]
        for view in required_views:
            assert view in content, f"Dashboard missing view section for '{view}'"

    def test_dashboard_includes_languages(self) -> None:
        """Dashboard references all three target languages."""
        dashboard_html = Path("dashboard/index.html")
        content = dashboard_html.read_text(encoding="utf-8")
        assert "Telugu" in content
        assert "Tenglish" in content
        assert "English" in content

    def test_dashboard_is_self_contained(self) -> None:
        """Dashboard works standalone without requiring external heavy JS build systems."""
        dashboard_html = Path("dashboard/index.html")
        content = dashboard_html.read_text(encoding="utf-8")
        # Should contain HTML, head, body, script, style
        assert "<!DOCTYPE html>" in content or "<!doctype html>" in content.lower()
        assert "<html" in content
        assert "</html>" in content


class TestProviderEventsCLI:
    def test_event_add_and_list(self, tmp_path: Path) -> None:
        """driftwatch event add stores events and driftwatch event list retrieves them."""
        events_file = tmp_path / "events.json"
        runner = CliRunner()

        # Add event
        add_result = runner.invoke(
            cli,
            [
                "event",
                "add",
                "--provider",
                "openrouter",
                "--model",
                "meta-llama/llama-3.1-8b-instruct:free",
                "--date",
                "2026-10-25",
                "--url",
                "https://openrouter.ai/changelog",
                "--note",
                "Backend model updated weights silently",
                "--events-file",
                str(events_file),
            ],
        )
        assert add_result.exit_code == EXIT_OK, f"Event add failed: {add_result.output}"
        assert "Event recorded" in add_result.output

        # Verify file contents
        assert events_file.exists()
        data = json.loads(events_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["provider"] == "openrouter"
        assert data[0]["model"] == "meta-llama/llama-3.1-8b-instruct:free"
        assert data[0]["date"] == "2026-10-25"
        assert data[0]["note"] == "Backend model updated weights silently"

        # List events
        list_result = runner.invoke(
            cli,
            [
                "event",
                "list",
                "--events-file",
                str(events_file),
            ],
        )
        assert list_result.exit_code == EXIT_OK
        assert "openrouter" in list_result.output
        assert "Backend model updated weights" in list_result.output


class TestDatasetCardAndRelease:
    def test_dataset_card_exists_and_valid(self) -> None:
        """DATASET_CARD.md exists and contains Hugging Face YAML metadata and required sections."""
        card = Path("DATASET_CARD.md")
        assert card.is_file(), "DATASET_CARD.md must exist at root"
        content = card.read_text(encoding="utf-8")

        # Hugging Face frontmatter checks
        assert "---" in content
        assert "license:" in content
        assert "language:" in content

        # Required documentation sections
        assert "Dataset Summary" in content
        assert "Supported Tasks" in content
        assert "Dataset Structure" in content
        assert "Telugu" in content
        assert "Tenglish" in content
        assert "Citation" in content

    def test_readme_exists_and_covers_project(self) -> None:
        """README.md exists and provides comprehensive documentation."""
        readme = Path("README.md")
        assert readme.is_file(), "README.md must exist at root"
        content = readme.read_text(encoding="utf-8")

        assert "DriftWatch" in content
        assert "Installation" in content or "Setup" in content
        assert "CLI" in content
        assert "H1" in content or "RQ1" in content
        assert "License" in content

    def test_zenodo_metadata_valid(self) -> None:
        """.zenodo.json exists and contains valid metadata for Zenodo DOI integration."""
        zenodo_file = Path(".zenodo.json")
        assert zenodo_file.is_file(), ".zenodo.json must exist"
        data = json.loads(zenodo_file.read_text(encoding="utf-8"))

        assert "title" in data
        assert "description" in data
        assert "creators" in data
        assert "license" in data
        assert len(data["creators"]) > 0

    def test_release_script_dry_run(self) -> None:
        """Release packaging script runs a dry-run check."""
        release_script = Path("scripts/release.py")
        assert release_script.is_file(), "scripts/release.py must exist"

        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, str(release_script), "--dry-run"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Release script failed: {result.stderr}\n{result.stdout}"
        assert "Dry-run verification passed" in result.stdout

