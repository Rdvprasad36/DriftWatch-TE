"""Two One-Sided Tests (TOST) for negative control equivalence.

Architecture.md §3.8 / Design.md §4.4:
  "TOST on the local model: show the difference between first-half and
   second-half ASR lies within +/-3 percentage points (margin set before data).
   If the local model drifts, investigate harness bugs before interpreting
   hosted results."
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class TOSTResult:
    """Result of Two One-Sided Tests for equivalence."""

    mean_first: float
    mean_second: float
    mean_diff: float  # second - first
    margin: float
    ci_lower: float
    ci_upper: float
    p_value_lower: float  # test H0: diff <= -margin
    p_value_upper: float  # test H0: diff >= +margin
    is_equivalent: bool  # True iff max(p_lower, p_upper) < alpha


def tost_equivalence(
    first_half: np.ndarray | list[float],
    second_half: np.ndarray | list[float],
    *,
    margin: float = 0.03,
    alpha: float = 0.05,
) -> TOSTResult:
    """Test equivalence of two independent sample proportions/means within +/-margin.

    H0_lower: diff <= -margin
    H0_upper: diff >= +margin
    Equivalence is established if both null hypotheses are rejected at level alpha.

    Args:
        first_half: Binary outcomes from period 1 (e.g. weeks 1-6).
        second_half: Binary outcomes from period 2 (e.g. weeks 7-12).
        margin: Equivalence margin (default 0.03 = +/-3 percentage points).
        alpha: Significance level (default 0.05).

    Returns:
        TOSTResult with statistics, p-values, and equivalence conclusion.
    """
    arr1 = np.asarray(first_half, dtype=float)
    arr2 = np.asarray(second_half, dtype=float)

    n1 = len(arr1)
    n2 = len(arr2)
    if n1 == 0 or n2 == 0:
        return TOSTResult(
            mean_first=0.0,
            mean_second=0.0,
            mean_diff=0.0,
            margin=margin,
            ci_lower=0.0,
            ci_upper=0.0,
            p_value_lower=1.0,
            p_value_upper=1.0,
            is_equivalent=False,
        )

    m1 = float(np.mean(arr1))
    m2 = float(np.mean(arr2))
    diff = m2 - m1

    # Standard error of the difference
    v1 = float(np.var(arr1, ddof=1)) if n1 > 1 else 0.0
    v2 = float(np.var(arr2, ddof=1)) if n2 > 1 else 0.0
    se = math.sqrt((v1 / n1) + (v2 / n2))

    if se == 0.0:
        # Perfectly identical constant samples
        equiv = abs(diff) < margin
        return TOSTResult(
            mean_first=m1,
            mean_second=m2,
            mean_diff=diff,
            margin=margin,
            ci_lower=diff,
            ci_upper=diff,
            p_value_lower=0.0 if diff > -margin else 1.0,
            p_value_upper=0.0 if diff < margin else 1.0,
            is_equivalent=equiv,
        )

    from scipy.stats import norm

    # Test 1: H0: diff <= -margin vs H1: diff > -margin
    z_lower = (diff - (-margin)) / se
    p_lower = float(1.0 - norm.cdf(z_lower))

    # Test 2: H0: diff >= margin vs H1: diff < margin
    z_upper = (diff - margin) / se
    p_upper = float(norm.cdf(z_upper))

    # 1 - 2*alpha confidence interval (matches TOST rejection rule)
    z_crit = float(norm.ppf(1 - alpha))
    ci_lower = diff - z_crit * se
    ci_upper = diff + z_crit * se

    is_equiv = max(p_lower, p_upper) < alpha

    return TOSTResult(
        mean_first=m1,
        mean_second=m2,
        mean_diff=diff,
        margin=margin,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        p_value_lower=p_lower,
        p_value_upper=p_upper,
        is_equivalent=is_equiv,
    )
