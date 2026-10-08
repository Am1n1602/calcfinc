"""SQLite reference store: entity identity, currency handling, exact decimal storage."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D

from calcfinc import Entity, FinancialFact, SharePrice, SqliteRepositories, StatementType
from calcfinc.store import AmbiguousEntity
from tests._fixture import pl


class TestEntities(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.ents = self.repos.entities

    def test_resolve_by_identifier_alias_and_name_case_insensitively(self):
        e = self.ents.upsert(Entity(name="Acme Corp", identifiers={"ticker": "ACME", "isin": "US0000000001"},
                                    aliases=("Acme Holdings",)))
        for key in ("acme", "US0000000001", "acme holdings", "ACME CORP"):
            self.assertEqual(self.ents.resolve(key).id, e.id, key)
        self.assertIsNone(self.ents.resolve("nobody"))
        self.assertIsNone(self.ents.resolve("  "))

    def test_upsert_matches_an_existing_entity_by_identifier_and_keeps_its_currency(self):
        a = self.ents.upsert(Entity(name="Acme", identifiers={"ticker": "ACME"}, currency="USD"))
        b = self.ents.upsert(Entity(name="Acme Corporation", identifiers={"ticker": "acme", "lei": "L1"}))
        self.assertEqual(a.id, b.id)
        self.assertEqual((b.name, b.currency, b.identifiers["lei"]), ("Acme Corporation", "USD", "L1"))
        self.assertEqual(len(self.ents.list()), 1)

    def test_an_ambiguous_key_raises_instead_of_guessing(self):
        self.ents.upsert(Entity(name="One", identifiers={"ticker": "X"}))
        self.ents.upsert(Entity(name="Two", identifiers={"mic": "X"}))
        with self.assertRaises(AmbiguousEntity):
            self.ents.resolve("x")

    def test_conflicting_identity_signals_raise_instead_of_merging_or_renaming(self):
        one = self.ents.upsert(Entity(name="One", identifiers={"isin": "I1"}))
        two = self.ents.upsert(Entity(name="Two", identifiers={"isin": "I2", "ticker": "T2"}))
        with self.assertRaises(ValueError):           # id says Two, the identifier belongs to One
            self.ents.upsert(Entity(id=two.id, name="Two", identifiers={"isin": "I1"}))
        with self.assertRaises(ValueError):           # two identifiers pointing at different entities
            self.ents.upsert(Entity(name="Mixed", identifiers={"isin": "I1", "ticker": "T2"}))
        self.assertEqual(self.ents.get(one.id).name, "One")           # nothing was renamed

    def test_entity_validation(self):
        for bad in ({"name": ""}, {"name": "x", "fiscal_year_end_month": 13}, {"name": "x", "currency": "dollars"}):
            with self.assertRaises(ValueError):
                Entity(**bad)


class TestCurrency(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)

    def _fact(self, eid, currency=None, metric="revenue"):
        return FinancialFact(entity_id=eid, metric=metric, value=5, currency=currency,
                             statement_type=StatementType.PROFIT_AND_LOSS, basis="consolidated",
                             period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), is_annual=True)

    def test_missing_currency_is_filled_from_the_entity_default(self):
        eid = self.repos.entities.upsert(Entity(name="A", currency="usd")).id
        self.repos.facts.add_many([self._fact(eid)])
        self.assertEqual(self.repos.facts.list_facts(eid)[0].currency, "USD")

    def test_an_amount_with_no_currency_anywhere_is_rejected(self):
        eid = self.repos.entities.upsert(Entity(name="B")).id
        with self.assertRaises(ValueError):
            self.repos.facts.add_many([self._fact(eid)])

    def test_dimensionless_metrics_need_no_currency(self):
        eid = self.repos.entities.upsert(Entity(name="C")).id
        self.repos.facts.add_many([self._fact(eid, metric="shares_outstanding")])
        self.assertIsNone(self.repos.facts.list_facts(eid)[0].currency)


class TestExactStorage(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.eid = self.repos.entities.upsert(Entity(name="A", currency="USD")).id

    def test_values_are_stored_as_text_and_read_back_exactly(self):
        exact = D("123456789012345678.123456789")           # needs 27 digits: more than a float holds
        self.repos.facts.add_many([
            pl(self.eid, "revenue", exact, 2026, None, date(2026, 1, 1), date(2026, 12, 31), annual=True),
            pl(self.eid, "net_profit", "0.1", 2026, None, date(2026, 1, 1), date(2026, 12, 31), annual=True),
            pl(self.eid, "other_income", "100.50", 2026, None, date(2026, 1, 1), date(2026, 12, 31), annual=True)])
        got = {f.metric: f.value for f in self.repos.facts.list_facts(self.eid)}
        self.assertEqual(got["revenue"], exact)
        self.assertEqual(got["net_profit"], D("0.1"))
        self.assertEqual(str(got["other_income"]), "100.50")          # the reported precision survives
        types = {r[0] for r in self.repos.connection.execute("SELECT DISTINCT typeof(value) FROM facts")}
        self.assertEqual(types, {"text"})

    def test_prices_round_trip_exactly_too(self):
        self.repos.prices.add_prices([SharePrice(self.eid, date(2026, 12, 28), "199.9999999999", "USD")])
        self.assertEqual(self.repos.prices.on_or_before(self.eid, date(2026, 12, 31)).close, D("199.9999999999"))

    def test_a_price_older_than_the_window_is_not_used(self):
        self.repos.prices.add_prices([SharePrice(self.eid, date(2026, 12, 1), 10, "USD")])
        self.assertIsNone(self.repos.prices.on_or_before(self.eid, date(2026, 12, 31)))

    def test_missing_values_stay_null_not_zero(self):
        self.repos.facts.add_many([pl(self.eid, "revenue", None, 2026, None, date(2026, 1, 1), date(2026, 12, 31))])
        self.assertIsNone(self.repos.facts.list_facts(self.eid)[0].value)
        self.assertEqual(self.repos.connection.execute("SELECT value FROM facts").fetchone()[0], None)


if __name__ == "__main__":
    unittest.main()
