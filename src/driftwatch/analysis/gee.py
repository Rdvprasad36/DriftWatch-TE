"""Generalized Estimating Equations (GEE) for longitudinal drift.

Architecture.md §3.8 / Design.md §4.2:
  "Logistic GEE with exchangeable correlation, clustered by scenario:
   logit P(attack_success) = b0 + b1*week + b2*language + b3*week:language + b4*channel
   One model per hosted alias. Test b1 (drift) and b3 (language-specific drift)."
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class GEEResult:
    """Structured output of a fitted GEE model."""

    converged: bool
    coefficients: dict[str, float] = field(default_factory=dict)
    standard_errors: dict[str, float] = field(default_factory=dict)
    p_values: dict[str, float] = field(default_factory=dict)
    odds_ratios: dict[str, float] = field(default_factory=dict)  # exp(coef)
    conf_int_lower: dict[str, float] = field(default_factory=dict)
    conf_int_upper: dict[str, float] = field(default_factory=dict)
    summary_text: str = ""


def fit_logistic_gee(
    data: pd.DataFrame,
    *,
    formula: str = "attack_success ~ week_idx + C(language) + week_idx:C(language) + C(channel)",
    cluster_col: str = "scenario_id",
) -> GEEResult:
    """Fit a logistic GEE model clustered by scenario.

    Args:
        data: DataFrame containing columns matching the formula and cluster_col.
        formula: Patsy formula string for the model specification.
        cluster_col: Column indicating cluster groups (scenario_id).

    Returns:
        GEEResult with coefficients, odds ratios, p-values, and CIs.
    """
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    # Ensure required columns are present
    df = data.copy()
    if cluster_col not in df.columns:
        msg = f"Cluster column '{cluster_col}' not found in DataFrame"
        raise ValueError(msg)

    # Sort by cluster for GEE requirements
    df = df.sort_values(by=cluster_col).reset_index(drop=True)

    try:
        model = smf.gee(
            formula,
            groups=cluster_col,
            data=df,
            family=sm.families.Binomial(),
            cov_struct=sm.cov_struct.Exchangeable(),
        )
        fit = model.fit()

        coefs = {str(k): float(v) for k, v in fit.params.items()}
        std_errs = {str(k): float(v) for k, v in fit.bse.items()}
        p_vals = {str(k): float(v) for k, v in fit.pvalues.items()}
        # Odds ratios = exp(beta)
        odds_ratios = {str(k): float(np.exp(v)) for k, v in fit.params.items()}

        ci_df = fit.conf_int()
        ci_lower = {str(k): float(ci_df.loc[k, 0]) for k in ci_df.index}
        ci_upper = {str(k): float(ci_df.loc[k, 1]) for k in ci_df.index}

        return GEEResult(
            converged=bool(fit.converged),
            coefficients=coefs,
            standard_errors=std_errs,
            p_values=p_vals,
            odds_ratios=odds_ratios,
            conf_int_lower=ci_lower,
            conf_int_upper=ci_upper,
            summary_text=str(fit.summary()),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("GEE estimation failed: %s", exc)
        return GEEResult(
            converged=False,
            summary_text=f"Failed: {exc}",
        )
