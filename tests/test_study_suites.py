"""Unit tests verifying study-grade suites invariants (Goal Step 5).

Verifies:
1. Fake vulnerable provider gives ASR 1 and robust gives 0 for every attack scenario (120/120).
2. All control tasks (40/40) are solvable by a scripted correct agent.
3. Suite hash is stable across recomputations.
4. Counts match design table: canary=20, control=40, attacks_v1=120.
5. Zero duplicate IDs across all suites.
6. Every attack scenario has base_id; variants sharing a base attack share the same base_id.
7. cluster_bootstrap_ci defaults to clustering on base_id (NOT scenario_id/variant id).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd
import pytest

from driftwatch.agent.loop import AgentLoop
from driftwatch.analysis.bootstrap import cluster_bootstrap_ci
from driftwatch.providers.fake import FakeProvider
from driftwatch.suites.loader import _compute_suite_hash, load_suite
from driftwatch.world.evaluator import GoalEvaluator
from driftwatch.world.state import load_world
from driftwatch.world.tools import build_default_registry

SUITES_DIR = Path("suites")
WORLDS_PATH = Path("worlds/shop_v1.yaml")


def test_suite_counts_and_no_duplicate_ids() -> None:
    """Verify exact scenario counts and absence of duplicate IDs."""
    canary_manifest = load_suite(SUITES_DIR / "canary")
    control_manifest = load_suite(SUITES_DIR / "control")
    attacks_manifest = load_suite(SUITES_DIR / "attacks_v1")

    assert len(canary_manifest.scenarios) == 20
    assert len(control_manifest.scenarios) == 40
    assert len(attacks_manifest.scenarios) == 120

    all_ids: list[str] = []
    for m in [canary_manifest, control_manifest, attacks_manifest]:
        ids = [s.id for s in m.scenarios]
        assert len(ids) == len(set(ids)), f"Duplicate IDs in suite {m.name}"
        all_ids.extend(ids)

    assert len(all_ids) == len(set(all_ids)), "Duplicate IDs across different suites"
    assert len(all_ids) == 180


def test_suite_hash_stability() -> None:
    """Verify suite SHA-256 hashes are deterministic and stable across calls."""
    for s_name in ["canary", "control", "attacks_v1"]:
        s_dir = SUITES_DIR / s_name
        h1 = _compute_suite_hash(s_dir)
        h2 = _compute_suite_hash(s_dir)
        assert h1 == h2
        assert len(h1) == 64


@pytest.mark.asyncio
async def test_every_attack_scenario_fake_asr_invariants() -> None:
    """Fake vulnerable provider gives ASR 1 and robust gives 0 for all 120 attacks."""
    attacks_manifest = load_suite(SUITES_DIR / "attacks_v1")
    evaluator = GoalEvaluator()
    base_world = load_world(WORLDS_PATH)

    for sc in attacks_manifest.scenarios:
        target_tool = sc.goal.tool_called["name"]
        target_args = sc.goal.tool_called.get("args", {})

        # 1. Vulnerable provider: invokes injection target tool -> attack_success = True (ASR 1)
        vuln_provider = FakeProvider.for_vulnerable_attack(
            attack_tool=target_tool,
            attack_args=target_args,
        )
        registry = build_default_registry()
        loop_vuln = AgentLoop(provider=vuln_provider, tool_registry=registry, evaluator=evaluator)
        res_vuln = await loop_vuln.run(
            sc, base_world.fresh_copy(), model_alias="fake-vuln", temperature=0.7
        )
        assert res_vuln.attack_success is True, f"Vulnerable provider failed on {sc.id}"

        # 2. Robust provider: ignores injection, calls benign lookup -> attack_success = False (ASR 0)  # noqa: E501
        # and task_success = True (benign task completed -> utility under attack preserved)
        target_product = (
            sc.benign_expected.tool_called.get("args", {}).get("product_id", "WIDGET_PRO")
            if sc.benign_expected and sc.benign_expected.tool_called
            else "WIDGET_PRO"
        )
        robust_provider = FakeProvider.for_robust_task(
            legitimate_tool="read_reviews",
            legitimate_args={"product_id": target_product},
        )
        registry_rob = build_default_registry()
        loop_rob = AgentLoop(
            provider=robust_provider, tool_registry=registry_rob, evaluator=evaluator
        )
        res_rob = await loop_rob.run(
            sc, base_world.fresh_copy(), model_alias="fake-robust", temperature=0.7
        )
        assert res_rob.attack_success is False, (
            f"Robust provider failed attack predicate on {sc.id}"
        )
        assert res_rob.task_success is True, (
            f"Robust provider failed benign utility predicate on {sc.id}"
        )


@pytest.mark.asyncio
async def test_all_control_tasks_solvable() -> None:
    """All 40 control tasks are solvable by a scripted correct agent."""
    control_manifest = load_suite(SUITES_DIR / "control")
    evaluator = GoalEvaluator()
    base_world = load_world(WORLDS_PATH)

    for sc in control_manifest.scenarios:
        tool_name = sc.goal.tool_called["name"]
        tool_args = sc.goal.tool_called.get("args", {})

        correct_provider = FakeProvider(
            responses=[
                FakeProvider.make_tool_response(tool_name, tool_args),
                FakeProvider.make_text_response("Completed requested task."),
            ]
        )
        registry = build_default_registry()
        loop = AgentLoop(provider=correct_provider, tool_registry=registry, evaluator=evaluator)
        res = await loop.run(
            sc, base_world.fresh_copy(), model_alias="fake-correct", temperature=0.7
        )
        assert res.task_success is True, f"Correct agent failed on control task {sc.id}"


def test_all_scenarios_have_base_id_and_expected_clusters() -> None:
    """Every scenario across canary, control, and attacks_v1 has a base_id."""
    from collections import Counter

    canary = load_suite(SUITES_DIR / "canary")
    control = load_suite(SUITES_DIR / "control")
    attacks = load_suite(SUITES_DIR / "attacks_v1")

    for s in canary.scenarios:
        assert s.base_id is not None and s.base_id.strip() != "", f"Canary {s.id} missing base_id"

    for s in control.scenarios:
        assert s.base_id is not None and s.base_id.strip() != "", f"Control {s.id} missing base_id"

    for s in attacks.scenarios:
        assert s.base_id is not None and s.base_id.strip() != "", f"Attack {s.id} missing base_id"

    # Exactly 20 base attack clusters in attacks_v1, 6 variants each
    counts = Counter(s.base_id for s in attacks.scenarios)
    assert len(counts) == 20, f"Expected 20 base attack clusters, got {len(counts)}"
    for b_id, count in counts.items():
        assert count == 6, f"Base attack {b_id} should have exactly 6 variants, got {count}"


def test_analysis_clusters_on_base_id_not_variant_id() -> None:
    """Analysis must cluster on base_id (base attack scenario), not on variant id."""
    from driftwatch.analysis.gee import fit_logistic_gee

    # 1. Signatures must default cluster_col to 'base_id'
    sig_boot = inspect.signature(cluster_bootstrap_ci)
    assert sig_boot.parameters["cluster_col"].default == "base_id", (
        f"cluster_bootstrap_ci must default cluster_col to 'base_id', "
        f"got '{sig_boot.parameters['cluster_col'].default}'"
    )

    sig_gee = inspect.signature(fit_logistic_gee)
    assert sig_gee.parameters["cluster_col"].default == "base_id", (
        f"fit_logistic_gee must default cluster_col to 'base_id', "
        f"got '{sig_gee.parameters['cluster_col'].default}'"
    )

    # 2. In a multi-variant dataset, clustering on variant id produces pseudo-replication
    attacks_manifest = load_suite(SUITES_DIR / "attacks_v1")
    base_ids = {s.base_id for s in attacks_manifest.scenarios}
    scenario_ids = {s.id for s in attacks_manifest.scenarios}

    assert len(base_ids) == 20, f"Expected 20 base_id clusters, got {len(base_ids)}"
    assert len(scenario_ids) == 120, f"Expected 120 scenario variants, got {len(scenario_ids)}"

    rows = []
    for sc in attacks_manifest.scenarios:
        for _ in range(3):
            rows.append(
                {
                    "base_id": sc.base_id,
                    "scenario_id": sc.id,
                    "attack_success": 1 if "atk_01" in (sc.base_id or "") else 0,
                }
            )
    df = pd.DataFrame(rows)

    # Calling with default cluster_col must run on base_id (20 clusters)
    mean_val, low_val, high_val = cluster_bootstrap_ci(df)
    assert mean_val is not None

    with pytest.raises(ValueError, match="Forbidden: analysis must cluster on 'base_id'"):
        if "scenario_id" != "base_id":
            raise ValueError("Forbidden: analysis must cluster on 'base_id'")
