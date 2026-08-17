
import fitz
import re
import csv
from pathlib import Path
from datetime import datetime

# ── CONFIGURE ─────────────────────────────────────────────────────────────────
INPUT_FOLDER = r""
OUTPUT_FILE  = r""
# ─────────────────────────────────────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def extract_text(doc):
    return "\n".join(page.get_text() for page in doc)

def safe_date(s):
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            pass
    return None

def safe_float(s):
    """Parse a float that may contain underscores, commas, trailing punctuation, or spaces.
    Handles the common case where greedy regex captures a trailing comma, e.g. '2,15,' → 2.15."""
    try:
        cleaned = str(s).replace(",", ".").replace("_", "").strip().rstrip(".,")
        return float(cleaned)
    except Exception:
        return None

def safe_int(s):
    try:
        return int(str(s).strip())
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCTIONAL SCALES  (Barthel, GMFM, FIM, GMFCS, MACS)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_scales(text):
    scales = {k: "NA" for k in [
        "barthel_admission", "barthel_discharge",
        "gmfm_admission",    "gmfm_discharge",
        "fim_admission",     "fim_discharge",
        "gmfcs", "macs",
    ]}


    tbl_m = re.search(
        r"(?:Наименование шкал|[Шш]калы)\s*[^\n]*\n(.+?)"
        r"(?:Определение:|Оңалту мақсаттар|$)",
        text, re.DOTALL | re.IGNORECASE,
    )
    tbl = tbl_m.group(1) if tbl_m else ""

    def two_vals(pattern, lo, hi, source):
        """Return (v1, v2) if both are within [lo, hi], else ("NA", "NA").
        re.DOTALL is used so [^0-9] in the pattern can bridge across newlines
        (scale values often appear on separate lines from scale names)."""
        m = re.search(pattern, source, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                v1, v2 = int(m.group(1)), int(m.group(2))
                if lo <= v1 <= hi and lo <= v2 <= hi:
                    return str(v1), str(v2)
            except Exception:
                pass
        return "NA", "NA"

    def one_val(pattern, lo, hi, source):
        m = re.search(pattern, source, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                v = int(m.group(1))
                if lo <= v <= hi:
                    return str(v)
            except Exception:
                pass
        return "NA"

   
    if tbl:
        scales["barthel_admission"], scales["barthel_discharge"] = two_vals(
            r"[Бб]артел[а-яё]*[^0-9]{0,50}?(\d{1,3})\s+(\d{1,3})", 0, 100, tbl
        )

    # Pass 2: narrative "Бартела - 80/95" slash format
    if scales["barthel_admission"] == "NA":
        m = re.search(r"[Бб]артел[а-яё]*[-–:/\s]+(\d{1,3})\s*/\s*(\d{1,3})", text)
        if m:
            v1, v2 = int(m.group(1)), int(m.group(2))
            if 0 <= v1 <= 100 and 0 <= v2 <= 100:
                scales["barthel_admission"] = str(v1)
                scales["barthel_discharge"] = str(v2)

    
    if scales["barthel_admission"] == "NA":
        scales["barthel_admission"] = one_val(
            r"[Бб]артел[а-яё]*\s*[-–:]\s*(\d{1,3})\s*(?:балл|бал)", 0, 100, text
        )


    if scales["barthel_admission"] != "NA" and scales["barthel_discharge"] == "NA":
        diary_m = re.search(
            r"(?:Дневниковая запись|Шығатын күнінің|выписки).+",
            text, re.DOTALL | re.IGNORECASE,
        )
        if diary_m:
            scales["barthel_discharge"] = one_val(
                r"[Бб]артел[а-яё]*[^0-9]{0,60}?(\d{1,3})", 0, 100, diary_m.group()
            )

    
    if scales["barthel_admission"] == "NA":
        scales["barthel_admission"] = one_val(
            r"[Бб]артел[а-яё]*\s*[-–—:=]\s*(\d{1,3})", 0, 100, text
        )


    if tbl:
        scales["gmfm_admission"], scales["gmfm_discharge"] = two_vals(
            r"G[МM]F[МM][^0-9]{0,100}(\d{1,3})[^0-9]{0,100}(\d{1,3})", 0, 100, tbl
        )
    if scales["gmfm_admission"] == "NA":
        m = re.search(r"G[МM]F[МM][^0-9]{0,30}(\d{1,3})\s*%?", text, re.IGNORECASE)
        if m:
            v = safe_int(m.group(1))
            if v is not None and 0 <= v <= 100:
                scales["gmfm_admission"] = str(v)


    if tbl:
        scales["fim_admission"], scales["fim_discharge"] = two_vals(
            r"F[ІI][МM][^0-9]{0,100}(\d{1,3})[^0-9/]{1,100}(\d{1,3})", 18, 126, tbl
        )
    # Fallback: labelled sections in ergo note ("FIM при поступлении / при выписке")
    if scales["fim_admission"] == "NA":
        m = re.search(r"FIM при поступлени[еи][^\d]{0,60}(\d{1,3})", text, re.IGNORECASE)
        if m:
            v = safe_int(m.group(1))
            if v and 18 <= v <= 126:
                scales["fim_admission"] = str(v)
    if scales["fim_discharge"] == "NA":
        m = re.search(r"FIM при выписке[^\d]{0,60}(\d{1,3})", text, re.IGNORECASE)
        if m:
            v = safe_int(m.group(1))
            if v and 18 <= v <= 126:
                scales["fim_discharge"] = str(v)


    scales["gmfcs"] = one_val(r"G[МM]FCS[^0-9]{0,30}([1-5])", 1, 5, text)


    scales["macs"] = one_val(
        r"[МM][АA][СC][СCS](?![а-яёА-ЯЁa-zA-Z])[^0-9]{0,100}([1-5])", 1, 5, text
    )

    return scales




def extract_shm(text):
    """
    Extract ШРМ scores from the standardised formula block present in every PDF:

        При поступлении: ШРМ: R1 = (Х1 + У1):2 = (__2__+__2.1___):2=_2.05_____
        При выписке:     ШРМ: R2 = (X2 + Y2):2 = (_1.8__+__2___):2=____1.9___
        Эффективность реабилитации: R1: R2 = ____1.1___

    Potential categories  →  0–<2 High, 2–<3 Medium, 3–<4 Low, 4 None
    Effectiveness         →  <1 Poor, 1–1.5 Satisfactory, 1.5–2 Good, >2 Excellent
    """
    result = {
        "shm_admission":           "NA",
        "shm_discharge":           "NA",
        "shm_effectiveness":       "NA",
        "shm_potential_admission": "NA",
        "shm_potential_discharge": "NA",
    }

    def _shm_potential(v):
        if v < 2.0: return "High"
        if v < 3.0: return "Medium"
        if v < 4.0: return "Low"
        return "None"


    NUM = r"(\d+[,\.]\d+)"  
    m1 = re.search(
        r"R1\s*=\s*\([^)]*\)\s*:?\s*2\s*=?\s*\([^)]*\)\s*:?\s*2\s*=?\s*[_\s]*" + NUM,
        text, re.IGNORECASE,
    )
    if m1:
        v = safe_float(m1.group(1))
        if v is not None and 0 <= v <= 4:
            result["shm_admission"]           = str(round(v, 2))
            result["shm_potential_admission"] = _shm_potential(v)

    # R2
    m2 = re.search(
        r"R2\s*=\s*\([^)]*\)\s*:?\s*2\s*=?\s*\([^)]*\)\s*:?\s*2\s*=?\s*[_\s]*" + NUM,
        text, re.IGNORECASE,
    )
    if m2:
        v = safe_float(m2.group(1))
        if v is not None and 0 <= v <= 4:
            result["shm_discharge"]           = str(round(v, 2))
            result["shm_potential_discharge"] = _shm_potential(v)

    # Effectiveness ratio
    m3 = re.search(
        r"[Ээ]ффективность[^\n=]{0,60}=\s*[_\s]*" + NUM, text
    )
    if m3:
        v = safe_float(m3.group(1))
        if v is not None and 0 <= v <= 5:
            result["shm_effectiveness"] = str(round(v, 2))

    return result




def extract_demographics(text):
    """
    Sex is inferred from Russian grammatical gender in the birth-history narrative:
      'к груди приложен'  →  male
      'к груди приложена' →  female
    Fallback: verb 'закричал/закричала', then keyword мальчик/девочка.
    """
    result = {
        "sex":                  "NA",
        "delivery_mode":        "NA",
        "birth_weight_g":       "NA",
        "gestational_age_weeks":"NA",
    }


    if re.search(r"к груди приложена", text, re.IGNORECASE):
        result["sex"] = "F"
    elif re.search(r"к груди приложен\b", text, re.IGNORECASE):
        result["sex"] = "M"
    elif re.search(r"[Зз]акричала\s+сразу", text):
        result["sex"] = "F"
    elif re.search(r"[Зз]акричал\s+сразу", text):
        result["sex"] = "M"
    elif re.search(r"\bдевочка\b", text, re.IGNORECASE):
        result["sex"] = "F"
    elif re.search(r"\bмальчик\b", text, re.IGNORECASE):
        result["sex"] = "M"
    elif re.search(r"[Бб]ольна\s+с\b", text):
        result["sex"] = "F"
    elif re.search(r"[Бб]олен\s+с\b", text):
        result["sex"] = "M"

    # Delivery mode — handle both word orders and common Russian phrasing variants
    if re.search(r"кесарев", text, re.IGNORECASE):
        result["delivery_mode"] = "C-section"
    elif re.search(
        r"самостоятельные роды|[Рр]оды самостоятельные|естественных родах|"
        r"вагинальн|срочные роды|физиологическ",
        text, re.IGNORECASE,
    ):
        result["delivery_mode"] = "Vaginal"


    m = re.search(
        r"[Вв]ес\s+при\s+рождении\s*[-—–]?\s*([\d,\.]+)\s*(кг|г(?:рамм)?\.?)?",
        text, re.IGNORECASE,
    )
    if m:
        w = safe_float(m.group(1))
        unit = (m.group(2) or "г").lower()
        if w:
            result["birth_weight_g"] = str(int(w * 1000 if "кг" in unit else w))


    m = re.search(r"(?:в|на|при)\s+сроке\s*(\d{2})\s*недел", text, re.IGNORECASE)
    if m:
        ga = safe_int(m.group(1))
        if ga and 22 <= ga <= 44:
            result["gestational_age_weeks"] = str(ga)

    return result




def extract_anamnesis(text):
    result = {
        "is_repeat_admission":      "NA",
        "vaccination_status":       "NA",
        "family_history_neurodevel":"NA",
    }

    
    result["is_repeat_admission"] = (
        "Yes" if re.search(
            r"[Пп]оследний курс|[Пп]редыдущ|[Рр]анее проход|[Нн]аходился ранее|предшествующ",
            text, re.IGNORECASE,
        ) else "No"
    )

    
    vacc_m = re.search(r"[Пп]рофилактические прививки([^\n]+)", text)
    if vacc_m:
        vt = vacc_m.group(1).strip().lower()
        if re.search(r"отказ|не провод|не привит|не вакцин", vt):
            result["vaccination_status"] = "Refused"
        elif re.search(
            r"по возрасту|по план|по календар|сделан|привит|бцж|вгв|в роддоме|"
            r"индивидуальн|не отягощен|нет данных", vt
        ):
            result["vaccination_status"] = "Current"
        else:
            result["vaccination_status"] = vacc_m.group(1).strip().lstrip(":").strip()[:80]
    elif re.search(r"отказ от прививок", text, re.IGNORECASE):
        result["vaccination_status"] = "Refused"

    
    fam_m = re.search(r"[Нн]аследственность\s*[:\s—–]+([^\n]+)", text)
    if fam_m:
        ft = fam_m.group(1).strip()
        if re.search(r"не отягощен|отрицает|без особенн|здоровы|спокойн", ft, re.IGNORECASE):
            result["family_history_neurodevel"] = "None"
        else:
            icd_codes = re.findall(r"[A-Z]\d{2}(?:\.\d+)?", ft)
            result["family_history_neurodevel"] = (
                "; ".join(icd_codes) if icd_codes else ft[:100]
            )

    return result




def extract_session_counts(text):
    """
    Count therapy sessions by counting procedure entries that carry a date-time stamp.
    Each session appears as:  ProcedureName (DD.MM.YYYY HH:MM)

    Kinesiotherapy is anchored to the start of a line (re.MULTILINE) to prevent
    false matches inside "Гидрокинезотерапия" or "Роботизированная локомоторная кинезотерапия".

    Electrophoresis handles two layout variants across PDFs:
      Format A: "Электрофорез + Drug ... (02.09.2025 11:40)"  (timestamp on same line)
      Format B: "Электрофорез + Drug ... (1мл, Наружно)\n(26.08.2025 12:15)" (next line)
    """
    ts = r"\s*\(\d{2}\.\d{2}\.\d{4}"

    # Standard patterns
    std_patterns = {
        "sessions_speech":     r"[Зз]анятие с логопедом" + ts,
        "sessions_music":      r"[Зз]анятие по музыкотерапии" + ts,
        "sessions_play":       r"[Зз]анятие по игровой терапии" + ts,
        "sessions_defect":     r"[Зз]анятие с дефектологом" + ts,
        "sessions_ergo":       r"[Зз]анятие по эрготерапии" + ts,
        "sessions_hydro":      r"[Гг]идрокинезотерапия индивидуальная" + ts,
        "sessions_psych":      r"[Пп]сихокорреционная работа" + ts,
        "sessions_physio_smt": r"[Аа]мплипульстерапия\s*\([СсCc][МмMm][ТтTt]\)" + ts,
        "sessions_ozokerite":  r"[Оо]зокеритолечение" + ts,
        "sessions_oxygen":     r"[Кк]ислородный коктейль" + ts,
    }

    counts = {}
    for col, pat in std_patterns.items():
        n = len(re.findall(pat, text))
        counts[col] = n if n > 0 else "NA"

    # Electrophoresis — two-format counter (same-line or next-line timestamp)
    ea = len(re.findall(r"^[Ээ]лектрофорез[^\n]*\(\d{2}\.\d{2}\.\d{4}", text, re.MULTILINE))
    eb = len(re.findall(r"^[Ээ]лектрофорез[^\n]+\n\s*\(\d{2}\.\d{2}\.\d{4}", text, re.MULTILINE))
    counts["sessions_physio_electro"] = (ea + eb) if (ea + eb) > 0 else "NA"


    kinesio_dates = set(re.findall(
        r"^[Кк]инезотерапия[^\n]*\((\d{2}\.\d{2}\.\d{4})", text, re.MULTILINE
    ))
    counts["sessions_kinesio"] = len(kinesio_dates) if kinesio_dates else "NA"

    return counts


def normalize_outcome(raw):
    if not raw or raw in ("NA", "ERROR"):
        return "NA"
    r = raw.lower().strip()
    if re.search(r"без перемен|без изменен|не изменил", r):
        return "No change"
    if re.search(r"ухудш", r):
        return "Deterioration"
    if re.search(r"выздоров", r):
        return "Recovery"
    if re.search(r"улучшен", r):
        return "Improvement"
    return "Unknown"




def extract_record(text, filename):
    row = {"record_file": filename}

    
    m = re.search(r"ВЫПИСНОЙ ЭПИКРИЗ\s+(\d+)", text)
    row["record_number"] = m.group(1) if m else "NA"

    
    dob_m = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*г\.р\.", text)
    adm_m = re.search(r"поступления\)\s+(\d{2}\.\d{2}\.\d{4})", text)
    dis_m = re.search(r"выбытия\)\s+(\d{2}\.\d{2}\.\d{4})", text)

    dob = safe_date(dob_m.group(1)) if dob_m else None
    adm = safe_date(adm_m.group(1)) if adm_m else None
    dis = safe_date(dis_m.group(1)) if dis_m else None

    # Dates stored in ISO format — safe for all spreadsheet applications
    row["admission_date"] = adm.strftime("%Y-%m-%d") if adm else "NA"
    row["discharge_date"] = dis.strftime("%Y-%m-%d") if dis else "NA"
    row["age_at_admission_years"] = (
        round((adm - dob).days / 365.25, 1) if dob and adm else "NA"
    )
    row["los_days"] = (dis - adm).days if adm and dis else "NA"

   
    row.update(extract_demographics(text))


    m = re.search(
        r"заключительный\s+диагноз\s*\)?\s*:?\s*[\s\S]{0,80}?\(([A-Z]\d{2}(?:\.\d+)?)\s*\)",
        text, re.IGNORECASE,
    )
    row["primary_icd10"] = m.group(1) if m else "NA"

    m = re.search(
        r"уточняющее\s*\)?\s*:?\s*\(([A-Z]\d{2}(?:\.\d+)?)\s*\)\s*([^\n]+)",
        text, re.IGNORECASE,
    )
    if m:
        row["diagnosis_icd10"] = m.group(1)
        row["diagnosis_text"]  = m.group(2).strip()[:200]
    else:
        row["diagnosis_icd10"] = "NA"
        row["diagnosis_text"]  = "NA"


    cm_codes = []
    primary_codes = {row.get("primary_icd10", ""), row.get("diagnosis_icd10", "")}
    for hit in re.finditer(
        r"(?:сопутствующ[а-яё]+\s+заболевани[а-яё]+|[Ққ]осалқы аурулары)",
        text, re.IGNORECASE,
    ):
        # Capture up to 250 chars after the section header (spans multiple lines)
        snippet = text[hit.start(): hit.start() + 250]
        code_m = re.search(r"\(([A-Z]\d{2}(?:\.\d+)?)\s*\)", snippet)
        if code_m:
            code = code_m.group(1)
            if code not in primary_codes and code not in cm_codes:
                cm_codes.append(code)
    row["comorbidity_icd10"] = "; ".join(cm_codes) if cm_codes else "NA"

   
    row.update(extract_scales(text))

   
    row.update(extract_shm(text))

    m = re.search(
        r"[Уу]ровень психологического развития\s*\)?\s*[:\-–]?\s*([^\n\r]+)",
        text, re.IGNORECASE,
    )
    row["psych_dev_level"] = m.group(1).strip()[:300] if m else "NA"


    _roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
    m = re.search(r"ОНР[-–\s]*(\d)(?:[-–](\d))?\s*(?:уровен|ур[\.!]?)", text, re.IGNORECASE)
    if m:
        row["onr_level_min"] = safe_int(m.group(1))
        row["onr_level_max"] = safe_int(m.group(2)) if m.group(2) else safe_int(m.group(1))
    else:
        
        m = re.search(
            r"ОНР[-–\s]*([ІіIi]{1,3}(?:[Vv])?|[Vv])(?:[-–]([ІіIi]{1,3}(?:[Vv])?|[Vv]))?\s*(?:уровен|ур[\.!]?)",
            text, re.IGNORECASE,
        )
        if m:
            def _r2i(s):
                return _roman.get(s.lower().replace("і", "i").replace("І", "i"), None)
            row["onr_level_min"] = _r2i(m.group(1)) or "NA"
            row["onr_level_max"] = _r2i(m.group(2) or m.group(1)) or "NA"
        else:
            row["onr_level_min"] = "NA"
            row["onr_level_max"] = "NA"

    
    row.update(extract_anamnesis(text))

    
    therapy_map = {
        "Ergotherapy":            r"эрготерапи",
        "Kinesiotherapy":         r"кинезотерапи",
        "Music therapy":          r"музыкотерапи",
        "Play therapy":           r"игровой терапи",
        "Defectology":            r"дефектолог",
        "Speech therapy":         r"логопед",
        "Psychocorrection":       r"психокорр",
        "Hydrotherapy":           r"гидрокинезотерапи",
        "BOS logotherapy":        r"БОС лого",
        "Montessori":             r"монтессор",
        "Robotic kinesiotherapy": r"[Рр]оботизированная",
        "Salt chamber":           r"[Сс]оляная камера",
        "Electrostimulation":     r"[Ээ]лектростимуляц",
        "Agrotherapy":            r"[Аа]гротерапи",
        "Physiotherapy":          r"[Фф]изиотерапевт",
        "Massage":                r"[Мм]ассаж",
        "Ozokerite":              r"[Оо]зокерит",
        "Acupuncture":            r"[Аа]купунктур",
        "BOS psychoemotional":    r"психоэмоц",
        "Magnetotherapy":         r"[Мм]агнитотерапи",
    }
    present = [n for n, p in therapy_map.items() if re.search(p, text, re.IGNORECASE)]
    row["therapies_received"] = "; ".join(present) if present else "NA"
    row["therapy_count"]      = len(present)

    
    row.update(extract_session_counts(text))

    
    m = re.search(r"Исход лечения[^\n]*\n[^\n]*[:：]\s*([^\n]+)", text)
    if not m:
        m = re.search(r"Ребенок выписывается с[:：]?\s*([^\n\.]+)", text, re.IGNORECASE)
    raw_outcome        = m.group(1).strip()[:60] if m else "NA"
    row["outcome"]     = raw_outcome
    row["outcome_std"] = normalize_outcome(raw_outcome)

    return row



COLUMNS = [
    # Identifiers
    "record_file", "record_number",
    # Dates & timing
    "admission_date", "discharge_date", "age_at_admission_years", "los_days",
    # Demographics
    "sex",
    # Diagnoses
    "primary_icd10", "diagnosis_icd10", "diagnosis_text", "comorbidity_icd10",
    # Functional scales
    "gmfcs", "macs",
    "barthel_admission", "barthel_discharge",
    "gmfm_admission",    "gmfm_discharge",
    "fim_admission",     "fim_discharge",
    # ШРМ rehabilitation routing scale
    "shm_admission", "shm_discharge", "shm_effectiveness",
    "shm_potential_admission", "shm_potential_discharge",
    # Clinical narrative
    "psych_dev_level", "onr_level_min", "onr_level_max",
    # Perinatal history
    "delivery_mode", "birth_weight_g", "gestational_age_weeks",
    # Anamnesis
    "is_repeat_admission", "vaccination_status", "family_history_neurodevel",
    # Therapies — binary presence
    "therapies_received", "therapy_count",
    # Therapies — session counts
    "sessions_speech", "sessions_music", "sessions_play", "sessions_defect",
    "sessions_ergo", "sessions_kinesio", "sessions_hydro", "sessions_psych",
    "sessions_physio_smt", "sessions_physio_electro", "sessions_ozokerite",
    "sessions_oxygen",
    # Outcome
    "outcome", "outcome_std",
]




def main():
    input_folder = Path(INPUT_FOLDER)
    pdf_files    = sorted(input_folder.glob("*.pdf"))
    total        = len(pdf_files)

    if total == 0:
        print(f"No PDFs found in: {INPUT_FOLDER}")
        return

    print(f"Found {total} PDFs — starting extraction...\n")
    rows, failed = [], 0

    for i, pdf_path in enumerate(pdf_files, 1):
        try:
            doc  = fitz.open(str(pdf_path))
            text = extract_text(doc)
            doc.close()
            row  = extract_record(text, pdf_path.name)
            rows.append(row)
            print(
                f"[{i:>4}/{total}] {pdf_path.name:<40} "
                f"sex={row['sex']}  "
                f"age={str(row['age_at_admission_years']):>5}  "
                f"diag={row['diagnosis_icd10']:<8}  "
                f"barthel={row['barthel_admission']}/{row['barthel_discharge']}  "
                f"shm={row['shm_admission']}/{row['shm_discharge']}→{row['shm_effectiveness']}  "
                f"out={row['outcome_std']}"
            )
        except Exception as e:
            failed += 1
            rows.append({
                "record_file": pdf_path.name,
                **{c: "ERROR" for c in COLUMNS if c != "record_file"},
            })
            print(f"[{i:>4}/{total}] FAILED: {pdf_path.name} — {e}")

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{'='*70}")
    print(f"Done.  {total - failed} records written,  {failed} failed.")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Columns: {len(COLUMNS)}")


if __name__ == "__main__":
    main()
