"""Hostile and malformed input: every one of these must end in a clear error or a None with a reason,
never a crash, a hang or a silently wrong number. Expected outcomes are stated, not read back."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D

from calcfinc import (
    Basis,
    Entity,
    FinancialEngine,
    FinancialFact,
    Segment,
    SharePrice,
    Source,
    SqliteRepositories,
    StatementType,
    register_metric,
    register_ratio,
)
from calcfinc.engine import EngineError
from calcfinc.fact import SegmentFact
from calcfinc.formula import MAX_LENGTH, CalcError, calculate, names_in
from calcfinc.loaders import LoadError
from calcfinc.num import to_decimal
from calcfinc.registry import RatioSpec

ROWS = [{"entity": "A", "metric": "revenue", "period": "FY2025", "value": "100", "currency": "USD"},
        {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "150", "currency": "USD"}]


class TestFormulaInput(unittest.TestCase):
    def test_every_disallowed_construct_is_a_calc_error(self):
        for bad in ("1 if 2 else 3", "1 < 2", "1 and 2", "f'{1}'", "(x := 1)", "max(*[1, 2])", "a[0]",
                    "abs(1).real", "abs(1, 2)", "round(1, 0.5)", "sqrt(-1)", "0 ** -1", "prior(1 + 2)",
                    "ttm()", "abs(x=1)", "not a", "a if a else a", "1 @ 2", "~a"):
            with self.assertRaises(CalcError, msg=bad):
                calculate(bad, a=1)

    def test_runaway_expressions_are_errors_not_crashes(self):
        for name, expr in (("long chain", "+".join(["1"] * 20000)), ("deep unary", "-" * 5000 + "1"),
                           ("over the length cap", "1" + " + 1" * MAX_LENGTH), ("huge power", "9 ** 9 ** 9")):
            with self.assertRaises(CalcError, msg=name):
                calculate(expr)
        with self.assertRaises(CalcError):
            names_in("+".join(["a"] * 20000))

    def test_numbers_outside_the_supported_exponent_range_are_refused(self):
        with self.assertRaises(CalcError):
            calculate("1e999999999")
        for bad in ("1e1000", D("1E+999999999"), "0E+99999", "1e-1000"):
            with self.assertRaises(ValueError, msg=str(bad)):
                to_decimal(bad)
        self.assertEqual(to_decimal("1e999"), D("1e999"))                    # the edge itself is fine

    def test_an_ordinary_deeply_parenthesised_formula_still_works(self):
        self.assertEqual(calculate("(" * 100 + "1" + ")" * 100), 1)


class TestFactValidation(unittest.TestCase):
    def test_bad_facts_are_refused_at_construction(self):
        base = dict(entity_id=1, statement_type=StatementType.PROFIT_AND_LOSS, basis=Basis.CONSOLIDATED, value=1)
        for override, error in (({"metric": ""}, ValueError), ({"metric": "revenue", "quarter": 5}, ValueError),
                                ({"metric": "revenue", "value": 0.5}, TypeError)):
            with self.assertRaises(error, msg=str(override)):
                FinancialFact(**{**base, **override})
        with self.assertRaises(ValueError):
            Source(kind="")
        with self.assertRaises(ValueError):
            Segment(entity_id=1, name="")
        with self.assertRaises(ValueError):
            SegmentFact(segment_id=1, entity_id=1, metric="", value=None, basis="consolidated")

    def test_soft_validation_names_each_inconsistency(self):
        base = dict(entity_id=1, statement_type=StatementType.PROFIT_AND_LOSS, basis=Basis.CONSOLIDATED)
        missing = FinancialFact(metric="revenue", value=None, **base)
        self.assertIn("mapping_reason is empty", missing.problems()[0])
        instant = FinancialFact(metric="total_assets", value=1, is_point_in_time=True,
                                period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), **base)
        self.assertIn("should not have a period_start", instant.problems()[0])
        annual = FinancialFact(metric="revenue", value=1, is_annual=True, quarter=2, **base)
        self.assertIn("should not carry a quarter", annual.problems()[0])
        self.assertEqual(FinancialFact(metric="revenue", value=1, **base).problems(), [])

    def test_entity_and_price_validation(self):
        for kwargs in ({"name": ""}, {"name": "x", "fiscal_year_end_month": 13}, {"name": "x", "currency": "US"}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                Entity(**kwargs)
        with self.assertRaises(TypeError):
            SharePrice(entity_id=1, price_date=date(2025, 1, 1), close=0.5, currency="USD")      # a float
        with self.assertRaises(ValueError):
            SharePrice(entity_id=1, price_date=date(2025, 1, 1), close=D("5"), currency="dollars")


class TestRegistryValidation(unittest.TestCase):
    def test_bad_metric_registrations(self):
        for name, kind in (("Revenue", "currency"), ("a b", "currency"), ("zz_test_ok", "money")):
            with self.assertRaises(ValueError, msg=name):
                register_metric(name, kind, StatementType.OTHER)
        register_metric("zz_test_metric", "x", StatementType.OTHER)
        register_metric("zz_test_metric", "x", StatementType.OTHER)                 # identical: no-op
        with self.assertRaises(ValueError):
            register_metric("zz_test_metric", "pct", StatementType.OTHER)           # different: refused

    def test_bad_ratio_registrations(self):
        cases = {
            "bad name": lambda: RatioSpec("Bad Name", "x", "revenue"),
            "bad unit": lambda: RatioSpec("zz_r1", "furlongs", "revenue"),
            "bad formula": lambda: RatioSpec("zz_r2", "x", "revenue +"),
            "optional not used": lambda: RatioSpec("zz_r3", "x", "revenue", optional=("net_profit",)),
            "requires_positive not used": lambda: RatioSpec("zz_r4", "x", "revenue",
                                                            requires_positive=("net_profit",)),
        }
        for label, build in cases.items():
            with self.assertRaises(ValueError, msg=label):
                build()
        with self.assertRaises(ValueError):
            register_ratio(RatioSpec("zz_r5", "x", "no_such_metric / revenue"))      # typo caught at registration
        with self.assertRaises(ValueError):
            register_ratio(RatioSpec("zz_r6", "x", "zz_r6 / revenue"))               # cannot use itself
        with self.assertRaises(ValueError):
            register_ratio(RatioSpec("zz_r7", "x", "ttm(total_assets)"))             # a balance cannot be summed
        with self.assertRaises(ValueError):
            register_ratio(RatioSpec("revenue", "x", "net_profit"))                  # name of a reported metric
        with self.assertRaises(ValueError):
            register_ratio(RatioSpec("roe", "pct", "net_profit"))                    # built-in redefined


class TestEngineArguments(unittest.TestCase):
    def setUp(self):
        self.eng = FinancialEngine.from_records(ROWS)
        self.addCleanup(self.eng.repos.close)

    def test_engine_error_is_a_value_error(self):
        self.assertTrue(issubclass(EngineError, ValueError))

    def test_unusable_arguments_are_engine_errors(self):
        for call in (lambda: self.eng.get_metric(None, "revenue"), lambda: self.eng.get_metric(7, "revenue"),
                     lambda: self.eng.get_metric("nope", "revenue"),
                     lambda: self.eng.get_metric("A", "revenue", period="garbage"),
                     lambda: self.eng.get_metric("A", "revenue", period=True)):
            with self.assertRaises(EngineError):
                call()
        with self.assertRaises(ValueError):
            self.eng.get_metric("A", "revenue", basis="weird")

    def test_questions_with_no_answer_are_none_with_a_reason_not_errors(self):
        for result in (self.eng.get_metric("A", ""), self.eng.get_ratio("A", "no_such_ratio"),
                       self.eng.get_growth("A", "revenue", kind="decade"),
                       self.eng.get_cagr("A", "net_profit"), self.eng.calculate("a + 1", a=0.5)):
            self.assertIsNone(result.value)
            self.assertTrue(result.limitations)

    def test_cagr_needs_a_positive_span_and_start(self):
        self.assertEqual(self.eng.get_cagr("A", "revenue", years=1).value, 50)           # 150 / 100 - 1
        # sqrt(1.5) = 1.22474487139158904909864203735..., so two years give 22.4744871391589049098642...
        two = self.eng.get_cagr("A", "revenue", years=2).value
        self.assertLess(abs(two - D("22.47448713915890490986420")), D("1e-20"))

    def test_a_row_that_is_not_a_mapping_is_a_load_error_naming_the_row(self):
        with self.assertRaises(LoadError) as ctx:
            FinancialEngine.from_records([ROWS[0], 7])
        self.assertIn("row 2: expected a mapping", "\n".join(ctx.exception.errors))

    def test_a_misspelt_metric_gets_a_suggestion(self):
        with self.assertRaises(LoadError) as ctx:
            FinancialEngine.from_records([{"entity": "A", "metric": "revnue", "period": "FY2026", "value": "1"}])
        self.assertIn("did you mean 'revenue'?", ctx.exception.errors[0])
        with self.assertRaises(LoadError) as ctx:
            FinancialEngine.from_records([{"entity": "A", "metric": "qqqqqqqq", "period": "FY2026", "value": "1"}])
        self.assertNotIn("did you mean", ctx.exception.errors[0])

    def test_an_empty_source_gives_an_engine_that_knows_no_entity(self):
        eng = FinancialEngine.from_records([])
        self.addCleanup(eng.repos.close)
        with self.assertRaises(EngineError):
            eng.get_metric("A", "revenue")


class TestRowValidation(unittest.TestCase):
    """Each bad row is named with its column; nothing is loaded; a failure while storing rolls back."""

    BASE = {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "1", "currency": "USD"}

    def errors(self, **override):
        row = {**self.BASE, **override}
        row = {k: v for k, v in row.items() if v is not None}
        with self.assertRaises(LoadError) as ctx:
            FinancialEngine.from_records([row])
        return "\n".join(ctx.exception.errors)

    def test_each_kind_of_bad_cell_is_reported_with_its_column(self):
        cases = (
            ({"period": None, "period_end": "31/12/2026"}, "period_end: '31/12/2026' is not a date"),
            ({"quarter": "two"}, "quarter: 'two' is not a whole number"),
            ({"is_annual": "maybe"}, "is_annual: 'maybe' is not true/false"),
            ({"period": "FY2026", "period_end": "2026-12-31"}, "give either period or period_start/period_end"),
            ({"period": None}, "required: give period or period_end"),
            ({"period": None, "period_start": "2026-12-31", "period_end": "2026-01-01"}, "is before period_start"),
            ({"period": None, "period_end": "2026-12-31"}, "is a flow metric and needs a period range"),
            ({"entity": None}, "entity: required"),
            ({"metric": None}, "metric: required"),
            ({"statement_type": "ledger"}, "'ledger' is not one of"),
            ({"currency": None}, "is an amount: add a currency column"),
            ({"basis": "pro_forma"}, "pro_forma"),
            ({"value": "1,200"}, "write 1200.5, not 1,200.5"),
            ({"quarter": "5"}, "quarter must be 1..4"),
        )
        for override, expected in cases:
            self.assertIn(expected, self.errors(**override), msg=str(override))

    def test_date_objects_and_booleans_are_accepted_as_they_are(self):
        from datetime import datetime
        eng = FinancialEngine.from_records([{
            "entity": "A", "metric": "revenue", "period_start": date(2026, 1, 1),
            "period_end": datetime(2026, 12, 31, 9, 30), "value": "5", "currency": "USD",
            "is_annual": True, "reported_at": date(2027, 2, 1)}])
        self.addCleanup(eng.repos.close)
        r = eng.get_metric("A", "revenue", period="FY2026")
        self.assertEqual((r.value, r.inputs[0].reported_at), (5, date(2027, 2, 1)))

    def test_a_custom_metric_can_be_loaded_without_registration_by_naming_its_statement(self):
        eng = FinancialEngine.from_records([{
            "entity": "A", "metric": "zz_unregistered", "statement_type": "profit_and_loss",
            "period": "FY2026", "value": "7", "currency": "USD"}])
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_metric("A", "zz_unregistered").value, 7)

    def test_a_failure_while_storing_rolls_back_and_raises(self):
        class Broken(SqliteRepositories):
            rolled_back = False

            def rollback(self):
                Broken.rolled_back = True
                super().rollback()

        repos = Broken(":memory:")
        self.addCleanup(repos.close)

        def boom(_facts):
            raise RuntimeError("disk full")

        repos.facts.add_many = boom
        from calcfinc.loaders import load_records
        with self.assertRaises(RuntimeError):
            load_records(repos, [self.BASE])
        self.assertTrue(Broken.rolled_back)
        self.assertEqual(repos.entities.list(), [])                     # the entity created for the load is gone


try:
    import pandas as pd
except ImportError:                                                     # pragma: no cover
    pd = None


@unittest.skipIf(pd is None, "pandas is not installed")
class TestDataFrameEdges(unittest.TestCase):
    def test_bad_options_are_refused(self):
        from calcfinc.loaders import frame_to_rows
        df = pd.DataFrame({"metric": ["revenue"], "FY2026": ["1"]})
        for kwargs in ({"float_policy": "guess"}, {"layout": "diagonal"}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                frame_to_rows(df, **kwargs)
        with self.assertRaises(ValueError):
            frame_to_rows(pd.DataFrame({"name": ["revenue"], "FY2026": ["1"]}), layout="wide")

    def test_an_index_named_metric_counts_and_ints_and_bools_pass_through(self):
        from calcfinc.loaders import frame_to_rows
        df = pd.DataFrame({"FY2026": [1200, 150]}, index=pd.Index(["revenue", "net_profit"], name="metric"))
        rows, converted = frame_to_rows(df, layout="wide")
        self.assertEqual([(r["metric"], r["period"], r["value"]) for r in rows],
                         [("revenue", "FY2026", 1200), ("net_profit", "FY2026", 150)])
        self.assertEqual(converted, 0)
        long = pd.DataFrame({"entity": ["A"], "metric": ["revenue"], "period": ["FY2026"], "value": [5],
                             "currency": ["USD"], "is_annual": [True], "quarter": [float("nan")]})
        (row,), _ = frame_to_rows(long)
        self.assertEqual((row["value"], row["is_annual"], row["quarter"]), (5, True, None))

    def test_floats_are_converted_through_their_shortest_text_and_nan_means_not_reported(self):
        from calcfinc.loaders import frame_to_rows
        df = pd.DataFrame({"metric": ["revenue", "net_profit"], "FY2026": [0.1, float("nan")]})
        rows, converted = frame_to_rows(df, layout="wide", float_policy="repr")
        self.assertEqual([(r["metric"], r["value"]) for r in rows], [("revenue", "0.1")])      # NaN cell: no fact
        self.assertEqual(converted, 2)                                       # every float cell handled, NaN included
        with self.assertRaises(TypeError):
            frame_to_rows(df, layout="wide")


class TestStoreLifecycle(unittest.TestCase):
    def test_closing_twice_is_harmless_and_use_after_close_is_an_error(self):
        repos = SqliteRepositories(":memory:")
        repos.close()
        repos.close()
        with self.assertRaises(Exception) as ctx:
            repos.entities.resolve("A")
        self.assertIn("closed", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
