"""Suite reporting utility for DriftWatch-TE.

Analyzes scenario files across suites and tallies scenarios by:
- language (en, te, te-Latn)
- channel (tool_output, tool_description)
- attack class
- origin (machine, human, etc.)
- tool used
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from driftwatch.suites.loader import _load_scenario_file


def generate_suite_report(suites_dir: Path) -> dict[str, Any]:
    """Generate structured audit report for all suites in suites_dir.

    Args:
        suites_dir: Path to root suites directory containing suite subdirs.

    Returns:
        Dict mapping suite_name to detailed count statistics.
    """
    report: dict[str, Any] = {}

    if not suites_dir.is_dir():
        return report

    # Iterate over subdirectories (canary, control, attacks_v1, etc.)
    suite_dirs = sorted(
        [p for p in suites_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    )

    for s_dir in suite_dirs:
        suite_name = s_dir.name
        yaml_files = sorted(
            [f for f in s_dir.glob("*.yaml") if f.is_file()]
            + [f for f in s_dir.glob("*.yml") if f.is_file()],
            key=lambda p: p.name,
        )

        scenarios = []
        for yf in yaml_files:
            try:
                scenarios.extend(_load_scenario_file(yf))
            except Exception:
                continue

        lang_counts: Counter[str] = Counter()
        channel_counts: Counter[str] = Counter()
        attack_class_counts: Counter[str] = Counter()
        origin_counts: Counter[str] = Counter()
        tools_used: Counter[str] = Counter()

        for sc in scenarios:
            # Language normalization (map te-en to te-Latn)
            lang = str(sc.language)
            if lang == "te-en":
                lang = "te-Latn"
            lang_counts[lang] += 1

            # Channel
            chan = str(sc.channel)
            channel_counts[chan] += 1

            # Attack Class
            atk_cls = sc.attack_class or "unspecified"
            attack_class_counts[atk_cls] += 1

            # Origin
            origin = sc.origin or "unspecified"
            origin_counts[origin] += 1

            # Tool used (either injection tool or goal tool)
            tools_in_scenario: set[str] = set()
            if sc.injection and sc.injection.tool:
                tools_in_scenario.add(sc.injection.tool)
            if sc.goal and sc.goal.tool_called and "name" in sc.goal.tool_called:
                tools_in_scenario.add(sc.goal.tool_called["name"])
            if not tools_in_scenario:
                tools_in_scenario.add("none")
            for t in tools_in_scenario:
                tools_used[t] += 1

        report[suite_name] = {
            "total_scenarios": len(scenarios),
            "languages": dict(lang_counts),
            "channels": dict(channel_counts),
            "attack_classes": dict(attack_class_counts),
            "origins": dict(origin_counts),
            "tools_used": dict(tools_used),
        }

    return report


def format_suite_report(report: dict[str, Any]) -> str:
    """Format suite report into human-readable text."""
    lines: list[str] = ["=== DriftWatch-TE Suite Audit Report ===", ""]
    for suite_name, data in report.items():
        lines.append(f"Suite: {suite_name}")
        lines.append(f"  Total Scenarios: {data['total_scenarios']}")

        # Languages
        langs = data.get("languages", {})
        lines.append("  Languages:")
        for lang in ("en", "te", "te-Latn"):
            lines.append(f"    - {lang}: {langs.get(lang, 0)}")

        # Channels
        channels = data.get("channels", {})
        lines.append("  Channels:")
        for ch in ("tool_output", "tool_description"):
            lines.append(f"    - {ch}: {channels.get(ch, 0)}")

        # Attack Classes
        atks = data.get("attack_classes", {})
        lines.append("  Attack Classes:")
        for ac, count in sorted(atks.items()):
            lines.append(f"    - {ac}: {count}")

        # Origins
        origins = data.get("origins", {})
        lines.append("  Origins:")
        for orig, count in sorted(origins.items()):
            lines.append(f"    - {orig}: {count}")

        # Tools Used
        tools = data.get("tools_used", {})
        lines.append("  Tools Used:")
        for tool, count in sorted(tools.items()):
            lines.append(f"    - {tool}: {count}")

        lines.append("")

    return "\n".join(lines)
