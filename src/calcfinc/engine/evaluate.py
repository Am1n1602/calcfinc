"""Evaluate registered formulas against one period record.

Every result carries its value, the reported facts it was computed from, notes about any
substitution made along the way, and -- when it cannot be computed -- the reason. Nothing is
ever estimated: a missing input gives value=None plus why (optional inputs, which a spec
declares explicitly, count as 0 and say so).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from calcfinc.engine.records import PeriodRecord
from calcfinc.fact import SharePrice
from calcfinc.formula import CalcError, evaluate, names_in
from calcfinc.num import ZERO, add, to_text
from calcfinc.registry.metrics import CURRENCY_KINDS
from calcfinc.registry.ratios import FORMULAS, NOT_FOR, PERIOD_DAYS, PRICE, RatioSpec


@dataclass(frozen=True, slots=True)
class FactRef:
    """One reported fact a result was computed from."""

    metric: str
    value: Decimal | None
    period: str | None
    source_id: int | None
    currency: str | None = None
    reported_at: date | None = None         # when the value used was first reported (the latest version wins)


@dataclass(frozen=True, slots=True)
class Outcome:
    value: Decimal | None
    reason: str | None = None
    notes: tuple[str, ...] = ()
    leaves: tuple[FactRef, ...] = ()
    currencies: frozenset[str] = frozenset()
    formula: str | None = None              # the formula actually used (primary or fallback)


def _fail(reason: str) -> Outcome:
    return Outcome(None, reason)


class Evaluator:
    """Evaluates names for one record. `prior` is the record one comparable period earlier
    (for prior(x)); `price` is the close at the record's period end (for share_price)."""

    def __init__(self, rec: PeriodRecord, *, prior: PeriodRecord | None = None,
                 price: SharePrice | None = None, price_reason: str | None = None,
                 window: list[PeriodRecord] | None = None, window_reason: str | None = None,
                 sector: str | None = None) -> None:
        self.rec = rec
        self.price = price
        self.sector = sector                   # ratios restricted for this sector return None
        self._price_reason = price_reason
        self._prior = Evaluator(prior, sector=sector) if prior is not None else None
        self._window = window                  # the adjacent periods making up a year, ending at `rec`
        self._window_reason = window_reason
        self._memo: dict[str, Outcome] = {}
        self._stack: list[str] = []

    def value(self, name: str) -> Outcome:
        if name not in self._memo:
            self._memo[name] = self._compute(name)
        return self._memo[name]

    # ---- sources of values ----
    def _compute(self, name: str) -> Outcome:
        if name.startswith("prior(") and name.endswith(")"):
            inner = name[len("prior("):-1]
            if self._prior is None:
                return _fail(f"{inner}: no earlier comparable period to compare with")
            return self._prior.value(inner)
        if name.startswith("ttm(") and name.endswith(")"):
            return self._ttm(name[len("ttm("):-1])
        if name == PRICE:
            if self.price is None or self.price.close is None:
                return _fail(self._price_reason or "share_price is not available")
            p = self.price
            ref = FactRef(PRICE, p.close, str(p.price_date), p.source_id, p.currency)
            return Outcome(p.close, leaves=(ref,), currencies=frozenset({p.currency}))
        if name == PERIOD_DAYS:
            r = self.rec
            if r.period_start is None or r.period_end is None:
                return _fail("period_days: this period has no start date, so its length is unknown")
            days = Decimal((r.period_end - r.period_start).days + 1)
            return Outcome(days, leaves=(FactRef(PERIOD_DAYS, days, r.label, None),))
        spec = FORMULAS.get(name)
        if spec is not None:
            return self._spec(spec)
        return self._leaf(name)

    def _ttm(self, inner: str) -> Outcome:
        """Sum `inner` over the window. Each period is evaluated on its own, so a derived flow
        such as EBITDA is summed from the periods' own EBITDA, not recomputed from sums."""
        if self._window is None:
            return _fail(f"{inner}: {self._window_reason or 'trailing twelve months is not available'}")
        total = ZERO
        leaves: list[FactRef] = []
        notes: list[str] = []
        currencies: set[str] = set()
        for r in self._window:
            out = self.value(inner) if r is self.rec else Evaluator(r, sector=self.sector).value(inner)
            if out.value is None:
                return _fail(f"{inner}: {out.reason} [{r.label}]")
            total = add(total, out.value)
            leaves.extend(out.leaves)
            notes.extend(out.notes)
            currencies |= out.currencies
        return Outcome(total, notes=tuple(dict.fromkeys(notes)), leaves=tuple(dict.fromkeys(leaves)),
                       currencies=frozenset(currencies))

    def _leaf(self, name: str) -> Outcome:
        v = self.rec.values.get(name)
        if v is None:
            return _fail(f"{name} not reported")
        cur = self.rec.currencies.get(name)
        ref = FactRef(name, v, self.rec.label, self.rec.sources.get(name), cur, self.rec.reported.get(name))
        return Outcome(v, leaves=(ref,), currencies=frozenset({cur}) if cur else frozenset())

    # ---- formulas ----
    def _spec(self, spec: RatioSpec) -> Outcome:
        if spec.name in self._stack:
            return _fail(f"{spec.name}: circular definition")
        why = NOT_FOR.get(spec.name, {}).get(self.sector or "")
        if why is not None:
            article = "an" if self.sector and self.sector[0] in "aeiou" else "a"
            return _fail(f"{spec.name} does not apply to {article} {self.sector}: {why}")
        self._stack.append(spec.name)
        try:
            first_reason: str | None = None
            for expr, note in spec.formulas:
                out = self._attempt(spec, expr)
                if out.value is not None:
                    notes = out.notes + ((note,) if note else ())
                    return self._finish(spec, replace(out, notes=notes, formula=expr))
                first_reason = first_reason or out.reason
            return _fail(first_reason or f"{spec.name} cannot be computed")
        finally:
            self._stack.pop()

    def _attempt(self, spec: RatioSpec, expr: str) -> Outcome:
        env: dict[str, Decimal] = {}
        leaves: list[FactRef] = []
        notes: list[str] = []
        currencies: set[str] = set()
        reasons: list[str] = []
        zero_filled: list[str] = []
        for n in names_in(expr):
            child = self.value(n)
            if child.value is None:
                if (n in spec.optional and n not in FORMULAS and n != PRICE
                        and not n.startswith(("prior(", "ttm("))):
                    env[n] = ZERO
                    zero_filled.append(n)
                else:
                    reasons.append(child.reason or f"{n} unavailable")
                continue
            env[n] = child.value
            leaves.extend(child.leaves)
            notes.extend(child.notes)
            currencies |= child.currencies
            if n in spec.requires_positive and child.value <= ZERO:
                reasons.append(f"{n} is not positive ({to_text(child.value)}); "
                               f"{spec.name} is not meaningful")
        if reasons:
            return _fail(f"{spec.name}: " + "; ".join(reasons))
        if zero_filled:
            notes.append(f"{', '.join(zero_filled)} not reported; treated as 0 in {spec.name}")
        try:
            value = evaluate(expr, env)
        except CalcError as e:
            return _fail(f"{spec.name}: {e} in {expr}")
        return Outcome(value, notes=tuple(dict.fromkeys(notes)),
                       leaves=tuple(dict.fromkeys(leaves)), currencies=frozenset(currencies))

    @staticmethod
    def _finish(spec: RatioSpec, out: Outcome) -> Outcome:
        if len(out.currencies) > 1:
            return _fail(f"{spec.name}: inputs are in different currencies "
                         f"({', '.join(sorted(out.currencies))}); not comparable")
        # A ratio is dimensionless: only amounts keep their currency.
        keep = out.currencies if spec.unit in CURRENCY_KINDS else frozenset()
        return replace(out, currencies=keep)
