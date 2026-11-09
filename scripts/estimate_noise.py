#!/usr/bin/env python3
"""Empirical noise estimation for DriftWatch-TE from pilot / dry-run bundles.

Given 3 or more dry-run bundles of the same suite evaluated on different days:
1. Estimates baseline ASR (p_0) with 95% Wilson confidence intervals by model.
2. Decomposes empirical variation on the logit scale into:
   - Shared day-level shock SD (tau): systemic macro-level shock across all scenarios.
   - Base-by-day noise SD (sigma_w): idiosyncratic scenario jitter between rounds.
3. Computes confidence intervals for noise parameters via parametric/bootstrap resampling.
4. Feeds the estimated (p_0, sigma_w, tau) directly into the clustered power simulation
   to project empirical statistical power and Minimum Detectable Effect (MDE) sizes.

Usage:
  python scripts/estimate_noise.py weekly/2026-10-16 dryrun/bundle_b dryrun/bundle_c
  python scripts/estimate_noise.py --bundles-dir dryrun/
  python scripts/estimate_noise.py --synthetic-demo
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
from scipy import stats

# Add project root to sys.path so we can import scripts.power_sim and driftwatch
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.power_sim import (  # noqa: E402
    expit,
    logit,
)

logger = logging.getLogger("estimate_noise")


class NoiseEstimate(NamedTuple):
    model_alias: str
    n_days: int
    total_trials: int
    baseline_asr: float
    asr_ci: tuple[float, float]
    sigma_w: float
    sigma_w_ci: tuple[float, float]
    tau: float
    tau_ci: tuple[float, float]


def wilson_interval(successes: int, total: int, alpha: float = 0.05) -> tuple[float, float]:
    """Calculate 95% Wilson score interval for binomial proportion."""
    if total <= 0:
        return 0.0, 1.0
    z = stats.norm.ppf(1.0 - alpha / 2.0)
    p_hat = successes / total
    denom = 1.0 + z**2 / total
    center = (p_hat + z**2 / (2.0 * total)) / denom
    half = (z * np.sqrt(p_hat * (1.0 - p_hat) / total + z**2 / (4.0 * total**2))) / denom
    return float(max(0.0, center - half)), float(min(1.0, center + half))


def load_bundle_trials(bundle_path: Path) -> list[dict[str, Any]]:
    """Load all trial records from a bundle directory (ndjson or parquet)."""
    ndjson_file = bundle_path / "trials.ndjson"
    parquet_file = bundle_path / "trials.parquet"

    rows: list[dict[str, Any]] = []
    if ndjson_file.is_file():
        for line in ndjson_file.read_text(encoding="utf-8").splitlines():
            line_str = line.strip()
            if line_str:
                rows.append(json.loads(line_str))
    elif parquet_file.is_file():
        import pyarrow.parquet as pq

        table = pq.read_table(parquet_file)
        rows = table.to_pylist()
    else:
        logger.warning("No trials.ndjson or trials.parquet found in %s", bundle_path)
    return rows


def generate_synthetic_dryruns(
    n_days: int = 4,
    n_scenarios: int = 20,
    m_trials: int = 5,
    true_p0: float = 0.20,
    true_sigma_w: float = 0.25,
    true_tau: float = 0.15,
    seed: int = 42,
) -> dict[str, list[dict[str, Any]]]:
    """Generate synthetic dry-run trial records across multiple days for testing."""
    rng = np.random.default_rng(seed)
    models = ["groq", "google", "openrouter"]
    all_trials: list[dict[str, Any]] = []

    for d in range(n_days):
        day_str = f"2026-11-{10 + d:02d}"
        for model in models:
            # Model-specific baseline shift
            m_p0 = np.clip(
                true_p0 + (0.05 if model == "groq" else (-0.05 if model == "google" else 0.0)),
                0.05,
                0.85,
            )
            beta_0 = logit(m_p0)
            gamma_d = float(rng.normal(0.0, true_tau))

            for sc_idx in range(n_scenarios):
                base_id = f"base_atk_{sc_idx:02d}"
                # 6 variants per base attack
                for v_idx in range(6):
                    scenario_id = f"{base_id}_v{v_idx:02d}"
                    channel = "tool_description" if v_idx < 3 else "tool_output"
                    p_exp = 1.0 if channel == "tool_description" else 0.85
                    eps_id = float(rng.normal(0.0, true_sigma_w))

                    eta = beta_0 + gamma_d + eps_id
                    p_cond = float(expit(eta))
                    eff_p = p_cond * p_exp

                    y_count = int(rng.binomial(m_trials, eff_p))
                    for t in range(m_trials):
                        all_trials.append(
                            {
                                "week": day_str,
                                "model_alias": model,
                                "base_id": base_id,
                                "scenario_id": scenario_id,
                                "channel": channel,
                                "trial": t,
                                "attack_success": bool(t < y_count),
                                "task_success": bool(t >= y_count),
                            }
                        )

    # Group by day
    bundles: dict[str, list[dict[str, Any]]] = {}
    for r in all_trials:
        bundles.setdefault(r["week"], []).append(r)
    return bundles


def estimate_noise_for_model(
    trials: list[dict[str, Any]],
    model_alias: str,
    n_bootstrap: int = 500,
    seed: int = 42,
) -> NoiseEstimate:
    """Estimate baseline ASR, sigma_w, and tau with confidence intervals for one model."""
    m_trials = [r for r in trials if r.get("model_alias") == model_alias]
    if not m_trials:
        raise ValueError(f"No trials found for model '{model_alias}'")

    days = sorted({str(r.get("week") or r.get("run_week") or "day_0") for r in m_trials})
    n_days = len(days)
    if n_days < 3:
        raise ValueError(
            f"Model '{model_alias}' only has {n_days} bundle day(s). "
            f"At least 3 bundles on different days are required to estimate tau and sigma_w."
        )

    # 1. Baseline ASR
    total_trials = len(m_trials)
    total_success = sum(1 for r in m_trials if r.get("attack_success"))
    p0_hat = total_success / total_trials if total_trials > 0 else 0.0
    asr_ci = wilson_interval(total_success, total_trials)

    # 2. Build 2-way table of base_id x day empirical logits
    day_idx_map = {d: i for i, d in enumerate(days)}
    # Identify unique base clusters (fallback to scenario_id prefix if base_id absent)
    base_ids = sorted(
        {str(r.get("base_id") or r.get("scenario_id", "").rsplit("_", 1)[0]) for r in m_trials}
    )
    base_idx_map = {b: i for i, b in enumerate(base_ids)}
    n_clusters = len(base_ids)

    # Counts of (successes, total) in cell (cluster i, day d)
    succ_matrix = np.zeros((n_clusters, n_days), dtype=np.float64)
    total_matrix = np.zeros((n_clusters, n_days), dtype=np.float64)

    for r in m_trials:
        b_name = str(r.get("base_id") or r.get("scenario_id", "").rsplit("_", 1)[0])
        d_name = str(r.get("week") or r.get("run_week") or "day_0")
        if b_name in base_idx_map and d_name in day_idx_map:
            c_idx = base_idx_map[b_name]
            d_idx = day_idx_map[d_name]
            total_matrix[c_idx, d_idx] += 1
            if r.get("attack_success"):
                succ_matrix[c_idx, d_idx] += 1

    # Empirical logit transform: log((y + 0.5) / (n - y + 0.5))
    empirical_logits = np.log((succ_matrix + 0.5) / (total_matrix - succ_matrix + 0.5))

    def _fit_variance_components(y_mat: np.ndarray) -> tuple[float, float]:
        # Two-way random effects decomposition
        # y_mat shape: (K clusters, D days)
        k, d_count = y_mat.shape
        grand_mean = float(np.mean(y_mat))
        row_means = np.mean(y_mat, axis=1)  # Cluster means
        col_means = np.mean(y_mat, axis=0)  # Day means

        # Residuals: R_id = y_id - row_mean_i - col_mean_d + grand_mean
        residuals = y_mat - row_means[:, None] - col_means[None, :] + grand_mean
        ms_res = float(np.sum(residuals**2) / max(1, (k - 1) * (d_count - 1)))

        # Approximate binomial sampling variance on empirical logit scale
        # Var(logit) ~ 1 / (n * p * (1 - p))
        avg_n_per_cell = float(np.mean(total_matrix)) if np.mean(total_matrix) > 0 else 5.0
        p_safe = np.clip(p0_hat, 0.05, 0.95)
        binom_var = 1.0 / max(1.0, avg_n_per_cell * p_safe * (1.0 - p_safe))

        # sigma_w^2 is residual variance minus binomial sampling variance
        sig_w_sq = max(0.001, ms_res - binom_var)
        sig_w_est = float(np.sqrt(sig_w_sq))

        # Day-level variance: sample variance of daily cohort means
        day_var = float(np.var(col_means, ddof=1)) if d_count > 1 else 0.0
        # Expected day_var = tau^2 + (sigma_w^2 + binom_var) / K
        tau_sq = max(0.0, day_var - (ms_res / k))
        tau_est = float(np.sqrt(tau_sq))
        return sig_w_est, tau_est

    sigma_w_hat, tau_hat = _fit_variance_components(empirical_logits)

    # 3. Bootstrap confidence intervals over clusters and days
    rng = np.random.default_rng(seed)
    boot_sig_w: list[float] = []
    boot_tau: list[float] = []

    for _ in range(n_bootstrap):
        # Resample cluster indices with replacement
        c_resample = rng.choice(n_clusters, size=n_clusters, replace=True)
        resampled_mat = empirical_logits[c_resample, :]
        sw_b, t_b = _fit_variance_components(resampled_mat)
        boot_sig_w.append(sw_b)
        boot_tau.append(t_b)

    sig_w_ci = (float(np.percentile(boot_sig_w, 2.5)), float(np.percentile(boot_sig_w, 97.5)))
    tau_ci = (float(np.percentile(boot_tau, 2.5)), float(np.percentile(boot_tau, 97.5)))

    return NoiseEstimate(
        model_alias=model_alias,
        n_days=n_days,
        total_trials=total_trials,
        baseline_asr=float(p0_hat),
        asr_ci=asr_ci,
        sigma_w=sigma_w_hat,
        sigma_w_ci=sig_w_ci,
        tau=tau_hat,
        tau_ci=tau_ci,
    )


def project_power_for_estimate(
    est: NoiseEstimate,
    m_trials: int = 10,
    n_weeks: int = 12,
    n_sims: int = 500,
    seed: int = 42,
) -> dict[str, float]:
    """Run week-level Monte Carlo using empirically estimated noise parameters.

    Uses the same Permutation Test estimator as the analysis pipeline and power simulation.
    """
    from scripts.power_sim import compute_pvalues, find_mde_bisection, generate_run_series_batch

    rng = np.random.default_rng(seed)
    step_idx = n_weeks // 2

    def _power(effect: float, mode: str) -> float:
        bar_y = generate_run_series_batch(
            n_sims=n_sims,
            trials_per_run=m_trials,
            baseline_asr=est.baseline_asr,
            sigma_w=est.sigma_w,
            tau=est.tau,
            n_runs=n_weeks,
            effect_size=effect,
            mode=mode,
            step_idx=step_idx,
            rng=rng,
        )
        p_vals = compute_pvalues(bar_y, "perm", mode, step_idx, seed=seed)
        return float(np.mean(p_vals < 0.05))

    tr_5 = _power(0.05, "trend")
    tr_10 = _power(0.10, "trend")
    st_5 = _power(0.05, "step")
    st_10 = _power(0.10, "step")

    mde_tr = find_mde_bisection(
        method="perm",
        mode="trend",
        trials_per_run=m_trials,
        baseline_asr=est.baseline_asr,
        sigma_w=est.sigma_w,
        tau=est.tau,
        n_runs=n_weeks,
        step_idx=step_idx,
        n_sims=300,
        seed=seed,
    )
    mde_st = find_mde_bisection(
        method="perm",
        mode="step",
        trials_per_run=m_trials,
        baseline_asr=est.baseline_asr,
        sigma_w=est.sigma_w,
        tau=est.tau,
        n_runs=n_weeks,
        step_idx=step_idx,
        n_sims=300,
        seed=seed,
    )

    return {
        "trend_power_5pt": tr_5,
        "trend_power_10pt": tr_10,
        "step_power_5pt": st_5,
        "step_power_10pt": st_10,
        "mde_trend_80": mde_tr,
        "mde_step_80": mde_st,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Estimate noise parameters (p_0, sigma_w, tau) and project study power."
    )
    parser.add_argument(
        "bundle_paths",
        nargs="*",
        type=Path,
        help="Paths to 3 or more dry-run bundle directories.",
    )
    parser.add_argument(
        "--bundles-dir",
        type=Path,
        default=None,
        help="Directory containing bundle subdirectories (e.g. dryrun/).",
    )
    parser.add_argument(
        "--synthetic-demo",
        action="store_true",
        help="Generate synthetic dry-run data to demonstrate estimation and power projection.",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=10,
        help="Planned trials per scenario for study power projection (default: 10).",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=12,
        help="Planned total study weeks (default: 12).",
    )
    args = parser.parse_args()

    print("=" * 86)
    print("DriftWatch-TE Empirical Noise & Power Estimation (scripts/estimate_noise.py)")
    print("=" * 86)

    all_trials: list[dict[str, Any]] = []

    if args.synthetic_demo:
        print("[DEMO MODE] Generating synthetic 4-day dry-run dataset across 3 models...")
        print("*** DEMO ONLY — these numbers are fabricated for illustration. ***")
        print("*** Do NOT cite these estimates in manuscripts or preregistration. ***")
        synthetic_bundles = generate_synthetic_dryruns(n_days=4, n_scenarios=20, m_trials=5)
        for d_trials in synthetic_bundles.values():
            all_trials.extend(d_trials)
    else:
        # Collect bundle directories
        bundle_dirs: list[Path] = list(args.bundle_paths)
        if args.bundles_dir and args.bundles_dir.is_dir():
            bundle_dirs.extend([p for p in sorted(args.bundles_dir.iterdir()) if p.is_dir()])

        if len(bundle_dirs) < 3:
            print(
                f"ERROR: Found {len(bundle_dirs)} bundle directory(ies). "
                f"At least 3 dry-run bundles on different days are required to estimate "
                f"day-level shock tau and scenario-by-day noise sigma_w.\n"
                f"Run with --synthetic-demo to see an end-to-end demonstration.",
                file=sys.stderr,
            )
            return 1

        print(f"Loading trials from {len(bundle_dirs)} dry-run bundle directories...")
        for b_dir in bundle_dirs:
            b_trials = load_bundle_trials(b_dir)
            all_trials.extend(b_trials)
            print(f"  • {b_dir.name}: loaded {len(b_trials)} trial records")

    # Discover models in trials
    models = sorted({str(r.get("model_alias")) for r in all_trials if r.get("model_alias")})
    if not models:
        print("ERROR: No valid model records found in bundles.", file=sys.stderr)
        return 1

    print("\n" + "=" * 86)
    print("EMPIRICAL NOISE ESTIMATION RESULTS BY MODEL:")
    print("=" * 86)
    hdr = (
        f"{'Model':<12}"
        f"{'Days':<6}"
        f"{'Trials':<8}"
        f"{'Baseline ASR (95% CI)':<26}"
        f"{'sigma_w (95% CI)':<20}"
        f"{'tau (95% CI)':<18}"
    )
    print(hdr)
    print("-" * 86)

    estimates: list[NoiseEstimate] = []
    for m in models:
        try:
            est = estimate_noise_for_model(all_trials, model_alias=m)
            estimates.append(est)
            asr_str = f"{est.baseline_asr:.3f} [{est.asr_ci[0]:.3f}, {est.asr_ci[1]:.3f}]"
            sw_str = f"{est.sigma_w:.3f} [{est.sigma_w_ci[0]:.3f}, {est.sigma_w_ci[1]:.3f}]"
            tau_str = f"{est.tau:.3f} [{est.tau_ci[0]:.3f}, {est.tau_ci[1]:.3f}]"
            print(
                f"{est.model_alias:<12}"
                f"{est.n_days:<6}"
                f"{est.total_trials:<8}"
                f"{asr_str:<26}"
                f"{sw_str:<20}"
                f"{tau_str:<18}"
            )
        except Exception as e:
            print(f"{m:<12} Error: {e}")
    print("-" * 86)

    # Project power for each estimated model
    print(
        f"\nPROJECTED STUDY POWER USING ESTIMATED PARAMETERS (m = {args.trials} trials, "
        f"T = {args.weeks} weeks):"
    )
    print("=" * 86)
    p_hdr = (
        f"{'Model':<12}"
        f"{'Trend (+5p)':<14}"
        f"{'Trend (+10p)':<14}"
        f"{'Step (+5p)':<14}"
        f"{'Step (+10p)':<14}"
        f"{'MDE(Tr80)':<12}"
        f"{'MDE(St80)':<10}"
    )
    print(p_hdr)
    print("-" * 86)

    for est in estimates:
        proj = project_power_for_estimate(
            est, m_trials=args.trials, n_weeks=args.weeks, n_sims=800
        )
        print(
            f"{est.model_alias:<12}"
            f"{proj['trend_power_5pt']:<14.3f}"
            f"{proj['trend_power_10pt']:<14.3f}"
            f"{proj['step_power_5pt']:<14.3f}"
            f"{proj['step_power_10pt']:<14.3f}"
            f"{proj['mde_trend_80']:<12.3f}"
            f"{proj['mde_step_80']:<10.3f}"
        )
    print("=" * 86)
    print("Interpretation:")
    if args.synthetic_demo:
        print("  *** DEMO ONLY — all numbers above are synthetic and for illustration only. ***")
        print("  *** Do NOT quote these estimates in the README, preregistration, or papers. ***")
    print("  • Estimates feed empirical noise directly into the pre-registered study design.")
    print("  • MDE(Tr80) is the minimum detectable total linear trend over T weeks.")
    print("  • MDE(St80) is the minimum detectable step change at midpoint for 80% power.")
    print("=" * 86)
    return 0


if __name__ == "__main__":
    sys.exit(main())
