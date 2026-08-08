# Halyk AI Challenge — Agent

## What's built and tested right now (no PDFs needed)

- **`src/ingestion/entity_resolver.py`** — deterministic `account_id -> scenario_id`
  mapping, built purely from `master_ledger_2025.csv`. Verified against your real
  ledger: it resolves exactly the 12 scenario accounts (`ACC-7201`, `ACC-7204`,
  `ACC-7801`–`ACC-7810` → `B1, B4, P1..P10`) and correctly ignores the 549 `ACC-9xxx`
  noise accounts. `tests/test_entity_resolver.py` passes.
- **`src/models/covenant_dsl.py`** — the structured covenant representation.
- **`src/engine/financial_engine.py`** — deterministic aggregate/ratio/bs-value
  evaluation against the ledger, exception handling (adjusts the *effective*
  threshold, never the reported `actual`). `tests/test_financial_engine.py`
  passes against synthetic covenants.
- **`src/evidence/counterfactual.py`** — brute-force "remove one transaction,
  recheck the verdict" evidence finder, per the challenge's exact definition
  of `evidence_txn_id` (not the largest line, not the one that tips the sum —
  the one whose removal flips the verdict).
- **`src/validation/validator.py`** — checks a submission dict against
  `submission_template.json`'s exact key structure before you ever write it
  to disk.
- **`evaluate.py`** — implements the exact scoring formula from CASE.md/CASE.ru.md
  (0.50 status / 0.30 actual on a decaying scale / 0.20 evidence, with the
  null-evidence-decays-with-actual rule). Sanity-checked: an all-null submission
  scores 0/36, and a near-perfect one with a single 2.5%-off `actual` scores
  ~99.4%, matching the formula by hand.

Run it:
```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
python3 evaluate.py /path/to/some_submission.json          # against ground truth
python3 evaluate.py /path/to/some_submission.json --report full_report.json
```

## What's NOT built yet — and why

`src/agents/gemini_document_processor.py` and `src/agents/covenant_extractor.py`
are written against the real Gemini structured-output API, but **untested**,
because the `documents/` folder wasn't part of this upload (you noted it's a
folder and couldn't attach it here). I can't verify prompt quality, JSON-schema
fit, or PDF-extraction accuracy without real documents.

**Next step: zip your `documents/` folder and upload it** (e.g.
`documents.zip`, or split into a few smaller zips if there's a size limit).
Once I have it I can:
1. Actually run `gemini_document_processor.py` on a sample and inspect the
   extraction quality (does it correctly find `account_id`s, get clause text
   verbatim, catch exception language?).
2. Tune `covenant_extractor.py`'s prompt against real clause wording — the
   12 scenarios × 3 covenants = 36 clauses will have real patterns (leverage
   ratios, expense caps, DSCR, etc.) that the current prompt is only a
   reasonable first guess at.
3. Run `run_agent.py` end-to-end and score the result with `evaluate.py`.
4. Iterate on whichever covenant type is scoring worst.

You'll also need a `GEMINI_API_KEY` environment variable set (from Google
AI Studio) to run the document-processing and extraction stages.

## Rule separation — please keep this boundary

The challenge explicitly prohibits manually-obtained answers and says
`ground_truth.json` must stay evaluation-only. This repo enforces that
structurally:
- `run_agent.py` (production) never imports anything under `evaluation/`.
- `evaluate.py` is the **only** file that reads `ground_truth.json`, and it's
  a separate, standalone script — not a library imported by the agent.
- Nothing in `src/` hardcodes any scenario's `status`/`actual`/`evidence_txn_id`.
  I did not look at `ground_truth.json`'s values when writing the entity
  resolver or financial engine logic — those were derived from `CASE.md`'s
  rules and the ledger's own structure, then checked with `evaluate.py`
  after the fact, same as your own report's Phase 7 describes.

Keep `evaluate.py` and `evaluation/` out of anything you'd hand in or run
in front of the judges as "the agent" — it's your local test harness only.

## Repo layout
```
halyk-ai-challenge/
├── data/                     # ledger, template (add documents/ here once you upload it)
├── evaluation/
│   └── ground_truth.json     # LOCAL EVAL ONLY — never imported by run_agent.py
├── src/
│   ├── ingestion/            # ledger_loader, entity_resolver  ✅ tested
│   ├── models/                # covenant_dsl                   ✅
│   ├── engine/                # financial_engine                ✅ tested
│   ├── evidence/               # counterfactual                  ✅ tested
│   ├── agents/                 # gemini_document_processor,       ⚠️ untested — needs PDFs
│   │                          # covenant_extractor                ⚠️ untested — needs PDFs
│   └── validation/            # validator                         ✅
├── tests/                     # pytest — 7/7 passing
├── run_agent.py                # production entrypoint
└── evaluate.py                 # local scoring harness (ground-truth only lives here)
```
