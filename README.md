# clinical_docs_extraction_pipeline

A set of four rule-based Python scripts for de-identifying, extracting structured
variables from, and reconciling duplicate records across Russian-language clinical
discharge documents that also contain embedded Kazakh personal names. Developed
for documents that mix Cyrillic and Latin script within the same clinical
abbreviation (e.g. scale names such as GMFCS or FIM), a case not handled by
existing English-language clinical NLP tooling.

## Contents

| File | Purpose |
|---|---|
| `anonymize_all_pdfs.py` | Primary de-identification pass: text-search-based redaction of patient name, national ID number, and home address from PDF discharge documents. |
| `anonymize_timeout_files.py` | Word-level fallback redaction for documents that time out under the primary pass. |
| `extract_clinical_fields.py` | Structured variable extraction from de-identified documents, including mixed-script (Cyrillic/Latin homoglyph) tolerant patterns and a grammatical-gender-based sex-inference cascade. |
| `deduplicate_dataset.py` | Reconciles duplicate records across independently processed batches of the same source documents. |

## Requirements

```bash
pip install pymupdf pandas
```

Developed and tested with PyMuPDF (`fitz`) — see https://pymupdf.readthedocs.io/

## Usage

Each script is intended to be run as a standalone step in the order listed above
(anonymize → extract → deduplicate). Input/output paths are configured via
constants at the top of each script; edit these before running.

```bash
python anonymize_all_pdfs.py
python anonymize_timeout_files.py   # only for documents flagged as timed out
python extract_clinical_fields.py
python deduplicate_dataset.py       # only if reconciling more than one batch
```

## Important notes

- **De-identification is not a substitute for a full privacy review.** These
  scripts perform pattern-based redaction of a specific, fixed set of fields
  (name, national ID number, home address) and were built for one institutional
  document template. They are not a general-purpose or certified de-identification
  solution, and should not be assumed to catch every form of identifying
  information in a differently structured document.
- **Name redaction currently matches the nominative (dictionary) form only.**
  Russian personal names inflect by grammatical case; a name appearing elsewhere
  in a document in a declined form (genitive, accusative, etc.) will not be
  matched or redacted by the current implementation.
- **Name detection covers both Russian and Kazakh names.** The name-matching
  pattern's character class includes the Cyrillic letters unique to Kazakh
  (Ә, Ү, Қ, Ғ, Ң, Һ, І, Ұ) alongside the standard Russian Cyrillic alphabet,
  since patient names in the source documents include both.
- **Sex inference relies on grammatical gender agreement** in specific Russian
  narrative constructions (birth-history and disease-onset phrasing). This is
  grammatically reliable where these constructions are present, but covers
  Russian-language narrative only — it has not been extended to equivalent
  Kazakh-language constructions, and will simply produce no inference (rather
  than an incorrect one) for narrative written in Kazakh.

