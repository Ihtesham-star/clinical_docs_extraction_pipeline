
import fitz
import re
from pathlib import Path


TIMEOUT_FILES = [
]


OUTPUT_FOLDER = r""


OUTPUT_NAMES = [

]
# ──────────────────────────────────────────────────────────────────────────


def get_patient_info(doc):
    """Extract patient name and IIN from the document text."""
    full_text = "".join(page.get_text() for page in doc)

    iin_match = re.search(r'\b(\d{12})\b', full_text)
    iin = iin_match.group(1) if iin_match else None

    name_match = re.search(
        r'больного\)\s+([А-ЯӘҮҚҒҢҺІҰЙа-яәүқғңһіұй\s]+?)\s+\d{12}',
        full_text
    )
    patient_name = name_match.group(1).strip() if name_match else None

    # Build list of individual name parts + IIN
    targets = set()
    if patient_name:
        for part in patient_name.split():
            if len(part) >= 3:
                targets.add(part.upper())
    if iin:
        targets.add(iin)

    return patient_name, iin, targets


def get_address_rects(page):
    """Find the bounding box of the address field (field 3) on page 1."""
    rects = []
    blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)

    found_addr = False
    for block in blocks:
        text = block[4].strip()
        if 'Домашний адрес' in text or 'Үйінің мекенжайы' in text:
            found_addr = True
            continue
        if found_addr and ('Жұмыс орны' in text or 'Место работы' in text):
            break
        if found_addr and len(text) > 10:
            rects.append(fitz.Rect(block[0], block[1], block[2], block[3]))

    return rects


def anonymize_precise(input_path, output_path):
    doc = fitz.open(input_path)
    patient_name, iin, name_parts = get_patient_info(doc)

    print(f"  Name detected: {patient_name}")
    print(f"  IIN detected:  {iin}")
    print(f"  Name parts to redact: {name_parts}")

    total_redactions = 0

    for page_num, page in enumerate(doc):
        redacted_on_page = 0

        
        words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,word_no)
        for word_data in words:
            word = word_data[4].strip().upper()
            # Check if this word matches any name part or IIN
            if word in name_parts:
                rect = fitz.Rect(word_data[0], word_data[1],
                                 word_data[2], word_data[3])
                # Expand slightly to catch surrounding whitespace
                rect = rect + (-2, -1, 2, 1)
                page.add_redact_annot(rect, fill=(1, 1, 1))
                redacted_on_page += 1

        
        if page_num == 0:
            addr_rects = get_address_rects(page)
            for r in addr_rects:
                page.add_redact_annot(r, fill=(1, 1, 1))
                redacted_on_page += len(addr_rects)

        total_redactions += redacted_on_page
        page.apply_redactions()

    doc.save(output_path, incremental=False)
    doc.close()
    return total_redactions, patient_name is not None, iin is not None


def main():
    output_folder = Path(OUTPUT_FOLDER)
    output_folder.mkdir(parents=True, exist_ok=True)

    for input_path, out_name in zip(TIMEOUT_FILES, OUTPUT_NAMES):
        input_path = Path(input_path)
        output_path = output_folder / out_name

        print(f"\nProcessing: {input_path.name}")
        try:
            count, found_name, found_iin = anonymize_precise(
                str(input_path), str(output_path)
            )
            status = "OK"
            if not found_name:
                status += " ⚠ no name detected"
            if not found_iin:
                status += " ⚠ no IIN detected"
            print(f"  → {out_name} | {count} redactions | {status}")
        except Exception as e:
            print(f"  → FAILED: {e}")

    print("\nDone. Check the output files visually to confirm names are removed.")


if __name__ == "__main__":
    main()
