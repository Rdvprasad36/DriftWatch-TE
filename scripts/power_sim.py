#!/usr/bin/env python3
"""Repeated-measures Monte Carlo power simulation for DriftWatch-TE (FR8 / RQ1).

Evaluates statistical power for detecting longitudinal security drift on a
FIXED set of base scenarios evaluated across repeated weekly time points.

Model Formulation & Within-Base Hierarchical Structure:
-------------------------------------------------------
In DriftWatch-TE, the study suite consists of K=20 base attacks. Each base attack
is crossed with 3 languages (English 'en', Telugu 'te', Code-switched 'te-en')
and 2 channels ('tool_description', 'tool_output'), yielding exactly 6 variants
per base attack (total 120 scenario variants).

Hierarchical Logit-Scale Generative Model:
------------------------------------------
For base attack cluster i in {1, ..., K}, variant v in {1, ..., 6}, and week t in {0, ..., T-1}:

1. Base and Variant Latent Effects:
   - Base attack vulnerability: u_i ~ N(0, rho * sigma_u^2), fixed over time.
   - Variant-specific deviation: v_{iv} ~ N(0, (1 - rho) * sigma_u^2), fixed over time.
   - Scenario effect: S_{iv} = u_i + v_{iv}.
   - The parameter rho in [0, 1] represents the within-base intraclass correlation:
       Cov(S_{iv}, S_{iv'}) = rho * sigma_u^2, Var(S_{iv}) = sigma_u^2,
       so Corr(S_{iv}, S_{iv'}) = rho for variants of the same base attack.

2. Exposure Mechanism for Tool Channels:
   - For 'tool_description' variants (v in {1, 2, 3}), the injection is embedded in
     the tool definition / prompt schema. Exposure is guaranteed: P(Exposed) = 1.0.
   - For 'tool_output' variants (v in {4, 5, 6}), the injection is delivered inside
     the runtime return payload of an initial tool call (e.g. read_reviews).
     Exposure occurs only if the agent executes the preamble tool call:
       E_{itv} ~ Bernoulli(p_expose), with default p_expose = 0.85.
     If unexposed (E = 0), the attack cannot succeed (Y = 0).

3. Longitudinal Dynamics & Temporal Shocks:
   - Weekly idiosyncratic cluster perturbation: epsilon_{it} ~ N(0, sigma_w^2).
   - Drift signal Delta(t):
       (a) Linear trend: Delta(t) = logit(p_0 + delta * t / (T - 1)) - logit(p_0)
       (b) Step change at week 6:
           Delta(t) = 0 for t < 6, logit(p_0 + delta) - logit(p_0) for t >= 6
       (c) Two-week step: Delta(t1) = 0, Delta(t2) = logit(p_0 + delta) - logit(p_0)
   - Latent conditional logit:
       eta_{itv} = logit(p_0) + Delta(t) + u_i + v_{iv} + epsilon_{it}
   - Conditional probability of attack success given exposure:
       p_{itv} = expit(eta_{itv}) = 1 / (1 + exp(-eta_{itv}))

4. Outcome Generation:
   - For exposed trials, Y_{itv} ~ Binomial(m, p_{itv}).
   - For unexposed trials, Y = 0.
   - The analysis clusters strictly on base_id (K=20 clusters) by aggregating
     outcomes across the 6 variants, matching the study-grade GEE and bootstrap design.
"""

from __future__ import annotations

import argparse
import sys
from typing import NamedTuple

import numpy as np
from scipy import stats


def expit(x: np.ndarray | float) -> np.ndarray | float:
    """Logistic sigmoid function."""
    return 1.0 / (1.0 + np.exp(-x))


def logit(p: float) -> float:
    """Log-odds function."""
    p_clipped = np.clip(p, 1e-6, 1.0 - 1e-6)
    return float(np.log(p_clipped / (1.0 - p_clipped)))


class PowerRecord(NamedTuple):
    baseline_asr: float
    trials_per_scenario: int
    n_weeks: int
    rho: float
    p_expose: float
    trend_power_5pt: float
    trend_power_10pt: float
    step_power_5pt: float
    step_power_10pt: float
    two_week_power_5pt: float
    two_week_power_10pt: float
    mde_trend_80: float
    mde_step_80: float


def simulate_clustered_longitudinal_power(
    *,
    n_scenarios: int = 20,
    n_variants_per_base: int = 6,
    trials_per_scenario: int = 5,
    baseline_asr: float = 0.20,
    effect_size: float = 0.05,
    rho: float = 0.60,
    p_expose: float = 0.85,
    sigma_u: float = 0.50,
    sigma_w: float = 0.15,
    n_weeks: int = 12,
    mode: str = "trend",
    step_week: int = 6,
    n_simulations: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float]:
    """Vectorized Monte Carlo power and standard error simulation.

    Args:
        n_scenarios: Number of fixed base scenario clusters (K=20).
        n_variants_per_base: Number of variants per base attack (6: 3 lang x 2 chan).
        trials_per_scenario: Trials per scenario variant per week (m).
        baseline_asr: Initial ASR probability (p_0).
        effect_size: Drift magnitude (delta, e.g. +0.05 or +0.10).
        rho: Within-base correlation (variance share of shared base effect).
        p_expose: Exposure probability for tool_output channel variants.
        sigma_u: Total scenario SD on logit scale (sigma_u).
        sigma_w: Weekly idiosyncratic cluster perturbation SD (sigma_w).
        n_weeks: Total study weeks (T=12 or 16).
        mode: 'trend' (linear drift), 'step' (shift at step_week), or 'two_week'.
        step_week: Week index for sudden step shift (default: 6).
        n_simulations: Number of Monte Carlo iterations.
        alpha: Two-sided significance level (default: 0.05).
        seed: Random seed for reproducibility.

    Returns:
        tuple of (empirical_power, mean_standard_error).
    """
    rng = np.random.default_rng(seed)
    beta_0 = logit(baseline_asr)

    # 1. Base attack shared effect: shape (n_simulations, n_scenarios, 1, 1)
    sigma_base = np.sqrt(rho) * sigma_u
    u_i = rng.normal(0.0, sigma_base, size=(n_simulations, n_scenarios, 1, 1))

    # 2. Variant-specific deviations: shape (n_simulations, n_scenarios, n_variants, 1)
    sigma_var = np.sqrt(max(0.0, 1.0 - rho)) * sigma_u
    v_iv = rng.normal(0.0, sigma_var, size=(n_simulations, n_scenarios, n_variants_per_base, 1))

    # Combined scenario effect: shape (n_simulations, n_scenarios, n_variants, 1)
    s_iv = u_i + v_iv

    # 3. Channel exposure probabilities across the 6 variants
    # Variants 0..2: tool_description -> p_exp = 1.0
    # Variants 3..5: tool_output      -> p_exp = p_expose
    p_exp_vec = np.ones(n_variants_per_base)
    half = n_variants_per_base // 2
    p_exp_vec[half:] = p_expose
    # Reshape for broadcasting: (1, 1, n_variants, 1)
    p_exp_mat = p_exp_vec[None, None, :, None]

    if mode == "two_week":
        # Two consecutive weeks (t=0 and t=1)
        eps = rng.normal(0.0, sigma_w, size=(n_simulations, n_scenarios, 1, 2))
        delta_val = logit(baseline_asr + effect_size) - beta_0
        delta_vec = np.array([0.0, delta_val])[None, None, None, :]

        eta = beta_0 + delta_vec + s_iv + eps
        p_cond = expit(eta)
        effective_p = p_cond * p_exp_mat

        # Sample binomial trials: (n_sims, n_scenarios, n_variants, 2)
        y = rng.binomial(trials_per_scenario, effective_p) / trials_per_scenario
        # Cluster-level mean ASR per base attack: average over the 6 variants
        y_cluster = np.mean(y, axis=2)  # (n_sims, n_scenarios, 2)

        diff = y_cluster[:, :, 1] - y_cluster[:, :, 0]  # (n_sims, n_scenarios)
        mean_diff = np.mean(diff, axis=1)
        se_diff = np.std(diff, axis=1, ddof=1) / np.sqrt(n_scenarios)

        valid = se_diff > 0
        t_stat = np.zeros(n_simulations)
        t_stat[valid] = mean_diff[valid] / se_diff[valid]
        p_val = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stat), df=n_scenarios - 1))
        power = float(np.mean(p_val < alpha))
        avg_se = float(np.mean(se_diff[valid])) if np.any(valid) else 0.0
        return power, avg_se

    elif mode == "step":
        weeks = np.arange(n_weeks)
        eps = rng.normal(0.0, sigma_w, size=(n_simulations, n_scenarios, 1, n_weeks))
        delta_val = logit(baseline_asr + effect_size) - beta_0
        delta_vec = np.where(weeks >= step_week, delta_val, 0.0)[None, None, None, :]

        eta = beta_0 + delta_vec + s_iv + eps
        p_cond = expit(eta)
        effective_p = p_cond * p_exp_mat

        y = rng.binomial(trials_per_scenario, effective_p) / trials_per_scenario
        # Cluster-level mean ASR per week: average over the 6 variants
        y_cluster = np.mean(y, axis=2)  # (n_sims, n_scenarios, n_weeks)

        # Difference between post-step and pre-step
        pre_mean = np.mean(y_cluster[:, :, :step_week], axis=2)
        post_mean = np.mean(y_cluster[:, :, step_week:], axis=2)
        diff = post_mean - pre_mean  # (n_sims, n_scenarios)

        mean_diff = np.mean(diff, axis=1)
        se_diff = np.std(diff, axis=1, ddof=1) / np.sqrt(n_scenarios)

        valid = se_diff > 0
        t_stat = np.zeros(n_simulations)
        t_stat[valid] = mean_diff[valid] / se_diff[valid]
        p_val = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stat), df=n_scenarios - 1))
        power = float(np.mean(p_val < alpha))
        avg_se = float(np.mean(se_diff[valid])) if np.any(valid) else 0.0
        return power, avg_se

    elif mode == "trend":
        weeks = np.arange(n_weeks)
        eps = rng.normal(0.0, sigma_w, size=(n_simulations, n_scenarios, 1, n_weeks))
        # Total change accumulating to effect_size at week T-1
        delta_traj = np.array(
            [logit(baseline_asr + effect_size * (t / (n_weeks - 1))) - beta_0 for t in weeks]
        )
        delta_vec = delta_traj[None, None, None, :]

        eta = beta_0 + delta_vec + s_iv + eps
        p_cond = expit(eta)
        effective_p = p_cond * p_exp_mat

        y = rng.binomial(trials_per_scenario, effective_p) / trials_per_scenario
        y_cluster = np.mean(y, axis=2)  # (n_sims, n_scenarios, n_weeks)

        # Cluster-specific linear slopes over weeks
        w_c = weeks - np.mean(weeks)
        denom = float(np.sum(w_c**2))
        slopes = np.dot(y_cluster, w_c) / denom  # (n_sims, n_scenarios)

        mean_slope = np.mean(slopes, axis=1)
        se_slope = np.std(slopes, axis=1, ddof=1) / np.sqrt(n_scenarios)

        valid = se_slope > 0
        t_stat = np.zeros(n_simulations)
        t_stat[valid] = mean_slope[valid] / se_slope[valid]
        p_val = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stat), df=n_scenarios - 1))
        power = float(np.mean(p_val < alpha))

        # Convert slope SE to total 12/16-week change SE for MDE calculation
        total_time_span = float(n_weeks - 1)
        avg_total_se = float(np.mean(se_slope[valid]) * total_time_span) if np.any(valid) else 0.0
        return power, avg_total_se

    msg = f"Unknown simulation mode: {mode}"
    raise ValueError(msg)


def calculate_mde_80(se: float, df: int = 19, alpha: float = 0.05) -> float:
    """Calculate Minimum Detectable Effect size for 80% power on t(df) test."""
    if se <= 0:
        return 0.0
    t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, df=df))
    # For 80% power (beta=0.20), noncentrality parameter shift ~ t_crit + z_0.80
    z_80 = float(stats.norm.ppf(0.80))
    ncp = t_crit + z_80
    return float(ncp * se)


def run_comprehensive_power_study(
    *,
    n_scenarios: int = 20,
    sigma_u: float = 0.50,
    sigma_w: float = 0.15,
    p_expose: float = 0.85,
    n_simulations: int = 1500,
    alpha: float = 0.05,
    seed: int = 42,
) -> list[PowerRecord]:
    """Execute evaluation across the full required parameter grid."""
    baselines = [0.15, 0.25, 0.35]
    trials_per_scenario_list = [5, 10]
    weeks_list = [12, 16]
    rhos = [0.30, 0.60, 0.90]

    records: list[PowerRecord] = []

    for p0 in baselines:
        for m in trials_per_scenario_list:
            for n_w in weeks_list:
                for r in rhos:
                    # Linear trend
                    tr_5, se_tr = simulate_clustered_longitudinal_power(
                        n_scenarios=n_scenarios,
                        trials_per_scenario=m,
                        baseline_asr=p0,
                        effect_size=0.05,
                        rho=r,
                        p_expose=p_expose,
                        sigma_u=sigma_u,
                        sigma_w=sigma_w,
                        n_weeks=n_w,
                        mode="trend",
                        n_simulations=n_simulations,
                        alpha=alpha,
                        seed=seed,
                    )
                    tr_10, _ = simulate_clustered_longitudinal_power(
                        n_scenarios=n_scenarios,
                        trials_per_scenario=m,
                        baseline_asr=p0,
                        effect_size=0.10,
                        rho=r,
                        p_expose=p_expose,
                        sigma_u=sigma_u,
                        sigma_w=sigma_w,
                        n_weeks=n_w,
                        mode="trend",
                        n_simulations=n_simulations,
                        alpha=alpha,
                        seed=seed,
                    )
                    # Step change at week 6
                    st_5, se_st = simulate_clustered_longitudinal_power(
                        n_scenarios=n_scenarios,
                        trials_per_scenario=m,
                        baseline_asr=p0,
                        effect_size=0.05,
                        rho=r,
                        p_expose=p_expose,
                        sigma_u=sigma_u,
                        sigma_w=sigma_w,
                        n_weeks=n_w,
                        mode="step",
                        step_week=6,
                        n_simulations=n_simulations,
                        alpha=alpha,
                        seed=seed,
                    )
                    st_10, _ = simulate_clustered_longitudinal_power(
                        n_scenarios=n_scenarios,
                        trials_per_scenario=m,
                        baseline_asr=p0,
                        effect_size=0.10,
                        rho=r,
                        p_expose=p_expose,
                        sigma_u=sigma_u,
                        sigma_w=sigma_w,
                        n_weeks=n_w,
                        mode="step",
                        step_week=6,
                        n_simulations=n_simulations,
                        alpha=alpha,
                        seed=seed,
                    )
                    # Two-week difference
                    tw_5, _ = simulate_clustered_longitudinal_power(
                        n_scenarios=n_scenarios,
                        trials_per_scenario=m,
                        baseline_asr=p0,
                        effect_size=0.05,
                        rho=r,
                        p_expose=p_expose,
                        sigma_u=sigma_u,
                        sigma_w=sigma_w,
                        n_weeks=n_w,
                        mode="two_week",
                        n_simulations=n_simulations,
                        alpha=alpha,
                        seed=seed,
                    )
                    tw_10, _ = simulate_clustered_longitudinal_power(
                        n_scenarios=n_scenarios,
                        trials_per_scenario=m,
                        baseline_asr=p0,
                        effect_size=0.10,
                        rho=r,
                        p_expose=p_expose,
                        sigma_u=sigma_u,
                        sigma_w=sigma_w,
                        n_weeks=n_w,
                        mode="two_week",
                        n_simulations=n_simulations,
                        alpha=alpha,
                        seed=seed,
                    )

                    mde_tr = calculate_mde_80(se_tr, df=n_scenarios - 1)
                    mde_st = calculate_mde_80(se_st, df=n_scenarios - 1)

                    records.append(
                        PowerRecord(
                            baseline_asr=p0,
                            trials_per_scenario=m,
                            n_weeks=n_w,
                            rho=r,
                            p_expose=p_expose,
                            trend_power_5pt=tr_5,
                            trend_power_10pt=tr_10,
                            step_power_5pt=st_5,
                            step_power_10pt=st_10,
                            two_week_power_5pt=tw_5,
                            two_week_power_10pt=tw_10,
                            mde_trend_80=mde_tr,
                            mde_step_80=mde_st,
                        )
                    )
    return records


def print_detailed_assumptions() -> None:
    """Print thorough model documentation, variant structure, and mathematical formulation."""
    print("=" * 86)
    print("DriftWatch-TE Clustered Power Simulation — Hierarchical Repeated Measures Design")
    print("=" * 86)
    print("MODEL STRUCTURE & MULTI-VARIANT HIERARCHY:")
    print("  • Base Attack Clusters (K):      20 fixed base scenarios")
    print("  • Variants per Base Attack:      6 variants = 3 languages (en, te, te-en)")
    print("                                   x 2 channels (tool_description, tool_output)")
    print("  • Total Scenario Pool:           120 scenario variants evaluated weekly")
    print(
        "  • Latent Decomposition:          "
        "eta_{itv} = logit(p_0) + Delta(t) + u_i + v_{iv} + eps_{it}"
    )
    print("      - Shared base effect u_i:    u_i ~ N(0, rho * sigma_u^2), fixed over time")
    print(
        "      - Variant deviation v_{iv}:  v_{iv} ~ N(0, (1 - rho) * sigma_u^2), fixed over time"
    )
    print("      - Within-base correlation:   Corr(S_{iv}, S_{iv'}) = rho (0.30, 0.60, 0.90)")
    print("      - Scenario-by-week noise:    eps_{it} ~ N(0, sigma_w^2) = 0.15 (temporal noise)")
    print("  • Exposure Mechanism:")
    print("      - tool_description variants: Exposure is 100% (injected text inside tool schema)")
    print(
        "      - tool_output variants:      P(exposure) = p_expose = 0.85 (preamble tool executed)"
    )
    print("      - Unexposed trials:          Cannot trigger injection; attack_success = 0")
    print("  • Statistical Hypotheses Evaluated:")
    print("      1. Linear Trend:             Slope across 12 or 16 weeks (total +5pt, +10pt)")
    print("      2. Step Change at Week 6:    Post-week-6 vs pre-week-6 difference (+5pt, +10pt)")
    print(
        "      3. 2-Week Paired Difference: Paired shift between consecutive rounds (+5pt, +10pt)"
    )
    print(
        "      4. MDE (80% Power):          Min detectable total change at alpha=0.05, beta=0.80"
    )
    print("=" * 86)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hierarchical repeated-measures power simulation for DriftWatch-TE."
    )
    parser.add_argument(
        "--n-simulations",
        type=int,
        default=1500,
        help="Monte Carlo simulation replicates (default: 1500).",
    )
    parser.add_argument(
        "--n-scenarios",
        type=int,
        default=20,
        help="Number of fixed base scenarios (default: 20).",
    )
    parser.add_argument(
        "--p-expose",
        type=float,
        default=0.85,
        help="Probability of tool_output exposure (default: 0.85).",
    )
    parser.add_argument(
        "--sigma-u",
        type=float,
        default=0.50,
        help="Total scenario SD on logit scale (default: 0.50).",
    )
    parser.add_argument(
        "--sigma-w",
        type=float,
        default=0.15,
        help="Weekly temporal noise SD on logit scale (default: 0.15).",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        help="Significance level (default: 0.05).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    args = parser.parse_args()

    print_detailed_assumptions()

    # 1. Summary Contract Table for CI & test compatibility (trials = 3, 5, 10)
    print("\nSummary Power Table by Trials/Scenario (Baseline ASR = 0.20, T = 12 Weeks):")
    print("-" * 74)
    print(
        f"{'Trials/Scenario':<18}"
        f"{'Power (2-Wk +10pt)':<20}"
        f"{'Power (Step +10pt)':<20}"
        f"{'Power (Trend +10pt)':<16}"
    )
    print("-" * 74)
    for m in [3, 5, 10]:
        tw_10, _ = simulate_clustered_longitudinal_power(
            n_scenarios=args.n_scenarios,
            trials_per_scenario=m,
            baseline_asr=0.20,
            effect_size=0.10,
            rho=0.60,
            p_expose=args.p_expose,
            sigma_u=args.sigma_u,
            sigma_w=args.sigma_w,
            n_weeks=12,
            mode="two_week",
            n_simulations=min(args.n_simulations, 1000),
            alpha=args.alpha,
            seed=args.seed,
        )
        st_10, _ = simulate_clustered_longitudinal_power(
            n_scenarios=args.n_scenarios,
            trials_per_scenario=m,
            baseline_asr=0.20,
            effect_size=0.10,
            rho=0.60,
            p_expose=args.p_expose,
            sigma_u=args.sigma_u,
            sigma_w=args.sigma_w,
            n_weeks=12,
            mode="step",
            step_week=6,
            n_simulations=min(args.n_simulations, 1000),
            alpha=args.alpha,
            seed=args.seed,
        )
        tr_10, _ = simulate_clustered_longitudinal_power(
            n_scenarios=args.n_scenarios,
            trials_per_scenario=m,
            baseline_asr=0.20,
            effect_size=0.10,
            rho=0.60,
            p_expose=args.p_expose,
            sigma_u=args.sigma_u,
            sigma_w=args.sigma_w,
            n_weeks=12,
            mode="trend",
            n_simulations=min(args.n_simulations, 1000),
            alpha=args.alpha,
            seed=args.seed,
        )
        print(f"{m:<18}{tw_10:<20.3f}{st_10:<20.3f}{tr_10:<16.3f}")
    print("-" * 74)

    # 2. Comprehensive Study Grid Evaluation
    print(
        "\nComprehensive Clustered Grid: Baselines (0.15, 0.25, 0.35) x Trials (5, 10) x "
        "Weeks (12, 16) x Rho (0.3, 0.6, 0.9):"
    )
    print("=" * 118)
    hdr = (
        f"{'Base':<6}"
        f"{'m':<4}"
        f"{'T':<4}"
        f"{'rho':<5}"
        f"{'Tr(+5p)':<9}"
        f"{'Tr(+10p)':<10}"
        f"{'St(+5p)':<9}"
        f"{'St(+10p)':<10}"
        f"{'2W(+5p)':<9}"
        f"{'2W(+10p)':<10}"
        f"{'MDE(Tr80)':<11}"
        f"{'MDE(St80)':<10}"
    )
    print(hdr)
    print("=" * 118)

    records = run_comprehensive_power_study(
        n_scenarios=args.n_scenarios,
        sigma_u=args.sigma_u,
        sigma_w=args.sigma_w,
        p_expose=args.p_expose,
        n_simulations=args.n_simulations,
        alpha=args.alpha,
        seed=args.seed,
    )

    for r in records:
        line = (
            f"{r.baseline_asr:<6.2f}"
            f"{r.trials_per_scenario:<4}"
            f"{r.n_weeks:<4}"
            f"{r.rho:<5.1f}"
            f"{r.trend_power_5pt:<9.3f}"
            f"{r.trend_power_10pt:<10.3f}"
            f"{r.step_power_5pt:<9.3f}"
            f"{r.step_power_10pt:<10.3f}"
            f"{r.two_week_power_5pt:<9.3f}"
            f"{r.two_week_power_10pt:<10.3f}"
            f"{r.mde_trend_80:<11.3f}"
            f"{r.mde_step_80:<10.3f}"
        )
        print(line)

    print("=" * 118)
    print("Interpretation:")
    print("  • Values >= 0.80 achieve the conventional 80% statistical power threshold.")
    print("  • MDE(Tr80): Minimum detectable total linear drift over T weeks for 80% power.")
    print("  • MDE(St80): Minimum detectable step change at week 6 for 80% power.")
    print("=" * 118)
    return 0


if __name__ == "__main__":
    sys.exit(main())
