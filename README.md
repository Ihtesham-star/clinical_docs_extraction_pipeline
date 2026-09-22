# clinical_docs_extraction_pipeline

A set of rule-based Python scripts for de-identifying, extracting structured
variables from, and reconciling duplicate records across Russian-language clinical
discharge documents that also contain embedded Kazakh personal names. Developed
for documents that mix Cyrillic and Latin script within the same clinical
abbreviation (e.g. scale names such as GMFCS or FIM), a case not handled by
existing English-language clinical NLP tooling. Includes a synthetic, fully
fabricated test corpus and scoring script used to quantitatively validate the
pipeline without using any real patient data.

Archived at: [https://doi.org/10.5281/zenodo.22896161](https://doi.org/10.5281/zenodo.22896161)

## Contents

| File | Purpose |
|---|---|
| `anonymize_all_pdfs.py` | Primary de-identification pass: text-search-based redaction of patient name, national ID number, and home address from PDF discharge documents. |
| `anonymize_timeout_files.py` | Word-level fallback redaction for documents that time out under the primary pass. |
| `extract_clinical_fields.py` | Structured variable extraction from de-identified documents, including mixed-script (Cyrillic/Latin homoglyph) tolerant patterns and a grammatical-gender-based sex-inference cascade. |
| `deduplicate_dataset.py` | Reconciles duplicate records across independently processed batches of the same source documents. |
| `generate_synthetic_test_corpus.py` | Generates a corpus of 85 fully synthetic documents, structurally matching the real document template, with a known ground-truth manifest, for quantitative validation without real patient data. |
| `compute_accuracy.py` | Scores the pipeline's output against the synthetic ground-truth manifest, computing de-identification recall, extraction accuracy, and sex-inference coverage/accuracy. |
| `latin_baseline_comparison.py` | Latin-only baseline: re-runs the scale-extraction patterns with plain Latin character classes (no homoglyph tolerance) and scores both variants against the manifest, quantifying the benefit of mixed-script tolerance. |

## Requirements

```bash
pip install -r requirements.txt
```

Developed and tested with PyMuPDF (`fitz`) — see https://pymupdf.readthedocs.io/

## Usage

Each pipeline script is intended to be run as a standalone step in the order
listed above (anonymize → extract → deduplicate). Input/output paths are
configured via constants at the top of each script; edit these before running.

```bash
python anonymize_all_pdfs.py
python anonymize_timeout_files.py   # only for documents flagged as timed out
python extract_clinical_fields.py
python deduplicate_dataset.py       # only if reconciling more than one batch
```

## Reproducing the validation results

The accuracy figures reported in the companion methods article were computed
as follows, and can be independently reproduced:

```bash
python generate_synthetic_test_corpus.py   # creates synthetic_test_docs/ and
                                            # synthetic_test_manifest.csv (fixed
                                            # random seed — regenerates the same
                                            # 85-document corpus every time)
python anonymize_all_pdfs.py               # point INPUT_FOLDER at synthetic_test_docs/
python extract_clinical_fields.py          # point INPUT_FOLDER at the anonymized output
python compute_accuracy.py                 # point ANONYMIZED_FOLDER / EXTRACTION_CSV
                                            # at the outputs of the two steps above
```

`compute_accuracy.py` prints de-identification recall (document-level and
mention-level), structured field extraction accuracy, and sex-inference
coverage/accuracy, scored automatically against the known ground truth in
`synthetic_test_manifest.csv` — no manual review required.

## Important notes

- **De-identification is not a substitute for a full privacy review.** These
  scripts perform pattern-based redaction of a specific, fixed set of fields
  (name, national ID number, home address) and were built for one institutional
  document template. They are not a general-purpose or certified de-identification
  solution, and should not be assumed to catch every form of identifying
  information in a differently structured document.
- **Name redaction uses stem-based matching to cover declined forms.**
  Russian personal names inflect by grammatical case, so in addition to the
  full labelled name, each name part is reduced to a stem (trailing vowels
  stripped, minimum stem length 5). Stems are matched twice per page: as
  exact substrings, and in a case-insensitive word-level pass (upper-normalised
  prefix comparison, length difference capped at 4), since the labelled field
  records names in UPPER CASE while narrative mentions are Title-case.
  Hyphenated name parts also contribute their components as separate stems.
  Measured on the synthetic corpus: nominative-only matching left declined
  mentions unredacted in 9/24 documents (mention-level recall 91.7%); with
  stem matching, 0/24 leaked (recall 109/109, 100%) with zero false-positive
  redactions. Additionally validated by a two-round independent review of 25
  real documents: 8 findings in round 1 (case variation, a hyphenated part,
  a missing Kazakh letter, short address lines), 0 findings after correction.
  Documents whose name cannot be detected at all are written to
  NEEDS_MANUAL_REVIEW.txt instead of being silently output. Irregularly
  declining names may need a morphological analyser (e.g. pymorphy2).
- **Name detection covers both Russian and Kazakh names.** The name-matching
  pattern's character class includes the Cyrillic letters unique to Kazakh
  (Ә, Ө, Ү, Қ, Ғ, Ң, Һ, І, Ұ) alongside the standard Russian Cyrillic alphabet,
  since patient names in the source documents include both.
- **Sex inference relies on grammatical gender agreement** in specific Russian
  narrative constructions (birth-history and disease-onset phrasing). This is
  grammatically reliable where these constructions are present, but covers
  Russian-language narrative only — it has not been extended to equivalent
  Kazakh-language constructions, and will simply produce no inference (rather
  than an incorrect one) for narrative written in Kazakh.

