"""Period typing: classify a duration by length, and map a date to a fiscal year."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class PeriodWindows:
    """Inclusive (min_days, max_days) of `period_end - period_start` for each period type.
    Override per engine for unusual calendars (e.g. 4-4-5 retail weeks)."""

    month: tuple[int, int] = (27, 32)
    quarter: tuple[int, int] = (71, 111)
    half: tuple[int, int] = (160, 200)
    year: tuple[int, int] = (330, 400)

    def classify(self, days: int | None) -> str | None:
        if days is None:
            return None
        for name in ("month", "quarter", "half", "year"):
            lo, hi = getattr(self, name)
            if lo <= days <= hi:
                return name
        return None


DEFAULT_WINDOWS = PeriodWindows()


@dataclass(frozen=True, slots=True)
class ResolvedPeriod:
    start: date | None                 # None for a single date (an instant)
    end: date
    financial_year: int
    quarter: int | None
    is_annual: bool


_FY = re.compile(r"FY(\d{4})(?:Q([1-4]))?", re.I)
_MONTH = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _month_end(year: int, month: int) -> date:
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


def _shift(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def position_in_year(d: date, fiscal_year_end_month: int) -> int:
    """1..12: which month of its fiscal year `d` falls in."""
    return (d.month - fiscal_year_end_month - 1) % 12 + 1


def classify_range(start: date, end: date, fiscal_year_end_month: int, windows: PeriodWindows) -> ResolvedPeriod:
    ptype = windows.classify((end - start).days)
    pos = position_in_year(end, fiscal_year_end_month)
    quarter = pos // 3 if ptype == "quarter" and pos % 3 == 0 else None
    return ResolvedPeriod(start, end, fiscal_year(end, fiscal_year_end_month), quarter, ptype == "year")


def resolve_period(label: str, fiscal_year_end_month: int = 12,
                   windows: PeriodWindows = DEFAULT_WINDOWS) -> ResolvedPeriod:
    """Turn a period label into dates. Accepted: 'FY2026', 'FY2026Q1' (fiscal calendar of the
    entity), '2026-03' (calendar month), '2026-01-01..2026-12-31' (explicit range) and
    '2026-12-31' (a single date, for balance-sheet items). Raises ValueError otherwise."""
    text = label.strip()
    f = fiscal_year_end_month
    if m := _FY.fullmatch(text):
        fy = int(m.group(1))
        sy, sm = (fy, 1) if f == 12 else (fy - 1, f + 1)
        if m.group(2):
            q = int(m.group(2))
            (ey, em), (qy, qm) = _shift(sy, sm, 3 * q - 1), _shift(sy, sm, 3 * (q - 1))
            return ResolvedPeriod(date(qy, qm, 1), _month_end(ey, em), fy, q, False)
        return ResolvedPeriod(date(sy, sm, 1), _month_end(fy, f), fy, None, True)
    if m := _MONTH.fullmatch(text):
        y, mo = int(m.group(1)), int(m.group(2))
        end = _month_end(y, mo)
        return ResolvedPeriod(date(y, mo, 1), end, fiscal_year(end, f), None, False)
    try:
        if m := _RANGE.fullmatch(text):
            start, end = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
            if end < start:
                raise ValueError("period ends before it starts")
            return classify_range(start, end, f, windows)
        if _DAY.fullmatch(text):
            end = date.fromisoformat(text)
            return ResolvedPeriod(None, end, fiscal_year(end, f), None, False)
    except ValueError as e:
        raise ValueError(f"bad period {label!r}: {e}") from None
    raise ValueError(f"unrecognised period {label!r}; use FY2026, FY2026Q1, 2026-03, "
                     "2026-01-01..2026-12-31 or 2026-12-31")


def fiscal_year(d: date, fiscal_year_end_month: int = 12) -> int:
    """Fiscal year labelled by the calendar year in which it ends: with a March year end,
    31-Mar-2026 and 30-Jun-2025 are both FY2026. A fact's own financial_year always wins."""
    return d.year if d.month <= fiscal_year_end_month else d.year + 1
