"""
run_agent.py -- PRODUCTION AGENT ENTRYPOINT.

Reads ONLY the allowed challenge inputs (ledger, PDFs, template) and
writes submission.json. This file must never import evaluation/*
or ground_truth.json, directly or indirectly -- that separation is
enforced by keeping evaluate.py as the sole consumer of ground truth.

    PDFs + ledger + template -> run_agent.py -> submission.json
"""
from __future__ import annotations
import argparse
import json
import os

from src.ingestion.ledger_loader import load_ledger
from src.ingestion.entity_resolver import build_account_to_scenario_map, scenario_transactions
from src.agents.gemini_document_processor import process_all_documents
from src.agents.covenant_extractor import extract_covenant
from src.engine.financial_engine import evaluate_covenant
from src.evidence.counterfactual import find_evidence_txn
from src.validation.validator import validate_submission
from src.models.covenant_dsl import MetricType

from google import genai


def build_submission(
    ledger_path: str,
    documents_dir: str,
    template_path: str,
    team: str,
    contact_email: str,
    model_name: str = "gemini-2.5-pro",
) -> dict:
    with open(template_path) as f:
        template = json.load(f)

    ledger = load_ledger(ledger_path)
    account_to_scenario = build_account_to_scenario_map(ledger)

    print("Processing documents with Gemini...")
    extractions = process_all_documents(documents_dir)

    # Group loan-agreement clauses by resolved scenario_id.
    clauses_by_scenario: dict[str, list[dict]] = {}
    definitions_by_scenario: dict[str, list[dict]] = {}
    for ext in extractions:
        if ext.doc_type != "loan_agreement" or not ext.covenant_clauses:
            continue
        scenario_ids = {account_to_scenario[a] for a in ext.account_ids_mentioned if a in account_to_scenario}
        if not scenario_ids:
            print(f"[WARN] {ext.source_file}: no known scenario account found, skipping")
            continue
        if len(scenario_ids) > 1:
            print(f"[WARN] {ext.source_file}: mentions multiple scenario accounts {scenario_ids}, skipping")
            continue
        scenario_id = next(iter(scenario_ids))
        clauses_by_scenario.setdefault(scenario_id, []).extend(ext.covenant_clauses)
        definitions_by_scenario.setdefault(scenario_id, []).extend(ext.definitions)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    answers: dict[str, dict] = {}
    for scenario_id, covenant_ids in template["answers"].items():
        answers[scenario_id] = {}
        account_id = next((a for a, s in account_to_scenario.items() if s == scenario_id), None)
        scen_txns = scenario_transactions(ledger, account_id) if account_id else ledger.iloc[0:0]
        clauses = {c["clause_number"]: c for c in clauses_by_scenario.get(scenario_id, [])}
        definitions = definitions_by_scenario.get(scenario_id, [])

        for covenant_id in covenant_ids:
            clause = clauses.get(covenant_id)
            if clause is None:
                print(f"[WARN] {scenario_id}.{covenant_id}: no clause text found, leaving unfilled")
                continue
            try:
                covenant = extract_covenant(
                    client, scenario_id, covenant_id,
                    clause["raw_text"], clause.get("exception_text", ""), definitions,
                )
                result = evaluate_covenant(covenant, scen_txns)

                evidence_txn_id = None
                if covenant.metric_type == MetricType.AGGREGATE:
                    evidence_txn_id = find_evidence_txn(covenant, scen_txns, result)

                answers[scenario_id][covenant_id] = {
                    "status": result["status"],
                    "actual": result["actual"],
                    "evidence_txn_id": evidence_txn_id,
                }
            except Exception as e:
                print(f"[ERROR] {scenario_id}.{covenant_id}: {e}")

    submission = {
        "team": team,
        "contact_email": contact_email,
        "model": model_name,
        "answers": answers,
    }
    return submission


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", default="data/master_ledger_2025.csv")
    parser.add_argument("--documents", default="data/documents")
    parser.add_argument("--template", default="data/submission_template.json")
    parser.add_argument("--out", default="submission.json")
    parser.add_argument("--team", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--model", default="gemini-2.5-pro")
    args = parser.parse_args()

    submission = build_submission(
        args.ledger, args.documents, args.template, args.team, args.email, args.model
    )

    problems = validate_submission(submission, args.template)
    if problems:
        print(f"\n{len(problems)} validation problem(s) -- fix before submitting:")
        for p in problems:
            print(" -", p)
    else:
        print("\nSubmission is structurally valid.")

    with open(args.out, "w") as f:
        json.dump(submission, f, indent=2)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
