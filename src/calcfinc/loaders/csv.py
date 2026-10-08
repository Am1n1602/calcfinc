"""CSV loader: a long file (one row per fact) or a wide file (one row per metric, one column
per period). See docs/fact-schema.md.

Long header example:   entity,metric,period,value,currency
Wide header example:   metric,FY2025,FY2026          (optionally an `entity` column first)

In a wide file an empty cell means "no data" and creates nothing; in a long file an empty
`value` is an explicit "not reported" fact.
"""
from __future__ import annotations

import csv as _csv
import hashlib
import io
from pathlib import Path
from typing import Any

from calcfinc.fact import Basis, Source
from calcfinc.loaders.records import LoadError, LoadReport, load_records
from calcfinc.period import DEFAULT_WINDOWS, PeriodWindows, resolve_period

_META = ("entity", "metric")


def read_rows(text: str, *, layout: str = "auto", fiscal_year_end_month: int = 12,
              windows: PeriodWindows = DEFAULT_WINDOWS, delimiter: str = ",") -> list[dict[str, Any]]:
    """Parse CSV text into long-layout row dicts (each carries its source line as `_row`)."""
    reader = _csv.reader(io.StringIO(text), delimiter=delimiter)
    header: list[str] | None = None
    body: list[tuple[int, list[str]]] = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        if header is None:
            header = [c.strip() for c in cells]
        else:
            body.append((reader.line_num, cells))
    if header is None:
        raise LoadError(["the file is empty"])
    lower = [h.lower() for h in header]
    if layout == "auto":
        layout = "long" if ("metric" in lower and "value" in lower) else "wide" if "metric" in lower else ""
    if layout not in ("long", "wide"):
        raise LoadError(["header: needs a 'metric' column, plus 'value' (long layout) or period columns (wide)"])

    for line, cells in body:
        if len(cells) > len(header):
            raise LoadError([f"row {line}: {len(cells)} cells but the header has {len(header)}"])

    if layout == "long":
        return [{"_row": line, **{lower[i]: c for i, c in enumerate(cells) if lower[i]}} for line, cells in body]

    period_cols = [i for i, h in enumerate(lower) if h and h not in _META]
    bad = []
    for i in period_cols:
        try:
            resolve_period(header[i], fiscal_year_end_month, windows)
        except ValueError as e:
            bad.append(f"header {header[i]!r}: {e}")
    if bad:
        raise LoadError(bad)
    meta = {m: lower.index(m) for m in _META if m in lower}
    out: list[dict[str, Any]] = []
    for line, cells in body:
        cells = cells + [""] * (len(header) - len(cells))
        for i in period_cols:
            if cells[i].strip():
                row: dict[str, Any] = {"_row": line, "_col": header[i], "period": header[i], "value": cells[i]}
                row.update({m: cells[j] for m, j in meta.items()})
                out.append(row)
    return out


def load_csv(repos: Any, path: str | Path, *, layout: str = "auto", entity: str | None = None,
             currency: str | None = None, basis: Basis | str = "consolidated",
             fiscal_year_end_month: int = 12, windows: PeriodWindows = DEFAULT_WINDOWS,
             entity_kind: str = "company", delimiter: str = ",", sector: str | None = None) -> LoadReport:
    p = Path(path)
    data = p.read_bytes()
    rows = read_rows(data.decode("utf-8-sig"), layout=layout, fiscal_year_end_month=fiscal_year_end_month,
                     windows=windows, delimiter=delimiter)
    source = Source(kind="csv", document_title=p.name, uri=str(p.resolve()),
                    content_hash=hashlib.sha256(data).hexdigest())
    return load_records(repos, rows, entity=entity, currency=currency, basis=basis,
                        fiscal_year_end_month=fiscal_year_end_month, windows=windows, source=source,
                        entity_kind=entity_kind, sector=sector)
