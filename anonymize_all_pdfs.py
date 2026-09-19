

import fitz
import re
import csv
import multiprocessing
from pathlib import Path

INPUT_FOLDER  = r"C:\Users\01\Desktop\Nccr_Data_annonymization\MethodX\synthetic_test_docs"
OUTPUT_FOLDER = r"C:\Users\01\Desktop\Nccr_Data_annonymization\MethodX\anon_output"

TIMEOUT_SECONDS = 30  # skip file if it takes longer than this


def anonymize_pdf(input_path, output_path, result_queue):
    """Runs in a separate process so it can be killed on timeout."""
    try:
        doc = fitz.open(input_path)
        full_text = "".join(page.get_text() for page in doc)

        iin_match = re.search(r'\b(\d{12})\b', full_text)
        iin = iin_match.group(1) if iin_match else None

        name_match = re.search(
            r'больного\)\s+([А-ЯЁӘҮҚҒҢҺІҰЙа-яёәүқғңһіұй\s]+?)\s+\d{12}',
            full_text
        )
        patient_name = name_match.group(1).strip() if name_match else None

        address_match = re.search(
            r'Домашний адрес\)\s*\n(.*?)\n4\.', full_text, re.DOTALL
        )
        address_lines = []
        if address_match:
            for line in address_match.group(1).strip().split('\n'):
                if len(line.strip()) > 10:
                    address_lines.append(line.strip())

                VOWELS = "аеёиоуыэюяәүіұ"

        def _stem(word):
            w = word
            while len(w) > 5 and w[-1].lower() in VOWELS:
                w = w[:-1]
            return w

        to_redact = []
        if patient_name:
            to_redact.append(patient_name)
            for part in patient_name.split():
                s = _stem(part)
                to_redact.append(s if len(s) >= 5 else part)
        if iin:
            to_redact.append(iin)
        to_redact.extend(address_lines)

        count = 0
        for page in doc:
            for text in to_redact:
                if not text or len(text) < 3:
                    continue
                for inst in page.search_for(text):
                    page.add_redact_annot(inst, fill=(1, 1, 1))
                    count += 1
            page.apply_redactions()

        doc.save(output_path)
        doc.close()
        result_queue.put(('ok', count, patient_name is not None, iin is not None))

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
        return 0, False, False, 'TIMEOUT — file skipped'

    if not q.empty():
        result = q.get()
        if result[0] == 'ok':
            return result[1], result[2], result[3], 'OK'
        else:
            return 0, False, False, f'FAILED: {result[1]}'

    return 0, False, False, 'UNKNOWN ERROR'


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

        count, found_name, found_iin, status = process_with_timeout(pdf_path, out_path)

        if 'TIMEOUT' in status:
            timeouts += 1
            print(f"[{i}/{total}] TIMEOUT: {pdf_path.name} — skipped after {TIMEOUT_SECONDS}s")
        elif 'FAILED' in status:
            failed += 1
            print(f"[{i}/{total}] FAILED: {pdf_path.name} — {status}")
        else:
            success += 1
            flag = " ⚠ no name/IIN" if not found_name or not found_iin else ""
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


if __name__ == "__main__":
    multiprocessing.freeze_support()  # needed for Windows
    main()
