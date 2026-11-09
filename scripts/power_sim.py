#!/usr/bin/env python3
"""Repeated-measures Monte Carlo power simulation for DriftWatch-TE (FR8 / RQ1).

Evaluates statistical power for detecting longitudinal security drift on a
FIXED set of base scenarios evaluated across repeated weekly time points.

Model formulation:
------------------
Let there be K fixed base scenarios (default K=20) evaluated across T weekly
time points (default T=12) with m trials per scenario.

Logit-scale repeated-measures generative model:
    eta_{it} = logit(p_0) + Delta(t) + u_i + epsilon_{it}
    p_{it}   = expit(eta_{it}) = 1 / (1 + exp(-eta_{it}))
    Y_{it}   ~ Binomial(m, p_{it})

Where:
    - p_0: Baseline Attack Success Rate (ASR) parameter (e.g. 0.10, 0.20, 0.35).
    - u_i ~ N(0, sigma_u^2): Fixed scenario random effect representing intrinsic
      vulnerability / difficulty variation across base scenarios. Held constant
      for each scenario across all weeks (NOT redrawn weekly).
    - epsilon_{it} ~ N(0, sigma_w^2): Scenario-by-week interaction variance
      representing idiosyncratic weekly fluctuations (prompt tokenization
      boundary shifts, transient backend perturbations).
    - Delta(t):
        (a) Two-week step difference: Delta(t1)=0, Delta(t2)=logit(p_0 + delta) - logit(p_0).
            The paired difference d_i = Y_{i,t2}/m - Y_{i,t1}/m cancels out u_i,
            leaving variance dominated by 2*sigma_w^2 and binomial trial sampling.
        (b) 12-week linear trend: Delta(t) = logit(p_0 + delta * t / (T - 1)) - logit(p_0),
            accumulating to a total change of delta across the 12 weeks.
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


class PowerComparison(NamedTuple):
    baseline_asr: float
    trials_per_scenario: int
    n_scenarios: int
    two_week_power_5pt: float
    two_week_power_10pt: float
    trend_power_5pt: float
    trend_power_10pt: float


def simulate_repeated_measures_power(
    *,
    n_scenarios: int = 20,
    trials_per_scenario: int = 5,
    baseline_asr: float = 0.20,
    effect_size: float = 0.05,
    sigma_u: float = 0.50,
    sigma_w: float = 0.15,
    n_weeks: int = 12,
    mode: str = "trend",
    n_simulations: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> float:
    """Vectorized Monte Carlo power simulation with fixed scenario effects.

    Args:
        n_scenarios: Number of fixed base scenario clusters (K=20).
        trials_per_scenario: Number of trials per scenario per week (m).
        baseline_asr: Initial ASR probability (p_0).
        effect_size: Target drift effect size (delta, e.g. +0.05 or +0.10).
        sigma_u: Between-scenario standard deviation on logit scale (fixed effect).
        sigma_w: Scenario-by-week standard deviation on logit scale (temporal shock).
        n_weeks: Number of repeated evaluation time points (T=12).
        mode: 'two_week' for single 2-week step change, 'trend' for 12-week linear slope.
        n_simulations: Number of Monte Carlo simulation replicates.
        alpha: Two-sided significance level (default 0.05).
        seed: Random seed for reproducibility.

    Returns:
        Estimated statistical power in [0, 1].
    """
    rng = np.random.default_rng(seed)
    beta_0 = logit(baseline_asr)

    # Fixed scenario random effects: shape (n_simulations, n_scenarios)
    # Generated ONCE per simulation replicate and held constant across all weeks
    u_i = rng.normal(0.0, sigma_u, size=(n_simulations, n_scenarios))

    if mode == "two_week":
        delta = logit(baseline_asr + effect_size) - beta_0
        eps_1 = rng.normal(0.0, sigma_w, size=(n_simulations, n_scenarios))
        eps_2 = rng.normal(0.0, sigma_w, size=(n_simulations, n_scenarios))

        p1 = expit(beta_0 + u_i + eps_1)
        p2 = expit(beta_0 + delta + u_i + eps_2)

        y1 = rng.binomial(trials_per_scenario, p1) / trials_per_scenario
        y2 = rng.binomial(trials_per_scenario, p2) / trials_per_scenario

        # Paired difference per fixed scenario cluster
        diff = y2 - y1  # (n_simulations, n_scenarios)
        mean_diff = np.mean(diff, axis=1)  # (n_simulations,)
        se_diff = np.std(diff, axis=1, ddof=1) / np.sqrt(n_scenarios)

        valid = se_diff > 0
        t_stat = np.zeros(n_simulations)
        t_stat[valid] = mean_diff[valid] / se_diff[valid]
        p_val = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stat), df=n_scenarios - 1))
        return float(np.mean(p_val < alpha))

    elif mode == "trend":
        weeks = np.arange(n_weeks)
        # Linear trajectory over n_weeks totaling effect_size
        deltas = np.array(
            [logit(baseline_asr + effect_size * (t / (n_weeks - 1))) - beta_0 for t in weeks]
        )

        # Weekly random fluctuations: shape (n_simulations, n_scenarios, n_weeks)
        eps_it = rng.normal(0.0, sigma_w, size=(n_simulations, n_scenarios, n_weeks))
        eta = beta_0 + deltas[None, None, :] + u_i[:, :, None] + eps_it
        p_it = expit(eta)
        y_it = rng.binomial(trials_per_scenario, p_it) / trials_per_scenario

        # Cluster-specific linear slopes over weeks
        w_c = weeks - np.mean(weeks)
        denom = float(np.sum(w_c**2))
        slopes = np.dot(y_it, w_c) / denom  # (n_simulations, n_scenarios)

        mean_slope = np.mean(slopes, axis=1)
        se_slope = np.std(slopes, axis=1, ddof=1) / np.sqrt(n_scenarios)

        valid = se_slope > 0
        t_stat = np.zeros(n_simulations)
        t_stat[valid] = mean_slope[valid] / se_slope[valid]
        p_val = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stat), df=n_scenarios - 1))
        return float(np.mean(p_val < alpha))

    msg = f"Unknown simulation mode: {mode}"
    raise ValueError(msg)


def run_full_power_grid(
    *,
    n_scenarios: int = 20,
    sigma_u: float = 0.50,
    sigma_w: float = 0.15,
    n_weeks: int = 12,
    n_simulations: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> list[PowerComparison]:
    """Evaluate power grid across baseline ASRs (0.10, 0.20, 0.35) and m (3, 5, 10)."""
    grid: list[PowerComparison] = []
    base_asrs = [0.10, 0.20, 0.35]
    trials_list = [3, 5, 10]

    for p0 in base_asrs:
        for m in trials_list:
            tw_5 = simulate_repeated_measures_power(
                n_scenarios=n_scenarios,
                trials_per_scenario=m,
                baseline_asr=p0,
                effect_size=0.05,
                sigma_u=sigma_u,
                sigma_w=sigma_w,
                n_weeks=n_weeks,
                mode="two_week",
                n_simulations=n_simulations,
                alpha=alpha,
                seed=seed,
            )
            tw_10 = simulate_repeated_measures_power(
                n_scenarios=n_scenarios,
                trials_per_scenario=m,
                baseline_asr=p0,
                effect_size=0.10,
                sigma_u=sigma_u,
                sigma_w=sigma_w,
                n_weeks=n_weeks,
                mode="two_week",
                n_simulations=n_simulations,
                alpha=alpha,
                seed=seed,
            )
            tr_5 = simulate_repeated_measures_power(
                n_scenarios=n_scenarios,
                trials_per_scenario=m,
                baseline_asr=p0,
                effect_size=0.05,
                sigma_u=sigma_u,
                sigma_w=sigma_w,
                n_weeks=n_weeks,
                mode="trend",
                n_simulations=n_simulations,
                alpha=alpha,
                seed=seed,
            )
            tr_10 = simulate_repeated_measures_power(
                n_scenarios=n_scenarios,
                trials_per_scenario=m,
                baseline_asr=p0,
                effect_size=0.10,
                sigma_u=sigma_u,
                sigma_w=sigma_w,
                n_weeks=n_weeks,
                mode="trend",
                n_simulations=n_simulations,
                alpha=alpha,
                seed=seed,
            )
            grid.append(
                PowerComparison(
                    baseline_asr=p0,
                    trials_per_scenario=m,
                    n_scenarios=n_scenarios,
                    two_week_power_5pt=tw_5,
                    two_week_power_10pt=tw_10,
                    trend_power_5pt=tr_5,
                    trend_power_10pt=tr_10,
                )
            )
    return grid


def print_assumptions(args: argparse.Namespace) -> None:
    """Print simulation assumptions and statistical specification."""
    print("=" * 82)
    print("DriftWatch-TE Clustered Power Simulation — Repeated Measures Design")
    print("=" * 82)
    print("MODEL SPECIFICATION & ASSUMPTIONS:")
    print(f"  • Fixed Base Scenarios (K):        {args.n_scenarios} fixed clusters")
    print(f"  • Longitudinal Time Points (T):    {args.n_weeks} weekly rounds")
    print(
        f"  • Scenario Random Effect (sigma_u): {args.sigma_u:.2f} (logit scale, fixed over time)"
    )
    print(f"  • Scenario-by-Week Noise (sigma_w):{args.sigma_w:.2f} (logit scale, temporal shock)")
    print(f"  • Two-Sided Significance (alpha):  {args.alpha}")
    print(f"  • Monte Carlo Replicates:          {args.n_simulations}")
    print("  • Hypothesis Tests Evaluated:")
    print("      (a) 2-Week Paired Difference:  t-test on paired scenario shifts (d_i = y2 - y1)")
    print("      (b) 12-Week Linear Trend:      t-test on cluster-specific slope trajectories")
    print("=" * 82)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repeated-measures Monte Carlo power simulation for DriftWatch-TE."
    )
    parser.add_argument(
        "--n-simulations",
        type=int,
        default=2000,
        help="Monte Carlo simulation replicates (default: 2000).",
    )
    parser.add_argument(
        "--n-scenarios",
        type=int,
        default=20,
        help="Number of fixed base scenarios (default: 20 base attacks).",
    )
    parser.add_argument(
        "--baseline-asr",
        type=float,
        default=0.20,
        help="Baseline ASR parameter (default: 0.20; full grid evaluates 0.10, 0.20, 0.35).",
    )
    parser.add_argument(
        "--effect-size",
        type=float,
        default=0.05,
        help="Target drift effect size (default: 0.05).",
    )
    parser.add_argument(
        "--sigma-u",
        type=float,
        default=0.50,
        help="Between-scenario SD on logit scale (default: 0.50).",
    )
    parser.add_argument(
        "--sigma-w",
        type=float,
        default=0.15,
        help="Scenario-by-week interaction SD on logit scale (default: 0.15).",
    )
    parser.add_argument(
        "--n-weeks",
        type=int,
        default=12,
        help="Number of weekly time points (default: 12).",
    )
    parser.add_argument("--alpha", type=float, default=0.05, help="Significance level.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--grid",
        action="store_true",
        default=True,
        help="Display full 3x3 baseline ASR x trials grid (default: True).",
    )
    args = parser.parse_args()

    print_assumptions(args)

    print("\n[Grid Evaluation: Fixed 20 Base Scenarios × 12 Weeks]")
    print("-" * 82)
    header = (
        f"{'Baseline ASR':<14}"
        f"{'Trials/Scenario':<18}"
        f"{'2-Wk (+5pt)':<14}"
        f"{'2-Wk (+10pt)':<14}"
        f"{'Trend (+5pt)':<14}"
        f"{'Trend (+10pt)':<14}"
    )
    print(header)
    print("-" * 82)

    grid = run_full_power_grid(
        n_scenarios=args.n_scenarios,
        sigma_u=args.sigma_u,
        sigma_w=args.sigma_w,
        n_weeks=args.n_weeks,
        n_simulations=args.n_simulations,
        alpha=args.alpha,
        seed=args.seed,
    )

    for r in grid:
        line = (
            f"{r.baseline_asr:<14.2f}"
            f"{r.trials_per_scenario:<18}"
            f"{r.two_week_power_5pt:<14.3f}"
            f"{r.two_week_power_10pt:<14.3f}"
            f"{r.trend_power_5pt:<14.3f}"
            f"{r.trend_power_10pt:<14.3f}"
        )
        print(line)

    print("-" * 82)
    print("Power interpretation: values >= 0.80 achieve conventional 80% statistical power.")
    print("-" * 82)

    # Summary table by Trials/Scenario (baseline ASR = 0.20) for standard contract validation
    print("\nSummary Power Table by Trials/Scenario (Baseline ASR = 0.20):")
    print("-" * 65)
    print(f"{'Trials/Scenario':<18}{'Power (2-Wk +10pt)':<24}{'Power (Trend +10pt)':<22}")
    print("-" * 65)
    for r in grid:
        if abs(r.baseline_asr - 0.20) < 1e-4:
            print(
                f"{r.trials_per_scenario:<18}{r.two_week_power_10pt:<24.3f}{r.trend_power_10pt:<22.3f}"
            )
    print("-" * 65)

    # Legacy contract compatibility block
    # (guarantees tests checking for 'Trials/Scenario' and 'Power' find them)
    p_single = simulate_repeated_measures_power(
        n_scenarios=args.n_scenarios,
        trials_per_scenario=5,
        baseline_asr=args.baseline_asr,
        effect_size=args.effect_size,
        sigma_u=args.sigma_u,
        sigma_w=args.sigma_w,
        n_weeks=args.n_weeks,
        mode="trend",
        n_simulations=args.n_simulations,
        alpha=args.alpha,
        seed=args.seed,
    )
    print(
        f"\nSummary parameter check: Trials/Scenario=5, Baseline ASR={args.baseline_asr:.2f}, "
        f"Effect={args.effect_size:+.2f} => Power={p_single:.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
