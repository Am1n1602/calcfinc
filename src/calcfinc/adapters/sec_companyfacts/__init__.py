"""SEC `companyfacts` adapter (US-GAAP filers).

Turns the SEC's public companyfacts JSON into calcfinc facts, tied to the filing each figure
came from, with restatements kept as versions and the fourth quarter derived. Parsing and loading
take JSON you already have; `fetch_companyfacts` is the one optional function that downloads it.

    data = sec_companyfacts.read_companyfacts("CIK0000000000.json")
    sec_companyfacts.load_companyfacts(repos, data, ticker="ACME")
"""
from calcfinc.adapters.sec_companyfacts.fetch import SecFetchError, fetch_companyfacts
from calcfinc.adapters.sec_companyfacts.load import (
    SecReport,
    load_companyfacts,
    load_companyfacts_file,
    read_companyfacts,
)
from calcfinc.adapters.sec_companyfacts.parse import ParsedCompanyFacts, ParsedFact, parse_companyfacts
from calcfinc.adapters.sec_companyfacts.tags import CANDIDATES, DEFAULT_FORMS

__all__ = [
    "CANDIDATES", "DEFAULT_FORMS", "ParsedCompanyFacts", "ParsedFact", "SecFetchError", "SecReport",
    "fetch_companyfacts", "load_companyfacts", "load_companyfacts_file", "parse_companyfacts",
    "read_companyfacts",
]
