"""Load dict rows into a repository bundle.

Every row is validated before anything is written: if any row is bad, `LoadError` lists them
all (row number and column) and the store is left untouched. An empty `value` cell is stored
as "not reported", never as 0.

Row keys (long layout). Required: `entity` (or the `entity=` argument), `metric`, `value`, and
either `period` or `period_end` (plus `period_start` for flow metrics). Optional: `currency`,
`basis`, `reported_at`, `source`, `mapping_reason`, and overrides for what is otherwise
inferred: `statement_type`, `is_point_in_time`, `financial_year`, `quarter`, `is_annual`.
`period` is a label such as FY2026, FY2026Q1, 2026-03, 2026-01-01..2026-12-31 or 2026-12-31.
"""
from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from calcfinc.entity import Entity
from calcfinc.fact import Basis, FinancialFact, Source, StatementType
from calcfinc.num import to_decimal
from calcfinc.period import (
    DEFAULT_WINDOWS,
    PeriodWindows,
    ResolvedPeriod,
    classify_range,
    fiscal_year,
    resolve_period,
)
from calcfinc.registry import metrics
from calcfinc.store.base import AmbiguousEntity

COLUMNS = frozenset({
    "entity", "metric", "value", "period", "period_start", "period_end", "currency", "basis",
    "reported_at", "source", "mapping_reason", "statement_type", "is_point_in_time",
    "financial_year", "quarter", "is_annual"})
_SHOWN = 20


class LoadError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        more = f"\n... and {len(errors) - _SHOWN} more" if len(errors) > _SHOWN else ""
        super().__init__(f"{len(errors)} problem(s) found; nothing was loaded:\n"
                         + "\n".join(errors[:_SHOWN]) + more)
        self.errors = errors


@dataclass(frozen=True, slots=True)
class LoadReport:
    facts: int
    entities: tuple[str, ...]            # every entity the rows referred to
    created: tuple[str, ...]             # the subset that did not exist yet


class _Bad(Exception):
    def __init__(self, col: str, msg: str) -> None:
        super().__init__(msg)
        self.col, self.msg = col, msg


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _date(v: Any, col: str) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _text(v)
    if s is None:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise _Bad(col, f"{s!r} is not a date; use YYYY-MM-DD") from None


def _int(v: Any, col: str) -> int | None:
    s = _text(v)
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        raise _Bad(col, f"{s!r} is not a whole number") from None


def _bool(v: Any, col: str) -> bool | None:
    if isinstance(v, bool):
        return v
    s = _text(v)
    if s is None:
        return None
    if s.lower() in ("1", "true", "yes", "y"):
        return True
    if s.lower() in ("0", "false", "no", "n"):
        return False
    raise _Bad(col, f"{s!r} is not true/false")


def _value(v: Any) -> Any:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return to_decimal(v)
    except TypeError as e:
        raise _Bad("value", str(e)) from None
    except ValueError as e:
        hint = "; write 1200.5, not 1,200.5" if isinstance(v, str) and "," in v else ""
        raise _Bad("value", f"{e}{hint}") from None


class _Ctx:
    """Resolves entities once per distinct name and remembers their calendar and currency."""

    def __init__(self, repos: Any, currency: str | None, fye: int) -> None:
        self.repos, self.currency, self.fye = repos, currency, fye
        self.seen: dict[str, tuple[Entity | None, int, str | None]] = {}

    def entity(self, name: str) -> tuple[Entity | None, int, str | None]:
        if name not in self.seen:
            try:
                ent = self.repos.entities.resolve(name)
            except AmbiguousEntity as e:
                raise _Bad("entity", str(e)) from None
            self.seen[name] = (ent, ent.fiscal_year_end_month if ent else self.fye,
                               (ent.currency if ent else None) or self.currency)
        return self.seen[name]


def load_records(repos: Any, rows: Iterable[Mapping[str, Any]], *, entity: str | None = None,
                 currency: str | None = None, basis: Basis | str = "consolidated",
                 fiscal_year_end_month: int = 12, windows: PeriodWindows = DEFAULT_WINDOWS,
                 source: Source | None = None, entity_kind: str = "company",
                 sector: str | None = None) -> LoadReport:
    ctx = _Ctx(repos, currency, fiscal_year_end_month)
    errors: list[str] = []
    pending: list[tuple[str, str | None, FinancialFact]] = []
    unknown: set[str] = set()

    for n, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            errors.append(f"row {n}: expected a mapping of column to value, got {type(row).__name__}")
            continue
        n = int(row.get("_row", n))
        bad = {k for k in row if not k.startswith("_") and k not in COLUMNS} - unknown
        for k in sorted(bad):
            errors.append(f"row {n}: unknown column {k!r}; expected one of {', '.join(sorted(COLUMNS))}")
        unknown |= bad
        try:
            pending.append(_convert(row, ctx, entity, basis, windows))
        except _Bad as e:
            errors.append(f"row {n}, {row.get('_col') or e.col}: {e.msg}")
    if errors:
        raise LoadError(errors)

    try:
        created: list[str] = []
        ids: dict[str, int] = {}
        for name, (ent, fye, cur) in ctx.seen.items():
            if ent is None:
                ent = repos.entities.upsert(Entity(name=name, kind=entity_kind, currency=cur,
                                                   fiscal_year_end_month=fye, sector=sector))
                created.append(name)
            elif sector is not None and ent.sector != sector.strip().lower():
                ent = repos.entities.upsert(replace(ent, sector=sector))     # a sector you declare is applied
            ids[name] = int(ent.id or 0)
        default_source = repos.sources.add(source).source_id if source is not None else None
        row_sources: dict[str, int | None] = {}
        facts = []
        for name, src_text, f in pending:
            if src_text is not None and src_text not in row_sources:
                row_sources[src_text] = repos.sources.add(
                    Source(kind="records", document_title=src_text)).source_id
            sid = row_sources[src_text] if src_text is not None else default_source
            facts.append(replace(f, entity_id=ids[name], source_id=sid))
        repos.facts.add_many(facts)
        repos.commit()
    except Exception:
        repos.rollback()
        raise
    return LoadReport(len(pending), tuple(ctx.seen), tuple(created))


def _convert(row: Mapping[str, Any], ctx: _Ctx, default_entity: str | None, default_basis: Basis | str,
             windows: PeriodWindows) -> tuple[str, str | None, FinancialFact]:
    name = _text(row.get("entity")) or default_entity
    if not name:
        raise _Bad("entity", "required: add an entity column or pass entity=")
    ent, fye, ent_currency = ctx.entity(name)

    metric = _text(row.get("metric"))
    if not metric:
        raise _Bad("metric", "required")
    spec = metrics.get(metric)
    st_raw = _text(row.get("statement_type"))
    try:
        st = StatementType(st_raw) if st_raw else None
    except ValueError:
        raise _Bad("statement_type", f"{st_raw!r} is not one of {[s.value for s in StatementType]}") from None
    if st is None:
        if spec is None:
            near = difflib.get_close_matches(metric, metrics.canonical_names(), n=1)
            hint = f"; did you mean {near[0]!r}?" if near else ""
            raise _Bad("metric", f"unknown metric {metric!r}{hint}; or register_metric() it, "
                                 "or add a statement_type")
        st = spec.statement_type
    instant = _bool(row.get("is_point_in_time"), "is_point_in_time")
    if instant is None:
        instant = spec.is_point_in_time if spec else st is StatementType.BALANCE_SHEET

    label = _text(row.get("period"))
    ps, pe = _date(row.get("period_start"), "period_start"), _date(row.get("period_end"), "period_end")
    if label and (ps or pe):
        raise _Bad("period", "give either period or period_start/period_end, not both")
    if label:
        try:
            rp = resolve_period(label, fye, windows)
        except ValueError as e:
            raise _Bad("period", str(e)) from None
    elif pe is None:
        raise _Bad("period", "required: give period or period_end")
    elif ps is None:
        rp = ResolvedPeriod(None, pe, fiscal_year(pe, fye), None, False)
    else:
        if pe < ps:
            raise _Bad("period_end", "is before period_start")
        rp = classify_range(ps, pe, fye, windows)
    if instant:
        rp = ResolvedPeriod(None, rp.end, rp.financial_year, None, False)
    elif rp.start is None:
        raise _Bad("period", f"{metric!r} is a flow metric and needs a period range or a period_start")

    fy = _int(row.get("financial_year"), "financial_year") or rp.financial_year
    q = _int(row.get("quarter"), "quarter") if _text(row.get("quarter")) else rp.quarter
    annual = _bool(row.get("is_annual"), "is_annual")
    cur = _text(row.get("currency")) or ctx.currency
    if spec and spec.kind in metrics.CURRENCY_KINDS and cur is None and ent_currency is None:
        raise _Bad("currency", f"{metric!r} is an amount: add a currency column, pass currency=, "
                               "or give the entity a default currency")
    reported_raw = _date(row.get("reported_at"), "reported_at")
    try:
        fact = FinancialFact(
            entity_id=0, metric=metric, value=_value(row.get("value")), statement_type=st,
            basis=Basis(_text(row.get("basis")) or default_basis), currency=cur, period_start=rp.start,
            period_end=rp.end, financial_year=fy, quarter=q,
            is_annual=rp.is_annual if annual is None else annual, is_point_in_time=instant,
            reported_at=reported_raw, mapping_reason=_text(row.get("mapping_reason")))
    except (ValueError, TypeError) as e:
        raise _Bad("row", str(e)) from None
    return name, _text(row.get("source")), fact
