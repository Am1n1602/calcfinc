"""Repository interfaces. The engine reads only through these Protocols, never a driver.
Creates return the stored object with its id set; reads return None / [] for absence."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol, runtime_checkable

from calcfinc.entity import Entity
from calcfinc.fact import Basis, FinancialFact, Segment, SegmentFact, SharePrice, Source

PRICE_WINDOW_DAYS = 14          # how far back on_or_before reaches for a trading day


class AmbiguousEntity(ValueError):
    """A lookup key matched more than one entity; the caller must be more specific."""


@runtime_checkable
class EntityRepository(Protocol):
    def upsert(self, entity: Entity) -> Entity:
        """Insert or update. An existing entity is matched by any identifier, else by name."""

    def get(self, entity_id: int) -> Entity | None: ...

    def resolve(self, key: str) -> Entity | None:
        """Match an identifier value, an alias, or the exact name, case-insensitively, in
        that order. Raises AmbiguousEntity if one tier matches several entities."""

    def list(self) -> list[Entity]: ...

    def add_alias(self, entity_id: int, alias: str) -> None: ...


@runtime_checkable
class SourceRepository(Protocol):
    def add(self, source: Source) -> Source: ...

    def get(self, source_id: int) -> Source | None: ...

    def get_by_hash(self, content_hash: str) -> Source | None: ...


@runtime_checkable
class FactRepository(Protocol):
    def add_many(self, facts: Iterable[FinancialFact]) -> int:
        """Upsert keyed by (entity, metric, basis, statement_type, period_end, period_start,
        reported_at). A missing currency is filled from the entity default; an amount that
        still has none is rejected. `value is None` round-trips as NULL."""

    def list_facts(self, entity_id: int, *, basis: Basis | str | None = None,
                   metric: str | None = None) -> list[FinancialFact]:
        """Ordered by period_end, period_start, then reported_at ascending (NULLs first), so
        the last fact for a period is the latest reported."""


@runtime_checkable
class SegmentRepository(Protocol):
    def upsert_segment(self, segment: Segment) -> Segment: ...

    def segments_for(self, entity_id: int) -> list[Segment]: ...

    def add_facts(self, facts: Iterable[SegmentFact]) -> int: ...

    def list_segment_facts(self, entity_id: int, *, metric: str | None = None,
                           basis: Basis | str | None = None,
                           segment_id: int | None = None) -> list[SegmentFact]: ...


@runtime_checkable
class PriceRepository(Protocol):
    def add_prices(self, prices: Iterable[SharePrice]) -> int: ...

    def on_or_before(self, entity_id: int, on: date) -> SharePrice | None:
        """Most recent traded close on or before `on`, within PRICE_WINDOW_DAYS."""


class Repositories(Protocol):
    """A bundle exposing every repository over one backing store."""

    entities: EntityRepository
    sources: SourceRepository
    facts: FactRepository
    segments: SegmentRepository
    prices: PriceRepository

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...
