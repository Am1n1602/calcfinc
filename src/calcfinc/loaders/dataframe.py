"""DataFrame loader. Duck-typed: it never imports pandas, so the core stays dependency-free
(install the `pandas` extra only if you want to build frames).

A DataFrame stores numbers as floats, which are inexact. By default any float in a value
cell is refused. With float_policy="repr" each float is converted through its shortest
round-trip text (0.1 becomes "0.1") and NaN becomes "not reported"; the number of converted
cells is recorded on the load's Source.
"""
from __future__ import annotations

import math
from typing import Any

from calcfinc.fact import Source

_NA_TYPES = ("NAType", "NaTType")
_INTEGRAL = ("financial_year", "quarter")


def _is_float(v: Any) -> bool:
    return isinstance(v, float) or getattr(getattr(v, "dtype", None), "kind", "") == "f"


def _label(col: Any) -> str:
    return col.date().isoformat() if hasattr(col, "date") and not isinstance(col, str) else str(col).strip()


def frame_to_rows(df: Any, *, layout: str = "long", float_policy: str = "refuse"
                  ) -> tuple[list[dict[str, Any]], int]:
    """Convert a frame to long-layout row dicts. Returns (rows, floats_converted)."""
    if float_policy not in ("refuse", "repr"):
        raise ValueError("float_policy must be 'refuse' or 'repr'")
    if layout not in ("long", "wide"):
        raise ValueError("layout must be 'long' or 'wide'")
    if "metric" not in [str(c).lower() for c in df.columns] and getattr(df.index, "name", None) == "metric":
        df = df.reset_index()
    cols = list(df.columns)
    names = [_label(c) for c in cols]
    lower = [n.lower() for n in names]
    if "metric" not in lower:
        raise ValueError("the frame needs a 'metric' column (or an index named 'metric')")

    refused: dict[str, int] = {}
    converted = 0

    def cell(v: Any, col: str, is_value: bool) -> Any:
        nonlocal converted
        if v is None or type(v).__name__ in _NA_TYPES:
            return None
        kind = getattr(getattr(v, "dtype", None), "kind", "")
        if kind in ("i", "u"):
            return int(v)
        if kind == "b":
            return bool(v)
        if _is_float(v):
            f = float(v)
            if is_value:
                if float_policy == "refuse":
                    refused[col] = refused.get(col, 0) + 1
                    return None
                converted += 1
                return None if math.isnan(f) else repr(f)
            if math.isnan(f):
                return None                       # pandas encodes an empty optional cell as NaN
            return int(f) if f.is_integer() and col in _INTEGRAL else f
        return v

    rows: list[dict[str, Any]] = []
    for r, record in enumerate(df.to_dict(orient="records"), 2):
        items = {names[i]: record[cols[i]] for i in range(len(cols))}
        if layout == "long":
            rows.append({"_row": r, **{n.lower(): cell(v, n.lower(), n.lower() == "value")
                                       for n, v in items.items()}})
        else:
            meta = {n.lower(): v for n, v in items.items() if n.lower() in ("entity", "metric")}
            for n, v in items.items():
                if n.lower() in ("entity", "metric"):
                    continue
                c = cell(v, n, True)
                if c is not None:
                    rows.append({"_row": r, "_col": n, "period": n, "value": c,
                                 **{k: cell(x, k, False) for k, x in meta.items()}})
    if refused:
        where = ", ".join(f"{c!r} ({n} cell(s))" for c, n in refused.items())
        raise TypeError(f"float values found in {where}. Floats are inexact. Load the numbers as "
                        "strings, ints or Decimals, or pass float_policy='repr' to convert each "
                        "float through its shortest text form (NaN then means not reported).")
    return rows, converted


def frame_source(converted: int) -> Source:
    note = f"DataFrame; {converted} float cell(s) converted via shortest text form" if converted else "DataFrame"
    return Source(kind="dataframe", document_title=note)
