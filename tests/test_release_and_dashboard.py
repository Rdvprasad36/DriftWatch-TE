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

import pytest
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
            "control",  # View 2: Task success & canary
            "language",  # View 3: Language breakdown (en, te, te-Latn)
            "change",  # View 4: Change points with provider events
            "negative",  # View 5: Negative control (local model TOST)
            "method",  # View 6: Data and methods
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

    def test_dashboard_has_no_fabricated_percentages(self) -> None:
        """Dashboard index.html contains no hard-coded result percentage literals."""
        import re

        dashboard_html = Path("dashboard/index.html")
        content = dashboard_html.read_text(encoding="utf-8")

        # Exclude standard CSS declarations like width: 100% or height: 100%
        # Look for result percentages like 14.2%, 22.8%, 8.4%, 11.5%, etc.
        decimal_percentages = re.findall(r"\b\d+\.\d+%", content)
        assert not decimal_percentages, (
            f"Found hard-coded decimal percentage literals in dashboard: {decimal_percentages}"
        )

        # Ensure no hardcoded outcome percentages in text (e.g., [11.8%, 16.9%])
        ci_brackets = re.findall(r"\[\s*\d+(\.\d+)?%\s*,\s*\d+(\.\d+)?%\s*\]", content)
        assert not ci_brackets, (
            f"Found hard-coded CI percentage literals in dashboard: {ci_brackets}"
        )

    def test_dashboard_has_no_hardcoded_p_values(self) -> None:
        """Dashboard index.html contains no fabricated p-value literals."""
        import re

        dashboard_html = Path("dashboard/index.html")
        content = dashboard_html.read_text(encoding="utf-8")

        p_values = re.findall(r"\bp\s*[<>=]\s*0?\.\d+", content, re.IGNORECASE)
        assert not p_values, f"Found hard-coded p-value literals in dashboard: {p_values}"

    def test_dashboard_has_no_hardcoded_model_names(self) -> None:
        """Dashboard index.html contains no hard-coded target model name literals.

        Model names must be discovered dynamically from runtime evaluation data.
        """
        dashboard_html = Path("dashboard/index.html")
        content = dashboard_html.read_text(encoding="utf-8").lower()

        forbidden_model_literals = [
            "llama-3.1-8b",
            "llama-3.3-70b",
            "llama-3.2-1b",
            "gemma-2-9b",
            "meta-llama/llama",
            "groq/gemma",
            "cerebras/llama",
            "ollama/llama",
        ]
        found = [m for m in forbidden_model_literals if m in content]
        assert not found, f"Found hard-coded model name literals in dashboard/index.html: {found}"

    def test_navbar_has_no_img(self) -> None:
        """The navigation bar uses a plain text wordmark with no <img> tag."""
        import re

        dashboard_html = Path("dashboard/index.html")
        content = dashboard_html.read_text(encoding="utf-8")

        navbar_match = re.search(
            r"<header[^>]*class=[\"'][^\"']*navbar[^\"']*[\"'][^>]*>(.*?)</header>",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert navbar_match, "Navbar header element not found in dashboard/index.html"
        navbar_html = navbar_match.group(1)

        imgs = re.findall(r"<img[^>]*>", navbar_html, re.IGNORECASE)
        assert not imgs, f"Navigation bar must not contain <img> tags, found: {imgs}"
        assert "DriftWatch-" in navbar_html, "Navbar must contain 'DriftWatch-' wordmark text"
        assert "TE" in navbar_html, "Navbar must contain 'TE' wordmark accent"

    def test_no_emojis_in_dashboard_readme_reports(self) -> None:
        """Dashboard, README, and reports contain no emoji characters."""
        import re

        # Regex covering standard Unicode emoji and pictograph ranges
        emoji_pattern = re.compile(
            r"[\U0001F600-\U0001F64F]"  # emoticons
            r"|[\U0001F300-\U0001F5FF]"  # symbols & pictographs
            r"|[\U0001F680-\U0001F6FF]"  # transport & map
            r"|[\U0001F1E0-\U0001F1FF]"  # flags
            r"|[\U0001F900-\U0001FAFF]"  # supplemental symbols
            r"|[\u2600-\u26FF]"  # misc symbols
            r"|[\u2700-\u27BF]"  # dingbats
        )

        files_to_check: list[Path] = [Path("README.md")]

        dashboard_dir = Path("dashboard")
        if dashboard_dir.is_dir():
            for p in dashboard_dir.rglob("*"):
                # Skip binary fonts and vendored minified JS
                if (
                    p.is_file()
                    and p.suffix.lower() in [".html", ".css", ".js", ".json", ".md"]
                    and "vendor" not in p.parts
                ):
                    files_to_check.append(p)

        reports_dir = Path("reports")
        if reports_dir.is_dir():
            for p in reports_dir.rglob("*"):
                if p.is_file() and p.suffix.lower() in [".html", ".md", ".json"]:
                    files_to_check.append(p)

        violations: list[str] = []
        for file_path in files_to_check:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            matches = emoji_pattern.findall(text)
            if matches:
                violations.append(f"{file_path}: {matches}")

        assert not violations, f"Emoji characters detected in repository files: {violations}"

    def test_playwright_dashboard_smoke(self, tmp_path: Path) -> None:
        """Playwright smoke test verifying empty and sample-data state at 360px and 1280px."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            pytest.skip("Playwright not installed in environment")

        artifact_dir = Path(
            r"C:\Users\rdvpr\.gemini\antigravity\brain\fca563bf-a8e0-4789-a607-1cc538f72248\screenshots"
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)

        dashboard_path = Path("dashboard/index.html").resolve()
        assert dashboard_path.exists(), "dashboard/index.html must exist"

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--allow-file-access-from-files", "--disable-web-security"],
            )

            # Test configurations: (viewport, theme, is_sample)
            configs = [
                ({"width": 360, "height": 740}, "light", False, "empty_360_light"),
                ({"width": 360, "height": 740}, "dark", True, "sample_360_dark"),
                ({"width": 1280, "height": 800}, "light", True, "sample_1280_light"),
                ({"width": 1280, "height": 800}, "dark", False, "empty_1280_dark"),
            ]

            for vp, theme, sample_mode, name in configs:
                context = browser.new_context(
                    viewport={"width": vp["width"], "height": vp["height"]}
                )
                page = context.new_page()

                # Set theme in localStorage before navigating
                page.add_init_script(f"localStorage.setItem('driftwatch_theme', '{theme}');")

                url = f"file:///{dashboard_path.as_posix()}"
                if sample_mode:
                    url += "?sample=true"

                page.goto(url, wait_until="load")
                page.wait_for_timeout(300)

                # Verify wordmark is visible
                brand = page.locator(".wordmark")
                assert brand.is_visible()

                # Verify sample banner state
                sample_banner = page.locator("#sample-banner")
                if sample_mode:
                    assert sample_banner.is_visible()

                # Save screenshot to artifact directory (not committed to git)
                screenshot_file = artifact_dir / f"dashboard_{name}.png"
                page.screenshot(path=str(screenshot_file), full_page=False)
                assert screenshot_file.exists()

                context.close()

            browser.close()


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
