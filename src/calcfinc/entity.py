"""Entity: anything with periodic statements (company, business unit, project, SME...)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Entity:
    """`id` is assigned by the store. `identifiers` maps a scheme to a value
    ({'ticker': 'AAPL', 'isin': ..., 'cik': ..., 'lei': ...}); `resolve(key)` in the store
    searches identifier values, aliases and the name, case-insensitively."""

    name: str
    kind: str = "company"
    identifiers: Mapping[str, str] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    currency: str | None = None                # default currency for facts that omit one
    fiscal_year_end_month: int = 12
    sector: str | None = None                  # 'bank' holds back ratios that do not apply to banks;
    id: int | None = None                      # None = infer from the facts (see engine), any other text = declared

    def __post_init__(self) -> None:
        if self.sector is not None:
            object.__setattr__(self, "sector", self.sector.strip().lower() or None)
        if not self.name or not self.kind:
            raise ValueError("Entity requires a name and a kind")
        if not 1 <= self.fiscal_year_end_month <= 12:
            raise ValueError(f"fiscal_year_end_month must be 1..12, got {self.fiscal_year_end_month!r}")
        if self.currency is not None:
            object.__setattr__(self, "currency", check_currency(self.currency))
        object.__setattr__(self, "identifiers", dict(self.identifiers))
        object.__setattr__(self, "aliases", tuple(dict.fromkeys(self.aliases)))


def check_currency(code: str) -> str:
    """ISO 4217 shape check (three letters); the code is upper-cased."""
    c = (code or "").strip().upper()
    if len(c) != 3 or not c.isalpha():
        raise ValueError(f"currency must be a 3-letter ISO 4217 code, got {code!r}")
    return c
