
import fitz
import pandas as pd
from pathlib import Path

# ── CONFIGURE ────────────────────────────────────────────────────────────────
MANIFEST_FILE = Path("synthetic_test_manifest.csv")
ANONYMIZED_FOLDER = Path("")   # output of your anonymize_*.py run on the synthetic docs
EXTRACTION_CSV = Path("")      # output of your extract_clinical_fields.py run
# ────────────────────────────────────────────────────────────────────────────


def deid_scoring():
    manifest = pd.read_csv(MANIFEST_FILE, encoding="utf-8-sig", dtype={"iin": str})
    manifest = manifest.sort_values("filename").reset_index(drop=True)

    anon_files = sorted(ANONYMIZED_FOLDER.glob("*.pdf"))

    if len(anon_files) == 0:
        print("=== DE-IDENTIFICATION SCORING ===")
        print(f"No PDF files found in ANONYMIZED_FOLDER ('{ANONYMIZED_FOLDER}').")
        print("Check that this path is correct and that your anonymize script's "
              "output actually landed there.")
        return

    if len(anon_files) != len(manifest):
        print("=== DE-IDENTIFICATION SCORING ===")
        print(f"WARNING: manifest has {len(manifest)} documents but "
              f"ANONYMIZED_FOLDER has {len(anon_files)} PDF files. These are "
              f"paired by sorted position below, but a count mismatch means "
              f"some documents were likely skipped or dropped during "
              f"anonymization — check for errors in that step before trusting "
              f"these numbers.")

    n = min(len(manifest), len(anon_files))

    # Pair by sorted position, since output filenames do not match input
    # filenames (e.g. anon_001.pdf instead of synthetic_000.pdf). Print the
    # first few pairs so you can visually confirm the pairing is correct.
    print("=== DE-IDENTIFICATION SCORING ===")
    print("First 5 filename pairings used (VERIFY these look correctly matched):")
    for i in range(min(5, n)):
        print(f"  {manifest.iloc[i]['filename']}  <->  {anon_files[i].name}")
    print()

    name_field_hits = 0       # document-level: was the labeled name field itself redacted
    iin_recall_hits = 0
    address_recall_hits = 0
    declined_name_leak = 0
    declined_name_total = 0

    total_mentions = 0        # mention-level: primary field + declined mentions, counted separately
    redacted_mentions = 0

    for i in range(n):
        row = manifest.iloc[i]
        anon_path = anon_files[i]

        doc = fitz.open(str(anon_path))
        page_text = "\n".join(page.get_text() for page in doc)
        doc.close()

        # Document-level: was the primary labeled name field redacted?
        primary_redacted = row["full_name"] not in page_text
        if primary_redacted:
            name_field_hits += 1
        total_mentions += 1
        if primary_redacted:
            redacted_mentions += 1

        if row["iin"] not in page_text:
            iin_recall_hits += 1
        if row["address"] not in page_text:
            address_recall_hits += 1

        if row["used_declined_name_mention"] == True or row["used_declined_name_mention"] == "True":
            surname = row["surname"]
            if surname.endswith("а"):
                declined = surname[:-1] + "ой"
            elif surname.endswith("ов") or surname.endswith("ин"):
                declined = surname + "а"
            else:
                continue
            declined_name_total += 1
            total_mentions += 1
            leaked = declined in page_text
            if leaked:
                declined_name_leak += 1
            else:
                redacted_mentions += 1

    print(f"Documents scored: {n}")
    print(f"Document-level name field redaction (primary labeled field only): "
          f"{name_field_hits}/{n}  ({100*name_field_hits/n:.1f}%)")
    print(f"IIN redaction recall:     {iin_recall_hits}/{n}  ({100*iin_recall_hits/n:.1f}%)")
    print(f"Address redaction recall: {address_recall_hits}/{n}  ({100*address_recall_hits/n:.1f}%)")
    if declined_name_total:
        leaked_pct = 100 * declined_name_leak / declined_name_total
        redacted_declined = declined_name_total - declined_name_leak
        print(f"\nDeclined-name-form leakage (of {declined_name_total} documents with a "
              f"declined-case surname mention): {declined_name_leak}/{declined_name_total} "
              f"({leaked_pct:.1f}%) unredacted — this quantifies the declension "
              f"limitation described in Method 1.")
        print(f"\nMENTION-LEVEL name recall (every occurrence of the name, primary "
              f"field + declined mentions, counted individually): "
              f"{redacted_mentions}/{total_mentions}  "
              f"({100*redacted_mentions/total_mentions:.1f}%)")
        print(f"  ({name_field_hits} primary fields + {redacted_declined} declined "
              f"mentions redacted, out of {n} primary + {declined_name_total} declined = "
              f"{total_mentions} total mentions)")


def extraction_scoring():
    if not EXTRACTION_CSV.exists() or not str(EXTRACTION_CSV):
        print("\n(EXTRACTION_CSV not set — skipping extraction scoring)")
        return

    manifest = pd.read_csv(MANIFEST_FILE, encoding="utf-8-sig")
    manifest = manifest.sort_values("filename").reset_index(drop=True)
    extracted = pd.read_csv(EXTRACTION_CSV, encoding="utf-8-sig")
    extracted = extracted.sort_values("record_file").reset_index(drop=True)

    # Match by sorted position, not filename, since the extraction CSV's
    # record_file column contains the ANONYMIZED filenames (e.g. anon_001.pdf),
    # not the original synthetic filenames — a direct merge on filename would
    # silently match zero rows.
    if len(manifest) != len(extracted):
        print(f"\nWARNING: manifest has {len(manifest)} rows but extraction "
              f"CSV has {len(extracted)} rows — pairing by sorted position "
              f"anyway, but this mismatch should be investigated.")
    n = min(len(manifest), len(extracted))
    merged = pd.concat(
        [manifest.iloc[:n].reset_index(drop=True),
         extracted.iloc[:n].reset_index(drop=True)],
        axis=1
    )

    fields = [
        ("gmfcs_expected", "gmfcs"),
        ("macs_expected", "macs"),
        ("shm_r1_expected", "shm_admission"),
        ("shm_r2_expected", "shm_discharge"),
    ]

    print("\n=== EXTRACTION SCORING ===")
    for true_col, pred_col in fields:
        if pred_col not in merged.columns:
            print(f"{pred_col}: column not found in extraction output — check column names")
            continue
        correct = (merged[true_col].round(2) == pd.to_numeric(
            merged[pred_col], errors="coerce").round(2)).sum()
        total = len(merged)
        print(f"{pred_col}: {correct}/{total} correct  ({100*correct/total:.1f}%)")

    # Homoglyph-specific subset accuracy for GMFCS/MACS
    homo = merged[merged["used_homoglyph_scales"] == True]
    if len(homo):
        gmfcs_correct = (homo["gmfcs_expected"].round(2) == pd.to_numeric(
            homo["gmfcs"], errors="coerce").round(2)).sum()
        print(f"\nHomoglyph-labelled documents only (n={len(homo)}): "
              f"GMFCS correctly extracted {gmfcs_correct}/{len(homo)} "
              f"({100*gmfcs_correct/len(homo):.1f}%) — quantifies Method 2's "
              f"mixed-script tolerance specifically.")


def sex_inference_scoring():
    """Scores Method 3 (grammatical-gender-based sex inference) against
    the manifest, reporting coverage (fraction of documents where an
    inference was produced at all) and accuracy (fraction of produced
    inferences that were correct), split by whether the document had a
    sex cue planted or not — documents with no cue should show low/zero
    coverage (correctly failing safe) rather than incorrect inferences."""
    if not EXTRACTION_CSV.exists() or not str(EXTRACTION_CSV):
        print("\n(EXTRACTION_CSV not set — skipping sex inference scoring)")
        return

    manifest = pd.read_csv(MANIFEST_FILE, encoding="utf-8-sig")
    manifest = manifest.sort_values("filename").reset_index(drop=True)
    extracted = pd.read_csv(EXTRACTION_CSV, encoding="utf-8-sig")
    extracted = extracted.sort_values("record_file").reset_index(drop=True)

    n = min(len(manifest), len(extracted))
    merged = pd.concat(
        [manifest.iloc[:n].reset_index(drop=True),
         extracted.iloc[:n].reset_index(drop=True)],
        axis=1
    )

    if "sex" not in merged.columns:
        print("\n(no 'sex' column found in extraction output — check column names)")
        return

    with_cue = merged[merged["has_sex_cue"] == True]
    no_cue = merged[merged["has_sex_cue"] == False]

    def _score(subset, label):
        produced = subset[subset["sex"].isin(["M", "F"])]
        coverage = len(produced) / len(subset) if len(subset) else 0
        if len(produced):
            correct = (produced["expected_sex"] == produced["sex"]).sum()
            accuracy = correct / len(produced)
        else:
            correct, accuracy = 0, None
        print(f"{label} (n={len(subset)}): "
              f"coverage {len(produced)}/{len(subset)} ({100*coverage:.1f}%), "
              f"accuracy of produced inferences "
              f"{correct}/{len(produced)} "
              f"({100*accuracy:.1f}%)" if accuracy is not None else
              f"{label} (n={len(subset)}): coverage {len(produced)}/{len(subset)} "
              f"({100*coverage:.1f}%), no inferences produced")

    print("\n=== METHOD 3 (SEX INFERENCE) SCORING ===")
    _score(with_cue, "Documents WITH a planted sex cue")
    _score(no_cue, "Documents with NO sex cue (fail-safe test)")


if __name__ == "__main__":
    deid_scoring()
    extraction_scoring()
    sex_inference_scoring()
