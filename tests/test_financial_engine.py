import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from src.models.covenant_dsl import Covenant, MetricType, Operator, AggregateSpec, RatioSpec, TransactionFilter, Exception_
from src.engine.financial_engine import evaluate_covenant
from src.evidence.counterfactual import find_evidence_txn


def make_txns(rows):
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_aggregate_expense_covenant_breach():
    txns = make_txns([
        {"txn_id": "TXN-X-0001", "date": "2025-01-01", "account_id": "ACC-1", "counterparty": "A",
         "description": "Marketing spend", "amount": -100000.0, "currency": "USD"},
        {"txn_id": "TXN-X-0002", "date": "2025-02-01", "account_id": "ACC-1", "counterparty": "B",
         "description": "Marketing spend", "amount": -50000.0, "currency": "USD"},
    ])
    covenant = Covenant(
        covenant_id="6.1", scenario_id="X", metric_type=MetricType.AGGREGATE,
        operator=Operator.LTE, threshold=120000.0,
        aggregate=AggregateSpec(filters=TransactionFilter(description_keywords=["marketing"], sign="expense")),
    )
    result = evaluate_covenant(covenant, txns)
    assert result["actual"] == 150000.0
    assert result["status"] == "BREACH"


def test_aggregate_compliant():
    txns = make_txns([
        {"txn_id": "TXN-X-0001", "date": "2025-01-01", "account_id": "ACC-1", "counterparty": "A",
         "description": "Marketing spend", "amount": -50000.0, "currency": "USD"},
    ])
    covenant = Covenant(
        covenant_id="6.1", scenario_id="X", metric_type=MetricType.AGGREGATE,
        operator=Operator.LTE, threshold=120000.0,
        aggregate=AggregateSpec(filters=TransactionFilter(description_keywords=["marketing"], sign="expense")),
    )
    result = evaluate_covenant(covenant, txns)
    assert result["status"] == "COMPLIANT"


def test_exception_raises_effective_threshold():
    txns = make_txns([
        {"txn_id": "TXN-X-0001", "date": "2025-01-01", "account_id": "ACC-1", "counterparty": "A",
         "description": "Marketing spend", "amount": -150000.0, "currency": "USD"},
    ])
    covenant = Covenant(
        covenant_id="6.1", scenario_id="X", metric_type=MetricType.AGGREGATE,
        operator=Operator.LTE, threshold=120000.0,
        aggregate=AggregateSpec(filters=TransactionFilter(description_keywords=["marketing"], sign="expense")),
        exceptions=[Exception_(description="board-approved overage", condition_met=True, adjusted_threshold=200000.0)],
    )
    result = evaluate_covenant(covenant, txns)
    # actual stays the real measured value even though status flips to compliant
    assert result["actual"] == 150000.0
    assert result["status"] == "COMPLIANT"


def test_ratio_covenant():
    txns = make_txns([
        {"txn_id": "TXN-X-0001", "date": "2025-01-01", "account_id": "ACC-1", "counterparty": "A",
         "description": "Debt service payment", "amount": -50000.0, "currency": "USD"},
        {"txn_id": "TXN-X-0002", "date": "2025-01-05", "account_id": "ACC-1", "counterparty": "B",
         "description": "Operating income", "amount": 100000.0, "currency": "USD"},
    ])
    covenant = Covenant(
        covenant_id="6.2", scenario_id="X", metric_type=MetricType.RATIO,
        operator=Operator.GTE, threshold=1.5,
        ratio=RatioSpec(
            numerator=AggregateSpec(filters=TransactionFilter(description_keywords=["operating income"])),
            denominator=AggregateSpec(filters=TransactionFilter(description_keywords=["debt service"])),
        ),
    )
    result = evaluate_covenant(covenant, txns)
    assert result["actual"] == 2.0
    assert result["status"] == "COMPLIANT"


def test_counterfactual_evidence_single_decisive_txn():
    txns = make_txns([
        {"txn_id": "TXN-X-0001", "date": "2025-01-01", "account_id": "ACC-1", "counterparty": "A",
         "description": "Capex spend", "amount": -80000.0, "currency": "USD"},
        {"txn_id": "TXN-X-0002", "date": "2025-01-02", "account_id": "ACC-1", "counterparty": "B",
         "description": "Capex spend", "amount": -50000.0, "currency": "USD"},
    ])
    covenant = Covenant(
        covenant_id="6.1", scenario_id="X", metric_type=MetricType.AGGREGATE,
        operator=Operator.LTE, threshold=100000.0,
        aggregate=AggregateSpec(filters=TransactionFilter(description_keywords=["capex"], sign="expense")),
    )
    result = evaluate_covenant(covenant, txns)
    assert result["status"] == "BREACH"  # 130000 > 100000
    evidence = find_evidence_txn(covenant, txns, result)
    # removing TXN-0002 (50000) -> 80000 <= 100000 compliant; removing TXN-0001 (80000) -> 50000 <= 100000 also compliant
    # both individually flip it -> ambiguous case, function should still return one deterministically
    assert evidence in {"TXN-X-0001", "TXN-X-0002"}
