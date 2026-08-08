"""
Covenant Extraction Agent (Gemini)

Input: one covenant_clause dict from DocumentExtraction (clause_number,
raw_text, exception_text, definitions_referenced) plus the resolved
definitions from the same document.

Output: a Covenant DSL object (src/models/covenant_dsl.py) that the
deterministic financial_engine.py can execute. Gemini decides *what
kind* of test this is and *how to filter the ledger*; it never sees
the ledger itself and never computes the actual value.

IMPORTANT: keyword filters the LLM proposes (description_keywords,
counterparty_keywords) are a hypothesis, not ground truth. Log the
raw_text alongside the extracted filter for every covenant so a human
can spot-check filter quality during Phase 7 (offline evaluation).
"""
from __future__ import annotations
import json
import os

from google import genai
from google.genai import types

from src.models.covenant_dsl import (
    Covenant, MetricType, Operator, AggregateSpec, RatioSpec, TransactionFilter, Exception_,
)

MODEL = "gemini-2.5-pro"

COVENANT_SCHEMA = {
    "type": "object",
    "properties": {
        "metric_type": {"type": "string", "enum": ["aggregate", "ratio", "bs_value"]},
        "operator": {"type": "string", "enum": ["<=", "<", ">=", ">"]},
        "threshold": {"type": "number"},
        "aggregate_filter": {
            "type": "object",
            "description": "Set only when metric_type == aggregate.",
            "properties": {
                "description_keywords": {"type": "array", "items": {"type": "string"}},
                "counterparty_keywords": {"type": "array", "items": {"type": "string"}},
                "sign": {"type": "string", "enum": ["expense", "income", "any"]},
                "date_start": {"type": "string"},
                "date_end": {"type": "string"},
            },
        },
        "ratio_numerator_filter": {"type": "object", "description": "Set only when metric_type == ratio."},
        "ratio_denominator_filter": {"type": "object", "description": "Set only when metric_type == ratio."},
        "has_exception": {"type": "boolean"},
        "exception_description": {"type": "string"},
        "exception_adjusted_threshold": {"type": "number"},
        "reasoning": {"type": "string", "description": "Brief note on how the clause maps to this structure."},
    },
    "required": ["metric_type", "operator", "threshold"],
}

PROMPT_TEMPLATE = """\
You are converting one financial covenant clause from a loan agreement into a
structured test that will be executed by deterministic code against a
transaction ledger. You do not compute anything yourself.

Clause {clause_number}:
\"\"\"{raw_text}\"\"\"

Exception/carve-out language attached to this clause (may be empty):
\"\"\"{exception_text}\"\"\"

Relevant defined terms:
{definitions}

Decide:
- Is this an AGGREGATE test (sum of some category of transactions vs a limit),
  a RATIO test (two aggregates divided), or a BS_VALUE test (a single figure
  taken directly from a financial statement, not computable from transactions)?
- What is the comparison operator and threshold as written in the clause?
- For aggregate/ratio: what transaction-level filter (keywords in description
  or counterparty, expense vs income sign, date window) captures exactly the
  category of transaction the clause is limiting? Prefer specific keywords
  drawn from the clause's own wording over generic guesses.
- Does the exception text change the effective threshold, and under what
  condition? Do not resolve whether the condition is actually met here --
  that requires reading other documents (e.g. board minutes, waivers).
"""


def _filter_from_dict(d: dict | None) -> TransactionFilter:
    d = d or {}
    sign = d.get("sign")
    sign = None if sign in (None, "any") else sign
    return TransactionFilter(
        description_keywords=d.get("description_keywords", []),
        counterparty_keywords=d.get("counterparty_keywords", []),
        sign=sign,
        date_start=d.get("date_start") or None,
        date_end=d.get("date_end") or None,
    )


def extract_covenant(
    client: genai.Client,
    scenario_id: str,
    clause_number: str,
    raw_text: str,
    exception_text: str,
    definitions: list[dict],
) -> Covenant:
    prompt = PROMPT_TEMPLATE.format(
        clause_number=clause_number,
        raw_text=raw_text,
        exception_text=exception_text or "(none)",
        definitions="\n".join(f"- {d['term']}: {d['definition_text']}" for d in definitions) or "(none)",
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=COVENANT_SCHEMA,
            temperature=0,
        ),
    )
    data = json.loads(response.text)

    metric_type = MetricType(data["metric_type"])
    aggregate, ratio = None, None
    if metric_type == MetricType.AGGREGATE:
        aggregate = AggregateSpec(filters=_filter_from_dict(data.get("aggregate_filter")))
    elif metric_type == MetricType.RATIO:
        ratio = RatioSpec(
            numerator=AggregateSpec(filters=_filter_from_dict(data.get("ratio_numerator_filter"))),
            denominator=AggregateSpec(filters=_filter_from_dict(data.get("ratio_denominator_filter"))),
        )

    exceptions = []
    if data.get("has_exception"):
        exceptions.append(Exception_(
            description=data.get("exception_description", ""),
            condition_met=False,  # deliberately conservative default; see module docstring
            adjusted_threshold=data.get("exception_adjusted_threshold"),
        ))

    return Covenant(
        covenant_id=clause_number,
        scenario_id=scenario_id,
        metric_type=metric_type,
        operator=Operator(data["operator"]),
        threshold=float(data["threshold"]),
        aggregate=aggregate,
        ratio=ratio,
        exceptions=exceptions,
        notes=data.get("reasoning", ""),
    )
