#!/usr/bin/env python3
"""Monte Carlo clustered statistical power simulation for DriftWatch-TE.

Simulates clustered binary outcomes (attack success/failure) across scenarios
to evaluate statistical power for detecting a 5-percentage-point change in Attack
Success Rate (ASR) at 3, 5, and 10 trials per scenario under scenario-level clustering.
"""

from __future__ import annotations

import argparse
import sys
from typing import NamedTuple

import numpy as np
from scipy import stats


class PowerResult(NamedTuple):
    trials_per_scenario: int
    n_scenarios: int
    total_n: int
    power: float
    baseline_asr: float
    effect_size: float
    alpha: float


def simulate_clustered_power(
    trials_per_scenario: int,
    n_scenarios: int = 16,
    baseline_asr: float = 0.15,
    effect_size: float = 0.05,
    icc: float = 0.10,
    alpha: float = 0.05,
    n_simulations: int = 1000,
    seed: int = 42,
) -> PowerResult:
    """Simulate power using cluster-robust Wald test comparing baseline vs post-drift.

    Uses a beta-binomial generative model to produce realistic scenario clustering
    with intra-cluster correlation (ICC).
    """
    rng = np.random.default_rng(seed)

    # Beta parameters for cluster random effects with target mean and ICC
    # ICC = 1 / (alpha + beta + 1) => M = alpha + beta = (1 - ICC) / ICC
    m = (1.0 - icc) / icc if icc > 0 else 100.0

    p_base = baseline_asr
    p_drift = baseline_asr + effect_size

    a_base, b_base = p_base * m, (1.0 - p_base) * m
    a_drift, b_drift = p_drift * m, (1.0 - p_drift) * m

    rejections = 0

    for _ in range(n_simulations):
        # Draw scenario-level probabilities
        probs_base = rng.beta(a_base, b_base, size=n_scenarios)
        probs_drift = rng.beta(a_drift, b_drift, size=n_scenarios)

        # Draw trials per scenario (cluster totals)
        succ_base = rng.binomial(trials_per_scenario, probs_base)
        succ_drift = rng.binomial(trials_per_scenario, probs_drift)

        # Cluster means
        p_hat_base = succ_base / trials_per_scenario
        p_hat_drift = succ_drift / trials_per_scenario

        # Point estimates of overall mean
        mean_base = float(np.mean(p_hat_base))
        mean_drift = float(np.mean(p_hat_drift))
        diff = mean_drift - mean_base

        # Cluster-level variance (variance between cluster means / K)
        var_base = float(np.var(p_hat_base, ddof=1) / n_scenarios)
        var_drift = float(np.var(p_hat_drift, ddof=1) / n_scenarios)
        se_diff = float(np.sqrt(var_base + var_drift))

        if se_diff > 0:
            z = diff / se_diff
            p_val = float(2.0 * (1.0 - stats.norm.cdf(abs(z))))
            if p_val < alpha:
                rejections += 1

    power = rejections / n_simulations
    total_n = trials_per_scenario * n_scenarios

    return PowerResult(
        trials_per_scenario=trials_per_scenario,
        n_scenarios=n_scenarios,
        total_n=total_n,
        power=power,
        baseline_asr=baseline_asr,
        effect_size=effect_size,
        alpha=alpha,
    )


def run_power_analysis(
    n_scenarios: int = 16,
    baseline_asr: float = 0.15,
    effect_size: float = 0.05,
    icc: float = 0.10,
    alpha: float = 0.05,
    n_simulations: int = 1000,
    seed: int = 42,
) -> list[PowerResult]:
    """Run simulations for 3, 5, and 10 trials per scenario."""
    results = []
    for m_trials in [3, 5, 10]:
        res = simulate_clustered_power(
            trials_per_scenario=m_trials,
            n_scenarios=n_scenarios,
            baseline_asr=baseline_asr,
            effect_size=effect_size,
            icc=icc,
            alpha=alpha,
            n_simulations=n_simulations,
            seed=seed,
        )
        results.append(res)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monte Carlo clustered power simulation for DriftWatch-TE."
    )
    parser.add_argument("--n-simulations", type=int, default=1000, help="Simulation runs.")
    parser.add_argument("--n-scenarios", type=int, default=16, help="Scenario clusters.")
    parser.add_argument("--baseline-asr", type=float, default=0.15, help="Baseline ASR.")
    parser.add_argument("--effect-size", type=float, default=0.05, help="Target ASR change.")
    parser.add_argument("--icc", type=float, default=0.10, help="Intra-cluster correlation.")
    parser.add_argument("--alpha", type=float, default=0.05, help="Significance level.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    args = parser.parse_args()

    print("=== DriftWatch-TE Clustered Power Simulation ===")
    print(f"Scenarios: {args.n_scenarios} | Baseline ASR: {args.baseline_asr:.2f}")
    print(f"Effect Size: {args.effect_size:+.2f} | Alpha: {args.alpha} | ICC: {args.icc}")
    print(f"Simulations per condition: {args.n_simulations}")
    print("-" * 65)
    print(f"{'Trials/Scenario':<18}{'Total N':<12}{'Power':<12}{'Target Change':<15}")
    print("-" * 65)

    results = run_power_analysis(
        n_scenarios=args.n_scenarios,
        baseline_asr=args.baseline_asr,
        effect_size=args.effect_size,
        icc=args.icc,
        alpha=args.alpha,
        n_simulations=args.n_simulations,
        seed=args.seed,
    )

    for r in results:
        print(f"{r.trials_per_scenario:<18}{r.total_n:<12}{r.power:<12.3f}{r.effect_size:+.2f}")

    print("-" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
