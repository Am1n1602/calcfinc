"""Ind-AS (India) adapter.

Reads exchange XBRL filings (a .xbrl file, raw fact rows, or canonical records) into
calcfinc facts: April-March fiscal year, INR, exact Decimal values, review flags for records
whose own arithmetic fails. Also holds the India-only vocabulary and the `india.*` ratios
(`register()`), so the core stays free of country names.

    from calcfinc.adapters import ind_as_xbrl
    ind_as_xbrl.load_xbrl_file(repos, "results_consolidated.xbrl", entity="ACME")
"""
from calcfinc.adapters.ind_as_xbrl.canonical import consistency_issues, map_facts, parse_number
from calcfinc.adapters.ind_as_xbrl.load import (
    IndAsReport,
    load_canonical,
    load_canonical_file,
    load_raw_facts,
    load_xbrl_file,
    read_canonical_json,
    record_to_facts,
)
from calcfinc.adapters.ind_as_xbrl.vocab import RENAMES, register, shares_outstanding
from calcfinc.adapters.ind_as_xbrl.xbrl import parse_xbrl_file

__all__ = [
    "IndAsReport", "RENAMES", "consistency_issues", "load_canonical", "load_canonical_file",
    "load_raw_facts", "load_xbrl_file", "map_facts", "parse_number", "parse_xbrl_file",
    "read_canonical_json", "record_to_facts", "register", "shares_outstanding",
]
