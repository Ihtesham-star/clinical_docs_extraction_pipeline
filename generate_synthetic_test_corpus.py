"""
Generate a corpus of synthetic (fully fabricated) clinical discharge documents,
structurally matching the real document template, for quantitative validation
of the de-identification and extraction pipeline.

Every document is entirely fictional: names, IINs, addresses, and clinical
values are all randomly generated. A ground-truth manifest (CSV) records the
"correct answer" for every field the pipeline should extract or redact, so
that pipeline output can be automatically scored (precision/recall) against
this known answer key using compute_deid_accuracy.py, with no manual review
and no real patient data involved anywhere in the process.

Requirements: pip install pymupdf
"""

import fitz
import random
import csv
from pathlib import Path

# ── CONFIGURE ────────────────────────────────────────────────────────────────
N_DOCS = 85
OUTPUT_FOLDER = Path("synthetic_test_docs")
MANIFEST_FILE = Path("synthetic_test_manifest.csv")
SEED = 42  # fixed seed for reproducibility
# ────────────────────────────────────────────────────────────────────────────

random.seed(SEED)

# ── FAKE NAME POOLS (entirely fabricated, not real patients) ─────────────────
RUSSIAN_MALE_FIRST = ["Александр", "Дмитрий", "Максим", "Артём", "Иван", "Кирилл",
                       "Никита", "Егор", "Тимур", "Владислав"]
RUSSIAN_FEMALE_FIRST = ["Анна", "Мария", "Елена", "Дарья", "София", "Алина",
                         "Виктория", "Полина", "Ксения", "Юлия"]
RUSSIAN_LAST_MALE = ["Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецов",
                      "Попов", "Соколов", "Лебедев", "Козлов", "Новиков"]
RUSSIAN_LAST_FEMALE = ["Иванова", "Петрова", "Сидорова", "Смирнова", "Кузнецова",
                        "Попова", "Соколова", "Лебедева", "Козлова", "Новикова"]
RUSSIAN_PATRONYMIC_MALE = ["Александрович", "Дмитриевич", "Сергеевич",
                            "Игоревич", "Андреевич"]
RUSSIAN_PATRONYMIC_FEMALE = ["Александровна", "Дмитриевна", "Сергеевна",
                              "Игоревна", "Андреевна"]

# Kazakh names, including the extended Cyrillic letters (Ә Ү Қ Ғ Ң Һ І Ұ)
# to test that Method 1's character class correctly captures them.
KAZAKH_MALE_FIRST = ["Алдияр", "Ерасыл", "Нұрсұлтан", "Асқар", "Бекзат",
                      "Дәулет", "Жандос", "Қайрат"]
KAZAKH_FEMALE_FIRST = ["Айгерім", "Дінара", "Меруерт", "Гүлнәр", "Сәуле",
                        "Ақбота", "Қарлығаш", "Әсел"]
KAZAKH_LAST = ["Нұрланұлы", "Серікұлы", "Жанұзақов", "Тұрсынов", "Әбдіров",
               "Қасымов", "Мұқанов"]

STREETS = ["ул. Тестовая", "ул. Образцовая", "пр. Демо", "ул. Примерная",
           "мкр. Синтетика", "ул. Вымышленная"]

DIAGNOSES = ["G80.1", "G80.2", "F80.8", "F84.0", "Q90.0"]


def random_iin():
    """Fabricated 12-digit identifier, structurally valid, not a real IIN."""
    return "".join(str(random.randint(0, 9)) for _ in range(12))


def make_name(sex):
    if random.random() < 0.25:  # ~25% of names are Kazakh
        if sex == "F":
            first = random.choice(KAZAKH_FEMALE_FIRST)
        else:
            first = random.choice(KAZAKH_MALE_FIRST)
        last = random.choice(KAZAKH_LAST)
        return f"{last} {first}", last, first, None
    else:
        if sex == "F":
            last = random.choice(RUSSIAN_LAST_FEMALE)
            first = random.choice(RUSSIAN_FEMALE_FIRST)
            patronymic = random.choice(RUSSIAN_PATRONYMIC_FEMALE)
        else:
            last = random.choice(RUSSIAN_LAST_MALE)
            first = random.choice(RUSSIAN_MALE_FIRST)
            patronymic = random.choice(RUSSIAN_PATRONYMIC_MALE)
        return f"{last} {first} {patronymic}", last, first, patronymic


def make_address():
    street = random.choice(STREETS)
    house = random.randint(1, 200)
    apt = random.randint(1, 300)
    return f"{street}, д. {house}, кв. {apt}"


# ── SEX-INFERENCE CASCADE TEST PHRASES ────────────────────────────────────────
# One entry per cascade level (matches extract_clinical_fields.py exactly).
# "homoglyph" cases are included at ~15% rate to also test Method 2 alongside.
CASCADE_PHRASES = {
    1: {"F": "К груди приложена в родильном зале.", "M": None},
    2: {"M": "К груди приложен в родильном зале.", "F": None},
    3: {"F": "Закричала сразу, крик громкий.", "M": None},
    4: {"M": "Закричал сразу, крик громкий.", "F": None},
    5: {"F": "При рождении: девочка, доношенная.", "M": None},
    6: {"M": "При рождении: мальчик, доношенный.", "F": None},
    7: {"F": "Больна с рождения, наблюдается неврологом.", "M": None},
    8: {"M": "Болен с рождения, наблюдается неврологом.", "F": None},
}


def make_birth_history(sex, cascade_level):
    """Returns narrative text containing only the phrase for the given
    cascade level, so ground truth is unambiguous."""
    phrase = CASCADE_PHRASES[cascade_level][sex]
    return phrase


def make_scale_block(use_homoglyph):
    """Builds a scale-score block. use_homoglyph substitutes Cyrillic
    lookalikes for GMFCS/MACS labels (М and С) to test Method 2's
    mixed-script tolerance."""
    gmfcs_val = random.randint(1, 5)
    macs_val = random.randint(1, 5)
    if use_homoglyph:
        # Cyrillic М (U+041C) instead of Latin M; Cyrillic С (U+0421) instead of Latin S/C
        gmfcs_label = "G\u041cFCS"
        macs_label = "\u041c\u0410\u0421\u0421"
    else:
        gmfcs_label = "GMFCS"
        macs_label = "MACS"

    shm_r1 = round(random.uniform(1.0, 4.0), 2)
    shm_r2 = round(shm_r1 - random.uniform(0.0, 0.8), 2)
    shm_x1, shm_y1 = round(shm_r1 * 2 - 0.1, 1), round(shm_r1 * 2 + 0.1, 1)
    shm_x2, shm_y2 = round(shm_r2 * 2 - 0.1, 1), round(shm_r2 * 2 + 0.1, 1)

    block = (
        f"{gmfcs_label}: {gmfcs_val}\n"
        f"{macs_label}: {macs_val}\n"
        f"R1 = (X1+Y1):2 = ({shm_x1}+{shm_y1}):2 = {shm_r1}\n"
        f"R2 = (X2+Y2):2 = ({shm_x2}+{shm_y2}):2 = {shm_r2}\n"
    )
    return block, {
        "gmfcs_expected": gmfcs_val,
        "macs_expected": macs_val,
        "shm_r1_expected": shm_r1,
        "shm_r2_expected": shm_r2,
        "used_homoglyph": use_homoglyph,
    }


def build_document_text(sex, full_name, iin, address, cascade_level,
                         use_homoglyph, use_declined_name, has_sex_cue):
    """Assembles full document text matching the real template's field
    labels and anchors, as used by the extraction/anonymization regex.

    has_sex_cue: if False, no birth-history/disease-onset phrase is
    inserted at all, so Method 3's cascade should correctly produce no
    inference (fail-safe) rather than a wrong one — this documents that
    the ~12% of documents with no cue are a deliberate test of that
    behaviour, not an oversight."""

    diagnosis = random.choice(DIAGNOSES)
    scale_block, scale_truth = make_scale_block(use_homoglyph)
    birth_phrase = make_birth_history(sex, cascade_level) if has_sex_cue else (
        "Поступил планово для проведения курса реабилитации."
    )

    # Optionally reference the patient a second time using a declined
    # (non-nominative) form of the surname, to quantify the declension
    # limitation directly. e.g. genitive case for a female surname
    # ending in -a: "Ивановой" instead of "Иванова".
    declined_mention = ""
    if use_declined_name:
        surname = full_name.split()[0]
        if surname.endswith("а"):
            declined = surname[:-1] + "ой"
        elif surname.endswith("ов") or surname.endswith("ин"):
            declined = surname + "а"
        else:
            declined = surname
        declined_mention = f"\nПовторный осмотр пациента {declined} проведён неврологом.\n"

    text = (
        f"ВЫПИСНОЙ ЭПИКРИЗ (синтетический тестовый документ)\n\n"
        f"Ф.И.О. больного) {full_name} {iin}\n\n"
        f"Домашний адрес)\n{address}\n4. Дата выписки: 01.01.2026\n\n"
        f"Диагноз: {diagnosis}\n\n"
        f"Анамнез: {birth_phrase}\n"
        f"{declined_mention}\n"
        f"Наименование шкал:\n{scale_block}\n"
        f"Определение: рекомендовано динамическое наблюдение.\n"
    )
    return text, scale_truth


# Candidate Cyrillic-capable font paths, checked in order, across platforms.
# The default PDF base-14 fonts (helv/times/cour) do NOT support Cyrillic at
# all and will silently render as blank glyphs, so a real font file must be
# located. If none of these exist on your machine, set FONT_PATH manually
# below to any .ttf/.otf file that supports Cyrillic (e.g. copy one into
# this folder and set FONT_PATH = "your_font.ttf").
FONT_PATH = None  # set this manually to override auto-detection, e.g. r"C:\Windows\Fonts\arial.ttf"

def _matplotlib_bundled_font():
    """matplotlib bundles its own copy of DejaVu Sans (used as its default
    rendering font), independent of any OS-installed fonts. This sidesteps
    platform-specific font/PyMuPDF quirks entirely, since it's the same
    file regardless of OS."""
    try:
        import matplotlib
        candidate = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        if candidate.exists():
            return str(candidate)
    except ImportError:
        pass
    return None


_CANDIDATE_FONTS = [
    _matplotlib_bundled_font(),  # tried first if matplotlib is installed
    # Windows
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    # macOS
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
_CANDIDATE_FONTS = [f for f in _CANDIDATE_FONTS if f]  # drop None entries

_SELF_TEST_STRING = "тест (проверка) больного) Артём Ё ё 1234567890"


def _font_round_trips_correctly(fontfile, verbose=False):
    """Writes a tiny throwaway PDF with the given font and confirms the
    extracted text exactly matches what was written — in particular, that
    plain ASCII parentheses and Cyrillic Ё/ё survive the round trip. If
    they don't, this font is unsafe to use and must be skipped, since a
    silent character substitution would corrupt every downstream regex
    match without any visible error."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_path = Path(tmp) / "font_test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_font(fontname="F0", fontfile=fontfile)
        page.insert_text((50, 50), _SELF_TEST_STRING, fontsize=11, fontname="F0")
        doc.save(str(test_path))
        doc.close()

        check = fitz.open(str(test_path))
        extracted = check[0].get_text().strip()
        check.close()

    ok = _SELF_TEST_STRING in extracted
    if not ok and verbose:
        print(f"    Expected: {_SELF_TEST_STRING!r}")
        print(f"    Got:      {extracted!r}")
        for exp_ch, got_ch in zip(_SELF_TEST_STRING, extracted):
            if exp_ch != got_ch:
                print(f"    First mismatch: expected {exp_ch!r} (U+{ord(exp_ch):04X}) "
                      f"got {got_ch!r} (U+{ord(got_ch):04X})")
                break
    return ok


def find_cyrillic_font():
    if FONT_PATH:
        if not Path(FONT_PATH).exists():
            raise FileNotFoundError(
                f"FONT_PATH was set to '{FONT_PATH}' but that file was not found."
            )
        if not _font_round_trips_correctly(FONT_PATH):
            raise RuntimeError(
                f"FONT_PATH ('{FONT_PATH}') does not round-trip correctly — "
                f"characters (likely parentheses or Ё/ё) were substituted on "
                f"extraction. Try a different font."
            )
        return FONT_PATH

    for candidate in _CANDIDATE_FONTS:
        if not Path(candidate).exists():
            continue
        if _font_round_trips_correctly(candidate, verbose=True):
            return candidate
        else:
            print(f"  (skipping {candidate} — failed character round-trip self-test)")

    raise FileNotFoundError(
        "No font was found that both supports Cyrillic AND passes the "
        "character round-trip self-test. Please set FONT_PATH near the top "
        "of this script to a different .ttf/.otf font file and re-run."
    )


def make_pdf(text, path, fontfile):
    doc = fitz.open()
    page = doc.new_page()
    # DejaVu Sans / Segoe UI / Arial all support Cyrillic, including the
    # extended Kazakh letters (Ә Ү Қ Ғ Ң Һ І Ұ).
    page.insert_font(fontname="F0", fontfile=fontfile)
    page.insert_text((50, 50), text, fontsize=11, fontname="F0")
    doc.save(str(path))
    doc.close()


def main():
    OUTPUT_FOLDER.mkdir(exist_ok=True)
    manifest_rows = []

    fontfile = find_cyrillic_font()
    print(f"Using font: {fontfile}")

    for i in range(N_DOCS):
        sex = random.choice(["M", "F"])
        full_name, last, first, patronymic = make_name(sex)
        iin = random_iin()
        address = make_address()
        cascade_level = random.choice([lvl for lvl in CASCADE_PHRASES
                                        if CASCADE_PHRASES[lvl][sex] is not None])
        use_homoglyph = random.random() < 0.20
        # Declension testing only applies to Russian-pattern surnames
        # (ending in а / ов / ин); Kazakh surnames in this generator
        # (e.g. -ұлы patronymic-style) do not follow the same declension
        # pattern, so applying the test to them would produce a
        # meaningless "undeclined == original" non-test.
        is_declinable = last.endswith("а") or last.endswith("ов") or last.endswith("ин")
        use_declined_name = is_declinable and (random.random() < 0.40)
        # ~12% of documents get no birth-history/disease-onset phrase at
        # all, deliberately testing that Method 3's cascade correctly
        # produces no inference (rather than a wrong one) when none of
        # its eight cues are present.
        has_sex_cue = random.random() >= 0.12

        text, scale_truth = build_document_text(
            sex, full_name, iin, address, cascade_level,
            use_homoglyph, use_declined_name, has_sex_cue
        )

        filename = f"synthetic_{i:03d}.pdf"
        make_pdf(text, OUTPUT_FOLDER / filename, fontfile)

        manifest_rows.append({
            "filename": filename,
            "full_name": full_name,
            "surname": last,
            "iin": iin,
            "address": address,
            "expected_sex": sex,
            "cascade_level_used": cascade_level if has_sex_cue else "NONE",
            "has_sex_cue": has_sex_cue,
            "used_homoglyph_scales": use_homoglyph,
            "used_declined_name_mention": use_declined_name,
            **scale_truth,
        })

    with open(MANIFEST_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"Generated {N_DOCS} synthetic documents in {OUTPUT_FOLDER}/")
    print(f"Ground-truth manifest saved to {MANIFEST_FILE}")
    print(f"  - Female: {sum(1 for r in manifest_rows if r['expected_sex']=='F')}")
    print(f"  - Male:   {sum(1 for r in manifest_rows if r['expected_sex']=='M')}")
    print(f"  - Homoglyph scale labels: {sum(1 for r in manifest_rows if r['used_homoglyph_scales'])}")
    print(f"  - Declined-name mentions: {sum(1 for r in manifest_rows if r['used_declined_name_mention'])}")
    print(f"  - Documents with NO sex cue (fail-safe test): {sum(1 for r in manifest_rows if not r['has_sex_cue'])}")


if __name__ == "__main__":
    main()
