"""calcfinc: auditable financial metrics for any entity."""
from calcfinc.engine import EngineError, EngineResult, FactRef, FinancialEngine
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
from calcfinc.period import PeriodWindows
from calcfinc.registry import RatioSpec, register_metric, register_ratio
from calcfinc.store import SqliteRepositories

__version__ = "0.0.1"

__all__ = [
    "Basis", "Entity", "EngineError", "EngineResult", "FactRef", "FinancialEngine", "FinancialFact",
    "MappingConfidence", "PeriodWindows", "RatioSpec", "Segment", "SegmentFact", "SharePrice",
    "Source", "SqliteRepositories", "StatementType", "register_metric", "register_ratio",
]
