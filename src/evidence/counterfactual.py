"""
Evidence Finder

Per CASE.md: evidence_txn_id is the SINGLE transaction whose removal
flips the verdict -- not the largest line, not the last one before
period close, not whatever tipped the cumulative sum. This module finds
it by brute-force counterfactual recomputation, which is cheap here
(covenant matched-sets are a few dozen rows at most).

Only applies to AGGREGATE-type covenants with a single-sided threshold.
For ratio/aggregate covenants where the ground truth key is null, the
CASE.md scoring rules say evidence_txn_id is not scored at all -- so
run_agent.py should leave it null for those rather than guessing.
"""
from __future__ import annotations
import pandas as pd

from src.models.covenant_dsl import Covenant
from src.engine.financial_engine import evaluate_covenant


def find_evidence_txn(covenant: Covenant, scenario_txns: pd.DataFrame, base_result: dict) -> str | None:
    """
    Returns a txn_id if removing exactly one transaction from the matched
    set flips base_result['status'], else None.
    """
    matched = base_result["matched_txns"]
    if matched.empty:
        return None

    base_status = base_result["status"]
    candidates = []

    for txn_id in matched["txn_id"]:
        without_txn = scenario_txns[scenario_txns["txn_id"] != txn_id]
        cf_result = evaluate_covenant(covenant, without_txn)
        if cf_result["status"] != base_status:
            candidates.append(txn_id)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # Ambiguous -- more than one transaction individually flips the verdict.
        # Prefer the one closest to the threshold boundary (smallest margin),
        # since that is most likely the single "decisive" one the case intends.
        return _closest_to_threshold(covenant, scenario_txns, candidates)
    return None


def _closest_to_threshold(covenant: Covenant, scenario_txns: pd.DataFrame, candidates: list[str]) -> str:
    best_txn, best_margin = None, float("inf")
    for txn_id in candidates:
        without_txn = scenario_txns[scenario_txns["txn_id"] != txn_id]
        cf_result = evaluate_covenant(covenant, without_txn)
        margin = abs(cf_result["actual"] - covenant.effective_threshold())
        if margin < best_margin:
            best_margin, best_txn = margin, txn_id
    return best_txn
