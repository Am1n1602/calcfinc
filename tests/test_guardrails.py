"""Acceptance test 6: structural guarantees about the library itself."""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

from calcfinc.adapters import ind_as_xbrl
from calcfinc.engine.evaluate import Evaluator
from calcfinc.registry import metrics, ratios
from tests._fixture import make_record

SRC = Path(__file__).resolve().parents[1] / "src" / "calcfinc"
CORE = [p for p in SRC.rglob("*") if p.suffix in (".py", ".sql") and "adapters" not in p.parts]
NETWORK = {"socket", "ssl", "http", "urllib", "ftplib", "smtplib", "xmlrpc", "requests", "httpx", "aiohttp"}


class TestCoreIsGeneric(unittest.TestCase):
    def test_no_country_or_exchange_names_in_core(self):
        pattern = re.compile(r"\b(INR|NSE|BSE|Exchange|bse_scrip|RBI|IRDAI|SEBI)\b")
        hits = [f"{p.relative_to(SRC)}:{n}" for p in CORE
                for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
        self.assertEqual(hits, [])
        self.assertTrue(CORE)                                  # the scan really found the core files

    def test_india_specific_names_are_not_core_metrics(self):
        # A fresh interpreter, so nothing another test registered can mask a leak into the core.
        code = ("from calcfinc.registry import metrics; "
                "print(sorted(set(metrics.REGISTRY) & {'paid_up_equity_capital', 'face_value_per_share', "
                "'debt_equity_ratio_reported', 'pat_continuing_ops'}))")
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "[]")

    def test_adapter_registers_its_names_idempotently(self):
        ind_as_xbrl.register()
        ind_as_xbrl.register()
        self.assertIn("paid_up_equity_capital", metrics.REGISTRY)
        self.assertEqual(ind_as_xbrl.shares_outstanding(D(100), D(10)), 10)
        self.assertIsNone(ind_as_xbrl.shares_outstanding(D(100), D(0)))


FETCHER = Path("adapters") / "sec_companyfacts" / "fetch.py"     # the one file that may reach the network


class TestNoDependencies(unittest.TestCase):
    def test_only_the_standard_library_is_imported_and_only_the_fetcher_may_use_the_network(self):
        offenders = []
        for p in SRC.rglob("*.py"):
            rel = p.relative_to(SRC)
            allowed = {"urllib"} if rel == FETCHER else set()
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
                for m in mods:
                    top = m.split(".")[0]
                    if top and top != "calcfinc" and (
                            top not in sys.stdlib_module_names or (top in NETWORK and top not in allowed)):
                        offenders.append(f"{rel}: {m}")
        self.assertEqual(offenders, [])

    def test_nothing_in_the_library_calls_the_fetcher(self):
        users = sorted(str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
                       if p.relative_to(SRC) != FETCHER and "fetch_companyfacts" in p.read_text(encoding="utf-8"))
        self.assertEqual(users, [str(Path("adapters") / "sec_companyfacts" / "__init__.py")])   # a re-export only

    def test_importing_the_core_loads_no_network_module(self):
        code = ("import sys, calcfinc; "
                "print(sorted(m for m in ('urllib.request', 'http.client', 'socket', 'ssl') if m in sys.modules))")
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "[]")


class TestMissingInputsAreNeverZero(unittest.TestCase):
    """Every registered formula, on an empty record and on an all-zero record, either gives a
    number or gives None with a reason. It never raises and never returns a silent 0 for
    missing data."""

    def test_empty_record_gives_none_with_a_reason_for_every_formula(self):
        for name, spec in ratios.FORMULAS.items():
            out = Evaluator(make_record({})).value(name)
            if spec.optional and out.value is not None:
                continue                                       # optional inputs legitimately default to 0
            self.assertIsNone(out.value, name)
            self.assertTrue(out.reason, name)

    def test_all_zero_record_never_raises_and_explains_every_none(self):
        zeros = {n: 0 for n in metrics.REGISTRY}
        for name in ratios.FORMULAS:
            out = Evaluator(make_record(zeros)).value(name)
            if out.value is None:
                self.assertTrue(out.reason, name)

    def test_only_declared_optional_inputs_default_to_zero(self):
        # finance_costs is optional for EBIT, so a missing one counts as 0 -- and the result says so.
        out = Evaluator(make_record({"pbt_before_exceptional": 100})).value("ebit")
        self.assertEqual(out.value, 100)
        self.assertTrue(any("finance_costs not reported; treated as 0" in n for n in out.notes))
        # depreciation is not optional for EBITDA, so its absence gives None, never 0.
        none = Evaluator(make_record({"pbt_before_exceptional": 100, "other_income": 0})).value("ebitda")
        self.assertIsNone(none.value)


if __name__ == "__main__":
    unittest.main()
