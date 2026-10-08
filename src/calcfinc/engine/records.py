"""Regroup stored facts into per-period records: one duration record (P&L / cash flow) with
the balance-sheet snapshot for the same period_end merged in."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from calcfinc.fact import Basis, FinancialFact
from calcfinc.period import DEFAULT_WINDOWS, PeriodWindows, fiscal_year


@dataclass(frozen=True, slots=True)
class PeriodRecord:
    basis: str
    period_start: date | None
    period_end: date | None
    financial_year: int | None
    quarter: int | None
    is_annual: bool
    period_type: str | None                  # 'month' | 'quarter' | 'half' | 'year' | None
    values: dict[str, Decimal] = field(default_factory=dict)
    currencies: dict[str, str] = field(default_factory=dict)      # metric -> ISO 4217
    sources: dict[str, int | None] = field(default_factory=dict)
    review_flags: dict[str, str] = field(default_factory=dict)

    # ---- access ----
    def get(self, metric: str, default: Any = None) -> Any:
        return self.values.get(metric, default)

    def __contains__(self, metric: str) -> bool:
        return metric in self.values

    def has_all(self, *metrics: str) -> bool:
        return all(m in self.values for m in metrics)

    # ---- classification ----
    @property
    def duration_days(self) -> int | None:
        if self.period_start is None or self.period_end is None:
            return None
        return (self.period_end - self.period_start).days

    @property
    def is_single_quarter(self) -> bool:
        return self.period_type == "quarter"

    @property
    def is_point_in_time_only(self) -> bool:
        return self.period_start is None and self.period_end is not None

    @property
    def label(self) -> str:
        fy = f"FY{self.financial_year}" if self.financial_year else "FY?"
        if self.is_point_in_time_only:
            return f"as of {self.period_end}"
        if self.quarter:
            return f"{fy} Q{self.quarter}"
        if self.is_annual:
            return fy
        if self.period_type == "month" and self.period_end:
            return f"{self.period_end:%Y-%m}"
        if self.period_start and self.period_end:
            return f"{self.period_start}..{self.period_end}"
        return fy

    def sort_key(self) -> tuple[date, date, int]:
        return (
            self.period_end or date.min,
            self.period_start or date.min,
            0 if self.is_annual else 1,      # annual before quarterly on the same end date
        )


def _bucket() -> dict[str, Any]:
    return {"values": {}, "currencies": {}, "sources": {}, "flags": {}}


def _put(bucket: dict[str, Any], f: FinancialFact) -> None:
    # Facts arrive oldest-reported first, so a later restatement overwrites an earlier value.
    # A fact with no value never erases a reported one: missing stays missing, not zero.
    if f.value is not None:
        bucket["values"][f.metric] = f.value
        bucket["sources"][f.metric] = f.source_id
        if f.currency is not None:
            bucket["currencies"][f.metric] = f.currency
        else:
            bucket["currencies"].pop(f.metric, None)
    if f.mapping_reason:
        bucket["flags"][f.metric] = f.mapping_reason


def build_period_records(repos: Any, entity_id: int, basis: Basis | str, *,
                         windows: PeriodWindows = DEFAULT_WINDOWS,
                         fiscal_year_end_month: int = 12) -> list[PeriodRecord]:
    basis = Basis(basis)
    facts: list[FinancialFact] = repos.facts.list_facts(entity_id, basis=basis)

    durations: dict[tuple[date | None, date | None], dict[str, Any]] = {}
    instants: dict[date | None, dict[str, Any]] = {}

    for f in facts:
        if f.is_point_in_time:
            bucket = instants.setdefault(f.period_end, _bucket())
        else:
            bucket = durations.setdefault((f.period_start, f.period_end), {
                **_bucket(), "meta": (f.financial_year, f.quarter, f.is_annual)})
        _put(bucket, f)

    records: list[PeriodRecord] = []
    used_instant_ends: set[date | None] = set()

    for (ps, pe), d in durations.items():
        fy, q, annual = d["meta"]
        values, currencies = dict(d["values"]), dict(d["currencies"])
        sources, flags = dict(d["sources"]), dict(d["flags"])
        snap = instants.get(pe)
        if snap is not None:
            used_instant_ends.add(pe)
            for m, v in snap["values"].items():
                values.setdefault(m, v)
                sources.setdefault(m, snap["sources"].get(m))
                if m in snap["currencies"]:
                    currencies.setdefault(m, snap["currencies"][m])
            for m, r in snap["flags"].items():
                flags.setdefault(m, r)
        days = (pe - ps).days if (ps is not None and pe is not None) else None
        ptype = "year" if annual else windows.classify(days)
        records.append(PeriodRecord(
            basis=basis.value, period_start=ps, period_end=pe, financial_year=fy, quarter=q,
            is_annual=annual, period_type=ptype, values=values, currencies=currencies,
            sources=sources, review_flags=flags))

    # balance-sheet dates with no matching duration record stay as snapshot-only records
    for pe, snap in instants.items():
        if pe in used_instant_ends:
            continue
        records.append(PeriodRecord(
            basis=basis.value, period_start=None, period_end=pe,
            financial_year=fiscal_year(pe, fiscal_year_end_month) if pe else None,
            quarter=None, is_annual=False, period_type=None, values=dict(snap["values"]),
            currencies=dict(snap["currencies"]), sources=dict(snap["sources"]),
            review_flags=dict(snap["flags"])))

    records.sort(key=PeriodRecord.sort_key)
    return records
