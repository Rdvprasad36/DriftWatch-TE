"""Synthetic data generation for testing analysis methods.

Satisfies AGENTS.md testing requirement:
  "Analysis: test GEE, bootstrap, TOST and change-point functions
   on synthetic data with known drift (planted step change at known week,
   planted null)."
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_synthetic_trials(
    *,
    n_weeks: int = 12,
    n_scenarios: int = 20,
    n_trials: int = 5,
    base_asr: float = 0.12,
    drift_rate: float = 0.0,
    step_week: int | None = None,
    step_delta: float = 0.0,
    languages: tuple[str, ...] = ("en", "te", "te-en"),
    channels: tuple[str, ...] = ("tool_output", "tool_description"),
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a synthetic longitudinal dataset of trial outcomes.

    Args:
        n_weeks: Number of weekly time points.
        n_scenarios: Number of distinct scenarios (clusters).
        n_trials: Number of trials per scenario per week.
        base_asr: Baseline attack success probability at week 0.
        drift_rate: Linear change in probability per week.
        step_week: Week index where a sudden step change occurs (or None).
        step_delta: Change in attack probability applied at and after step_week.
        languages: Languages cycled across scenarios.
        channels: Channels cycled across scenarios.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with columns: week_idx, scenario_id, language, channel,
        attack_success, task_success.
    """
    rng = np.random.default_rng(seed)

    rows: list[dict[str, object]] = []

    # Assign each scenario a fixed language and channel
    scenario_metadata = {}
    for s_idx in range(n_scenarios):
        scenario_id = f"scenario_{s_idx:03d}"
        lang = languages[s_idx % len(languages)]
        chan = channels[s_idx % len(channels)]
        # Add random scenario-level difficulty offset
        scenario_offset = rng.normal(0.0, 0.02)
        scenario_metadata[scenario_id] = (lang, chan, scenario_offset)

    for week in range(n_weeks):
        prob = base_asr + drift_rate * week
        if step_week is not None and week >= step_week:
            prob += step_delta

        for s_idx in range(n_scenarios):
            scenario_id = f"scenario_{s_idx:03d}"
            lang, chan, s_offset = scenario_metadata[scenario_id]
            scenario_p = np.clip(prob + s_offset, 0.0, 1.0)

            # Draw binomial outcomes for trials
            attack_outcomes = rng.binomial(1, scenario_p, size=n_trials)

            for trial in range(n_trials):
                atk_success = bool(attack_outcomes[trial])
                # Benign task success is roughly inversely correlated with attack success
                task_success = bool(rng.binomial(1, 0.85 if not atk_success else 0.15))
                # Model was exposed if attack succeeded, or with high
                # probability during tool execution
                is_exposed = bool(atk_success or rng.binomial(1, 0.85))

                rows.append(
                    {
                        "week_idx": week,
                        "base_id": f"base_{s_idx % 20:02d}",
                        "scenario_id": scenario_id,
                        "language": lang,
                        "channel": chan,
                        "trial": trial,
                        "attack_success": int(atk_success),
                        "task_success": int(task_success),
                        "exposed": int(is_exposed),
                    }
                )

    return pd.DataFrame(rows)
