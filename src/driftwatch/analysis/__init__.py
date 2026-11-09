"""Statistical analysis module for DriftWatch-TE.

Implements GEE, cluster bootstrap, change-point detection (PELT/CUSUM),
TOST equivalence testing, and multiple testing corrections.
FR8, design.md §4, architecture.md §3.8.
"""

from __future__ import annotations

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
from driftwatch.analysis.gee import (
    GEEResult,
    cluster_permutation_test,
    fit_logistic_gee,
)
from driftwatch.analysis.synthetic import generate_synthetic_trials
from driftwatch.analysis.tost import TOSTResult, tost_equivalence

__all__ = [
    "GEEResult",
    "TOSTResult",
    "benjamini_hochberg",
    "cluster_bootstrap_ci",
    "cluster_permutation_test",
    "detect_changepoints_cusum",
    "detect_changepoints_pelt",
    "fit_logistic_gee",
    "generate_synthetic_trials",
    "tost_equivalence",
    "validate_changepoint_with_bootstrap",
    "wilson_score_interval",
]
