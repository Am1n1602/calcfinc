"""FinancialEngine: the deterministic API over a repository bundle. No LLM, ever.

Every call returns an EngineResult. A missing input yields value=None with a `limitations`
entry saying why -- never 0, never a guess.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from calcfinc.engine import decompose, growth
from calcfinc.engine.check import ABS_TOL, REL_TOL, CheckResult, check_values, quarters_add_up
from calcfinc.engine.evaluate import Evaluator, FactRef, Outcome
from calcfinc.engine.records import PeriodRecord, build_period_records
from calcfinc.engine.segments import SegmentEngine, SegmentResult
from calcfinc.entity import Entity
from calcfinc.fact import Basis
from calcfinc.formula import CalcError, evaluate
from calcfinc.num import ZERO, Num, to_decimal, to_text
from calcfinc.period import DEFAULT_WINDOWS, PeriodWindows
from calcfinc.registry import metrics as _metrics
from calcfinc.registry import ratios
from calcfinc.registry.ratios import PERIOD_DAYS, RatioSpec
from calcfinc.store.base import PRICE_WINDOW_DAYS, AmbiguousEntity

_CURRENCY_UNITS = frozenset({"currency", "per_share"})


@dataclass(frozen=True, slots=True)
class EngineResult:
    kind: str
    name: str
    value: Decimal | None
    unit: str | None = None                 # ISO code for amounts, else 'pct' | 'x' | 'per_share' | ...
    entity: str | None = None
    basis: str | None = None
    period: str | None = None
    formula: str | None = None
    inputs: tuple[FactRef, ...] = ()
    components: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    currency: str | None = None
    definition_version: int | None = None

    @property
    def ok(self) -> bool:
        if self.value is not None:
            return True
        # compare_periods populates `components` and never sets `value` (a multi-metric
        # comparison has no single natural scalar), so look at the components instead.
        return any(isinstance(c, Mapping) and c.get("from") is not None and c.get("to") is not None
                   for c in self.components.values())

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form: Decimals become exact strings, never JSON numbers."""
        out: dict[str, Any] = _jsonable(self)
        return out


def _jsonable(x: Any) -> Any:
    if isinstance(x, Decimal):
        return to_text(x)
    if isinstance(x, date):
        return x.isoformat()
    if is_dataclass(x) and not isinstance(x, type):
        return {f.name: _jsonable(getattr(x, f.name)) for f in fields(x)}
    if isinstance(x, Mapping):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return x


class EngineError(Exception):
    pass


_KINDS = ("latest", "latest_annual", "latest_quarter", "latest_month")
_YEAR_OF = {"month": 12, "quarter": 4, "half": 2, "year": 1}     # periods that make up one year
_FY_RE = re.compile(r"FY(\d{4})(?:Q([1-4]))?", re.I)
_MONTH_RE = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")


def _parse_period(period: Any) -> tuple[Any, ...]:
    """'latest' | 'latest_annual' | 'latest_quarter' | 'latest_month' | 2026 | 'FY2026' |
    'FY2026Q1' | (2026, 1) | '2026-03'"""
    if isinstance(period, str) and period in _KINDS:
        return ("kind", period)
    if isinstance(period, int) and not isinstance(period, bool):
        return ("annual", period)
    if isinstance(period, tuple) and len(period) == 2:
        return ("quarter", int(period[0]), int(period[1]))
    if isinstance(period, str):
        m = _FY_RE.fullmatch(period.strip())
        if m:
            return ("quarter", int(m.group(1)), int(m.group(2))) if m.group(2) else ("annual", int(m.group(1)))
        m = _MONTH_RE.fullmatch(period.strip())
        if m:
            return ("month", int(m.group(1)), int(m.group(2)))
    raise EngineError(f"unrecognized period spec: {period!r}")


def _flag_limits(rec: PeriodRecord, used: Sequence[str]) -> tuple[str, ...]:
    """Review flags (a doubt about the source) and notes (how a value was derived) for the inputs used."""
    return (tuple(f"{m}: source record flagged for review ({rec.review_flags[m]})"
                  for m in used if m in rec.review_flags)
            + tuple(f"{m}: {rec.info_notes[m]}" for m in used if m in rec.info_notes))


VINTAGE_DAYS = 120       # inputs of one period first reported further apart than this were not filed together


def _vintage_note(leaves: Sequence[FactRef]) -> tuple[str, ...]:
    """Inputs for the same period that were first reported in different filings -- usually a
    restatement that touched some of them. The latest figure is used for each; they may not agree."""
    by_period: dict[str | None, list[tuple[date, str]]] = {}
    for leaf in leaves:
        if leaf.reported_at is not None:
            by_period.setdefault(leaf.period, []).append((leaf.reported_at, leaf.metric))
    notes = []
    for period, refs in by_period.items():
        (d0, m0), (d1, m1) = min(refs), max(refs)
        if (d1 - d0).days > VINTAGE_DAYS:
            notes.append(f"inputs for {period} come from different filings: {m0} reported {d0}, {m1} reported "
                         f"{d1}; a restatement may separate them (check_periods() tests whether the "
                         "quarters add up to the year)")
    return tuple(notes)


def _with_limit(res: EngineResult, msg: str) -> EngineResult:
    return EngineResult(res.kind, res.name, None, unit=res.unit, entity=res.entity, basis=res.basis,
                        limitations=res.limitations + (msg,))


def _flow_stock_note(rec: PeriodRecord, name: str, leaves: Sequence[FactRef]) -> tuple[str, ...]:
    """Flow / balance ratios over part of a year are not annualised; say so."""
    if rec.period_start is None or rec.period_type == "year" or any(leaf.metric == PERIOD_DAYS for leaf in leaves):
        return ()                          # days-based ratios are scaled by the real period length
    flows = stocks = False
    for leaf in leaves:
        m = _metrics.get(leaf.metric)
        if m is None:
            continue
        if m.is_point_in_time:
            stocks = True
        elif m.statement_type.value in ("profit_and_loss", "cash_flow"):
            flows = True
    if flows and stocks:
        return (f"{name} mixes period flows with period-end balances over a "
                f"{rec.period_type or 'partial-year'} period; the ratio is not annualised",)
    return ()


class FinancialEngine:
    """Build the engine after loading data; call `refresh()` if facts change afterwards."""

    def __init__(self, repos: Any, *, windows: PeriodWindows = DEFAULT_WINDOWS) -> None:
        self._repos = repos
        self._windows = windows
        self._cache: dict[tuple[int, str], list[PeriodRecord]] = {}
        self._inferred: dict[int, str | None] = {}         # id(records) -> sector inferred from the facts
        self._segments = SegmentEngine(repos)

    def refresh(self) -> None:
        self._cache.clear()
        self._inferred.clear()

    @property
    def repos(self) -> Any:
        """The backing repositories, e.g. to add share prices or segments after loading."""
        return self._repos

    @classmethod
    def _loaded(cls, windows: PeriodWindows, load: Callable[[Any], Any]) -> FinancialEngine:
        from calcfinc.store.sqlite import SqliteRepositories

        repos = SqliteRepositories(":memory:")
        try:
            load(repos)
        except BaseException:
            repos.close()
            raise
        return cls(repos, windows=windows)

    @classmethod
    def from_records(cls, rows: Iterable[Mapping[str, Any]], *, windows: PeriodWindows = DEFAULT_WINDOWS,
                     **options: Any) -> FinancialEngine:
        """Build an in-memory engine from dict rows. `options` are those of
        `calcfinc.loaders.load_records` (entity, currency, basis, fiscal_year_end_month...)."""
        from calcfinc.loaders import load_records

        return cls._loaded(windows, lambda r: load_records(r, rows, windows=windows, **options))

    @classmethod
    def from_csv(cls, path: str | Path, *, windows: PeriodWindows = DEFAULT_WINDOWS,
                 **options: Any) -> FinancialEngine:
        """Build an in-memory engine from a long or wide CSV file (see docs/fact-schema.md)."""
        from calcfinc.loaders import load_csv

        return cls._loaded(windows, lambda r: load_csv(r, path, windows=windows, **options))

    @classmethod
    def from_dataframe(cls, df: Any, *, layout: str = "long", float_policy: str = "refuse",
                       windows: PeriodWindows = DEFAULT_WINDOWS, **options: Any) -> FinancialEngine:
        """Build an in-memory engine from a pandas DataFrame (long or wide). Float cells are
        refused unless float_policy='repr'."""
        from calcfinc.loaders import frame_source, frame_to_rows, load_records

        rows, converted = frame_to_rows(df, layout=layout, float_policy=float_policy)
        return cls._loaded(windows, lambda r: load_records(r, rows, windows=windows,
                                                           source=frame_source(converted), **options))

    # ------------------------------------------------------------------ #
    # infrastructure
    # ------------------------------------------------------------------ #
    def _entity(self, key: str | Entity) -> Entity:
        try:
            ent = (self._repos.entities.get(key.id) if isinstance(key, Entity) and key.id is not None
                   else self._repos.entities.resolve(key if isinstance(key, str) else key.name))
        except AmbiguousEntity as e:
            raise EngineError(str(e)) from e
        if ent is None or ent.id is None:
            raise EngineError(f"unknown entity: {key!r}")
        return ent  # type: ignore[no-any-return]

    def _records(self, ent: Entity, basis: Basis | str) -> list[PeriodRecord]:
        key = (int(ent.id or 0), Basis(basis).value)
        if key not in self._cache:
            self._cache[key] = build_period_records(
                self._repos, key[0], key[1], windows=self._windows,
                fiscal_year_end_month=ent.fiscal_year_end_month)
        return self._cache[key]

    @staticmethod
    def _select(records: list[PeriodRecord], period: Any,
                predicate: Callable[[PeriodRecord], bool]) -> PeriodRecord | None:
        spec = _parse_period(period)
        candidates = [r for r in records if predicate(r)]
        if not candidates:
            return None
        if spec[0] == "kind":
            # a date that only carries a balance (an SEC cover-page share count) is not a reporting period
            candidates = [r for r in candidates if not r.is_point_in_time_only] or candidates
            if spec[1] == "latest_annual":
                candidates = [r for r in candidates if r.is_annual]
            elif spec[1] == "latest_quarter":
                candidates = [r for r in candidates if r.is_single_quarter]
            elif spec[1] == "latest_month":
                candidates = [r for r in candidates if r.period_type == "month"]
            return candidates[-1] if candidates else None
        for r in reversed(candidates):
            if spec[0] == "annual" and r.financial_year == spec[1] and r.is_annual:
                return r
            if spec[0] == "quarter" and r.financial_year == spec[1] and r.quarter == spec[2]:
                return r
            if (spec[0] == "month" and r.period_type == "month" and r.period_end is not None
                    and (r.period_end.year, r.period_end.month) == (spec[1], spec[2])):
                return r
        return None

    def _prior(self, records: list[PeriodRecord], rec: PeriodRecord) -> PeriodRecord | None:
        """The record one comparable period earlier: same period type, and adjacent -- a gap
        is not a prior period, so prior(x) is then unavailable rather than wrong."""
        if rec.period_type is None or rec.period_end is None:
            return None
        lo, hi = getattr(self._windows, rec.period_type)
        for r in reversed(records[:records.index(rec)]):
            if r.period_type == rec.period_type and r.is_annual == rec.is_annual and r.period_end:
                return r if lo <= (rec.period_end - r.period_end).days <= hi else None
        return None

    def _window(self, records: list[PeriodRecord], rec: PeriodRecord) -> tuple[list[PeriodRecord] | None, str]:
        """The adjacent periods of the same kind that make up one year and end at `rec`
        (4 quarters, 12 months, 2 half-years, or the year itself). A gap means no window."""
        n = _YEAR_OF.get(rec.period_type or "")
        if n is None or rec.period_end is None:
            return None, ("trailing twelve months needs a month, quarter, half-year or year period, "
                          f"but {rec.label} is none of these")
        lo, hi = getattr(self._windows, rec.period_type or "year")
        chain = [rec]
        for r in reversed(records[:records.index(rec)]):
            if len(chain) == n:
                break
            if r.period_type == rec.period_type and r.is_annual == rec.is_annual and r.period_end:
                if not lo <= (chain[0].period_end - r.period_end).days <= hi:  # type: ignore[operator]
                    break
                chain.insert(0, r)
        if len(chain) < n:
            return None, (f"trailing twelve months needs {n} adjacent {rec.period_type} periods ending at "
                          f"{rec.label}, found {len(chain)}")
        return chain, ""

    def _evaluator(self, ent: Entity, records: list[PeriodRecord], rec: PeriodRecord,
                   *, with_price: bool = False) -> Evaluator:
        price = reason = None
        if with_price:
            if rec.period_end is None:
                reason = f"period {rec.label} has no end date to price against"
            else:
                price = self._repos.prices.on_or_before(ent.id, rec.period_end)
                if price is None or price.close is None:
                    price = None
                    reason = (f"no share price within {PRICE_WINDOW_DAYS} days of {rec.period_end} "
                              f"for {ent.name}")
        window, window_reason = self._window(records, rec)
        return Evaluator(rec, prior=self._prior(records, rec), price=price, price_reason=reason,
                         window=window, window_reason=window_reason, sector=self._sector(ent, records))

    def _sector(self, ent: Entity, records: list[PeriodRecord]) -> str | None:
        """The declared sector, else 'bank' when the entity reports interest earned and expended
        (the defining lines of a bank's income statement) and deposits or loans."""
        if ent.sector is not None:
            return ent.sector
        if id(records) not in self._inferred:
            has = {m for r in records for m in r.values}
            self._inferred[id(records)] = (
                "bank" if {"bank.interest_earned", "bank.interest_expended"} <= has
                and has & {"bank.deposits", "bank.advances", "bank.gross_advances"} else None)
        return self._inferred[id(records)]

    def _formula_result(self, kind: str, ent: Entity, spec: RatioSpec, basis: Basis | str,
                        period: Any, fallback: bool = False) -> EngineResult:
        records = self._records(ent, basis)
        price_dep = ratios.needs_price(spec.name)
        ttm = ratios.uses_ttm(spec.name)
        if price_dep and not ttm and period == "latest":
            period = "latest_annual"          # valuation is priced at fiscal year ends, unless it uses TTM
        label = "valuation" if price_dep else kind
        cache: dict[int, tuple[Evaluator, Outcome]] = {}

        def run(r: PeriodRecord) -> tuple[Evaluator, Outcome]:
            if id(r) not in cache:
                ev = self._evaluator(ent, records, r, with_price=price_dep)
                cache[id(r)] = (ev, ev.value(spec.name))
            return cache[id(r)]

        base = (lambda r: r.is_annual) if price_dep and not ttm else (lambda r: True)
        # The period asked for is the one answered; an older period is used only on request.
        rec = self._select(records, period, base)
        stale = ""
        if rec is not None and run(rec)[1].value is None and fallback and _parse_period(period)[0] == "kind":
            newest = rec
            rec = self._select(records, period, lambda r: base(r) and run(r)[1].value is not None)
            if rec is not None:
                stale = (f"{spec.name} could not be computed for {newest.label} ({run(newest)[1].reason}); "
                         f"this is the newest period where it can: {rec.label}")
        if rec is None or run(rec)[1].value is None:
            why = (f"no {'annual ' if price_dep and not ttm else ''}period for {ent.name} ({basis}, period={period})"
                   if rec is None else f"{run(rec)[1].reason} [{rec.label}]")
            return EngineResult(label, spec.name, None, unit=spec.unit, entity=ent.name,
                                basis=Basis(basis).value, formula=spec.formula,
                                definition_version=spec.version, limitations=(why,))
        ev, out = run(rec)
        assert out.value is not None
        cur = next(iter(out.currencies), None) if spec.unit in _CURRENCY_UNITS else None
        used = [leaf.metric for leaf in out.leaves]
        comps: dict[str, Any] = {}
        if price_dep and ev.price is not None:
            comps = {"share_price": ev.price.close, "price_date": ev.price.price_date.isoformat()}
        return EngineResult(
            label, spec.name, out.value, unit=cur if (spec.unit == "currency" and cur) else spec.unit,
            entity=ent.name, basis=rec.basis, period=rec.label, formula=out.formula or spec.formula,
            inputs=out.leaves, components=comps, currency=cur, definition_version=spec.version,
            limitations=((stale,) if stale else ()) + out.notes
            + (() if ttm else _flow_stock_note(rec, spec.name, out.leaves)) + _flag_limits(rec, used)
            + _vintage_note(out.leaves))

    def _value_in(self, ent: Entity, records: list[PeriodRecord], rec: PeriodRecord,
                  name: str) -> Decimal | None:
        spec = ratios.get_spec(name)
        if spec is None:
            v = rec.get(name.strip())
            return v if isinstance(v, Decimal) else None
        ev = self._evaluator(ent, records, rec, with_price=ratios.needs_price(spec.name))
        return ev.value(spec.name).value

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    def get_metric(self, entity: str | Entity, metric: str, *, basis: Basis | str = "consolidated",
                   period: Any = "latest", fallback: bool = False) -> EngineResult:
        """A reported metric, or a derived quantity. For a derived one, 'latest*' means the newest
        period of that kind; with `fallback=True` it is the newest where the inputs exist (the
        result says which). A reported metric is the latest period that reports it."""
        ent = self._entity(entity)
        name = metric.strip()
        spec = ratios.get_spec(name)
        if spec is not None:
            return self._formula_result("metric", ent, spec, basis, period, fallback)
        records = self._records(ent, basis)
        rec = self._select(records, period, lambda r: r.get(name) is not None)
        if rec is None:
            return EngineResult("metric", name, None, entity=ent.name, basis=Basis(basis).value,
                                limitations=(f"{name!r} not reported for {ent.name} ({basis}, period={period})",))
        value = rec.get(name)
        reg = _metrics.get(name)
        cur = rec.currencies.get(name)
        unit = cur if (reg is None or reg.kind == "currency") and cur else (reg.kind if reg else None)
        return EngineResult(
            "metric", name, value, unit=unit, entity=ent.name, basis=rec.basis, period=rec.label,
            inputs=(FactRef(name, value, rec.label, rec.sources.get(name), cur, rec.reported.get(name)),),
            currency=cur,
            limitations=_flag_limits(rec, [name]))

    def get_ratio(self, entity: str | Entity, ratio: str, *, basis: Basis | str = "consolidated",
                  period: Any = "latest", fallback: bool = False) -> EngineResult:
        """One ratio. 'latest*' is the newest period of that kind: if its inputs are missing the
        result is None with the reason. `fallback=True` uses the newest period where it can be
        computed instead, and says so in `limitations`."""
        ent = self._entity(entity)
        spec = ratios.get_spec(ratio)
        if spec is None:
            return EngineResult("ratio", ratio, None, entity=ent.name, basis=Basis(basis).value,
                                limitations=(f"unknown ratio {ratio!r}; known: {', '.join(ratios.known())}",))
        return self._formula_result("ratio", ent, spec, basis, period, fallback)

    def get_valuation(self, entity: str | Entity, kind: str, *, basis: Basis | str = "consolidated",
                      period: Any = "latest_annual", fallback: bool = False) -> EngineResult:
        """P/E, P/B, EV/EBITDA, market cap, yields... anything priced at the fiscal year end."""
        ent = self._entity(entity)
        spec = ratios.get_spec(kind)
        if spec is None or not ratios.needs_price(spec.name):
            return EngineResult("valuation", kind, None, entity=ent.name, basis=Basis(basis).value,
                                limitations=(f"unknown valuation metric {kind!r}; known: "
                                             f"{', '.join(ratios.valuation_names())}",))
        return self._formula_result("valuation", ent, spec, basis, period, fallback)

    def _series(self, ent: Entity, records: list[PeriodRecord], metric: str,
                *, only: str) -> list[tuple[PeriodRecord, Decimal]]:
        out = []
        for r in records:
            if only == "annual" and not r.is_annual:
                continue
            if only == "quarter" and not r.is_single_quarter:
                continue
            if only == "month" and r.period_type != "month":
                continue
            v = self._value_in(ent, records, r, metric)
            if v is not None:
                out.append((r, v))
        return out

    def get_growth(self, entity: str | Entity, metric: str, *, kind: str = "yoy",
                   basis: Basis | str = "consolidated") -> EngineResult:
        """% change between comparable periods: kind 'yoy' | 'qoq' | 'mom'. `metric` may be a
        reported metric, a derived quantity or a ratio."""
        ent = self._entity(entity)
        records = self._records(ent, basis)
        metric = metric.strip()
        base = EngineResult("growth", f"{metric}_{kind}", None, unit="pct", entity=ent.name,
                            basis=Basis(basis).value)
        if kind in ("qoq", "mom"):
            unit_kind = "quarter" if kind == "qoq" else "month"
            series = self._series(ent, records, metric, only=unit_kind)
            if len(series) < 2:
                return _with_limit(base, f"need >=2 {unit_kind}ly periods with {metric}")
            (rp, vp), (rc, vc) = series[-2], series[-1]
        elif kind == "yoy":
            annual = self._series(ent, records, metric, only="annual")
            if len(annual) >= 2:
                (rp, vp), (rc, vc) = annual[-2], annual[-1]
            else:
                q = self._series(ent, records, metric, only="quarter")
                m = [] if q else self._series(ent, records, metric, only="month")
                latest = q or m
                if not latest:
                    return _with_limit(base, f"no periods with {metric}")
                rc, vc = latest[-1]
                match = [(r, v) for r, v in latest
                         if (q and r.quarter == rc.quarter and r.financial_year == (rc.financial_year or 0) - 1)
                         or (m and r.period_end and rc.period_end and r.period_end.month == rc.period_end.month
                             and r.period_end.year == rc.period_end.year - 1)]
                if not match:
                    return _with_limit(base, f"need two comparable annual periods, or {metric} "
                                             "for the same period of the prior year")
                rp, vp = match[-1]
        else:
            return _with_limit(base, f"unknown growth kind {kind!r} (use 'yoy', 'qoq' or 'mom')")

        return EngineResult(
            "growth", f"{metric}_{kind}", growth.pct_change(vp, vc), unit="pct", entity=ent.name,
            basis=Basis(basis).value, period=f"{rp.label} -> {rc.label}",
            formula="100 * (curr - prev) / prev",
            inputs=(FactRef(metric, vp, rp.label, None), FactRef(metric, vc, rc.label, None)),
            components={"abs_change": growth.abs_change(vp, vc), "from": rp.label, "to": rc.label,
                        "from_value": vp, "to_value": vc},
            limitations=() if vp > ZERO else ("prior value <= 0; % change not meaningful, "
                                              "see components.abs_change",))

    def get_cagr(self, entity: str | Entity, metric: str, *, basis: Basis | str = "consolidated",
                 years: Num | None = None) -> EngineResult:
        ent = self._entity(entity)
        records = self._records(ent, basis)
        metric = metric.strip()
        annual = self._series(ent, records, metric, only="annual")
        base = EngineResult("cagr", f"{metric}_cagr", None, unit="pct", entity=ent.name,
                            basis=Basis(basis).value)
        if len(annual) < 2:
            return _with_limit(base, f"need >=2 annual periods with {metric}")
        (rp, vp), (rc, vc) = annual[0], annual[-1]
        if years is not None:
            span = to_decimal(years)
        elif rc.financial_year and rp.financial_year:
            span = Decimal(rc.financial_year - rp.financial_year)
        else:
            span = Decimal(len(annual) - 1)
        return EngineResult(
            "cagr", f"{metric}_cagr", growth.cagr(vp, vc, span), unit="pct", entity=ent.name,
            basis=Basis(basis).value, period=f"{rp.label} -> {rc.label}",
            formula="((end / start) ** (1 / years) - 1) * 100",
            inputs=(FactRef(metric, vp, rp.label, None), FactRef(metric, vc, rc.label, None)),
            components={"years": span, "start_value": vp, "end_value": vc},
            limitations=() if vp > ZERO else ("start value <= 0; CAGR undefined",))

    def compare_periods(self, entity: str | Entity, metrics: str | Sequence[str], *,
                        basis: Basis | str = "consolidated", a: Any, b: Any) -> EngineResult:
        ent = self._entity(entity)
        records = self._records(ent, basis)
        ra = self._select(records, a, lambda r: True)
        rb = self._select(records, b, lambda r: True)
        if ra is None or rb is None:
            return EngineResult("comparison", "compare_periods", None, entity=ent.name,
                                basis=Basis(basis).value,
                                limitations=(f"could not resolve period(s): a={a!r} b={b!r}",))
        comp = {}
        for m in ([metrics] if isinstance(metrics, str) else list(metrics)):
            va = self._value_in(ent, records, ra, m)
            vb = self._value_in(ent, records, rb, m)
            comp[m] = {"from": va, "to": vb, "abs_change": growth.abs_change(va, vb),
                       "pct_change": growth.pct_change(va, vb)}
        return EngineResult("comparison", "compare_periods", None, entity=ent.name,
                            basis=Basis(basis).value, period=f"{ra.label} -> {rb.label}", components=comp)

    def compare_companies(self, metric: str, entities: Sequence[str | Entity], *,
                          basis: Basis | str = "consolidated", period: Any = "latest") -> dict[str, Any]:
        """Rank entities on one metric. Amounts in different currencies are listed but never
        ranked: comparing 100 USD with 100 EUR is meaningless. Ratios compare freely."""
        spec = ratios.get_spec(metric)
        is_ratio = spec is not None
        reg = _metrics.get(metric.strip())
        absolute = (spec.unit in _CURRENCY_UNITS) if spec else bool(reg and reg.kind in _metrics.CURRENCY_KINDS)
        results: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        unit = None
        for t in entities:
            try:
                r = (self.get_ratio(t, metric, basis=basis, period=period) if is_ratio
                     else self.get_metric(t, metric, basis=basis, period=period))
            except EngineError as e:
                missing.append({"entity": str(t.name if isinstance(t, Entity) else t), "reason": str(e)})
                continue
            unit = r.unit or unit
            if r.value is None:
                missing.append({"entity": r.entity, "reason": r.limitations[0] if r.limitations else "no data"})
            else:
                results.append({"entity": r.entity, "value": r.value, "currency": r.currency, "period": r.period})
        limitations: list[str] = []
        currencies = {row["currency"] for row in results if row["currency"]}
        if absolute and len(currencies) > 1:
            limitations.append(f"amounts are in different currencies ({', '.join(sorted(currencies))}); "
                               "listed but not ranked -- compare a ratio, or convert first")
            unit = None
        else:
            results.sort(key=lambda x: x["value"], reverse=True)
            for i, row in enumerate(results, 1):
                row["rank"] = i
        return {"metric": metric, "kind": "ratio" if is_ratio else "metric", "unit": unit,
                "basis": Basis(basis).value, "period": period, "results": results,
                "missing": missing, "limitations": limitations}

    def decompose_metric(self, entity: str | Entity, metric: str, *, basis: Basis | str = "consolidated",
                         period: Any = "latest") -> EngineResult:
        ent = self._entity(entity)
        records = self._records(ent, basis)
        key = metric.strip().lower()
        b = Basis(basis).value
        if key in ("roe", "dupont", "dupont5", "dupont_5"):
            five = key in ("dupont5", "dupont_5")
            need = (("net_profit", "pbt", "top_line", "total_assets", "total_equity") if five
                    else ("net_profit_margin", "asset_turnover", "equity_multiplier", "roe"))
            name = "dupont_roe_5" if five else "dupont_roe"

            def ok(r: PeriodRecord) -> bool:
                ev = self._evaluator(ent, records, r)
                return all(ev.value(n).value is not None for n in need)

            rec = self._select(records, period, ok)
            if rec is None:
                return EngineResult("decomposition", name, None, entity=ent.name, basis=b,
                                    limitations=(f"DuPont needs {', '.join(need)} in one period "
                                                 f"({ent.name}, {basis}, {period})",))
            ev = self._evaluator(ent, records, rec)
            d = (decompose.dupont_roe_5 if five else decompose.dupont_roe)(ev)
            return EngineResult(
                "decomposition", name, d["actual_roe_pct"], unit="pct", entity=ent.name, basis=rec.basis,
                period=rec.label, components=d,
                formula=("tax_burden x interest_burden x ebit_margin x asset_turnover x equity_multiplier"
                         if five else "net_profit_margin x asset_turnover x equity_multiplier"),
                limitations=tuple(d.get("notes", ()))
                + _flag_limits(rec, ["net_profit", "total_assets", "total_equity"]))
        if key in ("net_margin", "net_profit_margin", "margin"):
            def usable(r: PeriodRecord) -> bool:
                return (r.has_all("total_expenses", "net_profit")
                        and self._evaluator(ent, records, r).value("top_line").value is not None)

            annual = [r for r in records if r.is_annual and usable(r)]
            qtr = [r for r in records if r.is_single_quarter and usable(r)]
            seq = annual if len(annual) >= 2 else qtr
            if len(seq) < 2:
                return EngineResult("decomposition", "net_margin_bridge", None, entity=ent.name, basis=b,
                                    limitations=("need two comparable periods with top line, "
                                                 "total_expenses and net_profit",))
            d = decompose.net_margin_bridge(self._evaluator(ent, records, seq[-2]),
                                            self._evaluator(ent, records, seq[-1]))
            return EngineResult("decomposition", "net_margin_bridge", d.get("net_margin_change_pp"),
                                unit="pp", entity=ent.name, basis=b,
                                period=f"{seq[-2].label} -> {seq[-1].label}", components=d)
        return EngineResult("decomposition", key, None, entity=ent.name, basis=b,
                            limitations=(f"no decomposition for {metric!r}; try 'roe', 'dupont5' or "
                                         "'net_margin'",))

    def calculate(self, expr: str, **vars: Any) -> EngineResult:
        try:
            v = evaluate(expr, vars)
        except CalcError as e:
            return EngineResult("calculation", "calculate", None, formula=expr, limitations=(str(e),))
        return EngineResult("calculation", "calculate", v, formula=expr, components=dict(vars))

    def check(self, entity: str | Entity, *, basis: Basis | str = "consolidated", period: Any = None,
              abs_tol: Num = ABS_TOL, rel_tol: Num = REL_TOL) -> list[CheckResult]:
        """Accounting-identity checks (assets = liabilities + equity, ...) per period. With no
        `period`, every period is checked. A failure is reported, never corrected."""
        ent = self._entity(entity)
        records = self._records(ent, basis)
        if period is not None:
            one = self._select(records, period, lambda r: True)
            records = [one] if one is not None else []
        a, r_ = to_decimal(abs_tol), to_decimal(rel_tol)
        return [CheckResult(ent.name, rec.basis, rec.label, check_values(rec.values, a, r_))
                for rec in records]

    def check_periods(self, entity: str | Entity, *, basis: Basis | str = "consolidated",
                      abs_tol: Num = ABS_TOL, rel_tol: Num = REL_TOL) -> list[CheckResult]:
        """For each year that has four single quarters: do the quarters add up to the year, for
        every amount (not per-share figure) that the year and all four quarters report? A mismatch
        usually means the year and the quarters come from different restatement vintages."""
        ent = self._entity(entity)
        records = self._records(ent, basis)
        a, r_ = to_decimal(abs_tol), to_decimal(rel_tol)
        out = []
        for year in (r for r in records if r.is_annual and r.period_start and r.period_end):
            qs = [q for q in records if q.is_single_quarter and q.period_start and q.period_end
                  and year.period_start <= q.period_start and q.period_end <= year.period_end]  # type: ignore[operator]
            names = [n for n in year.values if (m := _metrics.get(n)) and m.kind == "currency"
                     and not m.is_point_in_time]
            checks = quarters_add_up(year.values, [q.values for q in qs], names, a, r_) if len(qs) == 4 else {}
            out.append(CheckResult(ent.name, year.basis, year.label, checks))
        return out

    def get_segment_data(self, entity: str | Entity, *, basis: Basis | str = "consolidated",
                         period: Any = "latest_annual") -> SegmentResult:
        """Per-segment revenue and contribution % for one period."""
        return self._segments.get_segment_data(entity, basis=basis, period=period)

    def segment_growth(self, entity: str | Entity, *, basis: Basis | str = "consolidated",
                       kind: str = "yoy") -> SegmentResult:
        """Per-segment revenue change, growth %, and each segment's share of the total change."""
        return self._segments.segment_growth(entity, basis=basis, kind=kind)

    # ------------------------------------------------------------------ #
    # introspection
    # ------------------------------------------------------------------ #
    def periods(self, entity: str | Entity, *, basis: Basis | str = "consolidated") -> list[str]:
        return [r.label for r in self._records(self._entity(entity), basis)]

    def available_metrics(self, entity: str | Entity, *, basis: Basis | str = "consolidated") -> list[str]:
        seen: set[str] = set()
        for r in self._records(self._entity(entity), basis):
            seen.update(r.values)
        return sorted(seen)
