"""
Deterministic Financial Engine

Takes a Covenant (structured DSL, produced upstream by the Covenant
Extraction Agent from PDF text) plus that scenario's transactions, and
computes:
  - actual: the factual measured value (always positive, per CASE.md)
  - status: COMPLIANT or BREACH, using the *effective* threshold
    (base threshold adjusted by any triggered exception)

No LLM calls happen in this file. This is the piece that protects the
0.30 (actual) and 0.50 (status) points from LLM arithmetic mistakes.
"""
from __future__ import annotations
import pandas as pd

from src.models.covenant_dsl import Covenant, MetricType, Operator, AggregateSpec, TransactionFilter


def apply_filter(txns: pd.DataFrame, f: TransactionFilter) -> pd.DataFrame:
    out = txns

    if f.sign == "expense":
        out = out[out["amount"] < 0]
    elif f.sign == "income":
        out = out[out["amount"] > 0]

    if f.currency:
        out = out[out["currency"] == f.currency]

    if f.date_start:
        out = out[out["date"] >= pd.Timestamp(f.date_start)]
    if f.date_end:
        out = out[out["date"] <= pd.Timestamp(f.date_end)]

    if f.description_keywords:
        pattern = "|".join(pd.Series(f.description_keywords).str.lower())
        out = out[out["description"].str.lower().str.contains(pattern, regex=True, na=False)]

    if f.counterparty_keywords:
        pattern = "|".join(pd.Series(f.counterparty_keywords).str.lower())
        out = out[out["counterparty"].str.lower().str.contains(pattern, regex=True, na=False)]

    if f.exclude_txn_ids:
        out = out[~out["txn_id"].isin(f.exclude_txn_ids)]

    return out


def compute_aggregate(txns: pd.DataFrame, spec: AggregateSpec) -> tuple[float, pd.DataFrame]:
    """Returns (value, matched_rows) so the evidence finder can reuse matched_rows."""
    matched = apply_filter(txns, spec.filters)
    col = matched[spec.field]
    if spec.use_abs:
        col = col.abs()
    return float(col.sum()), matched


def evaluate_covenant(covenant: Covenant, scenario_txns: pd.DataFrame) -> dict:
    """
    Returns {"actual": float, "status": "COMPLIANT"|"BREACH", "matched_txns": DataFrame}
    matched_txns is passed to the Evidence Finder, it is NOT part of the submission cell.
    """
    matched_txns = pd.DataFrame()

    if covenant.metric_type == MetricType.AGGREGATE:
        assert covenant.aggregate is not None
        actual, matched_txns = compute_aggregate(scenario_txns, covenant.aggregate)

    elif covenant.metric_type == MetricType.RATIO:
        assert covenant.ratio is not None
        num, num_matched = compute_aggregate(scenario_txns, covenant.ratio.numerator)
        den, den_matched = compute_aggregate(scenario_txns, covenant.ratio.denominator)
        if den == 0:
            raise ZeroDivisionError(f"Ratio denominator is zero for covenant {covenant.covenant_id}")
        actual = num / den
        matched_txns = pd.concat([num_matched, den_matched]).drop_duplicates(subset="txn_id")

    elif covenant.metric_type == MetricType.BALANCE_SHEET_VALUE:
        if covenant.bs_value is None:
            raise ValueError(f"bs_value not set for covenant {covenant.covenant_id}")
        actual = float(covenant.bs_value)

    else:
        raise ValueError(f"Unknown metric_type {covenant.metric_type}")

    threshold = covenant.effective_threshold()
    op = covenant.operator
    if op == Operator.LTE:
        compliant = actual <= threshold
    elif op == Operator.LT:
        compliant = actual < threshold
    elif op == Operator.GTE:
        compliant = actual >= threshold
    elif op == Operator.GT:
        compliant = actual > threshold
    else:
        raise ValueError(f"Unknown operator {op}")

    return {
        "actual": round(actual, 2),
        "status": "COMPLIANT" if compliant else "BREACH",
        "matched_txns": matched_txns,
    }
