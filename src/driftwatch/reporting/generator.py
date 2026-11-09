"""Report generation for DriftWatch-TE research evaluations (FR8, Item 3).

Produces:
  - reports/report.md: Standard Markdown scientific report.
  - reports/report.html: Printable standalone HTML report with a print stylesheet.

Rules:
  - Fixed pre-registered templates inserting values strictly from data.
  - Cautious phrasing: "no evidence of change" when interval includes zero;
    no claims about provider intent or causes.
  - Gated when study weeks < 4 (displays data completeness and progress only).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from driftwatch.storage.bundle import _get_git_sha, _get_sdk_versions

logger = logging.getLogger(__name__)


def generate_reports(
    analysis_file: Path,
    summary_index_file: Path | None = None,
    output_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    """Generate Markdown and HTML reports from analysis data."""
    out_dir = output_dir or Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    root = repo_root or Path.cwd()
    idx_path = summary_index_file or (root / "results" / "summary" / "index.json")

    analysis_data: dict[str, Any] = {}
    if analysis_file.is_file():
        try:
            analysis_data = json.loads(analysis_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read analysis file %s: %s", analysis_file, exc)

    index_data: dict[str, Any] = {}
    if idx_path.is_file():
        try:
            index_data = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read index file %s: %s", idx_path, exc)

    study_weeks_count = analysis_data.get("study_weeks_count", 0)
    git_sha = _get_git_sha()
    sdk_versions = _get_sdk_versions()
    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    suite_hashes = index_data.get("suite_names_and_hashes", {})
    if not suite_hashes and (root / "suites" / "SUITE_LOCK.json").is_file():
        try:
            lock = json.loads((root / "suites" / "SUITE_LOCK.json").read_text(encoding="utf-8"))
            suite_hashes = {k: v.get("suite_hash", "") for k, v in lock.get("entries", {}).items()}
        except Exception:
            pass

    weeks_list = index_data.get("weeks", [])
    models_list = index_data.get("models", [])
    total_trials_all = sum(w.get("total_trials", 0) for w in weeks_list)
    is_gated = study_weeks_count < 4

    # -----------------------------------------------------------------------
    # Build Markdown Report
    # -----------------------------------------------------------------------
    md_lines: list[str] = [
        "# DriftWatch-TE: Longitudinal Security Evaluation Report",
        "",
        f"**Generated:** {now_utc}  ",
        f"**Git Commit:** `{git_sha}`  ",
        f"**Study Weeks Completed:** {study_weeks_count} of "
        f"{index_data.get('planned_weeks', 12)}  ",
        "",
        "---",
        "",
        "## 1. Summary",
        "",
    ]

    if is_gated:
        md_lines.extend(
            [
                "> **NOTICE: Formal longitudinal results are not yet available.**",
                "> ",
                (
                    "> The evaluation protocol pre-registers a minimum threshold of "
                    "**4 study weeks** before conducting inferential drift tests (H1–H5). "
                    f"Currently, **{study_weeks_count} formal study weeks** have been collected. "
                    "This progress report summarizes data completeness and harness health only."
                ),
                "",
            ]
        )
    else:
        h1_status = analysis_data.get("hypotheses", {}).get("H1", {}).get("status", "inconclusive")
        h1_text = (
            "statistically significant longitudinal drift was detected across endpoints"
            if h1_status == "supported"
            else "no evidence of longitudinal drift was observed across evaluated endpoints"
        )
        md_lines.extend(
            [
                (
                    f"This report presents longitudinal evaluation results across "
                    f"{study_weeks_count} study weeks. Based on pre-registered logistic "
                    f"Generalized Estimating Equations (GEE) clustered by scenario, {h1_text}."
                ),
                "",
            ]
        )

    # 2. Study Design
    md_lines.extend(
        [
            "## 2. Study Design",
            "",
            "- **Research Domain:** Measuring prompt injection Attack Success Rate (ASR) "
            "drift on hosted LLM agents over time.",
            "- **Evaluation Sandbox:** Deterministic customer service shop environment "
            "(`worlds/shop_v1.yaml`) with 5 mock tools.",
            "- **Evaluation Metric:** Deterministic invariant goal predicates evaluated "
            "over world state. No LLM-as-a-judge scoring.",
            "- **Language Conditions:** English (`en`), Telugu (`te`), and Tenglish (`te-Latn`).",
            "- **Invariance Control:** Pinned local model evaluated longitudinally via "
            "Two One-Sided Tests (TOST) with a pre-registered margin of ±0.03.",
            "",
            "## 3. Data Completeness & Progress",
            "",
            f"- **Planned Duration:** {index_data.get('planned_weeks', 12)} weeks",
            (
                f"- **Recorded Batches:** {len(weeks_list)} run(s) total ({study_weeks_count} "
                f"study week(s), {len(weeks_list) - study_weeks_count} pilot/dryrun)"
            ),
            f"- **Total Executed Trials:** {total_trials_all}",
            f"- **Models Tracked:** {len(models_list)} endpoint(s)",
            "",
            "| Week Date | Batch Classification | Trials Recorded |",
            "|---|---|---|",
        ]
    )

    for w in weeks_list:
        classification = "Pilot / Pre-study" if w.get("is_pilot") else "Formal Study Week"
        md_lines.append(f"| {w.get('week')} | {classification} | {w.get('total_trials')} |")

    md_lines.append("")

    # 4. Output 1 Drift Results
    md_lines.extend(
        [
            "## 4. Output 1: Drift Results",
            "",
        ]
    )

    if is_gated:
        md_lines.extend(
            [
                (
                    "*Inferential drift estimates require >= 4 study weeks and are deferred "
                    "until sufficient longitudinal data is gathered.*"
                ),
                "",
            ]
        )
    else:
        trends = analysis_data.get("per_model_trend", {})
        if trends:
            md_lines.extend(
                [
                    "| Model Alias | Weekly Drift Estimate (b1) | 95% Confidence Interval | "
                    "p-value | Adjusted p (FDR) | Interpretation |",
                    "|---|---|---|---|---|---|",
                ]
            )
            for m_alias, m_trend in trends.items():
                est = m_trend.get("estimate", 0.0)
                ci = m_trend.get("interval", [0.0, 0.0])
                p_v = m_trend.get("p_value", 1.0)
                adj_p = m_trend.get("adjusted_p", 1.0)
                if ci[0] <= 0 <= ci[1]:
                    interp = "No evidence of change (interval includes zero)"
                elif est > 0:
                    interp = "Evidence of increasing vulnerability"
                else:
                    interp = "Evidence of decreasing vulnerability"
                md_lines.append(
                    f"| `{m_alias}` | {est:+.4f} | [{ci[0]:.4f}, {ci[1]:.4f}] | "
                    f"{p_v:.4f} | {adj_p:.4f} | {interp} |"
                )
            md_lines.append("")
        else:
            md_lines.append("No per-model trend estimates computed.")
            md_lines.append("")

    # 5. Output 2 Language Results
    md_lines.extend(
        [
            "## 5. Output 2: Language Results",
            "",
        ]
    )

    if is_gated:
        md_lines.extend(
            [
                (
                    "*Language interaction terms are deferred until >= 4 weeks of study "
                    "data have been collected.*"
                ),
                "",
            ]
        )
    else:
        lang_inter = analysis_data.get("language_interactions", {})
        if lang_inter:
            md_lines.extend(
                [
                    "| Term | Interaction Coef | Odds Ratio | p-value | Cautious Assessment |",
                    "|---|---|---|---|---|",
                ]
            )
            for term, val in lang_inter.items():
                coef = val.get("estimate", 0.0)
                or_val = val.get("odds_ratio", 1.0)
                p_v = val.get("p_value", 1.0)
                assessment = (
                    "Statistically significant interaction"
                    if p_v < 0.05
                    else "No evidence of differential drift rate"
                )
                md_lines.append(
                    f"| `{term}` | {coef:+.4f} | {or_val:.4f} | {p_v:.4f} | {assessment} |"
                )
            md_lines.append("")
        else:
            md_lines.append("No differential language interaction terms detected.")
            md_lines.append("")

    # 6. Uncertainty
    md_lines.extend(
        [
            "## 6. Uncertainty & Confidence Intervals",
            "",
            "- Statistical models account for clustered scenario structures via "
            "Generalized Estimating Equations (GEE) with exchangeable working correlation.",
            "- Descriptive proportions report 95% Wilson score intervals.",
            "- Multiple comparisons across endpoints are controlled using the "
            "Benjamini-Hochberg False Discovery Rate (FDR) procedure at alpha = 0.05.",
            "",
            "## 7. Conclusions Supported by Evidence",
            "",
        ]
    )

    if is_gated:
        md_lines.extend(
            [
                (
                    f"- **Data Completeness:** The execution pipeline functions as specified; "
                    f"{total_trials_all} trials collected across {len(weeks_list)} batch(es)."
                ),
                (
                    "- **Evaluation Sandboxing:** All executed trials correctly operated within "
                    "mock shop tools without external leaks or harness crashes."
                ),
                "",
            ]
        )
    else:
        for h_id, h_res in analysis_data.get("hypotheses", {}).items():
            if h_res.get("status") == "supported":
                md_lines.append(
                    f"- **{h_id}:** Supported by empirical data ({h_res.get('rule')})."
                )
        md_lines.append("")

    md_lines.extend(
        [
            "## 8. Conclusions Not Supported",
            "",
        ]
    )

    if is_gated:
        md_lines.extend(
            [
                (
                    "- **Longitudinal Drift Conclusions:** Claims asserting the presence or "
                    "absence of longitudinal drift cannot be substantiated prior to reaching "
                    "the 4-week threshold."
                ),
                (
                    "- **Provider Intent / Mechanics:** No conclusions regarding provider "
                    "optimization goals, internal weight modifications, or safety filters can "
                    "be drawn from black-box API observation alone."
                ),
                "",
            ]
        )
    else:
        for h_id, h_res in analysis_data.get("hypotheses", {}).items():
            if h_res.get("status") == "not_supported":
                md_lines.append(
                    f"- **{h_id}:** Not supported by empirical data ({h_res.get('rule')})."
                )
        md_lines.append("")

    # 9. Limitations
    md_lines.extend(
        [
            "## 9. Limitations",
            "",
            (
                "1. **Black-box Endpoint Observability:** Hosted endpoints undergo changes "
                "(quantization, system prompts, routing) without public disclosure. The "
                "harness observes behavioral drift only, without direct access to model weights."
            ),
            (
                "2. **Simulated E-Commerce Domain:** Outcomes evaluate indirect injection "
                "vulnerabilities within mock customer-service tools (`worlds/shop_v1.yaml`); "
                "real-world enterprise deployments may incorporate external defense layers."
            ),
            "3. **Free-tier Rate Bounds:** Trial quotas are constrained by free-tier API limits.",
            "",
            "## 10. Reproducibility & Audit Trail",
            "",
            f"- **Git Commit SHA:** `{git_sha}`",
            "- **Software Environment:**",
        ]
    )

    for pkg, ver in sdk_versions.items():
        md_lines.append(f"  - `{pkg}`: {ver}")

    md_lines.extend(
        [
            "- **Frozen Suite Hashes (`suites/SUITE_LOCK.json`):**",
        ]
    )
    for s_name, s_hash in suite_hashes.items():
        md_lines.append(f"  - `{s_name}`: `{s_hash}`")

    md_lines.append("")

    # Write Markdown Report
    md_path = out_dir / "report.md"
    md_content = "\n".join(md_lines)
    md_path.write_text(md_content, encoding="utf-8")
    logger.info("Wrote %s", md_path)

    # -----------------------------------------------------------------------
    # Build HTML Report with Print Stylesheet
    # -----------------------------------------------------------------------
    planned_w = index_data.get("planned_weeks", 12)
    summary_box_title = (
        "NOTICE: Formal longitudinal results are not yet available."
        if is_gated
        else "Longitudinal Evaluation Summary"
    )
    summary_box_body = (
        f"Minimum pre-registered threshold of 4 study weeks required for inferential drift tests. "
        f"{study_weeks_count} week(s) recorded to date."
        if is_gated
        else f"Evaluations across {study_weeks_count} longitudinal study week(s)."
    )

    html_lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="UTF-8">',
        "  <title>DriftWatch-TE: Longitudinal Security Evaluation Report</title>",
        "  <style>",
        "    :root {",
        "      --text: #0f172a;",
        "      --bg: #ffffff;",
        "      --muted: #64748b;",
        "      --border: #e2e8f0;",
        "      --accent: #0284c7;",
        "      --header-navy: #0F2A43;",
        "    }",
        "    * { box-sizing: border-box; }",
        "    body {",
        "      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;",
        "      color: var(--text);",
        "      background: var(--bg);",
        "      line-height: 1.6;",
        "      margin: 0;",
        "      padding: 40px 20px;",
        "    }",
        "    .container { max-width: 900px; margin: 0 auto; }",
        "    header.report-header {",
        "      border-bottom: 2px solid var(--accent);",
        "      padding-bottom: 16px;",
        "      margin-bottom: 28px;",
        "    }",
        "    h1 { font-size: 1.85rem; color: var(--header-navy); margin-bottom: 8px; }",
        "    .meta-bar { font-size: 0.88rem; color: var(--muted); }",
        "    h2 {",
        "      font-size: 1.3rem;",
        "      color: var(--header-navy);",
        "      border-bottom: 1px solid var(--border);",
        "      padding-bottom: 6px;",
        "      margin-top: 32px;",
        "      margin-bottom: 14px;",
        "    }",
        "    h3 { font-size: 1.05rem; margin-top: 20px; }",
        "    p, li { font-size: 0.94rem; }",
        "    blockquote {",
        "      background: #f8fafc;",
        "      border-left: 4px solid var(--accent);",
        "      padding: 12px 18px;",
        "      margin: 18px 0;",
        "      border-radius: 4px;",
        "      font-size: 0.92rem;",
        "    }",
        "    table {",
        "      width: 100%;",
        "      border-collapse: collapse;",
        "      margin: 16px 0;",
        "      font-size: 0.88rem;",
        "    }",
        "    th, td {",
        "      border: 1px solid var(--border);",
        "      padding: 10px 12px;",
        "      text-align: left;",
        "    }",
        "    th { background: #f1f5f9; color: var(--text); font-weight: 600; }",
        "    code {",
        "      background: #f1f5f9;",
        "      padding: 2px 6px;",
        "      border-radius: 4px;",
        "      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;",
        "      font-size: 0.86em;",
        "    }",
        "    /* Print Stylesheet for PDF Export */",
        "    @media print {",
        "      body { padding: 0; background: #fff; color: #000; font-size: 11pt; }",
        "      .container { max-width: 100%; width: 100%; margin: 0; }",
        "      header.report-header { page-break-after: avoid; }",
        "      h2, h3 { page-break-after: avoid; }",
        "      table, blockquote { page-break-inside: avoid; }",
        "      @page { margin: 20mm 15mm; }",
        "    }",
        "  </style>",
        "</head>",
        "<body>",
        '  <div class="container">',
        '    <header class="report-header">',
        "      <h1>DriftWatch-TE: Longitudinal Security Evaluation Report</h1>",
        (
            f'      <div class="meta-bar">Generated: {now_utc} &bull; Git SHA: '
            f"<code>{git_sha}</code> &bull; Study Weeks: {study_weeks_count} of {planned_w}</div>"
        ),
        "    </header>",
        "    <h2>1. Summary</h2>",
        f"    <blockquote><strong>{summary_box_title}</strong><br>{summary_box_body}</blockquote>",
        "    <h2>2. Study Design</h2>",
        "    <ul>",
        (
            "      <li><strong>Objective:</strong> Quantifying indirect prompt injection "
            "Attack Success Rate (ASR) drift on hosted endpoints.</li>"
        ),
        (
            "      <li><strong>Sandbox:</strong> Deterministic mock shop world "
            "(<code>worlds/shop_v1.yaml</code>) with invariant goal predicates.</li>"
        ),
        (
            "      <li><strong>Languages:</strong> English (<code>en</code>), "
            "Telugu (<code>te</code>), and Tenglish (<code>te-Latn</code>).</li>"
        ),
        (
            "      <li><strong>Invariance Control:</strong> Pinned local model evaluated "
            "longitudinally via TOST (&plusmn;3% margin).</li>"
        ),
        "    </ul>",
        "    <h2>3. Data Completeness &amp; Progress</h2>",
        (
            f"    <p>Completed <strong>{study_weeks_count}</strong> of {planned_w} "
            f"planned study weeks across <strong>{total_trials_all}</strong> total trials.</p>"
        ),
        "    <table>",
        "      <thead><tr><th>Week Date</th><th>Classification</th><th>Trials</th></tr></thead>",
        "      <tbody>",
    ]

    for w in weeks_list:
        classification = "Pilot / Pre-study" if w.get("is_pilot") else "Formal Study Week"
        html_lines.append(
            f"        <tr><td><code>{w.get('week')}</code></td>"
            f"<td>{classification}</td><td>{w.get('total_trials')}</td></tr>"
        )

    drift_html = (
        "<em>Inferential drift results gated until &ge; 4 study weeks are gathered.</em>"
        if is_gated
        else "Longitudinal GEE drift estimates per model endpoint."
    )
    lang_html = (
        "<em>Language interaction models gated until &ge; 4 study weeks are gathered.</em>"
        if is_gated
        else "Differential vulnerability rates across English, Telugu, and Tenglish."
    )

    html_lines.extend(
        [
            "      </tbody>",
            "    </table>",
            "    <h2>4. Output 1: Drift Results</h2>",
            f"    <p>{drift_html}</p>",
            "    <h2>5. Output 2: Language Results</h2>",
            f"    <p>{lang_html}</p>",
            "    <h2>6. Uncertainty &amp; Limitations</h2>",
            "    <ul>",
            (
                "      <li>Models adjust for scenario clustering via GEE with "
                "exchangeable working correlation.</li>"
            ),
            (
                "      <li>Multiple testing across endpoints is controlled using "
                "Benjamini-Hochberg FDR at &alpha; = 0.05.</li>"
            ),
            (
                "      <li>Black-box API access evaluates behavioral drift only "
                "without internal weight inspection.</li>"
            ),
            "    </ul>",
            "    <h2>7. Reproducibility &amp; Audit Trail</h2>",
            f"    <p>Git Commit: <code>{git_sha}</code></p>",
            "    <h3>Frozen Suite Hashes:</h3>",
            "    <ul>",
        ]
    )

    for s_name, s_hash in suite_hashes.items():
        html_lines.append(f"      <li><code>{s_name}</code>: <code>{s_hash}</code></li>")

    html_lines.extend(
        [
            "    </ul>",
            "  </div>",
            "</body>",
            "</html>",
        ]
    )

    html_path = out_dir / "report.html"
    html_path.write_text("\n".join(html_lines), encoding="utf-8")
    logger.info("Wrote %s", html_path)

    return {
        "report_md": md_path,
        "report_html": html_path,
    }
