"""Fact schema: one canonical figure for one entity / period / basis, plus supporting records.

All numbers are Decimal (floats are refused). `value is None` is a first-class state meaning
"not reported / not cleanly mappable"; it is never coerced to zero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from calcfinc.entity import check_currency
from calcfinc.num import to_decimal


class Basis(StrEnum):
    """Consolidated and standalone figures are separate bases and never substitute for each other."""

    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"


class StatementType(StrEnum):
    PROFIT_AND_LOSS = "profit_and_loss"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    SEGMENT = "segment"
    OTHER = "other"


class MappingConfidence(StrEnum):
    """How a raw source value became this canonical fact."""

    EXACT = "exact"
    ALTERNATE_TAG = "alternate_tag"
    DERIVED = "derived"
    UNMAPPED = "unmapped"


def _opt_decimal(v: object) -> Decimal | None:
    return None if v is None else to_decimal(v)


def _check_quarter(q: int | None) -> None:
    if q is not None and q not in (1, 2, 3, 4):
        raise ValueError(f"quarter must be 1..4 or None, got {q!r}")


@dataclass(frozen=True, slots=True)
class Source:
    """Provenance for a fact: the filing / file / feed it came from."""

    kind: str                                # 'xbrl' | 'csv' | 'management_accounts' | ...
    source_id: int | None = None
    entity_id: int | None = None
    document_title: str | None = None
    uri: str | None = None
    content_hash: str | None = None          # sha256 of the raw bytes, if known
    retrieved_at: datetime | None = None
    period_label: str | None = None          # raw period string as filed

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("Source requires a kind")


@dataclass(frozen=True, slots=True)
class FinancialFact:
    """`currency` is an ISO 4217 code for amounts and per-share figures, None for
    dimensionless ones (ratios, share counts). The store fills a missing currency from the
    entity default and rejects an amount that still has none.

    `reported_at` is when the figure was published. Two facts for the same period differing
    only in `reported_at` are kept side by side (a restatement); the engine uses the latest.
    """

    entity_id: int
    metric: str
    value: Decimal | None
    statement_type: StatementType
    basis: Basis
    currency: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    financial_year: int | None = None
    quarter: int | None = None               # 1..4, or None for annual / monthly / point-in-time
    is_annual: bool = False
    is_point_in_time: bool = False           # balance-sheet instant vs P&L duration
    reported_at: date | None = None
    source_id: int | None = None
    mapping_confidence: MappingConfidence = MappingConfidence.EXACT
    mapping_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.metric:
            raise ValueError("FinancialFact requires a metric name")
        object.__setattr__(self, "value", _opt_decimal(self.value))
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        object.__setattr__(self, "basis", Basis(self.basis))
        object.__setattr__(self, "mapping_confidence", MappingConfidence(self.mapping_confidence))
        if self.currency is not None:
            object.__setattr__(self, "currency", check_currency(self.currency))
        _check_quarter(self.quarter)

    def problems(self) -> list[str]:
        """Soft validation for ingestion QA; never raises."""
        out: list[str] = []
        if self.value is None and not self.mapping_reason:
            out.append("value is None but mapping_reason is empty (record why it is missing)")
        if self.is_point_in_time and self.period_start is not None:
            out.append("point-in-time fact should not have a period_start")
        if not self.is_point_in_time and self.is_annual and self.quarter is not None:
            out.append("annual duration fact should not carry a quarter")
        return out


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_") or "unnamed"


@dataclass(frozen=True, slots=True)
class Segment:
    """A reportable business segment. `name` is as reported; `slug` is the stable key
    within an entity."""

    entity_id: int
    name: str
    slug: str = ""
    segment_id: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Segment requires a name")
        if not self.slug:
            object.__setattr__(self, "slug", slugify(self.name))


@dataclass(frozen=True, slots=True)
class SegmentFact:
    segment_id: int
    entity_id: int
    metric: str                              # 'segment_revenue' | 'segment_result' | ...
    value: Decimal | None
    basis: Basis
    currency: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    financial_year: int | None = None
    quarter: int | None = None
    is_annual: bool = False
    source_id: int | None = None

    def __post_init__(self) -> None:
        if not self.metric:
            raise ValueError("SegmentFact requires a metric name")
        object.__setattr__(self, "value", _opt_decimal(self.value))
        object.__setattr__(self, "basis", Basis(self.basis))
        if self.currency is not None:
            object.__setattr__(self, "currency", check_currency(self.currency))
        _check_quarter(self.quarter)


@dataclass(frozen=True, slots=True)
class SharePrice:
    """One trading day's close. `close is None` means not traded; never zero-filled."""

    entity_id: int
    price_date: date
    close: Decimal | None
    currency: str
    source_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "close", _opt_decimal(self.close))
        object.__setattr__(self, "currency", check_currency(self.currency))
