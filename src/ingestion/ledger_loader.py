"""
Loads master_ledger_2025.csv into a normalized pandas DataFrame.

Columns (per CASE.md): txn_id, date, account_id, counterparty, description,
amount, currency. Expenses are negative, income is positive. Multiple
currencies are present -- no FX conversion is done here; downstream
covenant logic must filter by currency where relevant (most scenario
covenants in this dataset are USD-denominated).
"""
from __future__ import annotations
import pandas as pd


def load_ledger(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    required = {"txn_id", "date", "account_id", "counterparty", "description", "amount", "currency"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Ledger is missing expected columns: {missing}")
    df["amount"] = df["amount"].astype(float)
    df["abs_amount"] = df["amount"].abs()
    return df
