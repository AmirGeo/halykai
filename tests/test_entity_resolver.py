import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ingestion.ledger_loader import load_ledger
from src.ingestion.entity_resolver import build_account_to_scenario_map

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "master_ledger_2025.csv")


def test_resolves_all_twelve_scenarios():
    ledger = load_ledger(LEDGER_PATH)
    mapping = build_account_to_scenario_map(ledger)
    expected_scenarios = {"P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "B1", "B4"}
    assert set(mapping.values()) == expected_scenarios
    assert len(mapping) == 12  # one account per scenario, no ambiguity


def test_noise_accounts_are_not_resolved():
    ledger = load_ledger(LEDGER_PATH)
    mapping = build_account_to_scenario_map(ledger)
    assert "ACC-9001" not in mapping
