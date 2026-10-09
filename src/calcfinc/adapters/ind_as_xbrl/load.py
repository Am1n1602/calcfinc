"""Canonical records -> facts in a store.

Ind-AS reporting: an April-March fiscal year and INR by default. Values are exact Decimals; a
record whose own arithmetic does not add up (assets vs liabilities + equity, income vs
expenses...) still loads, but every fact from it carries a review reason so it can be routed
to a person.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from calcfinc.adapters.ind_as_xbrl.canonical import consistency_issues, drop_placeholder_zeros, map_facts
from calcfinc.adapters.ind_as_xbrl.tags import META_KEYS, NAME_MAP
from calcfinc.adapters.ind_as_xbrl.vocab import register
from calcfinc.adapters.ind_as_xbrl.xbrl import parse_xbrl_file
from calcfinc.engine.check import check_values
from calcfinc.entity import Entity
from calcfinc.fact import Basis, FinancialFact, MappingConfidence, Source
from calcfinc.num import div
from calcfinc.period import DEFAULT_WINDOWS, PeriodWindows, ResolvedPeriod, classify_range, fiscal_year
from calcfinc.registry import metrics

_FILENAME = re.compile(r"^(?P<symbol>.+)_(?P<basis>consolidated|standalone)_(?P<period>.+)_canonical\.json$")
_XBRL_BASIS = re.compile(r"consolidated|standalone", re.I)


@dataclass(frozen=True, slots=True)
class IndAsReport:
    entity: str
    records: int
    facts: int
    needs_review: tuple[str, ...] = ()            # period labels of records whose arithmetic failed
    skipped: tuple[str, ...] = ()                 # facts that could not be placed in a period
    consistency: tuple[dict[str, Any], ...] = field(default=())   # contexts that disagree on a balance
    conflicts: tuple[str, ...] = ()               # figures two contexts reported differently; one was used


_ORDER = {"One": 0, "Two": 1, "Three": 2, "Four": 3, "Five": 4, "Six": 5}
_CONTEXT_START = re.compile(r"(One|Two|Three|Four|Five|Six)")


def _rank(context_id: Any, fact: FinancialFact) -> tuple[int, str]:
    """How much to trust the context a fact came from: OneD / OneI describe the current period,
    TwoD... earlier ones, PY_ the prior year. A balance comes from the instant half of a merged
    id ('FourD+OneI'), a flow or a derived figure from the duration half."""
    parts = str(context_id or "").split("+")
    from_instant = fact.is_point_in_time and fact.mapping_confidence is MappingConfidence.EXACT
    part = parts[-1] if from_instant else parts[0]
    m = _CONTEXT_START.match(part)
    return (_ORDER[m.group(1)] if m else 9 if part.startswith("PY_") else 8), part


def _resolve_conflicts(items: list[tuple[int, str, FinancialFact]]) -> tuple[list[FinancialFact], list[str]]:
    """Two contexts of one filing can claim the same figure for the same period with different
    values (a cumulative context given the quarter's dates, a stale prior-year capital). The most
    current context wins, the winner is flagged, and the disagreement is reported; the store
    never gets to pick silently by load order."""
    groups: dict[tuple[Any, ...], list[tuple[int, str, FinancialFact]]] = {}
    for item in items:
        f = item[2]
        groups.setdefault((f.metric, f.basis, f.period_start, f.period_end), []).append(item)
    kept: list[FinancialFact] = []
    notes: list[str] = []
    for candidates in groups.values():
        if len({c[2].value for c in candidates}) == 1:
            kept.append(candidates[0][2])
            continue
        candidates.sort(key=lambda c: c[0])
        _, winner_ctx, winner = candidates[0]
        others = "; ".join(f"{ctx} reports {f.value}" for _, ctx, f in candidates[1:] if f.value != winner.value)
        why = f"contexts disagree on this figure ({others}); {winner_ctx} used"
        kept.append(replace(winner, mapping_reason=f"{winner.mapping_reason}; {why}" if winner.mapping_reason else why))
        notes.append(f"{winner.metric} {winner.period_end}: {winner_ctx} = {winner.value} used; {others}")
    return kept, notes


def _date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10]) if v else None


def record_to_facts(record: Mapping[str, Any], *, entity_id: int, basis: Basis | str = "consolidated",
                    currency: str = "INR", fiscal_year_end_month: int = 3,
                    windows: PeriodWindows = DEFAULT_WINDOWS, source_id: int | None = None,
                    reported_at: date | None = None,
                    placeholder_zeros: bool = True) -> tuple[list[FinancialFact], list[str]]:
    """Facts for one canonical record, and notes for any value that could not be placed or that
    was dropped. With `placeholder_zeros` (the default), figures the filing reports as an exact 0
    to mean 'not applicable' are treated as not reported (see `canonical.drop_placeholder_zeros`)."""
    register()
    notes: list[str] = []
    if placeholder_zeros:
        record, dropped = drop_placeholder_zeros(record)
        if dropped:
            notes.append(f"context {record.get('context_id')}: exactly 0, treated as not reported: "
                         + ", ".join(dropped))
    start, end = _date(record.get("period_start")), _date(record.get("period_end") or record.get("instant"))
    values = {NAME_MAP.get(k, k): v for k, v in record.items()
              if k not in META_KEYS and not k.startswith("_") and isinstance(v, Decimal)}
    if end is None or not values:
        return [], notes + [f"context {record.get('context_id')}: no period or no values"]
    failed = check_values(values)
    review = ("source record failed arithmetic checks: " + ", ".join(k for k, ok in failed.items() if not ok)
              if not all(failed.values()) else None)
    fye = fiscal_year_end_month
    duration = classify_range(start, end, fye, windows) if start is not None else None
    instant = ResolvedPeriod(None, end, fiscal_year(end, fye), None, False)

    facts: list[FinancialFact] = []
    for name, value in values.items():
        spec = metrics.get(name)
        if spec is None:
            continue
        pit = spec.is_point_in_time
        period = instant if pit else duration
        if period is None:
            notes.append(f"{name} ({record.get('context_id')}): a flow figure with no start date, not loaded")
            continue
        facts.append(FinancialFact(
            entity_id=entity_id, metric=name, value=value, statement_type=spec.statement_type,
            basis=Basis(basis), currency=currency if spec.kind in metrics.CURRENCY_KINDS else None,
            period_start=None if pit else period.start, period_end=period.end,
            financial_year=period.financial_year, quarter=None if pit else period.quarter,
            is_annual=period.is_annual and not pit, is_point_in_time=pit, reported_at=reported_at,
            source_id=source_id, mapping_confidence=MappingConfidence.EXACT, mapping_reason=review))
    paid_up, face = values.get("paid_up_equity_capital"), values.get("face_value_per_share")
    if paid_up is not None and face:
        facts.append(FinancialFact(
            entity_id=entity_id, metric="shares_outstanding", value=div(paid_up, face),
            statement_type=metrics.BS, basis=Basis(basis), period_end=end,
            financial_year=instant.financial_year, is_point_in_time=True, reported_at=reported_at,
            source_id=source_id, mapping_confidence=MappingConfidence.DERIVED,
            mapping_reason=review or "derived: paid-up equity capital / face value per share"))
    return facts, notes


def load_canonical(repos: Any, records: Iterable[Mapping[str, Any]], *, entity: str,
                   basis: Basis | str = "consolidated", currency: str = "INR",
                   fiscal_year_end_month: int = 3, windows: PeriodWindows = DEFAULT_WINDOWS,
                   reported_at: date | None = None, source: Source | None = None,
                   placeholder_zeros: bool = True) -> IndAsReport:
    """Load canonical records for one entity and basis. An existing entity keeps its own
    currency and fiscal year end; a new one is created with the arguments given."""
    register()
    records = list(records)
    ent = repos.entities.resolve(entity)
    fye = ent.fiscal_year_end_month if ent else fiscal_year_end_month
    try:
        if ent is None:
            ent = repos.entities.upsert(Entity(name=entity, currency=currency, fiscal_year_end_month=fye))
        source_id = repos.sources.add(source).source_id if source is not None else None
        items: list[tuple[int, str, FinancialFact]] = []
        skipped: list[str] = []
        review: list[str] = []
        for record in records:
            facts, notes = record_to_facts(record, entity_id=int(ent.id or 0), basis=basis, currency=currency,
                                           fiscal_year_end_month=fye, windows=windows, source_id=source_id,
                                           reported_at=reported_at, placeholder_zeros=placeholder_zeros)
            skipped += notes
            if any(f.mapping_reason and f.mapping_reason.startswith("source record failed") for f in facts):
                review.append(str(record.get("period_end") or record.get("instant")))
            items += [(*_rank(record.get("context_id"), f), f) for f in facts]
        all_facts, conflicts = _resolve_conflicts(items)
        repos.facts.add_many(all_facts)
        repos.commit()
    except Exception:
        repos.rollback()
        raise
    return IndAsReport(entity=ent.name, records=len(records), facts=len(all_facts), needs_review=tuple(review),
                       skipped=tuple(skipped), consistency=tuple(consistency_issues(records)),
                       conflicts=tuple(conflicts))


def load_raw_facts(repos: Any, facts: Iterable[Mapping[str, Any]], **kwargs: Any) -> IndAsReport:
    """Raw XBRL fact rows (see `xbrl.parse_xbrl_file`) -> canonical records -> store."""
    return load_canonical(repos, map_facts(facts), **kwargs)


def load_xbrl_file(repos: Any, path: str | Path, *, entity: str, basis: Basis | str | None = None,
                   **kwargs: Any) -> IndAsReport:
    """Load one .xbrl filing. The basis is read from the file name (it must say consolidated or
    standalone) unless you pass it."""
    p = Path(path)
    if basis is None:
        m = _XBRL_BASIS.search(p.stem)
        if m is None:
            raise ValueError(f"{p.name}: cannot tell consolidated from standalone; pass basis=")
        basis = m.group(0).lower()
    source = Source(kind="xbrl", document_title=p.name, uri=str(p.resolve()),
                    content_hash=hashlib.sha256(p.read_bytes()).hexdigest(),
                    retrieved_at=datetime.now(UTC))
    return load_raw_facts(repos, parse_xbrl_file(p, entity), entity=entity, basis=basis, source=source, **kwargs)


def load_xbrl_files(repos: Any, paths: Iterable[str | Path], *, entity: str, **kwargs: Any) -> list[IndAsReport]:
    """Load several filings, each "Revision" after the "Original" it corrects, whatever order they
    are given in. The filing carries no date, so with no `reported_at` a later load overwrites an
    earlier one for the same period, and a revision must therefore come last."""
    ordered = sorted((Path(p) for p in paths), key=lambda p: ("revision" in p.stem.lower(), p.name))
    return [load_xbrl_file(repos, p, entity=entity, **kwargs) for p in ordered]


def read_canonical_json(path: str | Path) -> list[dict[str, Any]]:
    """Canonical JSON with numbers read as exact Decimals (never through float)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
    return [data] if isinstance(data, dict) else list(data)


def load_canonical_file(repos: Any, path: str | Path, *, entity: str | None = None,
                        basis: Basis | str | None = None, **kwargs: Any) -> IndAsReport:
    """Load a `<SYMBOL>_<consolidated|standalone>_<period>_canonical.json` file. The entity and
    basis default to what the file name says."""
    p = Path(path)
    m = _FILENAME.match(p.name)
    if m is None and (entity is None or basis is None):
        raise ValueError(f"{p.name}: not a <SYMBOL>_<basis>_<period>_canonical.json name; "
                         "pass entity= and basis=")
    source = Source(kind="xbrl", document_title=p.name, uri=str(p.resolve()),
                    content_hash=hashlib.sha256(p.read_bytes()).hexdigest(),
                    retrieved_at=datetime.now(UTC), period_label=m["period"] if m else None)
    return load_canonical(repos, read_canonical_json(p), entity=entity or m["symbol"],  # type: ignore[index]
                          basis=basis or m["basis"], source=source, **kwargs)  # type: ignore[index]
