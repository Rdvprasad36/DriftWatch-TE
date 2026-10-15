"""Multiple comparison correction procedures.

Architecture.md §3.8 / Design.md §4.2:
  "Correct across models with Benjamini-Hochberg. Report odds ratios
   and risk differences with CIs."
"""

from __future__ import annotations


def benjamini_hochberg(
    p_values: list[float], *, alpha: float = 0.05
) -> list[tuple[float, bool]]:
    """Apply the Benjamini-Hochberg False Discovery Rate (FDR) procedure.

    Controls FDR at level alpha across m hypothesis tests.

    Args:
        p_values: Raw p-values from multiple statistical tests.
        alpha: Targeted false discovery rate (default 0.05).

    Returns:
        List of tuples ``(adjusted_p_value, is_significant)`` corresponding
        to the input order of *p_values*.
    """
    m = len(p_values)
    if m == 0:
        return []

    # Sort p-values while preserving original indices
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])

    adjusted = [0.0] * m
    significant = [False] * m

    # Step-up adjustment: p_adj(i) = min(1, min_{k >= i} (p(k) * m / k))
    min_coeff = 1.0
    for rank in range(m, 0, -1):
        orig_idx, p_val = indexed[rank - 1]
        adjusted_val = min(1.0, (p_val * m) / rank)
        min_coeff = min(min_coeff, adjusted_val)
        adjusted[orig_idx] = min_coeff

    for idx, adj_p in enumerate(adjusted):
        significant[idx] = adj_p <= alpha

    return list(zip(adjusted, significant, strict=True))

