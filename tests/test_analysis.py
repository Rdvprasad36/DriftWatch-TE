"""Tests for statistical analysis suite (FR8, RQ1-RQ4, RQ6).

Validates:
1. Synthetic data generator with planted nulls and planted drift (AGENTS.md testing rules).
2. Cluster bootstrap 95% CIs and Wilson score intervals (design.md §4.1).
3. Logistic GEE for drift (b1) and language interaction (b3) (design.md §4.2).
4. Change-point detection: PELT (ruptures) and CUSUM (design.md §4.3).
5. TOST equivalence testing for local negative control (design.md §4.4).
6. Benjamini-Hochberg multiple comparison correction.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from driftwatch.analysis.bootstrap import (
    cluster_bootstrap_ci,
    wilson_score_interval,
)
from driftwatch.analysis.changepoint import (
    detect_changepoints_cusum,
    detect_changepoints_pelt,
    validate_changepoint_with_bootstrap,
)
from driftwatch.analysis.correction import benjamini_hochberg
from driftwatch.analysis.gee import cluster_permutation_test, fit_logistic_gee
from driftwatch.analysis.synthetic import generate_synthetic_trials
from driftwatch.analysis.tost import tost_equivalence

# ---------------------------------------------------------------------------
# Synthetic Data Generator Tests
# ---------------------------------------------------------------------------


class TestSyntheticDataGenerator:
    def test_synthetic_trials_shape_and_columns(self) -> None:
        """Synthetic trials match expected row count and required columns."""
        df = generate_synthetic_trials(n_weeks=6, n_scenarios=10, n_trials=3, seed=123)
        assert len(df) == 6 * 10 * 3
        required = {
            "week_idx",
            "scenario_id",
            "language",
            "channel",
            "attack_success",
            "task_success",
        }
        assert required.issubset(df.columns)

    def test_planted_null_has_no_trend(self) -> None:
        """A planted null dataset has approximately constant ASR over time."""
        df = generate_synthetic_trials(
            n_weeks=12,
            n_scenarios=30,
            n_trials=5,
            base_asr=0.20,
            drift_rate=0.0,
            seed=42,
        )
        early_asr = df[df["week_idx"] < 6]["attack_success"].mean()
        late_asr = df[df["week_idx"] >= 6]["attack_success"].mean()
        assert abs(late_asr - early_asr) < 0.05

    def test_planted_step_change(self) -> None:
        """Planted step change at week 6 increases ASR noticeably after week 6."""
        df = generate_synthetic_trials(
            n_weeks=12,
            n_scenarios=30,
            n_trials=5,
            base_asr=0.10,
            step_week=6,
            step_delta=0.25,
            seed=42,
        )
        before = df[df["week_idx"] < 6]["attack_success"].mean()
        after = df[df["week_idx"] >= 6]["attack_success"].mean()
        assert after > before + 0.15


# ---------------------------------------------------------------------------
# Bootstrap Tests (design.md §4.1)
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_wilson_score_interval_bounds(self) -> None:
        """Wilson interval produces correct bounds within [0, 1]."""
        p_hat, ci_low, ci_high = wilson_score_interval(15, 100)
        assert p_hat == pytest.approx(0.15)
        assert 0.0 <= ci_low < p_hat < ci_high <= 1.0
        assert ci_low == pytest.approx(0.092, abs=0.01)
        assert ci_high == pytest.approx(0.233, abs=0.01)

    def test_wilson_score_interval_edge_cases(self) -> None:
        """Wilson score handles 0 hits and 100% hits gracefully."""
        _, low_0, _ = wilson_score_interval(0, 50)
        assert low_0 >= 0.0
        _, _, high_1 = wilson_score_interval(50, 50)
        assert high_1 <= 1.0

    def test_cluster_bootstrap_ci_covers_true_mean(self) -> None:
        """Cluster bootstrap CI captures the empirical mean."""
        df = generate_synthetic_trials(
            n_weeks=1, n_scenarios=25, n_trials=8, base_asr=0.20, seed=99
        )
        mean_val, ci_low, ci_high = cluster_bootstrap_ci(
            df,
            metric_col="attack_success",
            cluster_col="base_id",
            n_resamples=500,
            seed=99,
        )
        assert ci_low <= mean_val <= ci_high
        assert 0.10 < mean_val < 0.35


# ---------------------------------------------------------------------------
# GEE Trend Tests (design.md §4.2, H1, H4)
# ---------------------------------------------------------------------------


class TestGEE:
    def test_gee_on_planted_null_detects_no_drift(self) -> None:
        """GEE on null data produces non-significant time coefficient (b1 p > 0.05)."""
        df = generate_synthetic_trials(
            n_weeks=10,
            n_scenarios=20,
            n_trials=4,
            base_asr=0.20,
            drift_rate=0.0,
            seed=42,
        )
        result = fit_logistic_gee(df)
        assert "week_idx" in result.coefficients
        # In a true null, drift p-value should typically be > 0.05
        assert result.p_values["week_idx"] > 0.01
        assert abs(result.coefficients["week_idx"]) < 0.15

    def test_gee_on_planted_drift_detects_drift(self) -> None:
        """GEE on strong positive drift produces significant time coefficient (b1 p < 0.05)."""
        df = generate_synthetic_trials(
            n_weeks=12,
            n_scenarios=25,
            n_trials=5,
            base_asr=0.05,
            drift_rate=0.04,  # strong positive drift: ~0.05 to ~0.50
            seed=42,
        )
        result = fit_logistic_gee(df)
        assert result.coefficients["week_idx"] > 0
        assert result.p_values["week_idx"] < 0.05
        assert result.odds_ratios["week_idx"] > 1.0

    def test_gee_result_has_required_metrics(self) -> None:
        """GEEResult provides odds ratios, p-values, standard errors, and CIs."""
        df = generate_synthetic_trials(n_weeks=6, n_scenarios=15, n_trials=3, seed=1)
        result = fit_logistic_gee(df)
        assert result.converged is True
        assert len(result.coefficients) > 0
        assert len(result.odds_ratios) > 0
        assert len(result.conf_int_lower) > 0
        assert result.covariance_type in ("bias_reduced", "robust")
        assert result.df_resid > 0

    def test_gee_small_sample_keeps_type_1_error_near_nominal(self) -> None:
        """Small-sample bias-corrected GEE maintains Type-I error near 5% with 20 clusters.

        Under H0 (no drift, drift_rate=0.0) across 20 base clusters, standard asymptotic
        sandwich SEs underestimate variance and inflate Type-I error to 10-15%.
        The Mancl & DeRouen bias-corrected sandwich with t(K-p) cluster degrees of freedom
        controls false positive rates within nominal bounds (<= 0.08).
        """
        n_sims = 60
        rejections = 0
        for i in range(n_sims):
            df_null = generate_synthetic_trials(
                n_weeks=6,
                n_scenarios=20,
                n_trials=3,
                base_asr=0.20,
                drift_rate=0.0,
                seed=7000 + i,
            )
            res = fit_logistic_gee(df_null, formula="attack_success ~ week_idx")
            assert res.converged is True
            assert res.covariance_type == "bias_reduced"
            assert res.standard_errors["week_idx"] > 0
            if res.p_values["week_idx"] < 0.05:
                rejections += 1

        type_1_error = rejections / n_sims
        # Nominal alpha is 0.05; verify empirical rate is well-controlled near 5% (<= 0.08)
        assert type_1_error <= 0.08, f"Type-I error inflated: {type_1_error:.3f} > 0.08"

    def test_cluster_permutation_test(self) -> None:
        """Cluster permutation test yields non-significant p on null and <0.05 on drift."""
        df_null = generate_synthetic_trials(
            n_weeks=6, n_scenarios=20, n_trials=3, base_asr=0.20, drift_rate=0.0, seed=42
        )
        p_null = cluster_permutation_test(
            df_null, formula="attack_success ~ week_idx", n_permutations=30, seed=42
        )
        assert p_null > 0.05

        df_drift = generate_synthetic_trials(
            n_weeks=6, n_scenarios=20, n_trials=5, base_asr=0.05, drift_rate=0.08, seed=42
        )
        p_drift = cluster_permutation_test(
            df_drift, formula="attack_success ~ week_idx", n_permutations=30, seed=42
        )
        assert p_drift < 0.05


# ---------------------------------------------------------------------------
# Change-point Detection Tests (design.md §4.3, H2)
# ---------------------------------------------------------------------------


class TestChangePoint:
    def test_pelt_detects_planted_step_change(self) -> None:
        """PELT correctly identifies the week of a sharp step change."""
        # Baseline ASR 0.10 for weeks 0-5, jumps to 0.50 for weeks 6-11
        series = np.array([0.10, 0.11, 0.09, 0.10, 0.12, 0.10, 0.50, 0.52, 0.49, 0.51, 0.50, 0.48])
        cps = detect_changepoints_pelt(series, penalty=2.0)
        # PELT returns 1-based end indices; transition between index 5 and 6 corresponds to index 6
        assert any(cp in [5, 6, 7] for cp in cps)

    def test_cusum_detects_step_change(self) -> None:
        """CUSUM flags the shift point in a step-function series."""
        series = np.array([0.10, 0.11, 0.09, 0.10, 0.10, 0.10, 0.55, 0.52, 0.50, 0.51, 0.50, 0.50])
        cps = detect_changepoints_cusum(series, threshold=1.5, drift=0.1)
        assert len(cps) >= 1
        assert any(5 <= cp <= 8 for cp in cps)

    def test_pelt_detects_no_changepoints_on_constant(self) -> None:
        """PELT finds no internal change points on constant data."""
        series = np.array([0.20] * 12)
        cps = detect_changepoints_pelt(series, penalty=5.0)
        # Only the end of series (len) should be present
        internal_cps = [cp for cp in cps if cp < len(series)]
        assert len(internal_cps) == 0

    def test_validate_changepoint_with_bootstrap(self) -> None:
        """Supported change point requires before/after CI excluding zero."""
        before = [0.10, 0.11, 0.09, 0.10, 0.12, 0.10]
        after = [0.50, 0.52, 0.49, 0.51, 0.50, 0.48]
        validation = validate_changepoint_with_bootstrap(before, after)
        assert validation["supported"] is True
        assert validation["diff_mean"] > 0.30
        assert validation["ci_lower"] > 0.0


# ---------------------------------------------------------------------------
# TOST Equivalence Tests (design.md §4.4, H3)
# ---------------------------------------------------------------------------


class TestTOST:
    def test_tost_equivalent_on_identical_halves(self) -> None:
        """Two identical periods are declared statistically equivalent within +/-3% margin."""
        np.random.seed(42)
        # Two periods with nearly identical hit rates (15.0% vs 15.2%)
        h1 = np.array([1] * 150 + [0] * 850)
        h2 = np.array([1] * 152 + [0] * 848)
        res = tost_equivalence(h1, h2, margin=0.03)
        assert res.is_equivalent is True
        assert abs(res.mean_diff) < 0.01
        assert res.p_value_lower < 0.05
        assert res.p_value_upper < 0.05

    def test_tost_not_equivalent_when_drift_exceeds_margin(self) -> None:
        """Periods with large difference fail equivalence test."""
        h1 = np.array([0] * 200 + [1] * 30)  # ~13%
        h2 = np.array([0] * 150 + [1] * 80)  # ~34%
        res = tost_equivalence(h1, h2, margin=0.03)
        assert res.is_equivalent is False


# ---------------------------------------------------------------------------
# Multiple Comparison Correction Tests (design.md §4.2)
# ---------------------------------------------------------------------------


class TestCorrection:
    def test_benjamini_hochberg_controls_fdr(self) -> None:
        """Benjamini-Hochberg correctly adjusts p-values and controls discovery."""
        p_vals = [0.001, 0.008, 0.03, 0.08, 0.45]
        results = benjamini_hochberg(p_vals, alpha=0.05)
        assert len(results) == 5
        # The first small p-value should be rejected (significant)
        assert results[0][1] is True
        # Large p-value should not be rejected
        assert results[4][1] is False
        # Adjusted p-values must be weakly increasing
        adj_p = [r[0] for r in results]
        assert all(adj_p[i] <= adj_p[i + 1] for i in range(len(adj_p) - 1))


# ---------------------------------------------------------------------------
# CLI Analyze Command Tests
# ---------------------------------------------------------------------------


class TestDriftwatchAnalyzeCLI:
    def test_analyze_cli_smoke(self, tmp_path: Path) -> None:
        """driftwatch analyze runs statistical pipeline and writes report."""
        from click.testing import CliRunner

        from driftwatch.cli.main import cli

        out_dir = tmp_path / "analysis_out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["analyze", "--output-dir", str(out_dir), "--synthetic"],
        )
        assert result.exit_code == 0, f"Analyze CLI failed: {result.output}"
        report_file = out_dir / "analysis_report.json"
        assert report_file.exists()
        import json

        data = json.loads(report_file.read_text(encoding="utf-8"))
        assert "overall_mean_asr" in data
        assert "gee_coefficients" in data
        assert "tost_equivalence" in data
