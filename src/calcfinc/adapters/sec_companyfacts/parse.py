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

from calcfinc.adapters.sec_companyfacts.tags import (
    ANNUAL_FORMS,
    CANDIDATES,
    DEFAULT_FORMS,
    IFRS_BANK_MARKERS,
    INSURER_MARKERS,
    INSURER_TOTAL_COSTS,
)
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
    in_annual: bool = False        # some filing of this period was a 10-K / 20-F / 40-F, even if a 6-K came first


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
    year_end_known: bool = True    # False when no full-year figures existed and December was only assumed
    sector: str | None = None      # declared only for an IFRS bank, whose bank.* lines are not mapped


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


def _home_currency(taxonomies: Mapping[str, Any]) -> str | None:
    """The currency the filer reports most in, over every concept, so all of its metrics share one
    currency (a concept with a few translated periods in another unit does not change it)."""
    counts: Counter[str] = Counter()
    for concepts in taxonomies.values():
        for node in (concepts or {}).values():
            for unit, entries in ((node or {}).get("units") or {}).items():
                if _CURRENCY.match(unit):
                    counts[unit] += len(entries)
    return max(counts, key=lambda u: (counts[u], u == "USD")) if counts else None


def _unit_for(kind: str, units: Mapping[str, Any], home: str | None = None) -> tuple[str, str | None] | None:
    """(unit key, currency) to read for a metric of this kind, or None if the concept does not
    report in a matching unit. A figure in the wrong kind of unit is skipped, never coerced."""
    # The filer's home currency (see _home_currency) is read whenever the concept has it, so every
    # metric of one filer is in one currency; a concept that lacks it falls back to the unit it
    # reports most in (ties go to USD).
    if kind == "currency":
        keys = sorted(k for k in units if _CURRENCY.match(k))
        pick = home if home in keys else max(keys, key=lambda k: (len(units[k]), k == "USD"), default=None)
        return (pick, pick) if pick else None
    if kind == "per_share":
        keys = sorted(k for k in units if _PER_SHARE.match(k))
        pick = (f"{home}/shares" if f"{home}/shares" in keys
                else max(keys, key=lambda k: (len(units[k]), k == "USD/shares"), default=None))
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
            forms: Collection[str], home: str | None = None) -> dict[tuple[date | None, date], _Sel]:
    found: list[tuple[int, str, str, str | None, dict[tuple[date | None, date], list[Entry]]]] = []
    weight: Counter[tuple[date | None, date]] = Counter()
    for idx, (tax, concept) in enumerate(candidates):
        node = (taxonomies.get(tax) or {}).get(concept)
        if not node:
            continue
        pick = _unit_for(kind, node.get("units") or {}, home)
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
    group = _equivalent([(f"{f[1]}:{f[2]}", {(k, e.accn): e.value for k, es in m.items() for e in es})
                         for f, m in zip(found, merged_all, strict=True)])
    chosen: dict[tuple[date | None, date], _Sel] = {}
    for (idx, tax, concept, currency, _), merged in zip(found, merged_all, strict=True):
        for key, entries in merged.items():
            chosen.setdefault(key, _Sel(idx, tax, concept, currency, _versions(entries), group[f"{tax}:{concept}"],
                                        any(e.form.startswith(ANNUAL_FORMS) for e in entries)))
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


def _at(sel: _Sel, known: date) -> Entry | None:
    """The version of `sel` that was in the latest filing made on or before `known`."""
    return next((v for v in reversed(sel.versions) if v.filed <= known), None)


def _cumulative(cum: Mapping[int, tuple[date, _Sel]], direct: Mapping[int, tuple[date, _Sel]],
                j: int, known: date) -> _Cum | None:
    """Year-to-date value after `j` quarters as the filings made by `known` gave it: the reported
    cumulative figure, else the sum of the reported single quarters (only if one concept supplied
    them all)."""
    if j == 0:
        return _Cum(ZERO, None, None)
    if j in cum and (latest := _at(cum[j][1], known)) is not None:
        return _Cum(latest.value, latest, cum[j][1].group)
    if all(i in direct for i in range(1, j + 1)):
        parts = [direct[i][1] for i in range(1, j + 1)]
        if len({p.group for p in parts}) != 1:
            return None
        latest_parts = [_at(p, known) for p in parts]
        if any(lp is None for lp in latest_parts):
            return None
        total = ZERO
        for lp in latest_parts:
            assert lp is not None
            total = add(total, lp.value)
        return _Cum(total, max((lp for lp in latest_parts if lp is not None), key=lambda x: x.filed), parts[0].group)
    return None


def _drop_repeats(entries: list[Entry]) -> tuple[Entry, ...]:
    kept: list[Entry] = []
    for e in sorted(entries, key=lambda e: e.filed):
        if not kept or kept[-1].value != e.value:
            kept.append(e)
    return tuple(kept)


def _derive_quarters(chosen: Mapping[tuple[date | None, date], _Sel]) -> list[tuple[tuple[Entry, ...], _Sel, str]]:
    """Single quarters that were never reported on their own, from year-to-date figures. Each comes
    with its versions: the value the filings made by each date implied, so that a view as of a date
    between a filing and its restatement still has the quarter."""
    flows = {k: v for k, v in chosen.items() if k[0] is not None}
    klass = {k: _duration_class(k[0], k[1]) for k in flows if k[0] is not None}
    out: list[tuple[tuple[Entry, ...], _Sel, str]] = []
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
            if k not in cum:
                continue
            # A quarter that was only reported by a later filing (a recast) still had to be derived before it.
            reported_from = min((v.filed for v in direct[k][1].versions), default=None) if k in direct else None
            if (k - 1) not in cum and (k - 1) not in direct:
                continue
            if k in direct:
                # the filer's own dates for the quarter (they can differ from the neighbours' by a day), so
                # the derived and the reported figure are versions of one period, not two periods
                q_start, q_end = next(key for key, sel in flows.items() if sel is direct[k][1])
                assert q_start is not None
            else:
                prev_end = cum[k - 1][0] if (k - 1) in cum else direct[k - 1][0]
                q_start, q_end = prev_end + timedelta(days=1), cum[k][0]
            if q_start >= q_end:
                continue
            dates = sorted({v.filed for pool in (direct, cum) for i, (_, sel) in pool.items() if i <= k
                            for v in sel.versions if reported_from is None or v.filed < reported_from})
            versions: dict[date, Entry] = {}
            for known in dates:
                this, prev = _cumulative(cum, direct, k, known), _cumulative(cum, direct, k - 1, known)
                if this is None or prev is None or this.entry is None or (prev.concept not in (None, this.concept)):
                    continue
                later = this.entry if prev.entry is None or this.entry.filed >= prev.entry.filed else prev.entry
                filed = max(this.entry.filed, prev.entry.filed if prev.entry else this.entry.filed)
                versions[filed] = Entry(q_start, q_end, sub(this.value, prev.value), later.accn, later.form, filed)
            if not versions:
                continue
            why = f"single quarter derived: {_LABEL[k]} year-to-date less {_LABEL[k - 1]}"
            if k == 4:
                why += " (the SEC reports no stand-alone fourth quarter)"
            out.append((_drop_repeats(list(versions.values())), cum[k][1], why))
    return out


# ---------------------------------------------------------------------------------------------
# insurers: underwriting expenses
# ---------------------------------------------------------------------------------------------

TOTAL_COSTS = "_insurer_total_costs"       # selected like a metric, but only used to derive underwriting expenses


def _premiums_are_the_business(selections: Mapping[str, Mapping[tuple[date | None, date], _Sel]]) -> bool:
    """A filer that tags premiums earned is an insurer only if they are most of its revenue. A manufacturer
    with a captive insurer tags them too, on a few percent of its sales, and is not an insurer."""
    premiums = selections.get("insurance.net_earned_premium") or {}
    revenue = selections.get("revenue") or {}
    common = [k for k in premiums if k[0] is not None and _duration_class(k[0], k[1]) == "y" and k in revenue]
    if not common:                                     # nothing to compare with: claims reported too is enough
        return "insurance.claims_incurred" in selections
    newest = max(common, key=lambda k: k[1])
    total = revenue[newest].versions[-1].value
    return total > 0 and premiums[newest].versions[-1].value * 2 >= total


def _underwriting_expenses(costs: list[ParsedFact], parsed: list[ParsedFact]) -> list[ParsedFact]:
    """insurance.underwriting_expenses = total benefits, losses and expenses less claims incurred, for each
    period and, as the filings made by each date gave them, for each version of it."""
    claims: dict[tuple[date | None, date | None], list[ParsedFact]] = defaultdict(list)
    totals: dict[tuple[date | None, date | None], list[ParsedFact]] = defaultdict(list)
    for p in parsed:
        if p.fact.metric == "insurance.claims_incurred" and p.fact.value is not None:
            claims[(p.fact.period_start, p.fact.period_end)].append(p)
    for p in costs:
        if p.fact.value is not None:
            totals[(p.fact.period_start, p.fact.period_end)].append(p)

    def known(group: list[ParsedFact], day: date) -> ParsedFact | None:
        seen = [p for p in group if p.fact.reported_at is not None and p.fact.reported_at <= day]
        return max(seen, key=lambda p: p.fact.reported_at or date.min) if seen else None

    out: list[ParsedFact] = []
    for key in claims.keys() & totals.keys():
        last: Decimal | None = None
        for day in sorted({p.fact.reported_at for p in claims[key] + totals[key] if p.fact.reported_at}):
            c, t = known(claims[key], day), known(totals[key], day)
            if c is None or t is None or c.fact.currency != t.fact.currency:
                continue
            assert c.fact.value is not None and t.fact.value is not None
            value = sub(t.fact.value, c.fact.value)
            if value == last:
                continue
            last = value
            newer = c if (c.fact.reported_at or date.min) >= (t.fact.reported_at or date.min) else t
            out.append(ParsedFact(replace(
                c.fact, metric="insurance.underwriting_expenses", value=value, reported_at=day,
                mapping_confidence=MappingConfidence.DERIVED,
                mapping_reason=("derived: total benefits, losses and expenses less claims incurred; it also holds "
                                "interest expense, interest credited to policyholders and other items")),
                newer.accn, newer.form))
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
    ifrs = taxonomies.get("ifrs-full") or {}

    # Bank lines only for a filer that files like a bank: a concept such as Deposits or InterestExpense
    # also appears in insurers' and industrials' statements, where it does not mean what bank.* means.
    us = taxonomies.get("us-gaap") or {}
    is_bank = "NoninterestExpense" in us and "Deposits" in us
    maybe_insurer = not is_bank and any(m in us for m in INSURER_MARKERS)
    is_ifrs_bank = any(m in ifrs for m in IFRS_BANK_MARKERS)
    if is_ifrs_bank:
        notes.append("IFRS bank: declared a bank, so ratios that do not describe a bank are withheld; bank.* "
                     "lines are not mapped for IFRS and interest expense is not read as a finance cost")
    elif "InsuranceRevenue" in ifrs:
        notes.append("IFRS 17 insurer: insurance.* lines are not mapped, because insurance revenue is not "
                     "earned premium")

    home = _home_currency(taxonomies)
    selections: dict[str, dict[tuple[date | None, date], _Sel]] = {}
    wanted = {**CANDIDATES, **({TOTAL_COSTS: INSURER_TOTAL_COSTS} if maybe_insurer else {})}
    for metric, candidates in wanted.items():
        spec = metrics.get("total_expenses" if metric == TOTAL_COSTS else metric)
        if (spec is None or (metric.startswith("bank.") and not is_bank)
                or (metric.startswith("insurance.") and not maybe_insurer)
                or (metric == "finance_costs" and is_ifrs_bank)):
            continue
        chosen = _select(taxonomies, candidates, spec.kind, forms, home)
        if chosen:
            selections[metric] = chosen

    if maybe_insurer and not _premiums_are_the_business(selections):
        for name in [n for n in selections if n.startswith("insurance.") or n == TOTAL_COSTS]:
            del selections[name]

    # The fiscal year end is where the annual report's years end. Twelve-month figures in a 10-Q
    # (Amazon files trailing-twelve-month statements) end every quarter and are not fiscal years.
    year_ends = [e for ch in selections.values() for (s, e), sel in ch.items()
                 if s is not None and _duration_class(s, e) == "y"
                 and sel.in_annual]
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
        spec = metrics.get("total_expenses" if metric == TOTAL_COSTS else metric)
        assert spec is not None
        if not chosen:                      # every period was a year that does not end at the year end given
            continue
        pit = spec.is_point_in_time
        items: list[tuple[date | None, date, _Sel, tuple[Entry, ...], str | None]] = []
        for (s, e), sel in chosen.items():
            if s is None and pit:
                items.append((None, e, sel, sel.versions, None))
            elif s is not None and not pit and _duration_class(s, e) in ("q", "y"):
                items.append((s, e, sel, sel.versions, None))
        if spec.kind == "currency" and not pit:
            for versions, template, why in _derive_quarters(chosen):
                items.append((versions[0].start, versions[0].end, template, versions, why))
                derived_count += metric != TOTAL_COSTS         # that series is only an input, never stored
        # A concept is only an "alternate" if the filer uses a better-ranked one for this metric
        # elsewhere. A filer that only ever reports the second-choice concept is just using its own.
        best_used = min(sel.idx for sel in chosen.values())
        for s, e, sel, versions, derived_why in items:
            period = (ResolvedPeriod(None, e, fiscal_year(e, fye), None, False) if s is None
                      else classify_range(s, e, fye, windows))
            alt = (f"alternate concept {sel.tax}:{sel.concept}; the filer reports a better-ranked concept "
                   f"({wanted[metric][best_used][1]}) for other periods") if sel.idx > best_used else None
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

    costs = [p for p in parsed if p.fact.metric == TOTAL_COSTS]
    parsed = [p for p in parsed if p.fact.metric != TOTAL_COSTS] + _underwriting_expenses(costs, parsed)

    # Neither US GAAP nor IFRS has an exceptional-items line, so profit before exceptional items is pre-tax income.
    parsed += [ParsedFact(replace(p.fact, metric="pbt_before_exceptional",
                                  mapping_confidence=MappingConfidence.DERIVED,
                                  mapping_reason="no exceptional-items line in US GAAP or IFRS; equals pre-tax income"),
                          p.accn, p.form) for p in parsed if p.fact.metric == "pbt"]
    parsed.sort(key=lambda p: (p.fact.metric, p.fact.period_end or date.min, p.fact.period_start or date.min,
                               p.fact.reported_at or date.min))
    currencies = Counter(p.fact.currency for p in parsed if p.fact.currency)
    return ParsedCompanyFacts(cik, name, fye, currencies.most_common(1)[0][0] if currencies else None,
                              tuple(parsed), derived_count, tuple(notes),
                              year_end_known=fiscal_year_end_month is not None or bool(year_ends),
                              sector="bank" if is_ifrs_bank else None)
