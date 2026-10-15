"""Cluster bootstrap and Wilson score intervals for ASR estimates.

Architecture.md §3.8 / Design.md §4.1:
  "Per model, week, language: ASR = hits / trials, with cluster bootstrap
   95% CI (resample scenarios, then trials) because trials within a scenario
   are correlated. Wilson intervals are shown only for descriptive tiles."
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def wilson_score_interval(
    hits: int, total: int, *, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Calculate the Wilson score confidence interval for a proportion.

    Used for descriptive metric tiles (design.md §4.1).

    Args:
        hits: Number of positive outcomes (successes).
        total: Total number of trials.
        alpha: Significance level (default 0.05 for 95% CI).

    Returns:
        tuple of (p_hat, ci_lower, ci_upper) bounded in [0, 1].
    """
    if total <= 0:
        return 0.0, 0.0, 0.0

    p_hat = hits / total
    # z for standard normal (1.96 for alpha=0.05)
    from scipy.stats import norm

    z = float(norm.ppf(1 - alpha / 2))

    denom = 1 + (z**2) / total
    center = (p_hat + (z**2) / (2 * total)) / denom
    margin = (
        z * math.sqrt((p_hat * (1 - p_hat) / total) + (z**2) / (4 * (total**2)))
    ) / denom

    ci_lower = max(0.0, float(center - margin))
    ci_upper = min(1.0, float(center + margin))
    return p_hat, ci_lower, ci_upper


def cluster_bootstrap_ci(
    data: pd.DataFrame,
    *,
    metric_col: str = "attack_success",
    cluster_col: str = "scenario_id",
    n_resamples: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Compute two-stage cluster bootstrap 95% CI (resample scenarios, then trials).

    Trials within a scenario are correlated; simple i.i.d. bootstrap understates
    variance.  Resampling scenarios preserves intra-scenario correlation.

    Args:
        data: DataFrame containing trial results.
        metric_col: Binary column to compute mean of (e.g. 'attack_success').
        cluster_col: Scenario ID column representing clusters.
        n_resamples: Number of bootstrap iterations.
        alpha: Significance level (default 0.05 for 95% CI).
        seed: Random seed.

    Returns:
        tuple of (empirical_mean, ci_lower, ci_upper).
    """
    if data.empty:
        return 0.0, 0.0, 0.0

    empirical_mean = float(data[metric_col].mean())

    unique_clusters = data[cluster_col].unique()
    n_clusters = len(unique_clusters)
    if n_clusters == 0:
        return empirical_mean, empirical_mean, empirical_mean

    rng = np.random.default_rng(seed)

    # Pre-group data by cluster for speed
    cluster_groups: dict[Any, np.ndarray] = {
        c: group[metric_col].to_numpy() for c, group in data.groupby(cluster_col)
    }

    boot_means: list[float] = []

    for _ in range(n_resamples):
        # Stage 1: resample clusters with replacement
        sampled_clusters = rng.choice(unique_clusters, size=n_clusters, replace=True)

        # Stage 2: collect trials for sampled clusters
        sample_vals: list[float] = []
        for c in sampled_clusters:
            arr = cluster_groups[c]
            # Resample trials within the selected cluster
            resampled_trials = rng.choice(arr, size=len(arr), replace=True)
            sample_vals.extend(resampled_trials)

        if sample_vals:
            boot_means.append(float(np.mean(sample_vals)))

    if not boot_means:
        return empirical_mean, empirical_mean, empirical_mean

    ci_lower = float(np.percentile(boot_means, 100 * (alpha / 2)))
    ci_upper = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))

    return empirical_mean, ci_lower, ci_upper

