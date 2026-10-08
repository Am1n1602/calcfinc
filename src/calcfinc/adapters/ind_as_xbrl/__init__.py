"""Ind-AS (India) vocabulary. Everything India-specific lives here, never in the core.

This is the stub that holds the names; the XBRL-record -> canonical-fact pipeline is ported
in Phase 3. Call `register()` once to make the extra metrics known to the registry.
"""
from __future__ import annotations

from decimal import Decimal

from calcfinc.fact import StatementType
from calcfinc.num import div
from calcfinc.registry.metrics import register_metric

# Ind-AS / source tag names that differ from the generic core vocabulary.
RENAMES = {"pat_continuing_ops": "profit_continuing_ops"}

OTHER = StatementType.OTHER


def register() -> None:
    """Register the Ind-AS-only metrics (idempotent)."""
    register_metric("paid_up_equity_capital", "currency", StatementType.BALANCE_SHEET,
                    label="Paid-up equity share capital")
    register_metric("face_value_per_share", "per_share", StatementType.BALANCE_SHEET,
                    label="Face value per share")
    register_metric("debt_equity_ratio_reported", "x", OTHER, label="Debt/Equity ratio (as reported, SEBI)")
    register_metric("debt_service_coverage_ratio_reported", "x", OTHER,
                    label="Debt service coverage ratio (as reported, SEBI)")
    register_metric("interest_service_coverage_ratio_reported", "x", OTHER,
                    label="Interest service coverage ratio (as reported, SEBI)")


def shares_outstanding(paid_up_equity_capital: Decimal, face_value_per_share: Decimal) -> Decimal | None:
    """Indian filings give share capital and face value, not a share count. The adapter
    derives the count at ingestion so the core only ever sees `shares_outstanding`."""
    if not face_value_per_share:
        return None
    return div(paid_up_equity_capital, face_value_per_share)
