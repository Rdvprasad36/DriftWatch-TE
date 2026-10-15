"""Parquet conversion for DriftWatch-TE result bundles.

Architecture.md §3.7 / §5:
  "Storage: Parquet (pyarrow), Hugging Face Datasets, git."

Converts the NDJSON staging file produced by the orchestrator into a
columnar Parquet file for compact storage and fast analytical queries.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


def ndjson_to_parquet(ndjson_path: Path, parquet_path: Path) -> int:
    """Convert an NDJSON file to Parquet.

    Args:
        ndjson_path: Path to the source ``trials.ndjson`` file.
        parquet_path: Path to write the output ``trials.parquet`` file.

    Returns:
        Number of rows written.

    Raises:
        FileNotFoundError: If *ndjson_path* does not exist.
    """
    if not ndjson_path.exists():
        msg = f"NDJSON file not found: {ndjson_path}"
        raise FileNotFoundError(msg)

    rows: list[dict[str, Any]] = []
    for line in ndjson_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))

    if not rows:
        # Write an empty Parquet file with no columns
        table = pa.table({})
        pq.write_table(table, parquet_path)
        logger.info("Wrote empty Parquet file: %s", parquet_path)
        return 0

    # Build columnar data from row dicts
    columns: dict[str, list[Any]] = {}
    for key in rows[0]:
        columns[key] = [row.get(key) for row in rows]

    table = pa.table(columns)
    pq.write_table(table, parquet_path)

    logger.info(
        "Converted %d rows from %s → %s",
        len(rows),
        ndjson_path.name,
        parquet_path.name,
    )
    return len(rows)


def load_parquet_rows(parquet_path: Path) -> list[dict[str, Any]]:
    """Read a Parquet file and return rows as a list of dicts.

    Args:
        parquet_path: Path to the ``trials.parquet`` file.

    Returns:
        List of row dicts (empty list if the file has 0 rows).

    Raises:
        FileNotFoundError: If *parquet_path* does not exist.
    """
    if not parquet_path.exists():
        msg = f"Parquet file not found: {parquet_path}"
        raise FileNotFoundError(msg)

    table = pq.read_table(parquet_path)

    if table.num_rows == 0:
        return []

    # Convert to Python dicts, replacing pyarrow nulls with None
    rows: list[dict[str, Any]] = []
    col_names = table.column_names
    for i in range(table.num_rows):
        row: dict[str, Any] = {}
        for col in col_names:
            val = table.column(col)[i].as_py()
            row[col] = val
        rows.append(row)

    return rows

