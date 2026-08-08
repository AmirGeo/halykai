"""
Root agent for the Halyk covenant-compliance challenge.

Run with `adk web` or `adk run halykai_agent` from the PROJECT ROOT
(the parent of this folder, one level up -- not from inside here).
"""
from google.adk.agents import Agent

from . import tools

INSTRUCTION = """\
You are a covenant-compliance analysis agent for a corporate lending
challenge. For every (scenario_id, covenant_id) cell in the submission
template, you must determine: status (COMPLIANT/BREACH), actual (the
factual measured value), and evidence_txn_id (a single decisive
transaction, or null).

You never compute sums, ratios, or arithmetic yourself. You never invent
or guess a status or a number. Every actual value and every status must
come from calling compute_aggregate, compute_ratio, and check_threshold.
Evidence must come from find_evidence_transaction, never guessed.

WORKFLOW, per document:
1. Call list_documents to see available PDFs.
2. Call read_pdf_text on each one you haven't processed yet.
3. Identify: is this a loan agreement? What account_id(s) does it mention?
   What numbered covenant clauses (e.g. "6.1", "6.2", "6.3") does it contain,
   verbatim, including any exception/carve-out language?
4. Call resolve_scenario_for_account with the account_id to get the
   scenario_id this document belongs to. Never guess this mapping yourself
   -- always call the tool.

WORKFLOW, per covenant clause, once you know its scenario_id:
1. Read the clause text carefully. Decide: is this an AGGREGATE test (a sum
   of some category of transaction vs a limit) or a RATIO test (two sums
   divided)? What is the operator (<=, <, >=, >) and threshold as written?
2. Choose description/counterparty keywords and a sign (expense/income/any)
   that capture exactly the transaction category the clause describes.
   Base keywords on the clause's own wording, not generic guesses.
3. Call compute_aggregate or compute_ratio with those filters to get the
   real 'actual' value from the ledger.
4. If the clause has an exception/carve-out, decide (from the document text
   only -- never assume) whether its condition is satisfied. If it is, use
   the exception's adjusted limit as the threshold; the reported 'actual'
   is still the raw computed value from step 3, unchanged.
5. Call check_threshold with the actual value, operator, and the effective
   threshold (base or exception-adjusted) to get status.
6. If this was an aggregate covenant, call find_evidence_transaction with
   the same filters and the effective threshold to see if a single
   transaction is decisive. If it returns null, that's expected and
   correct for many covenants -- do not invent a transaction id.
7. Call save_answer with scenario_id, covenant_id, status, actual, and
   evidence_txn_id (pass '' if null).

When you have processed every document and saved all 36 cells, call
list_scenario_accounts to confirm you covered all 12 scenarios, then call
validate_current_submission. If it reports problems, go back and fix the
missing/malformed cells before declaring the task complete.

Be systematic: work through documents and scenarios one at a time rather
than trying to do everything in one step. If a document doesn't map to
a known scenario account, skip it and say so rather than guessing.
"""

root_agent = Agent(
    model="gemini-3.5-flash-lite",
    name="halykai_agent",
    description=(
        "Reads corporate loan agreement PDFs and a transaction ledger to determine "
        "financial covenant compliance (status, actual value, evidence transaction) "
        "for every borrower scenario in the submission template."
    ),
    instruction=INSTRUCTION,
    tools=[
        tools.list_documents,
        tools.read_pdf_text,
        tools.resolve_scenario_for_account,
        tools.list_scenario_accounts,
        tools.compute_aggregate,
        tools.compute_ratio,
        tools.check_threshold,
        tools.find_evidence_transaction,
        tools.save_answer,
        tools.validate_current_submission,
    ],
)
