import re
from datetime import date

import fitz

from modules.nlp_engine import extract_skills


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,5}[\s.-]?\d{4}(?!\w)")
URL_RE = re.compile(r"https?://[^\s<>]+", re.I)

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MONTH_YEAR = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{4}"
NUMERIC_MONTH_YEAR = r"(?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}"
YEAR = r"(?:19|20)\d{2}"
DATE_TOKEN = rf"(?:{MONTH_YEAR}|{NUMERIC_MONTH_YEAR}|{YEAR})"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{DATE_TOKEN})\s*(?:-|–|—|to|through)\s*(?P<end>{DATE_TOKEN}|present|current|now)",
    re.I,
)
EXPLICIT_EXPERIENCE_RE = re.compile(
    r"\b(?P<years>\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?"
    r"(?:(?:professional|work)\s+)?experience\b",
    re.I,
)
INTERNSHIP_RE = re.compile(r"\b(?:intern(?:ship)?|trainee)\b", re.I)
INTERNSHIP_DURATION_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>months?|mos?|years?|yrs?)\b", re.I
)

NAME_STOPWORDS = {
    "page", "resume", "curriculum", "vitae", "contact", "education", "experience",
    "skills", "projects", "certification", "certifications", "summary", "profile",
    "objective", "references", "achievement", "achievements", "personal", "details",
    "engineer", "developer", "analyst", "manager", "designer", "consultant", "student",
    "intern", "internship", "software", "data", "professional", "academic", "phone",
    "email", "linkedin", "github", "portfolio", "address", "btech", "bsc", "bca",
    "mca", "mtech", "degree", "university", "college", "present", "current",
    "name", "not", "detected", "provided", "contact",
}
NAME_LABEL_RE = re.compile(r"^(?:name|candidate)\s*[:\-]\s*", re.I)
NAME_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z'’.-]*$")

DEGREE_PATTERNS = (
    ("M.Tech", re.compile(r"\b(?:M\s*\.?\s*Tech(?:nology)?|Master(?:'s)?\s+of\s+Technology)\b", re.I), "master", "engineering"),
    ("M.E.", re.compile(r"\b(?:M\s*\.?\s*E\.?|Master(?:'s)?\s+of\s+Engineering)\b", re.I), "master", "engineering"),
    ("MCA", re.compile(r"\b(?:M\s*\.?\s*C\.?\s*A\.?|Master(?:'s)?\s+of\s+Computer\s+Applications?)\b", re.I), "master", "computing"),
    ("M.Sc.", re.compile(r"\b(?:M\s*\.?\s*Sc\.?|Master(?:'s)?\s+of\s+Science)\b", re.I), "master", "science"),
    ("MBA", re.compile(r"\b(?:M\s*\.?\s*B\.?\s*A\.?|Master(?:'s)?\s+of\s+Business\s+Administration)\b", re.I), "master", "business"),
    ("B.Tech", re.compile(r"\b(?:B\s*\.?\s*Tech(?:nology)?|Bachelor(?:'s)?\s+of\s+Technology)\b", re.I), "bachelor", "engineering"),
    ("B.E.", re.compile(r"\b(?:B\s*\.?\s*E\.?|Bachelor(?:'s)?\s+of\s+Engineering)\b", re.I), "bachelor", "engineering"),
    ("BCA", re.compile(r"\b(?:B\s*\.?\s*C\.?\s*A\.?|Bachelor(?:'s)?\s+of\s+Computer\s+Applications?)\b", re.I), "bachelor", "computing"),
    ("B.Sc.", re.compile(r"\b(?:B\s*\.?\s*Sc\.?|Bachelor(?:'s)?\s+of\s+Science)\b", re.I), "bachelor", "science"),
    ("Ph.D.", re.compile(r"\b(?:Ph\s*\.?\s*D\.?|Doctor(?:ate)?\s+of\s+Philosophy)\b", re.I), "doctorate", None),
    ("Diploma", re.compile(r"\bDiploma\b", re.I), "diploma", None),
    ("Master's degree", re.compile(r"\bMaster(?:'s)?\s+degree\b", re.I), "master", None),
    ("Bachelor's degree", re.compile(r"\bBachelor(?:'s)?\s+degree\b", re.I), "bachelor", None),
    ("Master's degree", re.compile(r"\bMaster(?:'s)?(?=\s+(?:in|of)\b)", re.I), "master", None),
    ("Bachelor's degree", re.compile(r"\bBachelor(?:'s)?(?=\s+(?:in|of)\b)", re.I), "bachelor", None),
    ("Master's degree", re.compile(r"\bMaster(?:'s)?\b", re.I), "master", None),
    ("Bachelor's degree", re.compile(r"\bBachelor(?:'s)?\b", re.I), "bachelor", None),
)

EDUCATION_HEADINGS = {
    "education", "educational background", "academic background", "education qualification",
    "educational qualifications", "academic qualifications", "qualifications",
}
EXPERIENCE_HEADINGS = {
    "experience", "work experience", "professional experience", "employment history",
    "work history", "employment experience", "career history",
}
PROJECT_HEADINGS = {"projects", "project experience", "academic projects", "personal projects"}
CERTIFICATION_HEADINGS = {"certifications", "certificates", "licenses and certifications"}
SKILL_HEADINGS = {"skills", "technical skills", "key skills", "core competencies"}
SECTION_STOP_HEADINGS = (
    EXPERIENCE_HEADINGS | EDUCATION_HEADINGS | PROJECT_HEADINGS | CERTIFICATION_HEADINGS
    | SKILL_HEADINGS | {"achievements", "summary", "professional summary", "objective", "references"}
)


def extract_pdf_document(path):
    """Return page-sorted text and first-page line layout for reliable header parsing."""
    try:
        with fitz.open(path) as document:
            if document.is_encrypted:
                raise ValueError("Password-protected PDFs are not supported.")
            pages_text = []
            layout_lines = []
            for page_number, page in enumerate(document):
                pages_text.append(page.get_text("text", sort=True))
                if page_number != 0:
                    continue
                page_height = page.rect.height
                for block in page.get_text("dict")["blocks"]:
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        line_text = " ".join(span.get("text", "") for span in spans).strip()
                        if line_text:
                            layout_lines.append({
                                "text": line_text,
                                "y": float(line["bbox"][1]),
                                "page_height": float(page_height),
                                "font_size": max((float(span.get("size", 0)) for span in spans), default=0.0),
                            })
            text = "\n".join(pages_text)
            image_only = not text.strip() and any(page.get_images() for page in document)
            if image_only:
                raise ValueError("This PDF appears to be scanned/image-only; OCR is not supported.")
            if not text.strip():
                raise ValueError("The PDF contains no extractable text.")
            return text, layout_lines
    except fitz.FileDataError as exc:
        raise ValueError("The PDF is corrupted or invalid.") from exc


def extract_pdf_text(path):
    return extract_pdf_document(path)[0]


def _normalized_heading(line):
    return re.sub(r"[^a-z ]", "", line.lower()).strip()


def _section(text, headings, stop_headings):
    collected = []
    active = False
    for line in text.splitlines():
        clean = line.strip()
        normalized = _normalized_heading(clean)
        if normalized in headings:
            active = True
            continue
        if active and normalized in stop_headings:
            break
        if active and clean:
            collected.append(clean)
    return "\n".join(collected)


def _valid_name(value):
    value = NAME_LABEL_RE.sub("", value.strip())
    if not value or EMAIL_RE.search(value) or URL_RE.search(value) or PHONE_RE.search(value):
        return None
    if re.search(r"\d|[@:/\\|]", value):
        return None
    tokens = value.split()
    if not 2 <= len(tokens) <= 4 or not all(NAME_TOKEN_RE.fullmatch(token) for token in tokens):
        return None
    normalized = [re.sub(r"[^a-z]", "", token.lower()) for token in tokens]
    if any(token in NAME_STOPWORDS for token in normalized):
        return None
    if len(normalized) < 2 or not any(len(token) >= 2 for token in normalized):
        return None
    return " ".join(tokens)


def is_valid_candidate_name(value):
    return _valid_name(value) is not None


def _extract_name(lines, document_lines=None):
    if document_lines:
        candidates = []
        for item in document_lines:
            page_height = item.get("page_height", 0)
            if not page_height or item.get("y", page_height) > page_height * 0.4:
                continue
            name = _valid_name(item.get("text", ""))
            if name:
                candidates.append((item.get("font_size", 0), item.get("y", 0), name))
        if candidates:
            candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
            return candidates[0][2]

    for line in lines[:20]:
        name = _valid_name(line)
        if name:
            return name
    return "Name not detected"


def _degree_qualifications(text):
    if not text:
        return []
    lower = text.lower()
    if re.search(r"\b(computer science|information technology|information systems|software engineering)\b", lower):
        computing = True
    else:
        computing = False
    qualifications = []
    for canonical, pattern, level, family in DEGREE_PATTERNS:
        matches = list(pattern.finditer(text))
        for match in matches:
            resolved_family = "computing" if family == "science" and computing else family
            qualifications.append({
                "degree": canonical,
                "level": level,
                "family": resolved_family,
                "start": match.start(),
                "end": match.end(),
            })
    qualifications.sort(key=lambda item: item["start"])
    result = []
    seen = set()
    for item in qualifications:
        key = (item["degree"], item["family"])
        if key not in seen:
            seen.add(key)
            result.append({key: value for key, value in item.items() if key not in {"start", "end"}})
    return result


def extract_education(text):
    details = _section(text or "", EDUCATION_HEADINGS, SECTION_STOP_HEADINGS - EDUCATION_HEADINGS)
    qualifications = _degree_qualifications(details)
    graduation_years = re.findall(r"\b(?:19|20)\d{2}\b", details)
    return {
        "degrees": list(dict.fromkeys(item["degree"] for item in qualifications)),
        "qualifications": qualifications,
        "graduation_years": list(dict.fromkeys(graduation_years)),
        "details": details,
    }


def _parse_month_year(value, is_end=False, today=None):
    value = value.strip().rstrip(".")
    current = today or date.today()
    if value.lower() in {"present", "current", "now"}:
        return current.year * 12 + current.month - 1
    month_match = re.fullmatch(r"([A-Za-z]+)\.?\s+((?:19|20)\d{2})", value)
    if month_match:
        month = MONTH_NAMES.get(month_match.group(1).lower())
        if month:
            return int(month_match.group(2)) * 12 + month - 1
    numeric_match = re.fullmatch(r"(0?[1-9]|1[0-2])[/.-]((?:19|20)\d{2})", value)
    if numeric_match:
        return int(numeric_match.group(2)) * 12 + int(numeric_match.group(1)) - 1
    year_match = re.fullmatch(r"((?:19|20)\d{2})", value)
    if year_match:
        # Year-only ranges use January boundaries to avoid inflating duration.
        return int(year_match.group(1)) * 12
    return None


def _merge_month_ranges(ranges):
    if not ranges:
        return 0
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(max(0, end - start) for start, end in merged)


def _extract_experience(text, today=None):
    details = _section(text or "", EXPERIENCE_HEADINGS, SECTION_STOP_HEADINGS - EXPERIENCE_HEADINGS)
    if not details:
        return {
            "details": "",
            "experience_years": None,
            "internship_years": None,
            "internship_details": "",
        }

    lines = details.splitlines()
    employment_ranges = []
    internship_ranges = []
    for index, line in enumerate(lines):
        for match in DATE_RANGE_RE.finditer(line):
            start = _parse_month_year(match.group("start"), today=today)
            end = _parse_month_year(match.group("end"), is_end=True, today=today)
            if start is None or end is None or end <= start:
                continue
            context = " ".join(lines[max(0, index - 2):index + 1])
            target = internship_ranges if INTERNSHIP_RE.search(context) else employment_ranges
            target.append((start, end))

    explicit_years = []
    internship_explicit_months = []
    internship_lines = []
    for index, line in enumerate(lines):
        context = " ".join(lines[max(0, index - 2):index + 1])
        if INTERNSHIP_RE.search(context):
            if line.strip() not in internship_lines:
                internship_lines.append(line.strip())
            duration_match = INTERNSHIP_DURATION_RE.search(line)
            if duration_match:
                value = float(duration_match.group("value"))
                unit = duration_match.group("unit").lower()
                internship_explicit_months.append(value * (12 if unit.startswith(("y", "yr")) else 1))
        elif match := EXPLICIT_EXPERIENCE_RE.search(line):
            explicit_years.append(float(match.group("years")))

    full_time_months = max(_merge_month_ranges(employment_ranges), max(explicit_years, default=0) * 12)
    internship_months = max(_merge_month_ranges(internship_ranges), max(internship_explicit_months, default=0))
    return {
        "details": details,
        "experience_years": round(full_time_months / 12, 2) if full_time_months else None,
        "internship_years": round(internship_months / 12, 2) if internship_months else None,
        "internship_details": "\n".join(internship_lines),
    }


def parse_resume(text, document_lines=None):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    email_match = EMAIL_RE.search(text or "")
    phone_match = PHONE_RE.search(text or "")
    urls = URL_RE.findall(text or "")
    education = extract_education(text or "")
    experience = _extract_experience(text or "")
    projects_text = _section(text or "", PROJECT_HEADINGS, SECTION_STOP_HEADINGS - PROJECT_HEADINGS)
    certifications_text = _section(text or "", CERTIFICATION_HEADINGS, SECTION_STOP_HEADINGS - CERTIFICATION_HEADINGS)
    skills = extract_skills(text or "")
    return {
        "candidate_name": _extract_name(lines, document_lines),
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0).strip() if phone_match else None,
        "linkedin": next((url.rstrip(".,)") for url in urls if "linkedin.com" in url.lower()), None),
        "github": next((url.rstrip(".,)") for url in urls if "github.com" in url.lower()), None),
        "portfolio": next((url.rstrip(".,)") for url in urls if "linkedin.com" not in url.lower()
                          and "github.com" not in url.lower()), None),
        "education": education,
        "experience_years": experience["experience_years"],
        "internship_years": experience["internship_years"],
        "experience_details": experience["details"],
        "internship_details": experience["internship_details"],
        "skills": skills,
        "projects": projects_text,
        "certifications": certifications_text,
        "summary": (lines[0] if lines else ""),
    }


def education_match_score(education, requirement):
    """Return a verified match score, or None when either side is not verifiable."""
    requirement = (requirement or "").strip()
    if not requirement:
        return None
    required_quals = _degree_qualifications(requirement)
    candidate_quals = education.get("qualifications") or _degree_qualifications(education.get("details", ""))
    if not required_quals or not candidate_quals:
        return None

    required_text = requirement.lower()
    required_family = None
    if re.search(r"\b(computer science|information technology|information systems|software engineering)\b", required_text):
        required_family = "computing"
    elif re.search(r"\b(engineering|technology)\b", required_text):
        required_family = "engineering"
    elif re.search(r"\b(business|management)\b", required_text):
        required_family = "business"

    level_order = {"diploma": 0, "bachelor": 1, "master": 2, "doctorate": 3}
    best = None
    for required in required_quals:
        family = required_family or required["family"]
        for candidate in candidate_quals:
            if family is None:
                matched = level_order.get(candidate["level"], -1) >= level_order.get(required["level"], 99)
            elif candidate["family"] is None:
                matched = None
            else:
                matched = (
                    candidate["family"] == family
                    and level_order.get(candidate["level"], -1) >= level_order.get(required["level"], 99)
                )
            if matched is True:
                return 100.0
            if matched is False:
                best = 0.0
    return best
