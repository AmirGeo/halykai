"""
evaluate.py -- LOCAL, OFFLINE EVALUATION ONLY.

This is the only script in the repo that reads evaluation/ground_truth.json.
It must never be imported by run_agent.py or by anything under src/.
Usage:
    python evaluate.py submission.json
    python evaluate.py submission.json --report report.json
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict

STATUS_WEIGHT = 0.50
ACTUAL_WEIGHT = 0.30
EVIDENCE_WEIGHT = 0.20
ACTUAL_ZERO_AT = 0.05  # relative error at which the actual/evidence score hits 0


def score_cell(pred: dict | None, key: dict) -> dict:
    """
    Implements the exact scoring rule from CASE.md/CASE.ru.md:
      - wrong/missing/malformed status -> whole cell is 0
      - actual scored on a decaying scale, 0 at >=5% relative error
      - evidence: exact match required when key evidence_txn_id is not null;
        when key evidence_txn_id is null, this component decays together
        with the actual error (not a free 0.20).
    """
    result = {"status_score": 0.0, "actual_score": 0.0, "evidence_score": 0.0, "cell_score": 0.0, "notes": []}

    if pred is None:
        result["notes"].append("cell missing from submission")
        return result

    pred_status = pred.get("status")
    key_status = key["status"]
    if pred_status != key_status:
        result["notes"].append(f"status mismatch: got {pred_status!r}, expected {key_status!r}")
        return result  # whole cell is 0 per the rules
    result["status_score"] = STATUS_WEIGHT

    pred_actual = pred.get("actual")
    key_actual = key["actual"]
    is_numeric = isinstance(pred_actual, (int, float)) and not isinstance(pred_actual, bool)

    if not is_numeric:
        result["notes"].append("actual missing or non-numeric")
        rel_err = 1.0
    elif key_actual == 0:
        rel_err = 0.0 if pred_actual == 0 else 1.0
    else:
        rel_err = abs(pred_actual - key_actual) / abs(key_actual)

    decay = max(0.0, 1 - rel_err / ACTUAL_ZERO_AT)
    result["actual_score"] = round(ACTUAL_WEIGHT * decay, 4)

    key_evidence = key.get("evidence_txn_id")
    if key_evidence is not None:
        pred_evidence = pred.get("evidence_txn_id")
        result["evidence_score"] = EVIDENCE_WEIGHT if pred_evidence == key_evidence else 0.0
        if pred_evidence != key_evidence:
            result["notes"].append(f"evidence mismatch: got {pred_evidence!r}, expected {key_evidence!r}")
    else:
        # Null-evidence cells: the 0.20 rides on the same decay as `actual`.
        result["evidence_score"] = round(EVIDENCE_WEIGHT * decay, 4)

    result["cell_score"] = round(result["status_score"] + result["actual_score"] + result["evidence_score"], 4)
    return result


def evaluate(submission: dict, ground_truth: dict) -> dict:
    per_cell = {}
    by_covenant = defaultdict(list)
    by_scenario = defaultdict(list)
    total = 0.0
    n_cells = 0

    for scenario_id, scenario_key in ground_truth["scenarios"].items():
        pred_scenario = submission.get("answers", {}).get(scenario_id, {})
        for covenant_id, key in scenario_key["covenants"].items():
            pred_cell = pred_scenario.get(covenant_id)
            scored = score_cell(pred_cell, key)
            per_cell[f"{scenario_id}.{covenant_id}"] = scored
            by_covenant[covenant_id].append(scored["cell_score"])
            by_scenario[scenario_id].append(scored["cell_score"])
            total += scored["cell_score"]
            n_cells += 1

    max_possible = n_cells * 1.0

    report = {
        "overall_score": round(total, 4),
        "max_possible": max_possible,
        "overall_pct": round(100 * total / max_possible, 2) if max_possible else 0.0,
        "n_cells": n_cells,
        "status_accuracy": round(
            sum(1 for c in per_cell.values() if c["status_score"] > 0) / n_cells, 4
        ) if n_cells else 0.0,
        "by_covenant": {
            cov: round(sum(scores) / len(scores), 4) for cov, scores in by_covenant.items()
        },
        "by_scenario": {
            scen: round(sum(scores) / len(scores), 4) for scen, scores in by_scenario.items()
        },
        "failing_cells": {
            k: v for k, v in per_cell.items() if v["cell_score"] < 1.0
        },
        "per_cell": per_cell,
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", help="Path to submission.json")
    parser.add_argument("--ground-truth", default="evaluation/ground_truth.json")
    parser.add_argument("--report", default=None, help="Optional path to dump full JSON report")
    args = parser.parse_args()

    with open(args.submission) as f:
        submission = json.load(f)
    with open(args.ground_truth) as f:
        ground_truth = json.load(f)

    report = evaluate(submission, ground_truth)

    print(f"Overall score: {report['overall_score']} / {report['max_possible']}  ({report['overall_pct']}%)")
    print(f"Status accuracy: {report['status_accuracy'] * 100:.1f}%")
    print("\nBy covenant:")
    for cov, score in sorted(report["by_covenant"].items()):
        print(f"  {cov}: {score}")
    print("\nBy scenario:")
    for scen, score in sorted(report["by_scenario"].items()):
        print(f"  {scen}: {score}")
    if report["failing_cells"]:
        print(f"\n{len(report['failing_cells'])} cell(s) losing points:")
        for cell_id, detail in report["failing_cells"].items():
            print(f"  {cell_id}: score={detail['cell_score']}  notes={detail['notes']}")

    if args.report:
        with open(args.report, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nFull report written to {args.report}")


if __name__ == "__main__":
    main()
