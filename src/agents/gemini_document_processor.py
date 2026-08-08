"""
Document Processor (Gemini)

Reads a single PDF (native document understanding, not OCR-first) and
extracts a DocumentExtraction: what kind of document it is, which
account_id it mentions, and -- if it's a loan agreement -- the raw text
of each numbered covenant clause plus any exception language, verbatim,
so the Covenant Extraction Agent can work from exact wording.

This module does NOT decide scenario_id (see entity_resolver.py) and
does NOT compute anything financial. Structured output only.

Requires: pip install google-genai
Requires: GEMINI_API_KEY env var
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from enum import Enum

from google import genai
from google.genai import types

MODEL = "gemini-2.5-pro"  # swap to gemini-2.5-flash for the bulk pass; escalate only on low-confidence docs


class DocType(str, Enum):
    LOAN_AGREEMENT = "loan_agreement"
    FINANCIAL_STATEMENT = "financial_statement"
    AUDIT_REPORT = "audit_report"
    KYC_FILE = "kyc_file"
    OTHER = "other"


DOCUMENT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": [d.value for d in DocType]},
        "account_ids_mentioned": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Every ACC-#### identifier that appears in this document, verbatim.",
        },
        "borrower_name": {"type": "string"},
        "covenant_clauses": {
            "type": "array",
            "description": "Only for loan_agreement docs. One entry per numbered financial covenant.",
            "items": {
                "type": "object",
                "properties": {
                    "clause_number": {"type": "string", "description": "e.g. '6.1'"},
                    "raw_text": {"type": "string", "description": "Verbatim clause text, unmodified."},
                    "definitions_referenced": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Defined terms used in this clause (e.g. 'Permitted Indebtedness') "
                                       "that are defined elsewhere in the document.",
                    },
                    "exception_text": {
                        "type": "string",
                        "description": "Any carve-out/exception language attached to this clause, verbatim. Empty string if none.",
                    },
                },
                "required": ["clause_number", "raw_text"],
            },
        },
        "definitions": {
            "type": "array",
            "description": "Defined terms found anywhere in the document, useful for resolving covenant_clauses.",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition_text": {"type": "string"},
                },
                "required": ["term", "definition_text"],
            },
        },
        "financial_figures": {
            "type": "array",
            "description": "For financial_statement/audit_report docs: any labeled figures that could "
                           "serve directly as a covenant's actual value (e.g. 'Total Equity: $1,284,663.42').",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "number"},
                    "as_of_date": {"type": "string"},
                },
                "required": ["label", "value"],
            },
        },
    },
    "required": ["doc_type", "account_ids_mentioned"],
}


@dataclass
class DocumentExtraction:
    source_file: str
    doc_type: str
    account_ids_mentioned: list[str]
    borrower_name: str | None = None
    covenant_clauses: list[dict] = field(default_factory=list)
    definitions: list[dict] = field(default_factory=list)
    financial_figures: list[dict] = field(default_factory=list)


def process_pdf(client: genai.Client, pdf_path: str) -> DocumentExtraction:
    uploaded = client.files.upload(file=pdf_path)

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            uploaded,
            (
                "Extract structured information from this document per the schema. "
                "Copy covenant clause text and defined-term text VERBATIM -- do not "
                "paraphrase, summarize, or normalize numbers. If this is not a loan "
                "agreement, leave covenant_clauses empty. Only include account_ids "
                "that literally appear in the document text."
            ),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DOCUMENT_EXTRACTION_SCHEMA,
            temperature=0,
        ),
    )

    import json
    data = json.loads(response.text)
    return DocumentExtraction(source_file=pdf_path, **data)


def process_all_documents(documents_dir: str) -> list[DocumentExtraction]:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    results = []
    for fname in sorted(os.listdir(documents_dir)):
        if not fname.lower().endswith(".pdf"):
            continue
        path = os.path.join(documents_dir, fname)
        try:
            results.append(process_pdf(client, path))
        except Exception as e:
            print(f"[WARN] failed to process {fname}: {e}")
    return results


if __name__ == "__main__":
    import sys
    docs_dir = sys.argv[1] if len(sys.argv) > 1 else "../../data/documents"
    extractions = process_all_documents(docs_dir)
    for ext in extractions:
        print(f"{ext.source_file}: type={ext.doc_type} accounts={ext.account_ids_mentioned}")
