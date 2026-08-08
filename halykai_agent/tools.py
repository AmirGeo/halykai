"""
ADK tool functions.

These are plain Python functions with type hints and docstrings -- ADK
reads the signature + docstring to build the tool schema the LLM sees.
Keep arguments/returns to primitives (str, float, list, dict) since the
model has to be able to generate valid calls to them.

The root agent (agent.py) reads a covenant clause itself (via read_pdf_text
or its own document understanding), decides how to translate it into a
filter, and calls compute_aggregate / compute_ratio / find_evidence to get
the deterministic answer -- it never computes the arithmetic itself.
"""
from __future__ import annotations
import json
import os

import pdfplumber

from src.ingestion.ledger_loader import load_ledger
from src.ingestion.entity_resolver import build_account_to_scenario_map, scenario_transactions
from src.models.covenant_dsl import (
    Covenant, MetricType, Operator, AggregateSpec, RatioSpec, TransactionFilter,
)
from src.engine.financial_engine import evaluate_covenant
from src.evidence.counterfactual import find_evidence_txn
from src.validation.validator import validate_submission

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
_LEDGER_PATH = os.path.join(_BASE_DIR, "data", "master_ledger_2025.csv")
_TEMPLATE_PATH = os.path.join(_BASE_DIR, "data", "submission_template.json")
_DOCUMENTS_DIR = os.path.join(_BASE_DIR, "data", "documents")

# Loaded once per process -- the ledger doesn't change during a run.
_ledger = load_ledger(_LEDGER_PATH)
_account_to_scenario = build_account_to_scenario_map(_ledger)
_scenario_to_account = {v: k for k, v in _account_to_scenario.items()}


def list_documents() -> dict:
    """Lists every PDF filename available in the documents folder.

    Returns:
        dict with key 'files': list of filenames (not full paths).
    """
    if not os.path.isdir(_DOCUMENTS_DIR):
        return {"files": [], "error": f"documents folder not found at {_DOCUMENTS_DIR}"}
    files = sorted(f for f in os.listdir(_DOCUMENTS_DIR) if f.lower().endswith(".pdf"))
    return {"files": files}


def read_pdf_text(filename: str) -> dict:
    """Extracts all text from one PDF in the documents folder, page by page.

    Args:
        filename: the PDF's filename as returned by list_documents (e.g. '04eee2e9ba8c.pdf').

    Returns:
        dict with 'filename' and 'pages': a list of page text strings.
        On error, returns a dict with an 'error' key instead.
    """
    path = os.path.join(_DOCUMENTS_DIR, filename)
    if not os.path.isfile(path):
        return {"error": f"{filename} not found in {_DOCUMENTS_DIR}"}
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return {"filename": filename, "pages": pages}
    except Exception as e:
        return {"error": str(e)}


def resolve_scenario_for_account(account_id: str) -> dict:
    """Deterministically maps a borrower's account_id (found in a document) to its scenario_id.

    This uses the ledger only -- never guess this mapping yourself.

    Args:
        account_id: e.g. 'ACC-7801'

    Returns:
        dict with 'scenario_id' (or None if the account isn't a known scenario account).
    """
    return {"scenario_id": _account_to_scenario.get(account_id)}


def list_scenario_accounts() -> dict:
    """Lists every known scenario_id -> account_id mapping (all 12 scenarios).

    Returns:
        dict mapping scenario_id to account_id, e.g. {'P1': 'ACC-7801', ...}
    """
    return dict(_scenario_to_account)


def _txns_for(scenario_id: str):
    account_id = _scenario_to_account.get(scenario_id)
    if account_id is None:
        return None
    return scenario_transactions(_ledger, account_id)


def compute_aggregate(
    scenario_id: str,
    description_keywords: list[str],
    counterparty_keywords: list[str],
    sign: str,
    date_start: str,
    date_end: str,
) -> dict:
    """Computes a deterministic aggregate (sum of absolute amounts) over a scenario's transactions.

    Use this for covenants that limit a category of spend/income (e.g. "aggregate capital
    expenditure shall not exceed $X"). Pass empty list / empty string for any filter you
    don't need (e.g. counterparty_keywords=[] if you're filtering by description only).

    Args:
        scenario_id: e.g. 'P1'
        description_keywords: words to match (case-insensitive, any-match) in the transaction description.
        counterparty_keywords: words to match (case-insensitive, any-match) in the counterparty name.
        sign: one of 'expense' (amount<0), 'income' (amount>0), or 'any'.
        date_start: ISO date 'YYYY-MM-DD' inclusive, or '' for no lower bound.
        date_end: ISO date 'YYYY-MM-DD' inclusive, or '' for no upper bound.

    Returns:
        dict with 'actual' (positive float) and 'matched_txn_ids' (list of txn_id strings).
    """
    txns = _txns_for(scenario_id)
    if txns is None:
        return {"error": f"unknown scenario_id {scenario_id}"}

    spec = AggregateSpec(filters=TransactionFilter(
        description_keywords=description_keywords or [],
        counterparty_keywords=counterparty_keywords or [],
        sign=None if sign in ("", "any") else sign,
        date_start=date_start or None,
        date_end=date_end or None,
    ))
    covenant = Covenant(
        covenant_id="_ad_hoc", scenario_id=scenario_id, metric_type=MetricType.AGGREGATE,
        operator=Operator.LTE, threshold=0.0, aggregate=spec,
    )
    result = evaluate_covenant(covenant, txns)
    return {
        "actual": result["actual"],
        "matched_txn_ids": result["matched_txns"]["txn_id"].tolist(),
    }


def compute_ratio(
    scenario_id: str,
    numerator_description_keywords: list[str],
    numerator_sign: str,
    denominator_description_keywords: list[str],
    denominator_sign: str,
) -> dict:
    """Computes numerator_sum / denominator_sum for a ratio-type covenant (e.g. debt service coverage).

    Args:
        scenario_id: e.g. 'P1'
        numerator_description_keywords: keywords identifying numerator transactions.
        numerator_sign: 'expense', 'income', or 'any' for the numerator filter.
        denominator_description_keywords: keywords identifying denominator transactions.
        denominator_sign: 'expense', 'income', or 'any' for the denominator filter.

    Returns:
        dict with 'actual' (the ratio, positive float) or 'error'.
    """
    txns = _txns_for(scenario_id)
    if txns is None:
        return {"error": f"unknown scenario_id {scenario_id}"}

    ratio = RatioSpec(
        numerator=AggregateSpec(filters=TransactionFilter(
            description_keywords=numerator_description_keywords or [],
            sign=None if numerator_sign in ("", "any") else numerator_sign,
        )),
        denominator=AggregateSpec(filters=TransactionFilter(
            description_keywords=denominator_description_keywords or [],
            sign=None if denominator_sign in ("", "any") else denominator_sign,
        )),
    )
    covenant = Covenant(
        covenant_id="_ad_hoc", scenario_id=scenario_id, metric_type=MetricType.RATIO,
        operator=Operator.GTE, threshold=0.0, ratio=ratio,
    )
    try:
        result = evaluate_covenant(covenant, txns)
    except ZeroDivisionError as e:
        return {"error": str(e)}
    return {"actual": result["actual"]}


def check_threshold(actual: float, operator: str, threshold: float) -> dict:
    """Compares a computed actual value against a covenant's threshold to get COMPLIANT/BREACH.

    Args:
        actual: the value returned by compute_aggregate or compute_ratio.
        operator: one of '<=', '<', '>=', '>' as written in the covenant clause.
        threshold: the numeric limit from the covenant clause (before any exception adjustment).

    Returns:
        dict with 'status': 'COMPLIANT' or 'BREACH'.
    """
    ops = {
        "<=": actual <= threshold, "<": actual < threshold,
        ">=": actual >= threshold, ">": actual > threshold,
    }
    if operator not in ops:
        return {"error": f"unknown operator {operator}"}
    return {"status": "COMPLIANT" if ops[operator] else "BREACH"}


def find_evidence_transaction(
    scenario_id: str,
    description_keywords: list[str],
    counterparty_keywords: list[str],
    sign: str,
    operator: str,
    threshold: float,
) -> dict:
    """Finds the single transaction whose removal would flip an aggregate covenant's verdict.

    Only meaningful for aggregate-type covenants where a specific transaction caused the
    breach (or is uniquely responsible for compliance). If no single transaction flips the
    verdict, or the covenant isn't aggregate-based, evidence_txn_id will be null -- that's
    correct and expected for ratio/aggregate-limit covenants with no single decisive transaction.

    Args:
        scenario_id: e.g. 'P1'
        description_keywords: same filter you used in compute_aggregate for this covenant.
        counterparty_keywords: same filter you used in compute_aggregate for this covenant.
        sign: 'expense', 'income', or 'any'.
        operator: '<=', '<', '>=', or '>' as written in the clause.
        threshold: the (effective) numeric threshold to test against.

    Returns:
        dict with 'evidence_txn_id' (string or null).
    """
    txns = _txns_for(scenario_id)
    if txns is None:
        return {"error": f"unknown scenario_id {scenario_id}"}

    spec = AggregateSpec(filters=TransactionFilter(
        description_keywords=description_keywords or [],
        counterparty_keywords=counterparty_keywords or [],
        sign=None if sign in ("", "any") else sign,
    ))
    covenant = Covenant(
        covenant_id="_ad_hoc", scenario_id=scenario_id, metric_type=MetricType.AGGREGATE,
        operator=Operator(operator), threshold=threshold, aggregate=spec,
    )
    result = evaluate_covenant(covenant, txns)
    evidence = find_evidence_txn(covenant, txns, result)
    return {"evidence_txn_id": evidence}


def save_answer(scenario_id: str, covenant_id: str, status: str, actual: float, evidence_txn_id: str) -> dict:
    """Saves one finished covenant answer to the running submission.json on disk.

    Call this once per covenant, after you've computed status/actual/evidence for it.
    Pass evidence_txn_id='' (empty string) if there is no single decisive transaction --
    it will be stored as null.

    Args:
        scenario_id: e.g. 'P1'
        covenant_id: e.g. '6.1'
        status: 'COMPLIANT' or 'BREACH'
        actual: the computed value, rounded to 2 decimals, always positive.
        evidence_txn_id: a txn_id string, or '' for null.

    Returns:
        dict confirming what was saved, or an error.
    """
    out_path = os.path.join(_BASE_DIR, "submission.json")
    if os.path.isfile(out_path):
        with open(out_path) as f:
            submission = json.load(f)
    else:
        with open(_TEMPLATE_PATH) as f:
            template = json.load(f)
        submission = {
            "team": os.environ.get("TEAM_NAME", ""),
            "contact_email": os.environ.get("TEAM_EMAIL", ""),
            "model": os.environ.get("SUBMISSION_MODEL_NAME", "gemini-3.5-flash"),
            "answers": {s: {c: None for c in covs} for s, covs in template["answers"].items()},
        }

    if scenario_id not in submission["answers"] or covenant_id not in submission["answers"][scenario_id]:
        return {"error": f"{scenario_id}.{covenant_id} is not a valid template cell"}

    submission["answers"][scenario_id][covenant_id] = {
        "status": status,
        "actual": round(float(actual), 2),
        "evidence_txn_id": evidence_txn_id or None,
    }

    with open(out_path, "w") as f:
        json.dump(submission, f, indent=2)

    return {"saved": f"{scenario_id}.{covenant_id}"}


def validate_current_submission() -> dict:
    """Validates the in-progress submission.json against the template's exact structure.

    Call this after saving all 36 answers, before finishing.

    Returns:
        dict with 'valid': bool and 'problems': list of strings (empty if valid).
    """
    out_path = os.path.join(_BASE_DIR, "submission.json")
    if not os.path.isfile(out_path):
        return {"valid": False, "problems": ["submission.json does not exist yet -- call save_answer first"]}
    with open(out_path) as f:
        submission = json.load(f)
    problems = validate_submission(submission, _TEMPLATE_PATH)
    return {"valid": not problems, "problems": problems}
