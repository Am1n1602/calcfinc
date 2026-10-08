"""The financial engine."""
from calcfinc.engine.check import CheckResult
from calcfinc.engine.engine import EngineError, EngineResult, FinancialEngine
from calcfinc.engine.evaluate import FactRef
from calcfinc.engine.records import PeriodRecord, build_period_records
from calcfinc.engine.segments import SegmentEngine, SegmentGrowthRow, SegmentResult, SegmentRow

__all__ = [
    "CheckResult", "EngineError", "EngineResult", "FactRef", "FinancialEngine", "PeriodRecord",
    "SegmentEngine", "SegmentGrowthRow", "SegmentResult", "SegmentRow", "build_period_records",
]
