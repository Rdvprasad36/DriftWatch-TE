"""Change-point detection for longitudinal security drift.

Architecture.md §3.8 / Design.md §4.3:
  "Methods: PELT (ruptures) with a penalty chosen by cross-validation-free
   rule fixed in advance, plus CUSUM as a check.
   A change point is 'supported' only if the before/after difference has
   a cluster-bootstrap CI excluding zero."
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def detect_changepoints_pelt(
    series: list[float] | np.ndarray,
    *,
    model: str = "rbf",
    penalty: float = 3.0,
    min_size: int = 2,
) -> list[int]:
    """Detect change points using the PELT algorithm via ruptures.

    Args:
        series: 1D array of metric values over consecutive time points (weeks).
        model: Segment model ('rbf', 'l2', 'normal').
        penalty: Penalty parameter balancing fit vs number of segments.
        min_size: Minimum segment size.

    Returns:
        List of change point indices (1-based end of segment).
    """
    arr = np.asarray(series, dtype=float)
    if len(arr) < min_size * 2:
        return []

    import ruptures as rpt

    algo = rpt.Pelt(model=model, min_size=min_size, jump=1).fit(arr)
    cps: list[int] = algo.predict(pen=penalty)
    return cps


def detect_changepoints_cusum(
    series: list[float] | np.ndarray,
    *,
    threshold: float = 2.0,
    drift: float = 0.2,
) -> list[int]:
    """Detect mean shifts using Cumulative Sum (CUSUM) as a check.

    Args:
        series: 1D array of weekly metrics.
        threshold: Decision threshold for flagging a shift.
        drift: Slack parameter (expected shift size allowance).

    Returns:
        List of 0-based week indices where shifts were detected.
    """
    arr = np.asarray(series, dtype=float)
    n = len(arr)
    if n < 3:
        return []

    mean_val = float(np.mean(arr))
    std_val = float(np.std(arr, ddof=1)) if n > 1 else 1.0
    if std_val == 0.0:
        return []

    # Standardize series
    z = (arr - mean_val) / std_val

    s_pos = 0.0
    s_neg = 0.0
    detected: list[int] = []

    for i in range(n):
        s_pos = max(0.0, s_pos + z[i] - drift)
        s_neg = max(0.0, s_neg - z[i] - drift)

        if s_pos > threshold or s_neg > threshold:
            detected.append(i)
            # Reset after alarm
            s_pos = 0.0
            s_neg = 0.0

    return detected


def validate_changepoint_with_bootstrap(
    before_series: list[float] | np.ndarray,
    after_series: list[float] | np.ndarray,
    *,
    n_resamples: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, Any]:
    """Test if a detected change point is 'supported' by bootstrap CI excluding 0.

    Per design.md §4.3: "A change point is 'supported' only if the before/after
    difference has a cluster-bootstrap CI excluding zero."

    Args:
        before_series: Metric values from segment before change point.
        after_series: Metric values from segment after change point.
        n_resamples: Bootstrap iterations.
        alpha: Significance level (default 0.05).
        seed: Random seed.

    Returns:
        Dict with diff_mean, ci_lower, ci_upper, and supported (bool).
    """
    b = np.asarray(before_series, dtype=float)
    a = np.asarray(after_series, dtype=float)

    if len(b) == 0 or len(a) == 0:
        return {
            "diff_mean": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 0.0,
            "supported": False,
        }

    diff_mean = float(np.mean(a) - np.mean(b))

    rng = np.random.default_rng(seed)
    diffs: list[float] = []

    for _ in range(n_resamples):
        resampled_b = rng.choice(b, size=len(b), replace=True)
        resampled_a = rng.choice(a, size=len(a), replace=True)
        diffs.append(float(np.mean(resampled_a) - np.mean(resampled_b)))

    ci_lower = float(np.percentile(diffs, 100 * (alpha / 2)))
    ci_upper = float(np.percentile(diffs, 100 * (1 - alpha / 2)))

    # Supported if 0 is outside the confidence interval
    supported = (ci_lower > 0.0) or (ci_upper < 0.0)

    return {
        "diff_mean": diff_mean,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "supported": supported,
    }
