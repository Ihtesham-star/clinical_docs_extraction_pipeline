

import fitz
import re
import csv
import multiprocessing
from pathlib import Path

INPUT_FOLDER  = r""
OUTPUT_FOLDER = r""

TIMEOUT_SECONDS = 30  # skip file if it takes longer than this


def anonymize_pdf(input_path, output_path, result_queue):
    """Runs in a separate process so it can be killed on timeout."""
    try:
        doc = fitz.open(input_path)
        full_text = "".join(page.get_text() for page in doc)

        iin_match = re.search(r'\b(\d{12})\b', full_text)
        iin = iin_match.group(1) if iin_match else None

        # Character class covers the full Kazakh Cyrillic alphabet
        # (incl. Ө) and hyphenated name parts.
        name_match = re.search(
            r'больного\)\s+([А-ЯЁӘӨҮҚҒҢҺІҰЙа-яёәөүқғңһіұй\s\-]+?)\s+\d{12}',
            full_text
        )
        patient_name = name_match.group(1).strip() if name_match else None

        address_match = re.search(
            r'Домашний адрес\)\s*\n(.*?)\n4\.', full_text, re.DOTALL
        )
        # Every non-empty line of the address block is redacted; a minimum-
        # length filter previously skipped short lines such as «ДОМ: 11»,
        # leaving partial addresses in the output.
        address_lines = []
        if address_match:
            for line in address_match.group(1).strip().split('\n'):
                line = line.strip()
                if line:
                    address_lines.append(line)

        VOWELS = "аеёиоуыэюяәөүіұ"

        def _stem(word):
            w = word
            while len(w) > 5 and w[-1].lower() in VOWELS:
                w = w[:-1]
            return w

        # Name targets: full labelled string (exact search), plus per-part
        # stems for the word-level pass below. Hyphenated parts also
        # contribute their components (>= 4 chars) so a component reused
        # alone elsewhere is still caught.
        name_parts = patient_name.split() if patient_name else []
        name_stems = set()
        for part in name_parts:
            subparts = [part] + ([p for p in part.split('-') if len(p) >= 4]
                                 if '-' in part else [])
            for p in subparts:
                s = _stem(p)
                name_stems.add((s if len(s) >= 5 else p).upper())

        to_redact = []
        if patient_name:
            to_redact.append(patient_name)
            for part in name_parts:
                s = _stem(part)
                to_redact.append(s if len(s) >= 5 else part)
        if iin:
            to_redact.append(iin)
        to_redact.extend(address_lines)

        count = 0
        for page in doc:
            # Pass A: exact substring search (full name string, IIN,
            # address lines, nominative/stem forms as typed in the
            # labelled field).
            for text in to_redact:
                if not text or len(text) < 3:
                    continue
                for inst in page.search_for(text):
                    page.add_redact_annot(inst, fill=(1, 1, 1))
                    count += 1
            # Pass B: case-insensitive word-level scan. The labelled field
            # is upper-case while narrative mentions are title-case, and
            # exact substring search does not bridge that; comparing
            # upper-normalised words against upper-normalised stems does.
            # The length cap stops a stem from swallowing much longer
            # unrelated words.
            if name_stems:
                for w in page.get_text("words"):
                    token = w[4].strip().upper()
                    if any(token.startswith(s) and len(token) - len(s) <= 4
                           for s in name_stems):
                        rect = fitz.Rect(w[0], w[1], w[2], w[3])
                        page.add_redact_annot(rect, fill=(1, 1, 1))
                        count += 1
            page.apply_redactions()

        doc.save(output_path)
        doc.close()
        result_queue.put(('ok', count, patient_name is not None, iin is not None,
                          len(name_parts)))

    except Exception as e:
        result_queue.put(('error', str(e)))


def process_with_timeout(pdf_path, out_path):
    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=anonymize_pdf, args=(str(pdf_path), str(out_path), q))
    p.start()
    p.join(TIMEOUT_SECONDS)

    if p.is_alive():
        p.terminate()
        p.join()
        return 0, False, False, 0, 'TIMEOUT — file skipped'

    if not q.empty():
        result = q.get()
        if result[0] == 'ok':
            return result[1], result[2], result[3], result[4], 'OK'
        else:
            return 0, False, False, 0, f'FAILED: {result[1]}'

    return 0, False, False, 0, 'UNKNOWN ERROR'


def main():
    input_folder  = Path(INPUT_FOLDER)
    output_folder = Path(OUTPUT_FOLDER)
    output_folder.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(input_folder.glob("*.pdf"))
    total = len(pdf_files)

    if total == 0:
        print(f"No PDF files found in: {INPUT_FOLDER}")
        return

    print(f"Found {total} PDF files.\n")

    mapping_path = output_folder / "PRIVATE_mapping_do_not_share.csv"
    mapping_rows = []
    needs_review = []
    success, failed, timeouts = 0, 0, 0

    for i, pdf_path in enumerate(pdf_files, 1):
        anon_name = f"anon_{i:03d}.pdf"
        out_path  = output_folder / anon_name

        # Skip if already done
        if out_path.exists():
            print(f"[{i}/{total}] SKIP (already done): {anon_name}")
            mapping_rows.append({
                "anon_id": anon_name,
                "original_name": pdf_path.name,
                "redactions": "?",
                "status": "SKIPPED (already existed)"
            })
            continue

        count, found_name, found_iin, n_parts, status = process_with_timeout(pdf_path, out_path)

        if 'TIMEOUT' in status:
            timeouts += 1
            print(f"[{i}/{total}] TIMEOUT: {pdf_path.name} — skipped after {TIMEOUT_SECONDS}s")
        elif 'FAILED' in status:
            failed += 1
            print(f"[{i}/{total}] FAILED: {pdf_path.name} — {status}")
        else:
            success += 1
            flag = ""
            if not found_name or n_parts < 2:
                flag = " ⚠⚠ NAME NOT (FULLY) DETECTED — output may contain the patient name; MANUAL REVIEW REQUIRED"
                needs_review.append(pdf_path.name)
            elif not found_iin:
                flag = " ⚠ no IIN detected"
            print(f"[{i}/{total}] OK {anon_name} <- {pdf_path.name} ({count} redactions){flag}")

        mapping_rows.append({
            "anon_id": anon_name,
            "original_name": pdf_path.name,
            "redactions": count,
            "status": status
        })

    with open(mapping_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["anon_id", "original_name", "redactions", "status"]
        )
        writer.writeheader()
        writer.writerows(mapping_rows)

    print(f"\n{'='*60}")
    print(f"DONE. Total: {total} | OK: {success} | Timeout: {timeouts} | Failed: {failed}")
    print(f"Anonymized files -> {OUTPUT_FOLDER}")
    print(f"Mapping file (PRIVATE) -> {mapping_path}")
    if needs_review:
        review_path = output_folder / "NEEDS_MANUAL_REVIEW.txt"
        with open(review_path, "w", encoding="utf-8") as f:
            f.write("\n".join(needs_review))
        print(f"\n⚠⚠ {len(needs_review)} document(s) had no (full) name detected and MUST be manually reviewed/redacted:")
        for n in needs_review:
            print(f"   - {n}")
        print(f"List written to -> {review_path}  (PRIVATE — contains original filenames)")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # needed for Windows
    main()
