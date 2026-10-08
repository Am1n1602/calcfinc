"""Load parsed SEC companyfacts into a store. Every fact is tied to the SEC filing (accession
number) it came from, so a result can be traced back to that filing."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from calcfinc.adapters.sec_companyfacts.parse import ParsedCompanyFacts, parse_companyfacts
from calcfinc.adapters.sec_companyfacts.tags import DEFAULT_FORMS
from calcfinc.entity import Entity
from calcfinc.fact import FinancialFact, Source
from calcfinc.period import DEFAULT_WINDOWS, PeriodWindows


@dataclass(frozen=True, slots=True)
class SecReport:
    entity: str
    cik: str
    facts: int
    filings: int
    derived_quarters: int
    fiscal_year_end_month: int
    notes: tuple[str, ...]


def read_companyfacts(source: str | Path | bytes) -> dict[str, Any]:
    """The JSON of a companyfacts download, with decimals read as exact Decimals."""
    text = source.decode("utf-8") if isinstance(source, bytes) else Path(source).read_text(encoding="utf-8")
    data = json.loads(text, parse_float=Decimal)
    if not isinstance(data, dict):
        raise ValueError("a companyfacts document is a JSON object")
    return data


def _filing_url(cik: str, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/"


def load_companyfacts(repos: Any, data: Mapping[str, Any], *, ticker: str | None = None,
                      fiscal_year_end_month: int | None = None, forms: Collection[str] = DEFAULT_FORMS,
                      windows: PeriodWindows = DEFAULT_WINDOWS) -> SecReport:
    """Load one company. The entity is found by its CIK (or `ticker`); a new one is created with
    the CIK as an identifier, the filer's currency and the inferred fiscal year end. An existing
    entity keeps its own fiscal year end."""
    cik = str(data.get("cik", "")).strip().zfill(10)
    ent = repos.entities.resolve(cik) or (repos.entities.resolve(ticker) if ticker else None)
    fye = ent.fiscal_year_end_month if ent else fiscal_year_end_month
    parsed: ParsedCompanyFacts = parse_companyfacts(data, fiscal_year_end_month=fye, forms=forms, windows=windows)
    try:
        if ent is None:
            ids = {"cik": parsed.cik, **({"ticker": ticker} if ticker else {})}
            ent = repos.entities.upsert(Entity(name=parsed.name, identifiers=ids, currency=parsed.currency,
                                               fiscal_year_end_month=parsed.fiscal_year_end_month))
        eid = int(ent.id or 0)
        source_ids: dict[str, int | None] = {}
        facts: list[FinancialFact] = []
        for p in parsed.facts:
            if p.accn not in source_ids:
                # The content hash here is a stable identifier for the filing (not a hash of bytes),
                # used so loading the same company twice reuses one source row per filing.
                key = hashlib.sha256(f"sec-filing:{parsed.cik}:{p.accn}".encode()).hexdigest()
                source_ids[p.accn] = repos.sources.add(Source(
                    kind="sec-filing", entity_id=eid, document_title=f"{p.form} {p.accn}",
                    uri=_filing_url(parsed.cik, p.accn), content_hash=key)).source_id
            facts.append(replace(p.fact, entity_id=eid, source_id=source_ids[p.accn]))
        repos.facts.add_many(facts)
        repos.commit()
    except Exception:
        repos.rollback()
        raise
    return SecReport(ent.name, parsed.cik, len(facts), len(source_ids), parsed.derived_quarters,
                     parsed.fiscal_year_end_month, parsed.notes)


def load_companyfacts_file(repos: Any, path: str | Path, **kwargs: Any) -> SecReport:
    return load_companyfacts(repos, read_companyfacts(path), **kwargs)
