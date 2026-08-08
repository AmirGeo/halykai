"""
Validates a submission dict against submission_template.json's exact
key structure before writing to disk, so we never silently ship a
malformed / renamed / missing key.
"""
from __future__ import annotations
import json

VALID_STATUSES = {"COMPLIANT", "BREACH"}


def load_template_keys(template_path: str) -> dict[str, list[str]]:
    with open(template_path) as f:
        template = json.load(f)
    return {scenario: list(covenants.keys()) for scenario, covenants in template["answers"].items()}


def validate_submission(submission: dict, template_path: str) -> list[str]:
    """Returns a list of problems; empty list means the submission is valid."""
    problems = []
    expected = load_template_keys(template_path)

    for field in ("team", "contact_email", "model"):
        if not submission.get(field):
            problems.append(f"Top-level field '{field}' is empty.")

    answers = submission.get("answers", {})

    if set(answers.keys()) != set(expected.keys()):
        missing = set(expected.keys()) - set(answers.keys())
        extra = set(answers.keys()) - set(expected.keys())
        if missing:
            problems.append(f"Missing scenarios: {sorted(missing)}")
        if extra:
            problems.append(f"Unexpected scenarios (not in template): {sorted(extra)}")

    for scenario, covenant_ids in expected.items():
        if scenario not in answers:
            continue
        got_ids = set(answers[scenario].keys())
        if got_ids != set(covenant_ids):
            problems.append(f"{scenario}: covenant keys {sorted(got_ids)} != template {sorted(covenant_ids)}")

        for cov_id in covenant_ids:
            cell = answers[scenario].get(cov_id)
            if cell is None:
                problems.append(f"{scenario}.{cov_id}: missing cell")
                continue

            status = cell.get("status")
            if status not in VALID_STATUSES:
                problems.append(f"{scenario}.{cov_id}: status={status!r} is not one of {VALID_STATUSES}")

            actual = cell.get("actual")
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                problems.append(f"{scenario}.{cov_id}: actual={actual!r} is not numeric")
            elif actual < 0:
                problems.append(f"{scenario}.{cov_id}: actual={actual} must be positive")

            evidence = cell.get("evidence_txn_id")
            if evidence is not None and not isinstance(evidence, str):
                problems.append(f"{scenario}.{cov_id}: evidence_txn_id={evidence!r} must be a string or null")

    return problems


if __name__ == "__main__":
    import sys
    sub_path = sys.argv[1] if len(sys.argv) > 1 else "../../data/submission_template.json"
    tmpl_path = sys.argv[2] if len(sys.argv) > 2 else "../../data/submission_template.json"
    with open(sub_path) as f:
        submission = json.load(f)
    problems = validate_submission(submission, tmpl_path)
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(" -", p)
    else:
        print("Valid.")
