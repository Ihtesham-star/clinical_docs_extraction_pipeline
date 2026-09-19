"""
Latin-only baseline comparison (professor's item 3).

Runs TWO variants of the scale-extraction patterns over the anonymized
synthetic corpus and scores both against the ground-truth manifest:

  1. TOLERANT  — the homoglyph-tolerant patterns exactly as used in
                 extract_clinical_fields.py (control: should reproduce
                 the published 85/85 result, proving this script is a
                 faithful re-implementation).
  2. LATIN-ONLY — identical patterns except the mixed-script character
                 classes are replaced with plain Latin letters, i.e. the
                 behaviour of standard English-language tooling that does
                 not anticipate Cyrillic homoglyph contamination.

The ShM (R1/R2) patterns are anchored on Latin "R1"/"R2" and contain no
homoglyph character classes, so they are IDENTICAL in both variants and
serve as a negative control (both variants should score the same).

Usage: set the two paths below, then  python latin_baseline_comparison.py
"""

import re
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd

# ── CONFIGURE ────────────────────────────────────────────────────────────────
ANON_FOLDER = Path(r"")           # folder with anon_*.pdf from the synthetic run
MANIFEST_FILE = Path(r"")
# ─────────────────────────────────────────────────────────────────────────────

NUM = r"(\d+[,\.]\d+)"

# Patterns: (field, tolerant_regex, latin_only_regex)
# The ONLY difference between the two columns is the character class for
# letters that have Cyrillic homoglyphs; everything else is byte-identical.
PATTERNS = [
    ("gmfcs",
     r"G[МM]FCS[^0-9]{0,30}([1-5])",
     r"GMFCS[^0-9]{0,30}([1-5])"),
    ("macs",
     r"[МM][АA][СC][СCS](?![а-яёА-ЯЁa-zA-Z])[^0-9]{0,100}([1-5])",
     r"MACS(?![а-яёА-ЯЁa-zA-Z])[^0-9]{0,100}([1-5])"),
]

SHM_R1 = r"R1\s*=\s*\([^)]*\)\s*:?\s*2\s*=?\s*\([^)]*\)\s*:?\s*2\s*=?\s*[_\s]*" + NUM
SHM_R2 = r"R2\s*=\s*\([^)]*\)\s*:?\s*2\s*=?\s*\([^)]*\)\s*:?\s*2\s*=?\s*[_\s]*" + NUM


def extract(text, latin_only):
    out = {}
    for field, tol, lat in PATTERNS:
        m = re.search(lat if latin_only else tol, text, re.IGNORECASE | re.DOTALL)
        out[field] = m.group(1) if m else "NA"
    for field, pat in (("shm_r1", SHM_R1), ("shm_r2", SHM_R2)):
        m = re.search(pat, text, re.IGNORECASE)
        out[field] = m.group(1).replace(",", ".") if m else "NA"
    return out


def main():
    manifest = pd.read_csv(MANIFEST_FILE, encoding="utf-8-sig")
    manifest = manifest.sort_values("filename").reset_index(drop=True)
    pdfs = sorted(ANON_FOLDER.glob("*.pdf"))
    assert len(pdfs) == len(manifest), (
        f"manifest has {len(manifest)} rows but {ANON_FOLDER} has "
        f"{len(pdfs)} PDFs — cannot align by sorted position")

    rows = []
    for i, pdf in enumerate(pdfs):
        doc = fitz.open(str(pdf))
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        row = {"i": i}
        for variant, latin in (("tol", False), ("lat", True)):
            for k, v in extract(text, latin).items():
                row[f"{variant}_{k}"] = v
        rows.append(row)
    res = pd.DataFrame(rows)

    truth = manifest[["gmfcs_expected", "macs_expected",
                      "shm_r1_expected", "shm_r2_expected",
                      "used_homoglyph_scales"]].reset_index(drop=True)
    df = pd.concat([truth, res], axis=1)

    def correct(pred_col, true_col):
        pred = pd.to_numeric(df[pred_col], errors="coerce").round(2)
        return pred == df[true_col].round(2)

    fields = [("gmfcs", "gmfcs_expected"), ("macs", "macs_expected"),
              ("shm_r1", "shm_r1_expected"), ("shm_r2", "shm_r2_expected")]

    homo = df["used_homoglyph_scales"] == True   # noqa: E712
    n, nh, nc = len(df), int(homo.sum()), int((~homo).sum())

    print(f"Documents: {n} total | {nh} homoglyph-contaminated | {nc} clean\n")
    header = (f"{'field':10} | {'tolerant (ours)':>18} | {'Latin-only baseline':>20} | "
              f"{'baseline on homoglyph subset':>28} | {'baseline on clean subset':>24}")
    print(header)
    print("-" * len(header))
    for f, t in fields:
        ok_tol = correct(f"tol_{f}", t)
        ok_lat = correct(f"lat_{f}", t)
        print(f"{f:10} | {int(ok_tol.sum()):>7}/{n} ({100*ok_tol.mean():5.1f}%) | "
              f"{int(ok_lat.sum()):>8}/{n} ({100*ok_lat.mean():5.1f}%) | "
              f"{int(ok_lat[homo].sum()):>16}/{nh} ({100*ok_lat[homo].mean():5.1f}%) | "
              f"{int(ok_lat[~homo].sum()):>12}/{nc} ({100*ok_lat[~homo].mean():5.1f}%)")

    print("\nInterpretation guide: the 'tolerant' column should reproduce the "
          "published 85/85 results (control). The gap between the two GMFCS/MACS "
          "columns, concentrated in the homoglyph subset, is the measured benefit "
          "of mixed-script tolerance. shm_r1/shm_r2 use identical patterns in "
          "both variants (negative control) and should show no gap.")


if __name__ == "__main__":
    main()
