"""
Structured covenant representation.

Gemini's job is to read the loan agreement PDF and translate the natural-
language covenant clause into ONE of these objects. Python's job is to
execute it against the ledger. The LLM never touches the ledger or does
arithmetic; the engine never interprets prose.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MetricType(str, Enum):
    AGGREGATE = "aggregate"          # sum/count of filtered transactions
    RATIO = "ratio"                  # numerator metric / denominator metric
    BALANCE_SHEET_VALUE = "bs_value" # a figure taken directly from a financial statement doc


class Operator(str, Enum):
    LTE = "<="
    LT = "<"
    GTE = ">="
    GT = ">"


@dataclass
class TransactionFilter:
    """Deterministic filter applied to a scenario's transactions."""
    description_keywords: list[str] = field(default_factory=list)   # any-match, case-insensitive
    counterparty_keywords: list[str] = field(default_factory=list)
    sign: Optional[str] = None          # "expense" (amount<0) | "income" (amount>0) | None
    date_start: Optional[str] = None    # ISO date, inclusive
    date_end: Optional[str] = None      # ISO date, inclusive
    currency: Optional[str] = None
    exclude_txn_ids: list[str] = field(default_factory=list)  # exceptions/exclusions from the clause


@dataclass
class AggregateSpec:
    filters: TransactionFilter
    field: str = "amount"    # column to aggregate
    use_abs: bool = True     # take absolute value before summing (per CASE.md: actual is always positive)


@dataclass
class RatioSpec:
    numerator: AggregateSpec
    denominator: AggregateSpec


@dataclass
class Exception_:
    """A contractual carve-out that changes the *effective* threshold, never the actual value."""
    description: str
    condition_met: bool          # resolved by the LLM/human reading the doc, or left False if undetermined
    adjusted_threshold: Optional[float] = None


@dataclass
class Covenant:
    covenant_id: str             # e.g. "6.1"
    scenario_id: str             # e.g. "P1"
    metric_type: MetricType
    operator: Operator
    threshold: float
    aggregate: Optional[AggregateSpec] = None
    ratio: Optional[RatioSpec] = None
    bs_value: Optional[float] = None   # for BALANCE_SHEET_VALUE, extracted directly by the LLM from a doc
    exceptions: list[Exception_] = field(default_factory=list)
    source_pages: list[int] = field(default_factory=list)
    notes: str = ""

    def effective_threshold(self) -> float:
        t = self.threshold
        for exc in self.exceptions:
            if exc.condition_met and exc.adjusted_threshold is not None:
                t = exc.adjusted_threshold
        return t
