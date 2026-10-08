"""SEC `companyfacts` JSON -> calcfinc facts. Pure parsing: no network, no files.

What it does, and why:
- Periods are matched on the exact start and end dates. The `fy` / `fp` fields in the JSON
  describe the *filing*, not the period, so they are never used to place a figure.
- For each metric and period the first candidate concept (see `tags.CANDIDATES`) that was
  reported for that exact period wins; a lower-priority concept is flagged as an alternate.
- A figure restated in a later filing is kept as a second version with `reported_at` set to the
  filing date; the engine uses the latest. Identical repeats (a later filing's comparative
  column) are dropped.
- Only single quarters and full years are emitted. Year-to-date figures (6 and 9 months) are
  used solely to *derive* single quarters, for currency flows only. This is what produces the
  fourth quarter, which the SEC never reports on its own (12 months less 9 months), and what
  turns cash-flow statements (reported year-to-date) into quarters. Per-share figures are not
  additive and are never derived.
- Values are base units already (USD, not thousands). Facts carrying a dimension are ignored.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from calcfinc.adapters.sec_companyfacts.tags import CANDIDATES, DEFAULT_FORMS
from calcfinc.fact import Basis, FinancialFact, MappingConfidence
from calcfinc.num import ZERO, add, sub, to_decimal
from calcfinc.period import DEFAULT_WINDOWS, PeriodWindows, ResolvedPeriod, classify_range, fiscal_year
from calcfinc.registry import metrics

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_PER_SHARE = re.compile(r"^([A-Z]{3})/shares$")
# Days between a duration's start and end. 13-week quarters and 52/53-week years fall inside.
_RANGES = {"q": (71, 111), "h": (160, 200), "n": (250, 290), "y": (330, 400)}
_CUM_INDEX = {"q": 1, "h": 2, "n": 3, "y": 4}
_LABEL = {1: "3M", 2: "6M", 3: "9M", 4: "12M"}


@dataclass(frozen=True, slots=True)
class Entry:
    """One reported value of one concept for one period, from one filing."""

    start: date | None
    end: date
    value: Decimal
    accn: str
    form: str
    filed: date


@dataclass(frozen=True, slots=True)
class _Sel:
    idx: int                       # position in the candidate list (0 = preferred)
    tax: str
    concept: str
    currency: str | None
    versions: tuple[Entry, ...]    # oldest filing first; consecutive repeats removed
    group: str = ""                # concepts proven equal for this filer share a group (see _equivalent)


@dataclass(frozen=True, slots=True)
class ParsedFact:
    fact: FinancialFact            # entity_id is 0 until the loader assigns it
    accn: str                      # SEC accession number of the filing it came from
    form: str


@dataclass(frozen=True, slots=True)
class ParsedCompanyFacts:
    cik: str
    name: str
    fiscal_year_end_month: int
    currency: str | None
    facts: tuple[ParsedFact, ...]
    derived_quarters: int
    notes: tuple[str, ...]


# ---------------------------------------------------------------------------------------------
# reading one concept
# ---------------------------------------------------------------------------------------------

def _num(v: object) -> Decimal | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return to_decimal(repr(v) if isinstance(v, float) else v)
    except (TypeError, ValueError):
        return None


def _date(v: object) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _unit_for(kind: str, units: Mapping[str, Any]) -> tuple[str, str | None] | None:
    """(unit key, currency) to read for a metric of this kind, or None if the concept does not
    report in a matching unit. A figure in the wrong kind of unit is skipped, never coerced."""
    if kind == "currency":
        keys = sorted(k for k in units if _CURRENCY.match(k))
        pick = "USD" if "USD" in keys else keys[0] if keys else None
        return (pick, pick) if pick else None
    if kind == "per_share":
        keys = sorted(k for k in units if _PER_SHARE.match(k))
        pick = "USD/shares" if "USD/shares" in keys else keys[0] if keys else None
        return (pick, pick[:3]) if pick else None
    if kind == "shares":
        return ("shares", None) if "shares" in units else None
    return ("pure", None) if "pure" in units else None


def _entries(items: Any, forms: Collection[str]) -> list[Entry]:
    out = []
    for it in items or ():
        if "dimensions" in it or "segment" in it:
            continue
        end, filed, value = _date(it.get("end")), _date(it.get("filed")), _num(it.get("val"))
        accn, form = it.get("accn"), it.get("form")
        if end is None or filed is None or value is None or not accn or form not in forms:
            continue
        out.append(Entry(_date(it.get("start")), end, value, str(accn), str(form), filed))
    return out


def _versions(entries: list[Entry]) -> tuple[Entry, ...]:
    kept: list[Entry] = []
    for e in sorted(entries, key=lambda e: (e.filed, e.accn)):
        if not kept or kept[-1].value != e.value:
            kept.append(e)
    return tuple(kept)


START_JITTER_DAYS = 3


def _canonical_periods(weight: Mapping[tuple[date | None, date], int]
                       ) -> dict[tuple[date | None, date], tuple[date | None, date]]:
    """Map each (start, end) to the period it really is. Filings of one company sometimes give the
    same fiscal quarter a start a day apart (a recast filing says 2 July where the original said
    1 July). Durations with the same end and starts within a few days are one period; the start
    carried by the most entries is kept."""
    by_end: dict[date, list[date]] = defaultdict(list)
    for start, end in weight:
        if start is not None:
            by_end[end].append(start)
    canon: dict[tuple[date | None, date], tuple[date | None, date]] = {}
    for end, starts in by_end.items():
        cluster: list[date] = []
        for s in [*sorted(starts), None]:
            if s is not None and (not cluster or (s - cluster[-1]).days <= START_JITTER_DAYS):
                cluster.append(s)
                continue
            keep = max(cluster, key=lambda x: (weight[(x, end)], -x.toordinal()))
            canon.update({(c, end): (keep, end) for c in cluster})
            cluster = [s] if s is not None else []
    return canon


def _select(taxonomies: Mapping[str, Any], candidates: tuple[tuple[str, str], ...], kind: str,
            forms: Collection[str]) -> dict[tuple[date | None, date], _Sel]:
    found: list[tuple[int, str, str, str | None, dict[tuple[date | None, date], list[Entry]]]] = []
    weight: Counter[tuple[date | None, date]] = Counter()
    for idx, (tax, concept) in enumerate(candidates):
        node = (taxonomies.get(tax) or {}).get(concept)
        if not node:
            continue
        pick = _unit_for(kind, node.get("units") or {})
        if pick is None:
            continue
        unit, currency = pick
        by_period: dict[tuple[date | None, date], list[Entry]] = defaultdict(list)
        for e in _entries(node["units"][unit], forms):
            by_period[(e.start, e.end)].append(e)
        weight.update({k: len(v) for k, v in by_period.items()})
        found.append((idx, tax, concept, currency, by_period))
    canon = _canonical_periods(weight)
    merged_all: list[dict[tuple[date | None, date], list[Entry]]] = []
    for _idx, _tax, _concept, _currency, by_period in found:
        merged: dict[tuple[date | None, date], list[Entry]] = defaultdict(list)
        for key, entries in by_period.items():
            merged[canon.get(key, key)].extend(entries)
        merged_all.append(merged)
    group = _equivalent([(f[2], {(k, e.accn): e.value for k, es in m.items() for e in es})
                         for f, m in zip(found, merged_all, strict=True)])
    chosen: dict[tuple[date | None, date], _Sel] = {}
    for (idx, tax, concept, currency, _), merged in zip(found, merged_all, strict=True):
        for key, entries in merged.items():
            chosen.setdefault(key, _Sel(idx, tax, concept, currency, _versions(entries), group[concept]))
    return chosen


def _equivalent(series: list[tuple[str, dict[tuple[tuple[date | None, date], str], Decimal]]]) -> dict[str, str]:
    """Group concepts that are the same quantity *for this filer*: within the same filing they
    cover at least one common period and agree exactly on every common period. (A bank reports its
    total net revenue under two concepts; the same 10-K gives the same annual figure for both.)
    Values are compared filing by filing, so a recast in a later filing is not mistaken for two
    different definitions. Quarters are only derived across concepts inside one group, because
    two concepts that disagree within a filing measure different things."""
    rep = {name: name for name, _ in series}

    def find(x: str) -> str:
        while rep[x] != x:
            x = rep[x]
        return x

    for i, (a, va) in enumerate(series):
        for b, vb in series[i + 1:]:
            shared = va.keys() & vb.keys()
            if shared and all(va[k] == vb[k] for k in shared):
                rep[find(b)] = find(a)
    return {name: find(name) for name, _ in series}


# ---------------------------------------------------------------------------------------------
# durations: classes, fiscal year end, derived quarters
# ---------------------------------------------------------------------------------------------

def _duration_class(start: date, end: date) -> str | None:
    days = (end - start).days
    return next((name for name, (lo, hi) in _RANGES.items() if lo <= days <= hi), None)


def _infer_fye(year_ends: list[date]) -> int | None:
    """Month the fiscal year ends, from the dates of the full-year figures. A week is
    subtracted so a 52/53-week year ending on, say, 1 Feb counts as a January year end."""
    months = Counter((e - timedelta(days=7)).month for e in year_ends)
    return months.most_common(1)[0][0] if months else None


@dataclass(frozen=True, slots=True)
class _Cum:
    value: Decimal
    entry: Entry | None            # the latest component filing, for the derived fact's provenance
    concept: str | None


def _cumulative(cum: Mapping[int, tuple[date, _Sel]], direct: Mapping[int, tuple[date, _Sel]],
                j: int) -> _Cum | None:
    """Year-to-date value after `j` quarters: the reported cumulative figure, else the sum of the
    reported single quarters (only if one concept supplied them all)."""
    if j == 0:
        return _Cum(ZERO, None, None)
    if j in cum:
        latest = cum[j][1].versions[-1]
        return _Cum(latest.value, latest, cum[j][1].group)
    if all(i in direct for i in range(1, j + 1)):
        parts = [direct[i][1] for i in range(1, j + 1)]
        if len({p.group for p in parts}) != 1:
            return None
        latest_parts = [p.versions[-1] for p in parts]
        total = ZERO
        for lp in latest_parts:
            total = add(total, lp.value)
        return _Cum(total, max(latest_parts, key=lambda x: x.filed), parts[0].group)
    return None


def _derive_quarters(chosen: Mapping[tuple[date | None, date], _Sel]) -> list[tuple[Entry, _Sel, str]]:
    """Single quarters that were never reported on their own, from year-to-date figures."""
    flows = {k: v for k, v in chosen.items() if k[0] is not None}
    klass = {k: _duration_class(k[0], k[1]) for k in flows if k[0] is not None}
    out: list[tuple[Entry, _Sel, str]] = []
    for start in sorted({k[0] for k, c in klass.items() if c in ("h", "n", "y") and k[0] is not None}):
        cum: dict[int, tuple[date, _Sel]] = {}
        for (s, e), c in klass.items():
            if s == start and c in _CUM_INDEX:
                cum.setdefault(_CUM_INDEX[c], (e, flows[(s, e)]))
        direct: dict[int, tuple[date, _Sel]] = {1: cum[1]} if 1 in cum else {}
        for (s, e), c in klass.items():
            if c == "q" and s is not None and start < s <= start + timedelta(days=366):
                k = 1 + round((s - start).days / 91.3125)
                if 2 <= k <= 4:
                    direct.setdefault(k, (e, flows[(s, e)]))

        for k in (2, 3, 4):
            if k in direct or k not in cum:
                continue
            this, prev = _cumulative(cum, direct, k), _cumulative(cum, direct, k - 1)
            if this is None or prev is None or this.entry is None or (prev.concept not in (None, this.concept)):
                continue
            prev_end = cum[k - 1][0] if (k - 1) in cum else direct[k - 1][0]
            q_start, q_end = prev_end + timedelta(days=1), cum[k][0]
            if q_start >= q_end:
                continue
            later = this.entry if prev.entry is None or this.entry.filed >= prev.entry.filed else prev.entry
            entry = Entry(q_start, q_end, sub(this.value, prev.value), later.accn, later.form,
                          max(this.entry.filed, prev.entry.filed if prev.entry else this.entry.filed))
            why = f"single quarter derived: {_LABEL[k]} year-to-date less {_LABEL[k - 1]}"
            if k == 4:
                why += " (the SEC reports no stand-alone fourth quarter)"
            out.append((entry, cum[k][1], why))
    return out


# ---------------------------------------------------------------------------------------------
# the whole document
# ---------------------------------------------------------------------------------------------

def parse_companyfacts(data: Mapping[str, Any], *, fiscal_year_end_month: int | None = None,
                       forms: Collection[str] = DEFAULT_FORMS,
                       windows: PeriodWindows = DEFAULT_WINDOWS) -> ParsedCompanyFacts:
    if "cik" not in data:
        raise ValueError("not a companyfacts document: no 'cik'")
    cik = str(data["cik"]).strip().zfill(10)
    name = str(data.get("entityName") or f"CIK {cik}")
    taxonomies = data.get("facts") or {}
    notes: list[str] = []
    if not taxonomies.get("us-gaap") and taxonomies.get("ifrs-full"):
        notes.append("IFRS filer: ifrs-full concepts are not mapped in this version, so most metrics are absent")

    # Bank lines only for a filer that files like a bank: a concept such as Deposits or InterestExpense
    # also appears in insurers' and industrials' statements, where it does not mean what bank.* means.
    us = taxonomies.get("us-gaap") or {}
    is_bank = "NoninterestExpense" in us and "Deposits" in us

    selections: dict[str, dict[tuple[date | None, date], _Sel]] = {}
    for metric, candidates in CANDIDATES.items():
        spec = metrics.get(metric)
        if spec is None or (metric.startswith("bank.") and not is_bank):
            continue
        chosen = _select(taxonomies, candidates, spec.kind, forms)
        if chosen:
            selections[metric] = chosen

    # The fiscal year end is where the annual report's years end. Twelve-month figures in a 10-Q
    # (Amazon files trailing-twelve-month statements) end every quarter and are not fiscal years.
    annual_forms = ("10-K", "20-F", "40-F")
    year_ends = [e for ch in selections.values() for (s, e), sel in ch.items()
                 if s is not None and _duration_class(s, e) == "y"
                 and any(v.form.startswith(annual_forms) for v in sel.versions)]
    fye = fiscal_year_end_month or _infer_fye(year_ends) or 12
    if fiscal_year_end_month is None and not year_ends:
        notes.append("no full-year figures found; assumed a December fiscal year end")
    for chosen in selections.values():
        for key in [(s, e) for (s, e) in chosen if s is not None and _duration_class(s, e) == "y"
                    and (e - timedelta(days=7)).month != fye]:
            del chosen[key]

    parsed: list[ParsedFact] = []
    derived_count = 0
    for metric, chosen in selections.items():
        spec = metrics.get(metric)
        assert spec is not None
        pit = spec.is_point_in_time
        items: list[tuple[date | None, date, _Sel, tuple[Entry, ...], str | None]] = []
        for (s, e), sel in chosen.items():
            if s is None and pit:
                items.append((None, e, sel, sel.versions, None))
            elif s is not None and not pit and _duration_class(s, e) in ("q", "y"):
                items.append((s, e, sel, sel.versions, None))
        if spec.kind == "currency" and not pit:
            for entry, template, why in _derive_quarters(chosen):
                items.append((entry.start, entry.end, template, (entry,), why))
                derived_count += 1
        # A concept is only an "alternate" if the filer uses a better-ranked one for this metric
        # elsewhere. A filer that only ever reports the second-choice concept is just using its own.
        best_used = min(sel.idx for sel in chosen.values())
        for s, e, sel, versions, derived_why in items:
            period = (ResolvedPeriod(None, e, fiscal_year(e, fye), None, False) if s is None
                      else classify_range(s, e, fye, windows))
            alt = (f"alternate concept {sel.tax}:{sel.concept}; the filer reports a better-ranked concept "
                   f"({CANDIDATES[metric][best_used][1]}) for other periods") if sel.idx > best_used else None
            if derived_why:
                confidence, reason = MappingConfidence.DERIVED, derived_why + (f"; {alt}" if alt else "")
            elif alt:
                confidence, reason = MappingConfidence.ALTERNATE_TAG, alt
            else:
                confidence, reason = MappingConfidence.EXACT, None
            for v in versions:
                parsed.append(ParsedFact(FinancialFact(
                    entity_id=0, metric=metric, value=v.value, statement_type=spec.statement_type,
                    basis=Basis.CONSOLIDATED, currency=sel.currency if spec.kind in metrics.CURRENCY_KINDS else None,
                    period_start=s, period_end=e, financial_year=period.financial_year,
                    quarter=period.quarter if s is not None else None, is_annual=period.is_annual,
                    is_point_in_time=s is None, reported_at=v.filed, mapping_confidence=confidence,
                    mapping_reason=reason), v.accn, v.form))

    # US GAAP has no exceptional-items line, so profit before exceptional items is pre-tax income.
    parsed += [ParsedFact(replace(p.fact, metric="pbt_before_exceptional",
                                  mapping_confidence=MappingConfidence.DERIVED,
                                  mapping_reason="US GAAP has no exceptional-items line; equals pre-tax income"),
                          p.accn, p.form) for p in parsed if p.fact.metric == "pbt"]
    parsed.sort(key=lambda p: (p.fact.metric, p.fact.period_end or date.min, p.fact.period_start or date.min,
                               p.fact.reported_at or date.min))
    currencies = Counter(p.fact.currency for p in parsed if p.fact.currency)
    return ParsedCompanyFacts(cik, name, fye, currencies.most_common(1)[0][0] if currencies else None,
                              tuple(parsed), derived_count, tuple(notes))
