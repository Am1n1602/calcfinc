"""calcfinc: auditable financial metrics for any entity."""
import logging

from calcfinc.engine import CheckResult, EngineError, EngineResult, FactRef, FinancialEngine
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

__version__ = "0.1.3"

# A library logs through the standard `logging` module and leaves the handlers to the application.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "Basis", "CheckResult", "Entity", "EngineError", "EngineResult", "FactRef", "FinancialEngine",
    "FinancialFact", "MappingConfidence", "PeriodWindows", "RatioSpec", "Segment", "SegmentFact",
    "SharePrice", "Source", "SqliteRepositories", "StatementType", "__version__", "register_metric",
    "register_ratio",
]
