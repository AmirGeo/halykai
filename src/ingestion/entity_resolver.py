"""
Entity Resolver

Maps account_id -> scenario_id using ONLY the ledger. No LLM call, no
guessing: every txn_id for a borrower's account is prefixed with that
borrower's scenario_id (e.g. TXN-P1-0007 on ACC-7801 means ACC-7801 -> P1).

This is verified against the real uploaded ledger: exactly 12 accounts
(ACC-7201, ACC-7204, ACC-7801..ACC-7810) carry a scenario-prefixed txn_id,
matching the 12 scenarios in submission_template.json (P1-P10, B1, B4).
All other accounts (the ACC-9xxx range) are noise/decoy accounts that do
not belong to any scenario and should be ignored by the pipeline.

The Document Processor (Gemini) only needs to extract the account_id
mentioned in a given PDF -- this module then deterministically tells you
which scenario_id that document belongs to. Never ask the LLM to guess
the scenario_id itself.
"""
from __future__ import annotations
from collections import defaultdict
import re
import pandas as pd

SCENARIO_TXN_RE = re.compile(r"^TXN-([A-Z]+\d+)-\d+$")


def build_account_to_scenario_map(ledger: pd.DataFrame) -> dict[str, str]:
    """
    Returns {account_id: scenario_id}. Raises if an account maps to more
    than one scenario_id (would indicate a corrupt ledger / bad assumption).
    """
    candidates: dict[str, set[str]] = defaultdict(set)

    for txn_id, account_id in zip(ledger["txn_id"], ledger["account_id"]):
        m = SCENARIO_TXN_RE.match(str(txn_id))
        if not m:
            continue
        candidates[account_id].add(m.group(1))

    resolved: dict[str, str] = {}
    conflicts = {}
    for account_id, scenario_ids in candidates.items():
        if len(scenario_ids) == 1:
            resolved[account_id] = next(iter(scenario_ids))
        else:
            conflicts[account_id] = scenario_ids

    if conflicts:
        raise ValueError(f"Ambiguous account->scenario mapping: {conflicts}")

    return resolved


def scenario_transactions(ledger: pd.DataFrame, account_id: str) -> pd.DataFrame:
    """All ledger rows belonging to a single resolved scenario account."""
    return ledger[ledger["account_id"] == account_id].copy()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")
    from ledger_loader import load_ledger  # type: ignore

    ledger = load_ledger("../../data/master_ledger_2025.csv")
    mapping = build_account_to_scenario_map(ledger)
    print(f"Resolved {len(mapping)} scenario accounts:")
    for acc, scen in sorted(mapping.items(), key=lambda kv: kv[1]):
        n = len(scenario_transactions(ledger, acc))
        print(f"  {acc} -> {scen}  ({n} txns)")
