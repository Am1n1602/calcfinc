"""Raw XBRL facts -> canonical records, with exact Decimal values.

A *raw fact* is a dict as produced by `xbrl.parse_xbrl_file`: line_item_tag, value (text),
context_id, period_start / period_end / instant, sign. A *canonical record* is one context's
facts under the source-side canonical names (`tags.TAG_MAP`), plus its period.

Only whole-company contexts are used (OneD, OneI, PY_D...), never segment or note breakdowns.
Duration and instant contexts are kept as separate records; the engine merges a balance sheet
into the duration record that ends on the same day.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from calcfinc.adapters.ind_as_xbrl.tags import (
    BANK_BALANCE_SHEET_AUX_TAGS,
    BANK_EQUITY_AUX_TAGS,
    DEBT_ALT_TAGS,
    HIGH_SEVERITY,
    SECTOR_ALT_TAGS,
    SNAPSHOT_FIELDS,
    TAG_MAP,
    is_primary_context,
)
from calcfinc.num import HUNDRED, add, div, mul, sub

_MISSING = {"", "-", "—", "NA", "N/A"}


def parse_number(raw: object) -> Decimal | None:
    """Parse a reported number exactly. Handles Indian formatting ('59,553.00'), accounting
    negatives ('(1,234.5)'), a rupee sign and trailing footnote markers. Returns None for
    anything that is not a number. A float (from JSON) is taken through its shortest text,
    which is the original text for any figure of 17 significant digits or fewer."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        return raw if raw.is_finite() else None
    if isinstance(raw, int):
        return Decimal(raw)
    s = repr(raw) if isinstance(raw, float) else str(raw).strip()
    if s in _MISSING:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace("₹", "").strip()
    for candidate in (s, "".join(c for c in s if c.isdigit() or c in ".-")):
        try:
            value = Decimal(candidate)
        except InvalidOperation:
            continue
        if value.is_finite():
            return -value if negative else value
    return None


def _tag_index() -> tuple[dict[str, str], dict[str, str]]:
    by_tag = {v: k for k, v in TAG_MAP.items()}
    by_tag.update({v: k for k, v in BANK_EQUITY_AUX_TAGS.items()})
    by_tag.update({v: k for k, v in BANK_BALANCE_SHEET_AUX_TAGS.items()})
    by_tag.update(SECTOR_ALT_TAGS)
    by_tag.update(DEBT_ALT_TAGS)
    # Older Regulation 33 filings use the in-bse-fin: prefix with the same local concept name.
    # An exact full-tag match always wins; the local name is only a fallback.
    by_local: dict[str, str] = {}
    for tag, name in by_tag.items():
        by_local.setdefault(tag.split(":", 1)[1] if ":" in tag else tag, name)
    return by_tag, by_local


def map_facts(facts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Group raw facts into canonical records, newest first."""
    by_tag, by_local = _tag_index()
    fields: dict[str, dict[str, Decimal | None]] = defaultdict(dict)
    periods: dict[str, dict[str, Any]] = {}

    for fact in facts:
        ctx = fact.get("context_id")
        if not isinstance(ctx, str) or not is_primary_context(ctx):
            continue
        tag = fact.get("line_item_tag")
        name = by_tag.get(tag or "")
        if name is None and tag and ":" in tag:
            name = by_local.get(tag.split(":", 1)[1])
        if name is None:
            continue                                   # not a field we track
        value = parse_number(fact.get("value"))
        if value is not None and fact.get("sign") == "-":
            value = -value
        fields[ctx][name] = value
        periods[ctx] = {"context_id": ctx, "period_start": fact.get("period_start"),
                        "period_end": fact.get("period_end"), "instant": fact.get("instant")}

    records = []
    for ctx, values in fields.items():
        record: dict[str, Any] = {**periods[ctx], **values}
        _derive_bank_lines(record)
        records.append(record)
    records.sort(key=lambda r: r.get("period_end") or r.get("instant") or "", reverse=True)
    return records


def _derive_bank_lines(record: dict[str, Any]) -> None:
    """Banks report their equity, cash and liabilities as sub-lines. Build the totals only when
    the total itself is absent and every needed part is present."""
    capital = record.pop("_bank_capital", None)
    reserves = record.pop("_bank_reserves_and_surplus", None)
    if record.get("total_equity") is None and capital is not None and reserves is not None:
        record["total_equity"] = add(capital, reserves)
    cash_with_central_bank = record.pop("_bank_cash_with_rbi", None)
    balances_with_banks = record.pop("_bank_balances_with_banks", None)
    if (record.get("cash_and_equivalents") is None and cash_with_central_bank is not None
            and balances_with_banks is not None):
        record["cash_and_equivalents"] = add(cash_with_central_bank, balances_with_banks)
    other = record.pop("_bank_other_liabilities_and_provisions", None)
    if (record.get("total_liabilities") is None and other is not None
            and record.get("deposits_debt") is not None and record.get("borrowings_noncurrent") is not None):
        record["total_liabilities"] = add(add(record["deposits_debt"], record["borrowings_noncurrent"]), other)


# Fields a filing reports as an exact 0 when it means "not applicable". Found in real filings:
# a consolidated bank filing carries 0 for its whole NPA block; paid-up capital, face value and
# CET1 are never genuinely 0; a coverage ratio of exactly 0 is a placeholder, not a result.
NPA_BLOCK = ("gross_npa", "net_npa", "gross_npa_ratio", "net_npa_ratio")
BANK_REGULATORY = (*NPA_BLOCK, "return_on_assets", "cet1_ratio", "additional_tier1_ratio")
ZERO_IS_MISSING = ("paid_up_equity_capital", "face_value_per_share", "cet1_ratio",
                   "debt_service_coverage_ratio_reported", "interest_service_coverage_ratio_reported")


def drop_placeholder_zeros(record: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The record without the zeros that mean 'not reported', and the names removed. A genuine
    zero (no exceptional items, no borrowings, no minority interest) is left alone."""
    out = dict(record)
    dropped: list[str] = []
    npa = [record.get(k) for k in NPA_BLOCK]
    if all(isinstance(v, Decimal) and v == 0 for v in npa):          # the whole block is zero together
        dropped += [k for k in BANK_REGULATORY if isinstance(record.get(k), Decimal)]
    dropped += [k for k in ZERO_IS_MISSING if isinstance(record.get(k), Decimal) and record[k] == 0
                and k not in dropped]
    for k in dropped:
        out.pop(k, None)
    return out, dropped


def consistency_issues(records: Iterable[Mapping[str, Any]],
                       tolerance: Decimal = Decimal(1)) -> list[dict[str, Any]]:
    """Records that end on the same date but disagree on a balance-sheet / capital field, as a
    filing sometimes does between its quarterly and cumulative contexts. Differences within
    `tolerance` (rounding) are ignored."""
    by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in records:
        key = r.get("period_end") or r.get("instant")
        if key:
            by_date[key].append(r)
    issues: list[dict[str, Any]] = []
    for date_key, group in by_date.items():
        if len(group) < 2:
            continue
        for name in SNAPSHOT_FIELDS:
            values: dict[Any, Decimal] = {r.get("context_id"): r[name] for r in group if r.get(name) is not None}
            distinct = set(values.values())
            if len(distinct) <= 1 or sub(max(distinct), min(distinct)) <= tolerance:
                continue
            nonzero = [v for v in distinct if v != 0]
            smallest = min(nonzero, key=abs) if nonzero else Decimal(1)
            pct = div(mul(sub(max(distinct), min(distinct)), HUNDRED), abs(smallest)).quantize(Decimal("0.01"))
            issues.append({"period_end": date_key, "field": name, "values": values,
                           "severity": "high" if name in HIGH_SEVERITY else "low", "magnitude_pct": pct})
    return issues
