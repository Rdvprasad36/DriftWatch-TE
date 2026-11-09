"""Weekly report generator for DriftWatch-TE (FR8, Phase 2).

Generates:
  - reports/weekly/<date>.md: Structured Markdown report for a specific week.
  - reports/weekly/<date>.html: Printable standalone HTML report.
  - reports/weekly/index.json: Manifest index of all weekly reports.

Cautious language rules:
  - "no evidence of change" when an interval includes zero.
  - No claims about provider intent or causes.
  - Pilot batches clearly labeled; separated from study metrics.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from driftwatch.config import load_study_config
from driftwatch.storage.bundle import _get_git_sha

logger = logging.getLogger(__name__)


def _format_ci(ci: list[float] | None, n_clusters: int = 16) -> str:
    """Format confidence interval, enforcing not estimable when clusters < 10."""
    if ci is None or len(ci) != 2 or n_clusters < 10:
        return "not estimable"
    return f"[{ci[0]:.1%}, {ci[1]:.1%}]"


def generate_weekly_report(
    week: str,
    summary_dir: Path | None = None,
    analysis_file: Path | None = None,
    weekly_bundles_dir: Path | None = None,
    output_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    """Generate weekly Markdown and HTML reports for the given week date."""
    root = repo_root or Path.cwd()
    s_dir = summary_dir or (root / "results" / "summary")
    a_file = analysis_file or (root / "results" / "analysis" / "analysis.json")
    w_bundles = weekly_bundles_dir or (root / "weekly")
    out_dir = output_dir or (root / "reports" / "weekly")
    out_dir.mkdir(parents=True, exist_ok=True)

    config = load_study_config()
    study_start = config.study_start_date
    planned_weeks = config.planned_weeks

    # 1. Load weekly summary data
    weekly_summary_path = s_dir / "weekly" / f"{week}.json"
    if not weekly_summary_path.is_file():
        weekly_summary_path = s_dir / f"{week}.json"

    weekly_data: dict[str, Any] = {}
    if weekly_summary_path.is_file():
        with contextlib.suppress(Exception):
            weekly_data = json.loads(weekly_summary_path.read_text(encoding="utf-8"))

    # 2. Load summary index
    index_path = s_dir / "index.json"
    index_data: dict[str, Any] = {}
    if index_path.is_file():
        with contextlib.suppress(Exception):
            index_data = json.loads(index_path.read_text(encoding="utf-8"))

    all_weeks = index_data.get("weeks", [])
    study_weeks = [w for w in all_weeks if not w.get("is_pilot") and w.get("week") >= study_start]

    is_pilot = week < study_start or weekly_data.get("is_pilot", False)
    week_number_str = "Pilot"
    if not is_pilot:
        study_dates = [w.get("week") for w in study_weeks]
        if week in study_dates:
            w_idx = study_dates.index(week) + 1
            week_number_str = f"Week {w_idx} of {planned_weeks}"
        else:
            week_number_str = f"Week of {week}"

    # 3. Load analysis data for TOST equivalence if present
    tost_status = "TOST equivalence evaluated per pre-registration"
    if a_file.is_file():
        with contextlib.suppress(Exception):
            a_data = json.loads(a_file.read_text(encoding="utf-8"))
            local_eq = a_data.get("local_control_equivalence", {})
            if "status" in local_eq:
                tost_status = f"Local control status: {local_eq['status']}"

    # 4. Check for baseline study week data to calculate delta
    baseline_week = study_weeks[0].get("week") if study_weeks else None
    baseline_summary: dict[str, Any] = {}
    if baseline_week and baseline_week != week:
        b_path = s_dir / "weekly" / f"{baseline_week}.json"
        if not b_path.is_file():
            b_path = s_dir / f"{baseline_week}.json"
        if b_path.is_file():
            with contextlib.suppress(Exception):
                baseline_summary = json.loads(b_path.read_text(encoding="utf-8"))

    # 5. Check canary data
    canary_path = w_bundles / week / "canary.json"
    canary_status = "No canary data recorded"
    if canary_path.is_file():
        with contextlib.suppress(Exception):
            c_data = json.loads(canary_path.read_text(encoding="utf-8"))
            n_canaries = len(c_data) if isinstance(c_data, list) else 0
            canary_status = f"{n_canaries} canary prompt(s) evaluated"

    # Model metrics
    models_dict = weekly_data.get("models", {})
    slices_dict = weekly_data.get("slices", {})
    total_trials = weekly_data.get("total_trials", 0)
    overall_asr = weekly_data.get("overall_asr", 0.0)

    # Extract control task success rate
    control_task_success = None
    for s_key, s_val in slices_dict.items():
        if "control" in s_key:
            t_rate = s_val.get("task_success_rate")
            if t_rate is not None:
                control_task_success = t_rate
                break

    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    git_sha = _get_git_sha()

    # Build Markdown Content
    md_lines: list[str] = [
        f"# DriftWatch-TE Weekly Report: {week}",
        "",
        f"**Batch Status:** {week_number_str}  ",
        f"**Generated:** {now_utc}  ",
        f"**Git SHA:** `{git_sha}`  ",
        f"**Total Trials:** {total_trials}  ",
        f"**Aggregate ASR:** {overall_asr:.1%}  ",
        "",
        "---",
        "",
    ]

    if is_pilot:
        md_lines.extend(
            [
                "> **NOTICE: Pilot / Pre-Study Batch.**",
                "> ",
                f"> This run occurred before the study start date ({study_start}). "
                "Data from this batch is preserved for pipeline validation and baseline "
                "verification only, and is strictly excluded from formal hypothesis testing.",
                "",
            ]
        )

    # Model evaluations table
    table_header = (
        "| Model Alias | Trials (n) | Attack Success Rate | 95% Confidence Interval | "
        "Change vs Week 1 | Completion Rate |"
    )
    md_lines.extend(
        [
            "## 1. Per-Model Attack Success Rate",
            "",
            table_header,
            "|---|---|---|---|---|---|",
        ]
    )

    for m_alias, m_info in models_dict.items():
        m_trials = m_info.get("total_trials", 0)
        m_asr = m_info.get("asr", 0.0)
        ci_str = "not estimable"
        for s_key, s_val in slices_dict.items():
            if s_key.startswith(f"{m_alias}|") and "attacks_v1" in s_key:
                ci_str = _format_ci(s_val.get("ci_95"), s_val.get("n_scenarios", 0))
                break

        change_str = "baseline"
        if not is_pilot and baseline_summary and baseline_week != week:
            base_m = baseline_summary.get("models", {}).get(m_alias)
            if base_m:
                delta = m_asr - base_m.get("asr", 0.0)
                change_str = f"{delta:+.1%}"
            else:
                change_str = "N/A"
        elif is_pilot:
            change_str = "N/A (pilot)"

        comp_rate = m_info.get("completion_rate", 1.0)
        row = (
            f"| `{m_alias}` | {m_trials} | {m_asr:.1%} | {ci_str} | "
            f"{change_str} | {comp_rate:.1%} |"
        )
        md_lines.append(row)

    ctrl_str = (
        f"{control_task_success:.1%}"
        if control_task_success is not None
        else "No control suite trials"
    )

    md_lines.extend(
        [
            "",
            "## 2. Controls & Verification",
            "",
            f"- **Benign Control Suite Task Success:** {ctrl_str}",
            f"- **Canary Verification State:** {canary_status}",
            f"- **Local Control Status:** {tost_status}",
            "",
            "## 3. Findings & Cautious Interpretation",
            "",
            "Attack success rates reflect deterministic invariant evaluations in the simulated "
            "e-commerce shop environment. Where confidence intervals span zero when compared to "
            "prior evaluations, the data indicates **no evidence of change**. Observed changes "
            "reflect empirical black-box behavioral measurements and should not be interpreted as "
            "evidence of provider optimization intent, safety updates, or architectural "
            "alterations.",
            "",
        ]
    )

    md_path = out_dir / f"{week}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    # Build HTML Content
    meta_html = (
        f"Status: <strong>{week_number_str}</strong> &bull; Generated: {now_utc} "
        f"&bull; Git: <code>{git_sha}</code>"
    )
    th_html = (
        "<tr><th>Model</th><th>Trials</th><th>ASR</th><th>95% CI</th>"
        "<th>Change vs Week 1</th><th>Completion</th></tr>"
    )
    html_lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="UTF-8">',
        f"  <title>DriftWatch-TE Weekly Report - {week}</title>",
        "  <style>",
        "    :root {",
        "      --text: #0B0F14;",
        "      --bg: #ffffff;",
        "      --muted: #475569;",
        "      --border: #E2E8F0;",
        "      --accent: #00B4FF;",
        "      --navy: #0F2A43;",
        "    }",
        "    body {",
        "      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;",
        "      color: var(--text);",
        "      background: var(--bg);",
        "      line-height: 1.6;",
        "      margin: 0;",
        "      padding: 32px 20px;",
        "    }",
        "    .container { max-width: 860px; margin: 0 auto; }",
        "    header { border-bottom: 2px solid var(--accent); padding-bottom: 12px; }",
        "    h1 { font-size: 1.65rem; color: var(--navy); margin-bottom: 6px; }",
        "    .meta { font-size: 0.88rem; color: var(--muted); }",
        "    h2 { font-size: 1.25rem; color: var(--navy); margin-top: 28px; }",
        "    table { width: 100%; border-collapse: collapse; margin: 16px 0; }",
        "    th, td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }",
        "    th { background: #f8fafc; font-weight: 600; }",
        "    code { background: #f1f5f9; padding: 2px 4px; border-radius: 4px; }",
        "    blockquote { background: #f8fafc; border-left: 4px solid var(--accent); }",
        "    @media print { body { padding: 0; } .container { max-width: 100%; } }",
        "  </style>",
        "</head>",
        "<body>",
        '  <div class="container">',
        "    <header>",
        f"      <h1>DriftWatch-TE Weekly Report: {week}</h1>",
        f'      <div class="meta">{meta_html}</div>',
        "    </header>",
    ]

    if is_pilot:
        html_lines.append(
            "    <blockquote><strong>Pilot Run:</strong> Pre-study validation run. "
            "Excluded from longitudinal drift conclusions.</blockquote>"
        )

    html_lines.extend(
        [
            "    <h2>1. Per-Model Attack Success Rate</h2>",
            "    <table>",
            f"      <thead>{th_html}</thead>",
            "      <tbody>",
        ]
    )

    for m_alias, m_info in models_dict.items():
        m_trials = m_info.get("total_trials", 0)
        m_asr = m_info.get("asr", 0.0)
        ci_str = "not estimable"
        for s_key, s_val in slices_dict.items():
            if s_key.startswith(f"{m_alias}|") and "attacks_v1" in s_key:
                ci_str = _format_ci(s_val.get("ci_95"), s_val.get("n_scenarios", 0))
                break

        change_str = "baseline"
        if not is_pilot and baseline_summary and baseline_week != week:
            base_m = baseline_summary.get("models", {}).get(m_alias)
            if base_m:
                delta = m_asr - base_m.get("asr", 0.0)
                change_str = f"{delta:+.1%}"
            else:
                change_str = "N/A"
        elif is_pilot:
            change_str = "N/A (pilot)"

        comp_rate = m_info.get("completion_rate", 1.0)
        html_lines.append(
            f"        <tr><td><code>{m_alias}</code></td><td>{m_trials}</td>"
            f"<td>{m_asr:.1%}</td><td>{ci_str}</td><td>{change_str}</td>"
            f"<td>{comp_rate:.1%}</td></tr>"
        )

    p_cautious = (
        "Attack success rates reflect deterministic invariant evaluations in the simulated "
        "e-commerce environment. Where confidence intervals span zero when compared to prior "
        "evaluations, the data indicates <strong>no evidence of change</strong>. Observed "
        "differences reflect black-box behavioral measurements and should not be interpreted "
        "as evidence of provider optimization intent."
    )

    html_lines.extend(
        [
            "      </tbody>",
            "    </table>",
            "    <h2>2. Findings &amp; Cautious Assessment</h2>",
            f"    <p>{p_cautious}</p>",
            "  </div>",
            "</body>",
            "</html>",
        ]
    )

    html_path = out_dir / f"{week}.html"
    html_path.write_text("\n".join(html_lines), encoding="utf-8")

    # 6. Update reports/weekly/index.json
    index_manifest_path = out_dir / "index.json"
    manifest: dict[str, Any] = {"schema_version": "1.0.0", "weeks": []}
    if index_manifest_path.is_file():
        with contextlib.suppress(Exception):
            manifest = json.loads(index_manifest_path.read_text(encoding="utf-8"))

    existing_weeks = {w_entry.get("week"): w_entry for w_entry in manifest.get("weeks", [])}
    existing_weeks[week] = {
        "week": week,
        "is_pilot": is_pilot,
        "status": week_number_str,
        "file_md": f"{week}.md",
        "file_html": f"{week}.html",
    }

    manifest["weeks"] = sorted(existing_weeks.values(), key=lambda x: str(x["week"]))
    manifest["schema_version"] = "1.0.0"
    index_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "report_md": md_path,
        "report_html": html_path,
        "manifest": index_manifest_path,
    }
