"""
Cross-batch duplicate reconciliation.

Detects and resolves duplicate records that arise when the same underlying
source documents are processed through more than one independent pipeline,
e.g. when documents are supplied in a pre-processed form and, separately, in
a raw form later processed independently. Retains all records from a
designated primary batch and adds only genuinely novel records from a
secondary batch, matched on a shared identifier extracted independently in
each batch.
"""

import pandas as pd
from pathlib import Path

# ── CONFIGURE ─────────────────────────────────────────────────────────────────
INPUT_FILE = r""          # combined dataset with a column identifying batch provenance
OUTPUT_FILE = r""
BATCH_COLUMN = "record_file"       # column used to identify which batch a row came from
PRIMARY_PREFIX = "batch_a_"        # filename/tag prefix identifying the primary batch
SECONDARY_PREFIX = "batch_b_"      # filename/tag prefix identifying the secondary batch
ID_COLUMN = "record_number"        # shared unique identifier present in both batches
# ─────────────────────────────────────────────────────────────────────────────


def main():
    df = pd.read_csv(INPUT_FILE, encoding='utf-8-sig')
    print(f"Original dataset: {len(df)} records")
    print(f"Unique identifiers: {df[ID_COLUMN].nunique()}")

    primary = df[df[BATCH_COLUMN].str.startswith(PRIMARY_PREFIX)].copy()
    secondary = df[df[BATCH_COLUMN].str.startswith(SECONDARY_PREFIX)].copy()

    print(f"Primary batch: {len(primary)} records, "
          f"{primary[ID_COLUMN].nunique()} unique identifiers")
    print(f"Secondary batch: {len(secondary)} records, "
          f"{secondary[ID_COLUMN].nunique()} unique identifiers")

    # Step 1: exclude secondary-batch records whose identifier already
    # appears in the primary batch.
    primary_ids = set(primary[ID_COLUMN].dropna().unique())
    secondary_unique = secondary[~secondary[ID_COLUMN].isin(primary_ids)]

    print(f"Secondary-batch records with identifiers NOT in primary batch: "
          f"{len(secondary_unique)}")

    # Step 2: check the secondary batch for duplicates against itself.
    secondary_unique = secondary_unique.drop_duplicates(
        subset=ID_COLUMN, keep='first'
    )

    # Step 3: combine.
    reconciled = pd.concat([primary, secondary_unique], ignore_index=True)
    reconciled = reconciled.sort_values(BATCH_COLUMN).reset_index(drop=True)

    print(f"Reconciled dataset: {len(reconciled)} unique records")

    # Step 4: verification — confirm no duplicate identifiers remain.
    remaining_dupes = reconciled[ID_COLUMN].duplicated().sum()
    print(f"Remaining duplicate identifiers: {remaining_dupes}")
    assert remaining_dupes == 0, "Reconciliation incomplete — duplicates remain."

    reconciled.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
    print(f"Saved reconciled dataset: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
