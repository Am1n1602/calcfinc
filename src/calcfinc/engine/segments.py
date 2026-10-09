"""Segment revenue intelligence: per-segment revenue, contribution %, growth, and each
segment's share of the total change. Segment margin is not computed: it is reported as a
limitation rather than approximated."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from calcfinc.engine.growth import abs_change, pct_change
from calcfinc.entity import Entity
from calcfinc.fact import Basis, SegmentFact
from calcfinc.num import HUNDRED, ZERO, div, dsum, mul
from calcfinc.period import DEFAULT_WINDOWS
from calcfinc.store.base import AmbiguousEntity


@dataclass(frozen=True, slots=True)
class SegmentRow:
    segment: str
    revenue: Decimal | None
    contribution_pct: Decimal | None
    period: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentGrowthRow:
    segment: str
    from_revenue: Decimal | None
    to_revenue: Decimal | None
    abs_change: Decimal | None
    growth_pct: Decimal | None
    share_of_total_change_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class SegmentResult:
    kind: str
    entity: str
    basis: str
    period: str | None
    rows: tuple[Any, ...]
    currency: str | None = None
    total_revenue: Decimal | None = None
    total_change: Decimal | None = None
    limitations: tuple[str, ...] = ()
    components: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.rows)


def _label(f: SegmentFact) -> str:
    fy = f"FY{f.financial_year}" if f.financial_year else "FY?"
    if f.quarter:
        return f"{fy} Q{f.quarter}"
    return fy if f.is_annual else (f"{f.period_start}..{f.period_end}" if f.period_start else fy)


def _period_matches(f: SegmentFact, spec: Any) -> bool:
    if isinstance(spec, str) and spec in ("latest", "latest_annual"):
        return f.is_annual
    if isinstance(spec, str) and spec == "latest_quarter":
        return f.quarter is not None
    if isinstance(spec, int):
        return f.is_annual and f.financial_year == spec
    if isinstance(spec, tuple) and len(spec) == 2:
        return bool(f.financial_year == spec[0] and f.quarter == spec[1])
    if isinstance(spec, str):
        m = re.fullmatch(r"FY(\d{4})(?:Q([1-4]))?", spec.strip(), re.I)
        if m and m.group(2):
            return f.financial_year == int(m.group(1)) and f.quarter == int(m.group(2))
        if m:
            return f.is_annual and f.financial_year == int(m.group(1))
    return False


def _currency(facts: list[SegmentFact]) -> tuple[str | None, tuple[str, ...]]:
    codes = {f.currency for f in facts if f.currency}
    if len(codes) > 1:
        return None, (f"segments are reported in different currencies ({', '.join(sorted(codes))}); "
                      "totals are not meaningful",)
    return (next(iter(codes)) if codes else None), ()


class SegmentEngine:
    def __init__(self, repos: Any) -> None:
        self._repos = repos

    def _resolve(self, entity: str | Entity) -> tuple[Entity | None, str | None]:
        """(entity, None) or (None, why-not); lookup problems become limitations, not errors."""
        try:
            if isinstance(entity, Entity):
                ent = self._repos.entities.get(entity.id) if entity.id is not None else None
            else:
                ent = self._repos.entities.resolve(entity)
        except AmbiguousEntity as e:
            return None, str(e)
        return (ent, None) if ent is not None else (None, f"unknown entity {entity!r}")

    def _revenue_facts(self, entity_id: int, basis: Basis | str) -> list[SegmentFact]:
        facts: list[SegmentFact] = self._repos.segments.list_segment_facts(
            entity_id, metric="segment_revenue", basis=Basis(basis))
        return facts

    def get_segment_data(self, entity: Any, *, basis: Basis | str = "consolidated",
                         period: Any = "latest_annual") -> SegmentResult:
        ent, why = self._resolve(entity)
        if ent is None:
            return SegmentResult("segment_data", str(entity), Basis(basis).value, None, (),
                                 limitations=(why or "unknown entity",))
        assert ent.id is not None
        cand = [f for f in self._revenue_facts(ent.id, basis) if _period_matches(f, period)]
        ends = [f.period_end for f in cand if f.period_end is not None]
        facts = [f for f in cand if f.period_end == max(ends)] if ends else []
        if not facts:
            return SegmentResult(
                "segment_data", ent.name, Basis(basis).value, None, (),
                limitations=(f"no reportable-segment revenue for {ent.name} ({basis}, period={period})"
                             " -- single-segment or not disclosed",))
        currency, cur_notes = _currency(facts)
        seg_name = {s.segment_id: s.name for s in self._repos.segments.segments_for(ent.id)}
        total = dsum(f.value for f in facts if f.value is not None) or None
        rows = tuple(
            SegmentRow(
                segment=seg_name.get(f.segment_id, str(f.segment_id)), revenue=f.value,
                contribution_pct=div(mul(HUNDRED, f.value), total) if (total and f.value is not None) else None,
                period=_label(f))
            for f in sorted(facts, key=lambda x: (x.value is None, -(x.value or ZERO))))
        return SegmentResult(
            "segment_data", ent.name, Basis(basis).value, _label(facts[0]), rows, currency=currency,
            total_revenue=None if cur_notes else total,
            limitations=("segment margin not available: filings report segment revenue only",) + cur_notes)

    def segment_growth(self, entity: Any, *, basis: Basis | str = "consolidated",
                       kind: str = "yoy") -> SegmentResult:
        ent, why = self._resolve(entity)
        if ent is None:
            return SegmentResult("segment_growth", str(entity), Basis(basis).value, None, (),
                                 limitations=(why or "unknown entity",))
        assert ent.id is not None
        if kind not in ("yoy", "qoq"):
            return SegmentResult("segment_growth", ent.name, Basis(basis).value, None, (),
                                 limitations=(f"unknown growth kind {kind!r} (use 'yoy' or 'qoq')",))
        facts = self._revenue_facts(ent.id, basis)
        only_annual = [f for f in facts if f.is_annual]
        only_qtr = [f for f in facts if f.quarter is not None]
        series = only_annual if kind == "yoy" else only_qtr

        ends = sorted({f.period_end for f in series if f.period_end})
        if len(ends) < 2:
            return SegmentResult("segment_growth", ent.name, Basis(basis).value, None, (),
                                 limitations=(f"need two comparable periods of segment revenue for {ent.name}",))
        prev_end, curr_end = ends[-2], ends[-1]
        lo, hi = DEFAULT_WINDOWS.year if series is only_annual else DEFAULT_WINDOWS.quarter
        if not lo <= (curr_end - prev_end).days <= hi:
            return SegmentResult("segment_growth", ent.name, Basis(basis).value, None, (),
                                 limitations=(f"{prev_end} and {curr_end} are not consecutive periods, so no "
                                              "segment growth is given",))
        used = [f for f in series if f.period_end in (prev_end, curr_end)]
        currency, cur_notes = _currency(used)
        if cur_notes:
            return SegmentResult("segment_growth", ent.name, Basis(basis).value, None, (),
                                 limitations=cur_notes)
        seg_name = {s.segment_id: s.name for s in self._repos.segments.segments_for(ent.id)}
        prev = {f.segment_id: f.value for f in series if f.period_end == prev_end}
        curr = {f.segment_id: f.value for f in series if f.period_end == curr_end}

        total_prev = dsum(v for v in prev.values() if v is not None) or None
        total_curr = dsum(v for v in curr.values() if v is not None) or None
        total_delta = abs_change(total_prev, total_curr)

        rows = []
        for sid in sorted(set(prev) | set(curr)):
            vp, vc = prev.get(sid), curr.get(sid)
            delta = abs_change(vp, vc)
            rows.append(SegmentGrowthRow(
                segment=seg_name.get(sid, str(sid)), from_revenue=vp, to_revenue=vc,
                abs_change=delta, growth_pct=pct_change(vp, vc),
                share_of_total_change_pct=(div(mul(HUNDRED, delta), total_delta)
                                           if (total_delta and delta is not None) else None)))
        rows.sort(key=lambda r: (r.abs_change is None, -(r.abs_change or ZERO)))
        return SegmentResult(
            "segment_growth", ent.name, Basis(basis).value, f"{prev_end} -> {curr_end}", tuple(rows),
            currency=currency, total_change=total_delta,
            components={"total_from": total_prev, "total_to": total_curr})
