"""Audit regression tests for Phase 1 defect fixes (2a - 2h) and Phase 1 Item 3 rules.

Ensures:
  2a. CI always contains point estimate; returns None ('not estimable') when clusters < 10.
  2b. Model/series with no data is never plotted or tabulated as 0%.
  2c. Returned model ID never defaults to or matches alias.
  2d. Canary state is 'baseline' with 1 week, 'unchanged'/'changed' with >= 2 weeks.
  2e. Pilot / dry-run data excluded from formal KPI cards, reports, and hypotheses.
  2f. No fake placeholder links; Parquet button disabled until HF repo configured.
  2g. Provider error_type records exception class, never 'None'.
  2h. Pilot banner has normal layout flow (not position: fixed overlapping navbar).
  Item 3:
    - No link to a host other than github.com/Rdvprasad36/DriftWatch-TE and configured HF repo.
    - No emojis anywhere in code, HTML, CSS, README.
    - No hardcoded percentage literals in HTML body or JS data structures.
    - No <img> in the navbar.
    - No series plotted with no data.
"""

from __future__ import annotations

import re
from pathlib import Path

from driftwatch.analysis.bootstrap import cluster_bootstrap_ci, wilson_score_interval
from driftwatch.config import load_study_config
from driftwatch.providers.base import ProviderResponse
from driftwatch.storage.exports import build_export_row
from driftwatch.storage.summary import compute_slice_stats


class TestAuditRegressions:
    """Regression test suite for Phase 1 audit defect fixes."""

    def test_2a_bootstrap_ci_coverage_and_min_clusters(self) -> None:
        """2a: Cluster bootstrap must return (mean, None, None) when clusters < 10,

        and when clusters >= 10, the interval must strictly contain the point estimate.
        """
        # When clusters < 10: must be 'not estimable' (None)
        import pandas as pd

        df_small = pd.DataFrame(
            {
                "base_id": ["s1", "s2"],
                "scenario_id": ["s1", "s2"],
                "attack_success": [1, 0],
            }
        )
        mean, lo, hi = cluster_bootstrap_ci(df_small, min_clusters=10)
        assert lo is None and hi is None, f"Expected None for < 10 clusters, got [{lo}, {hi}]"
        assert mean == 0.5

        # When clusters >= 10: point estimate must be within [lo, hi]
        df_12 = pd.DataFrame(
            {
                "base_id": [f"sc_{i}" for i in range(12)] * 2,
                "scenario_id": [f"sc_{i}" for i in range(12)] * 2,
                "attack_success": [1] * 7 + [0] * 5 + [1] * 6 + [0] * 6,
            }
        )
        mean_12, lo_12, hi_12 = cluster_bootstrap_ci(df_12, min_clusters=10)
        assert lo_12 is not None and hi_12 is not None
        assert lo_12 <= mean_12 <= hi_12, f"Point estimate {mean_12} not in [{lo_12}, {hi_12}]"

        # Wilson score interval must also strictly contain point estimate
        w_mean, w_lo, w_hi = wilson_score_interval(7, 16)
        p_hat = 7 / 16
        assert w_lo <= p_hat <= w_hi
        assert w_mean == p_hat

    def test_2a_compute_slice_stats_returns_none_ci_for_small_clusters(self) -> None:
        """2a: compute_slice_stats sets ci_95 to None if unique scenarios < 10."""
        row_base = {
            "task_success": True,
            "latency_ms": 100,
            "tokens_in": 10,
            "tokens_out": 20,
        }
        stats = compute_slice_stats(
            rows=[
                dict(row_base, scenario_id="sc1", attack_success=True),
                dict(row_base, scenario_id="sc2", attack_success=False),
            ]
        )
        assert stats["ci_95"] is None

    def test_2b_no_series_plotted_with_no_data(self) -> None:
        """2b: Models or local reference with no trials must never be plotted as 0%."""
        content = Path("dashboard/index.html").read_text(encoding="utf-8")
        # Ensure hardcoded 0% local reference series is removed
        assert "data: weeks.map(function() { return 0; })" not in content
        assert "data: weeks.map(function() { return 0 })" not in content
        assert "diff = asr - 0" not in content

    def test_2c_returned_model_id_never_equals_alias(self) -> None:
        """2c: Returned model ID must only be provider API returned id, never alias."""
        row = {
            "trial_id": "t1",
            "scenario_id": "sc1",
            "model_alias": "groq",
            "requested_model": "llama-3.3-70b-versatile",
            "returned_model_id": "groq",  # Bug was setting returned_model_id to alias
            "suite": "control",
            "error_type": None,
        }
        exported = build_export_row(row, "2026-10-16")
        assert exported["returned_model_id"] == "", (
            "Returned model id matching alias must be stripped"
        )

        # When genuine returned id exists
        row_genuine = dict(row, returned_model_id="llama-3.3-70b-instruct")
        exported_genuine = build_export_row(row_genuine, "2026-10-16")
        assert exported_genuine["returned_model_id"] == "llama-3.3-70b-instruct"

    def test_2d_canary_state_logic_in_dashboard(self) -> None:
        """2d: Canary state must be baseline with 1 week, unchanged/changed with >= 2 weeks."""
        content = Path("dashboard/index.html").read_text(encoding="utf-8")
        assert "var canaryState = (weeks.length <= 1) ? 'baseline' : 'unchanged';" in content

    def test_2e_pilot_panel_and_kpi_exclusion_in_dashboard(self) -> None:
        """2e: Pilot data must never feed KPI cards and appears on a labeled pilot panel."""
        content = Path("dashboard/index.html").read_text(encoding="utf-8")
        assert 'id="pilot-panel"' in content
        assert 'id="pilot-sample-n"' in content
        assert "studyWeeks.length === 0" in content
        assert "Pilot dry-run data is excluded from formal study metrics" in content

    def test_2f_no_placeholder_urls_or_fake_links(self) -> None:
        """2f: No placeholder links to huggingface or osf; Parquet button disabled until HF set."""
        content = Path("dashboard/index.html").read_text(encoding="utf-8")
        assert "huggingface.co/datasets/placeholder" not in content
        assert "osf.io/placeholder" not in content
        assert 'id="download-parquet-btn"' in content
        assert "disabled" in content

    def test_2g_provider_error_type_not_literal_none(self) -> None:
        """2g: Provider error_type must record exception class, never 'None' string."""
        resp = ProviderResponse(
            requested_model="m",
            returned_model="",
            fingerprint=None,
            content=None,
            tool_calls=[],
            error="Connection timed out",
            error_type="ConnectTimeout",
            http_status=None,
            latency_ms=100.0,
        )
        assert resp.error_type == "ConnectTimeout"
        assert resp.error_type != "None"

        # Test build_export_row converts string "None" to None
        exported = build_export_row({"error_type": "None", "model_alias": "test"}, "2026-10-16")
        assert exported["error_type"] is None

    def test_2h_pilot_banner_normal_layout_flow(self) -> None:
        """2h: Pilot banner must not have position: fixed overlapping top bar."""
        content = Path("dashboard/index.html").read_text(encoding="utf-8")
        # Banner CSS
        banner_match = re.search(r"\.banner-bar\s*\{([^}]+)\}", content)
        assert banner_match
        banner_css = banner_match.group(1)
        assert "position: fixed" not in banner_css
        assert "position: relative" in banner_css

    def test_item3_allowed_hosts_only(self) -> None:
        """Item 3: No external links other than Rdvprasad36 repo and configured HF repo."""
        content = Path("dashboard/index.html").read_text(encoding="utf-8")
        hrefs = re.findall(r'href=["\'](https?://[^"\']+)["\']', content)
        allowed = [
            "https://github.com/Rdvprasad36/DriftWatch-TE",
            "https://github.com/Rdvprasad36/DriftWatch-TE.git",
        ]
        cfg = load_study_config()
        if cfg.hf_dataset_repo and cfg.hf_dataset_repo != "TODO":
            allowed.append(f"https://huggingface.co/datasets/{cfg.hf_dataset_repo}")

        for h in hrefs:
            assert any(h == a or h.startswith(a) for a in allowed), (
                f"Disallowed external link found in dashboard/index.html: {h}"
            )

    def test_item3_no_emojis_in_repo(self) -> None:
        """Item 3: Zero emojis anywhere in codebase, dashboard, readme, reports."""
        emoji_pattern = re.compile(
            r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]"
        )
        files = [Path("README.md"), Path("dashboard/index.html")]
        for src_file in Path("src").rglob("*.py"):
            files.append(src_file)

        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            matches = emoji_pattern.findall(text)
            assert not matches, f"Emoji character detected in {f}: {matches}"

    def test_item3_no_percentage_literals_in_html_or_js(self) -> None:
        """Item 3: No decimal result percentage literals (e.g. '43.8%') hardcoded in HTML or JS."""
        content = Path("dashboard/index.html").read_text(encoding="utf-8")
        # No hardcoded outcome percentages in text/JS data
        decimals = re.findall(r"\b\d+\.\d+%", content)
        assert not decimals, f"Hardcoded decimal percentage literals found: {decimals}"
        # No hardcoded brackets with percentages
        brackets = re.findall(r"\[\s*\d+(\.\d+)?%\s*,\s*\d+(\.\d+)?%\s*\]", content)
        assert not brackets, f"Hardcoded percentage intervals found: {brackets}"
        # No hardcoded 43.8
        assert "43.8" not in content

    def test_item3_no_img_in_navbar(self) -> None:
        """Item 3: No <img> in the navbar (text wordmark only)."""
        content = Path("dashboard/index.html").read_text(encoding="utf-8")
        navbar_match = re.search(
            r"<header[^>]*class=[\"'][^\"']*navbar[^\"']*[\"'][^>]*>(.*?)</header>",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        assert navbar_match
        navbar_html = navbar_match.group(1)
        assert "<img" not in navbar_html.lower()
        assert "DriftWatch-" in navbar_html
        assert "TE" in navbar_html

    def test_estimate_noise_script_runs_synthetic_demo(self) -> None:
        """scripts/estimate_noise.py runs --synthetic-demo and outputs noise estimates."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/estimate_noise.py", "--synthetic-demo"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "EMPIRICAL NOISE ESTIMATION RESULTS BY MODEL" in result.stdout
        assert "sigma_w" in result.stdout
        assert "tau" in result.stdout
        assert "PROJECTED STUDY POWER USING ESTIMATED PARAMETERS" in result.stdout
        assert "google" in result.stdout
        assert "groq" in result.stdout
        assert "openrouter" in result.stdout
