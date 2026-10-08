"""SQLite reference repositories (stdlib sqlite3; `:memory:` works). Decimals are stored as
exact text, never as REAL."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from calcfinc.entity import Entity
from calcfinc.fact import (
    Basis,
    FinancialFact,
    MappingConfidence,
    Segment,
    SegmentFact,
    SharePrice,
    Source,
    StatementType,
)
from calcfinc.num import to_decimal, to_text
from calcfinc.registry import metrics
from calcfinc.store.base import PRICE_WINDOW_DAYS, AmbiguousEntity

_log = logging.getLogger("calcfinc.sqlite")
_SCHEMA = Path(__file__).with_name("schema.sql")
_OVERWRITE_ABS = Decimal(1)
_OVERWRITE_REL = Decimal("0.0005")


# --------------------------------------------------------------------------- #
# scalar helpers
# --------------------------------------------------------------------------- #

def _ds(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _vs(v: Decimal | None) -> str | None:
    return to_text(v) if v is not None else None


def _vd(s: str | None) -> Decimal | None:
    return to_decimal(s) if s is not None else None


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


# --------------------------------------------------------------------------- #
# repositories
# --------------------------------------------------------------------------- #

class SqliteEntityRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def _build(self, row: sqlite3.Row) -> Entity:
        eid = row["id"]
        ids = {r["scheme"]: r["value"] for r in self._c.execute(
            "SELECT scheme, value FROM entity_identifiers WHERE entity_id = ? ORDER BY scheme", (eid,))}
        aliases = tuple(r["alias"] for r in self._c.execute(
            "SELECT alias FROM entity_aliases WHERE entity_id = ? ORDER BY alias", (eid,)))
        return Entity(id=eid, name=row["name"], kind=row["kind"], identifiers=ids, aliases=aliases,
                      currency=row["currency"], fiscal_year_end_month=row["fiscal_year_end_month"],
                      sector=row["sector"])

    def _find_id(self, e: Entity) -> int | None:
        matched = {int(r["entity_id"]) for scheme, value in e.identifiers.items() for r in self._c.execute(
            "SELECT entity_id FROM entity_identifiers WHERE scheme = ? AND value = ? COLLATE NOCASE",
            (scheme, value))}
        by_id = e.id is not None and self._c.execute("SELECT 1 FROM entities WHERE id = ?", (e.id,)).fetchone()
        # Conflicting signals must not silently merge or rename entities.
        if len(matched) > 1 or (matched and by_id and e.id not in matched):
            raise ValueError(f"identifiers of {e.name!r} match different existing entities; "
                             "resolve the conflict before upserting")
        if matched:
            return next(iter(matched))
        if by_id:
            return e.id
        if not e.identifiers:
            row = self._c.execute(
                "SELECT id FROM entities WHERE name = ? COLLATE NOCASE ORDER BY id", (e.name,)).fetchone()
            if row:
                return int(row["id"])
        return None

    def upsert(self, entity: Entity) -> Entity:
        eid = self._find_id(entity)
        if eid is None:
            cur = self._c.execute(
                "INSERT INTO entities (name, kind, currency, fiscal_year_end_month, sector) VALUES (?, ?, ?, ?, ?)",
                (entity.name, entity.kind, entity.currency, entity.fiscal_year_end_month, entity.sector))
            eid = int(cur.lastrowid or 0)
        else:
            self._c.execute(
                "UPDATE entities SET name = ?, kind = ?, currency = COALESCE(?, currency), "
                "fiscal_year_end_month = ?, sector = COALESCE(?, sector) WHERE id = ?",
                (entity.name, entity.kind, entity.currency, entity.fiscal_year_end_month, entity.sector, eid))
        for scheme, value in entity.identifiers.items():
            try:
                self._c.execute(
                    "INSERT INTO entity_identifiers (entity_id, scheme, value) VALUES (?, ?, ?) "
                    "ON CONFLICT (entity_id, scheme) DO UPDATE SET value = excluded.value",
                    (eid, scheme, value))
            except sqlite3.IntegrityError:
                raise ValueError(f"identifier {scheme}={value!r} already belongs to another entity") from None
        for alias in entity.aliases:
            self.add_alias(eid, alias)
        got = self.get(eid)
        assert got is not None
        return got

    def get(self, entity_id: int) -> Entity | None:
        row = self._c.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        return self._build(row) if row else None

    def resolve(self, key: str) -> Entity | None:
        key = (key or "").strip()
        if not key:
            return None
        tiers = (
            "SELECT DISTINCT entity_id AS id FROM entity_identifiers WHERE value = ? COLLATE NOCASE",
            "SELECT DISTINCT entity_id AS id FROM entity_aliases WHERE alias = ? COLLATE NOCASE",
            "SELECT id FROM entities WHERE name = ? COLLATE NOCASE",
        )
        for sql in tiers:
            ids = sorted({int(r["id"]) for r in self._c.execute(sql, (key,))})
            if len(ids) > 1:
                raise AmbiguousEntity(f"{key!r} matches {len(ids)} entities; use a more specific key")
            if ids:
                return self.get(ids[0])
        return None

    def list(self) -> list[Entity]:
        return [self._build(r) for r in self._c.execute("SELECT * FROM entities ORDER BY id")]

    def add_alias(self, entity_id: int, alias: str) -> None:
        if alias:
            self._c.execute(
                "INSERT OR IGNORE INTO entity_aliases (entity_id, alias) VALUES (?, ?)", (entity_id, alias))


class SqliteSourceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    @staticmethod
    def _row(r: sqlite3.Row) -> Source:
        rt = r["retrieved_at"]
        return Source(source_id=r["source_id"], kind=r["kind"], entity_id=r["entity_id"],
                      document_title=r["document_title"], uri=r["uri"], content_hash=r["content_hash"],
                      retrieved_at=datetime.fromisoformat(rt) if rt else None,
                      period_label=r["period_label"])

    def add(self, source: Source) -> Source:
        if source.content_hash:
            existing = self.get_by_hash(source.content_hash)
            if existing is not None:
                return existing
        cur = self._c.execute(
            "INSERT INTO sources (kind, entity_id, document_title, uri, content_hash, retrieved_at, "
            "period_label) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source.kind, source.entity_id, source.document_title, source.uri, source.content_hash,
             source.retrieved_at.isoformat() if source.retrieved_at else None, source.period_label))
        got = self.get(int(cur.lastrowid or 0))
        assert got is not None
        return got

    def get(self, source_id: int) -> Source | None:
        row = self._c.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        return self._row(row) if row else None

    def get_by_hash(self, content_hash: str) -> Source | None:
        row = self._c.execute("SELECT * FROM sources WHERE content_hash = ?", (content_hash,)).fetchone()
        return self._row(row) if row else None


class SqliteFactRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    @staticmethod
    def _row(r: sqlite3.Row) -> FinancialFact:
        return FinancialFact(
            entity_id=r["entity_id"], metric=r["metric"], value=_vd(r["value"]),
            statement_type=StatementType(r["statement_type"]), basis=Basis(r["basis"]),
            currency=r["currency"], period_start=_d(r["period_start"]), period_end=_d(r["period_end"]),
            financial_year=r["financial_year"], quarter=r["quarter"], is_annual=bool(r["is_annual"]),
            is_point_in_time=bool(r["is_point_in_time"]), reported_at=_d(r["reported_at"]),
            source_id=r["source_id"], mapping_confidence=MappingConfidence(r["mapping_confidence"]),
            mapping_reason=r["mapping_reason"])

    def _with_currency(self, f: FinancialFact, defaults: dict[int, str | None]) -> FinancialFact:
        spec = metrics.get(f.metric)
        if f.currency is not None or spec is None or spec.kind not in metrics.CURRENCY_KINDS:
            return f
        if f.entity_id not in defaults:
            row = self._c.execute("SELECT currency FROM entities WHERE id = ?", (f.entity_id,)).fetchone()
            defaults[f.entity_id] = row["currency"] if row else None
        cur = defaults[f.entity_id]
        if cur is None:
            raise ValueError(f"currency required for {f.metric!r}: set it on the fact or give the "
                             "entity a default currency")
        return replace(f, currency=cur)

    def add_many(self, facts: Iterable[FinancialFact]) -> int:
        """Upserts on the (entity, metric, basis, statement_type, period, reported_at) grain.
        Overwriting a value at the same grain with a materially different one is logged: it is
        a plain overwrite, not a precedence decision, so a source conflict stays visible."""
        defaults: dict[int, str | None] = {}
        n = 0
        for raw in facts:
            f = self._with_currency(raw, defaults)
            key = (f.entity_id, f.metric, f.basis.value, f.statement_type.value,
                   _ds(f.period_end) or "", _ds(f.period_start) or "", _ds(f.reported_at) or "")
            if f.value is not None:
                old_row = self._c.execute(
                    "SELECT value FROM facts WHERE entity_id = ? AND metric = ? AND basis = ? "
                    "AND statement_type = ? AND COALESCE(period_end, '') = ? "
                    "AND COALESCE(period_start, '') = ? AND COALESCE(reported_at, '') = ?", key).fetchone()
                old = _vd(old_row["value"]) if old_row else None
                if old is not None and abs(old - f.value) > max(_OVERWRITE_ABS, abs(old) * _OVERWRITE_REL):
                    _log.warning("facts overwrite changes value: entity_id=%s metric=%s basis=%s "
                                 "period=%s..%s old=%s new=%s", f.entity_id, f.metric, f.basis.value,
                                 f.period_start, f.period_end, old, f.value)
            self._c.execute(
                "INSERT INTO facts (entity_id, metric, value, currency, period_start, period_end, "
                "financial_year, quarter, statement_type, basis, is_annual, is_point_in_time, "
                "reported_at, source_id, mapping_confidence, mapping_reason) "
                "VALUES (:entity_id, :metric, :value, :currency, :period_start, :period_end, "
                ":financial_year, :quarter, :statement_type, :basis, :is_annual, :is_point_in_time, "
                ":reported_at, :source_id, :mapping_confidence, :mapping_reason) "
                "ON CONFLICT (entity_id, metric, basis, statement_type, COALESCE(period_end, ''), "
                "COALESCE(period_start, ''), COALESCE(reported_at, '')) DO UPDATE SET "
                "value = excluded.value, currency = excluded.currency, "
                "financial_year = excluded.financial_year, quarter = excluded.quarter, "
                "is_annual = excluded.is_annual, is_point_in_time = excluded.is_point_in_time, "
                "source_id = COALESCE(excluded.source_id, facts.source_id), "
                "mapping_confidence = excluded.mapping_confidence, "
                "mapping_reason = excluded.mapping_reason",
                {"entity_id": f.entity_id, "metric": f.metric, "value": _vs(f.value),
                 "currency": f.currency, "period_start": _ds(f.period_start),
                 "period_end": _ds(f.period_end), "financial_year": f.financial_year,
                 "quarter": f.quarter, "statement_type": f.statement_type.value,
                 "basis": f.basis.value, "is_annual": int(f.is_annual),
                 "is_point_in_time": int(f.is_point_in_time), "reported_at": _ds(f.reported_at),
                 "source_id": f.source_id, "mapping_confidence": f.mapping_confidence.value,
                 "mapping_reason": f.mapping_reason})
            n += 1
        return n

    def list_facts(self, entity_id: int, *, basis: Basis | str | None = None,
                   metric: str | None = None) -> list[FinancialFact]:
        clauses = ["entity_id = ?"]
        params: list[Any] = [entity_id]
        if basis is not None:
            clauses.append("basis = ?")
            params.append(Basis(basis).value)
        if metric is not None:
            clauses.append("metric = ?")
            params.append(metric)
        rows = self._c.execute(
            f"SELECT * FROM facts WHERE {' AND '.join(clauses)} "
            "ORDER BY (period_end IS NULL), period_end, (period_start IS NULL), period_start, "
            "(reported_at IS NOT NULL), reported_at, fact_id", params)
        return [self._row(r) for r in rows]


class SqliteSegmentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    @staticmethod
    def _seg(r: sqlite3.Row) -> Segment:
        return Segment(entity_id=r["entity_id"], name=r["name"], slug=r["slug"], segment_id=r["segment_id"])

    @staticmethod
    def _fact(r: sqlite3.Row) -> SegmentFact:
        return SegmentFact(
            segment_id=r["segment_id"], entity_id=r["entity_id"], metric=r["metric"],
            value=_vd(r["value"]), basis=Basis(r["basis"]), currency=r["currency"],
            period_start=_d(r["period_start"]), period_end=_d(r["period_end"]),
            financial_year=r["financial_year"], quarter=r["quarter"],
            is_annual=bool(r["is_annual"]), source_id=r["source_id"])

    def upsert_segment(self, segment: Segment) -> Segment:
        self._c.execute(
            "INSERT INTO segments (entity_id, name, slug) VALUES (?, ?, ?) "
            "ON CONFLICT (entity_id, slug) DO UPDATE SET name = excluded.name",
            (segment.entity_id, segment.name, segment.slug))
        row = self._c.execute("SELECT * FROM segments WHERE entity_id = ? AND slug = ?",
                              (segment.entity_id, segment.slug)).fetchone()
        return self._seg(row)

    def segments_for(self, entity_id: int) -> list[Segment]:
        return [self._seg(r) for r in self._c.execute(
            "SELECT * FROM segments WHERE entity_id = ? ORDER BY name", (entity_id,))]

    def add_facts(self, facts: Iterable[SegmentFact]) -> int:
        n = 0
        for f in facts:
            self._c.execute(
                "INSERT INTO segment_facts (segment_id, entity_id, metric, value, currency, "
                "period_start, period_end, financial_year, quarter, is_annual, basis, source_id) "
                "VALUES (:segment_id, :entity_id, :metric, :value, :currency, :period_start, "
                ":period_end, :financial_year, :quarter, :is_annual, :basis, :source_id) "
                "ON CONFLICT (segment_id, metric, basis, COALESCE(period_end, ''), "
                "COALESCE(period_start, '')) DO UPDATE SET value = excluded.value, "
                "currency = excluded.currency, financial_year = excluded.financial_year, "
                "quarter = excluded.quarter, is_annual = excluded.is_annual, "
                "source_id = COALESCE(excluded.source_id, segment_facts.source_id)",
                {"segment_id": f.segment_id, "entity_id": f.entity_id, "metric": f.metric,
                 "value": _vs(f.value), "currency": f.currency, "period_start": _ds(f.period_start),
                 "period_end": _ds(f.period_end), "financial_year": f.financial_year,
                 "quarter": f.quarter, "is_annual": int(f.is_annual), "basis": f.basis.value,
                 "source_id": f.source_id})
            n += 1
        return n

    def list_segment_facts(self, entity_id: int, *, metric: str | None = None,
                           basis: Basis | str | None = None,
                           segment_id: int | None = None) -> list[SegmentFact]:
        clauses = ["entity_id = ?"]
        params: list[Any] = [entity_id]
        if metric is not None:
            clauses.append("metric = ?")
            params.append(metric)
        if basis is not None:
            clauses.append("basis = ?")
            params.append(Basis(basis).value)
        if segment_id is not None:
            clauses.append("segment_id = ?")
            params.append(segment_id)
        rows = self._c.execute(
            f"SELECT * FROM segment_facts WHERE {' AND '.join(clauses)} "
            "ORDER BY (period_end IS NULL), period_end, (period_start IS NULL), period_start, segment_id",
            params)
        return [self._fact(r) for r in rows]


class SqlitePriceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def add_prices(self, prices: Iterable[SharePrice]) -> int:
        n = 0
        for p in prices:
            self._c.execute(
                "INSERT INTO share_prices (entity_id, price_date, close, currency, source_id) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (entity_id, price_date) DO UPDATE SET "
                "close = excluded.close, currency = excluded.currency, "
                "source_id = COALESCE(excluded.source_id, share_prices.source_id)",
                (p.entity_id, _ds(p.price_date), _vs(p.close), p.currency, p.source_id))
            n += 1
        return n

    def on_or_before(self, entity_id: int, on: date) -> SharePrice | None:
        row = self._c.execute(
            "SELECT * FROM share_prices WHERE entity_id = ? AND close IS NOT NULL AND price_date <= ? "
            "ORDER BY price_date DESC LIMIT 1", (entity_id, _ds(on))).fetchone()
        if row is None:
            return None
        got = SharePrice(entity_id=row["entity_id"], price_date=date.fromisoformat(row["price_date"]),
                         close=_vd(row["close"]), currency=row["currency"], source_id=row["source_id"])
        return got if (on - got.price_date).days <= PRICE_WINDOW_DAYS else None


class SqliteRepositories:
    """Opens (or creates) a database, applies the schema, and exposes every repository over
    one connection. A context manager: commits on a clean exit, always closes."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = connect(path)
        init_db(self._conn)
        self.entities = SqliteEntityRepository(self._conn)
        self.sources = SqliteSourceRepository(self._conn)
        self.facts = SqliteFactRepository(self._conn)
        self.segments = SqliteSegmentRepository(self._conn)
        self.prices = SqlitePriceRepository(self._conn)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteRepositories:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self._conn.commit()
        self._conn.close()
