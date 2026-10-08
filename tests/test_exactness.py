"""The numeric guarantees: no floats in, results independent of global settings, and every
built-in ratio agrees with exact rational arithmetic to far below any reported digit."""
from __future__ import annotations

import ast
import decimal
import json
import random
import unittest
from datetime import date
from decimal import Decimal as D
from fractions import Fraction

from calcfinc import FinancialEngine, FinancialFact, SharePrice, SqliteRepositories, StatementType
from calcfinc.engine.evaluate import Evaluator
from calcfinc.num import to_decimal
from calcfinc.registry import metrics, ratios
from tests._fixture import make_record, seed


class TestFloatsAreRefused(unittest.TestCase):
    def test_at_every_entry_point(self):
        with self.assertRaises(TypeError):
            to_decimal(0.1)
        with self.assertRaises(TypeError):
            to_decimal(True)
        with self.assertRaises(TypeError):
            FinancialFact(entity_id=1, metric="revenue", value=0.1, statement_type=StatementType.PROFIT_AND_LOSS,
                          basis="consolidated")
        with self.assertRaises(TypeError):
            SharePrice(1, date(2026, 1, 1), 1.5, "USD")

    def test_other_bad_numbers(self):
        for bad in ("abc", "NaN", "Infinity", "1" * 35):
            with self.assertRaises(ValueError, msg=bad):
                to_decimal(bad)

    def test_ints_strings_and_decimals_are_accepted_unchanged(self):
        self.assertEqual(to_decimal(" 12.50 "), D("12.50"))
        self.assertEqual(str(to_decimal("12.50")), "12.50")
        self.assertEqual(to_decimal(7), D(7))


class TestIndependenceFromGlobalDecimalSettings(unittest.TestCase):
    def test_a_callers_low_precision_context_does_not_change_results(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        seed(repos)
        eng = FinancialEngine(repos)
        want = {name: eng.get_ratio("TEST", name).value for name in ("roce", "effective_tax_rate")}
        want_cagr = eng.get_cagr("TEST", "revenue", years=2).value
        ctx = decimal.getcontext()
        old = (ctx.prec, ctx.rounding)
        self.addCleanup(lambda: (setattr(ctx, "prec", old[0]), setattr(ctx, "rounding", old[1])))
        ctx.prec, ctx.rounding = 5, decimal.ROUND_DOWN
        for name, value in want.items():
            self.assertEqual(eng.get_ratio("TEST", name).value, value)
        self.assertEqual(eng.get_cagr("TEST", "revenue", years=2).value, want_cagr)


class TestResultsSerialiseWithoutFloats(unittest.TestCase):
    def test_to_dict_is_json_safe_and_lossless(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        seed(repos)
        res = FinancialEngine(repos).get_ratio("TEST", "roce")
        text = json.dumps(res.to_dict())
        back = json.loads(text, parse_float=lambda s: (_ for _ in ()).throw(AssertionError("float in output")))
        self.assertEqual(D(back["value"]), res.value)
        self.assertEqual(D(back["inputs"][0]["value"]), res.inputs[0].value)


# --- an independent exact evaluator: Fractions, no rounding anywhere ---------------------------

def _exact(expr: str, get):
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return Fraction(ast.get_source_segment(expr, n))
        if isinstance(n, ast.BinOp):
            return _bin(n.op, ev(n.left), ev(n.right))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "abs":
            return abs(ev(n.args[0]))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "ttm":
            return ev(n.args[0])                    # one period makes up the year
        # (a TTM over several periods is covered by the hand-computed tests)
        if isinstance(n, ast.UnaryOp):
            return -ev(n.operand)
        if isinstance(n, (ast.Name, ast.Attribute)):
            return get(_dotted(n))
        raise NotImplementedError(type(n).__name__)
    return ev(ast.parse(expr, mode="eval"))


def _bin(op, a, b):
    if isinstance(op, ast.Add):
        return a + b
    if isinstance(op, ast.Sub):
        return a - b
    if isinstance(op, ast.Mult):
        return a * b
    if isinstance(op, ast.Div):
        return a / b
    raise NotImplementedError(type(op).__name__)


def _dotted(n):
    return n.id if isinstance(n, ast.Name) else f"{_dotted(n.value)}.{n.attr}"


class TestAgreesWithExactArithmetic(unittest.TestCase):
    """Every built-in formula that uses only + - * / is recomputed with exact Fractions on
    awkward inputs; the library's result must agree to a relative error below 1e-30."""

    def test_every_plain_arithmetic_formula(self):
        rnd = random.Random(20261008)
        # core vocabulary only: whether the optional Indian adapter was registered earlier in this
        # process must not change the draw or the set of formulas checked
        core = [n for n in metrics.REGISTRY if not n.startswith("india.")]
        raw = {name: D(rnd.randint(10_000, 99_999_999)).scaleb(-rnd.randint(0, 4)) for name in core}
        rec = make_record(raw)                      # a full year, so its trailing twelve months is itself
        ev = Evaluator(rec, price=SharePrice(1, date(2026, 12, 31), "137.3719", "USD"), window=[rec])
        price = Fraction("137.3719")
        checked = 0

        def exact_value(name):
            if name == "share_price":
                return price
            if name == "period_days":
                return Fraction(365)                    # the test record spans 2026-01-01..2026-12-31
            spec = ratios.FORMULAS.get(name)
            if spec is None:
                return Fraction(raw[name])
            return _exact(spec.formula, exact_value)

        for name, spec in ratios.FORMULAS.items():
            if name.startswith("india.") or any(tok in spec.formula for tok in ("sqrt", "prior", "**")):
                continue
            got = ev.value(name).value
            self.assertIsNotNone(got, f"{name}: {ev.value(name).reason}")
            want = exact_value(name)
            if want == 0:
                self.assertEqual(got, 0, name)
                continue
            rel = abs(Fraction(got) - want) / abs(want)
            self.assertLess(rel, Fraction(1, 10**30), f"{name}: relative error {float(rel):.3e}")
            checked += 1
        self.assertGreater(checked, 55)         # the loop really covered the registry, not a handful

    def test_known_repeating_decimals(self):
        ev = Evaluator(make_record({"net_profit": 100, "total_equity": 300}))
        self.assertEqual(str(ev.value("roe").value), "33.33333333333333333333333333333333")   # 100/3, 34 digits


if __name__ == "__main__":
    unittest.main()
