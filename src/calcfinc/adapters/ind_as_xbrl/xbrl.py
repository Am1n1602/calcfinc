"""Read an XBRL instance document (.xbrl / .xml) into raw fact rows, using only the standard
library. No taxonomy and no network are needed: tags are reported as `prefix:LocalName`
exactly as the filing declares them.

The standard-library XML parser does not fetch external entities. For files from an untrusted
source, parse them with a hardened parser such as defusedxml first and pass the facts to
`canonical.map_facts` instead.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Any

XBRLI = "{http://www.xbrl.org/2003/instance}"

# Some filers (banks in particular) declare the end of the reporting period under a context
# but not its start. The primary context is always the discrete quarter, whatever the
# ReportingQuarter label says: "Yearly" and "Fourth quarter" both mean the last quarter.
_QUARTER_INDEX = {"First quarter": 0, "Half yearly": 1, "Third quarter": 2, "Fourth quarter": 3, "Yearly": 3}


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    return date(d.year + total // 12, total % 12 + 1, d.day)


def _derive_quarter_period(fy_start: str | None, reporting_quarter: str | None,
                           declared_end: str | None) -> tuple[str, str] | None:
    """(start, end) of a quarter whose context declares no start, worked out from the financial
    year start and the quarter label and cross-checked against the declared end. None whenever
    the check fails, so an unexpected filing keeps its period unset rather than mistagged."""
    n = _QUARTER_INDEX.get(reporting_quarter or "")
    if n is None or not fy_start or not declared_end:
        return None
    try:
        start = _add_months(date.fromisoformat(fy_start), 3 * n)
        end = date.fromisoformat(declared_end)
    except ValueError:
        return None
    if _add_months(start, 3) - timedelta(days=1) != end:
        return None
    return start.isoformat(), end.isoformat()


def _on_quarter_boundary(start: str | None, fy_start: str | None) -> bool:
    """Does a declared period start fall where a quarter of the financial year starts? One filing
    declared 10 January and 4 January for 1 October and 1 April (day and month swapped); its
    contexts were right. With no financial year start to test against, the declaration is believed."""
    if not fy_start or not start:
        return True
    try:
        s, f = date.fromisoformat(start), date.fromisoformat(fy_start)
    except ValueError:
        return False
    return s.day == f.day and (s.year * 12 + s.month - f.year * 12 - f.month) % 3 == 0


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def parse_xbrl_file(path: str | Path, company: str = "") -> list[dict[str, Any]]:
    """Facts of one instance document as raw rows (see `canonical.map_facts`)."""
    data = Path(path).read_bytes()
    prefix_of: dict[str, str] = {}
    elements: list[ET.Element] = []
    for event, item in ET.iterparse(io.BytesIO(data), events=("start-ns", "end")):
        if event == "start-ns":
            prefix, uri = item
            if prefix:
                prefix_of.setdefault(uri, prefix)
        else:
            elements.append(item)
    root = elements[-1]                                           # the root element ends last

    def qname(elem: ET.Element) -> str:
        if "}" not in elem.tag:
            return elem.tag
        uri, local = elem.tag[1:].split("}")
        return f"{prefix_of.get(uri, uri)}:{local}"

    contexts: dict[str, dict[str, str | None]] = {}
    for context in root.iter(XBRLI + "context"):
        period = context.find(XBRLI + "period")
        contexts[context.get("id", "")] = {
            "instant": period.findtext(XBRLI + "instant") if period is not None else None,
            "start": period.findtext(XBRLI + "startDate") if period is not None else None,
            "end": period.findtext(XBRLI + "endDate") if period is not None else None}

    units = {u.get("id", ""): u.findtext(".//" + XBRLI + "measure") for u in root.iter(XBRLI + "unit")}

    # Periods the filing declares about itself, as plain facts under the same context. A few
    # filings give a <context> period that is wrong while these facts are right, so they win.
    declared: dict[str, dict[str, str | None]] = {}
    keys = {"DateOfStartOfReportingPeriod": "start", "DateOfEndOfReportingPeriod": "end",
            "ReportingQuarter": "quarter", "DateOfStartOfFinancialYear": "fy_start"}
    for elem in root.iter():
        ref = elem.get("contextRef")
        if ref is not None and _local(elem.tag) in keys:
            declared.setdefault(ref, {})[keys[_local(elem.tag)]] = elem.text
    for info in declared.values():
        if info.get("start") or not info.get("end"):
            continue
        derived = _derive_quarter_period(info.get("fy_start"), info.get("quarter"), info["end"])
        if derived:
            info["start"], info["end"] = derived

    fy_start = next((i["fy_start"] for i in declared.values() if i.get("fy_start")), None)
    rows: list[dict[str, Any]] = []
    for elem in root.iter():
        ref = elem.get("contextRef")
        if ref is None:
            continue
        ctx = dict(contexts.get(ref, {}))
        own = declared.get(ref)
        if own and own.get("start") and own.get("end") and (
                not (ctx.get("start") and ctx.get("end")) or _on_quarter_boundary(own["start"], fy_start)):
            ctx["start"], ctx["end"], ctx["instant"] = own["start"], own["end"], None
        unit_ref = elem.get("unitRef")
        rows.append({
            "company": company, "line_item_tag": qname(elem), "value": elem.text,
            "unit": units.get(unit_ref) if unit_ref else None, "context_id": ref,
            "period_start": ctx.get("start"), "period_end": ctx.get("end"), "instant": ctx.get("instant"),
            "decimals": elem.get("decimals"), "sign": elem.get("sign"), "source_doc": str(path)})
    return rows
