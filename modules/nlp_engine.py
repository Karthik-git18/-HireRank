import re
from collections import Counter

from nltk.tokenize import RegexpTokenizer


SKILL_CATEGORIES = {
    "Programming": ["Python", "Java", "C", "C++", "C#", "JavaScript", "TypeScript", "SQL", "R", "Go", "Ruby", "PHP"],
    "Web": ["HTML", "CSS", "Flask", "Django", "FastAPI", "React", "Bootstrap", "REST API"],
    "AI/ML": ["Machine Learning", "Deep Learning", "Natural Language Processing", "Computer Vision",
              "TensorFlow", "PyTorch", "Scikit-learn", "Pandas", "NumPy"],
    "Databases": ["MySQL", "SQLite", "PostgreSQL", "MongoDB", "Redis", "Oracle"],
    "Tools": ["Git", "GitHub", "Docker", "Linux", "VS Code", "Kubernetes", "Jenkins"],
    "Cloud": ["AWS", "Azure", "Google Cloud", "GCP"],
    "Soft skills": ["Communication", "Leadership", "Teamwork", "Problem Solving", "Time Management"],
}

SYNONYMS = {
    "ml": "Machine Learning",
    "machine-learning": "Machine Learning",
    "nlp": "Natural Language Processing",
    "js": "JavaScript",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "sklearn": "Scikit-learn",
    "scikit learn": "Scikit-learn",
    "gcp": "Google Cloud",
    "rest api": "REST API",
    "restapis": "REST API",
}

SOFT_SKILLS = ["Communication", "Leadership", "Teamwork", "Problem Solving", "Time Management", "Collaboration", "Adaptability", "Analytical Thinking"]
STOPWORDS = set("""
a an the and or but if then of at by for with about against between into through during before after
above below to from up down in out on off over under again further once is am are was were be been
being have has had do does did will would should can could may might must this that these those it
its as not no nor so than too very we our you your they their he she them his her i me my
""".split())
TOKENIZER = RegexpTokenizer(r"[\w+#./-]+")


def preprocess_text(text):
    text = (text or "").lower()
    text = re.sub(r"[^\w+#./-]", " ", text)
    tokens = TOKENIZER.tokenize(text)
    tokens = [token for token in tokens if token not in STOPWORDS and len(token) > 1]
    return " ".join(tokens)


def _phrase_pattern(phrase):
    escaped = re.escape(phrase).replace(r"\ ", r"\s+")
    return re.compile(r"(?<![\w+#])" + escaped + r"(?![\w+#])", re.IGNORECASE)


def extract_skills(text):
    found = {}
    source = text or ""
    for category, skills in SKILL_CATEGORIES.items():
        for skill in skills:
            if _phrase_pattern(skill).search(source):
                found[skill] = category
    lowered = source.lower()
    for alias, canonical in SYNONYMS.items():
        if _phrase_pattern(alias).search(lowered):
            for category, skills in SKILL_CATEGORIES.items():
                if canonical in skills:
                    found[canonical] = category
                    break
    return found


def normalize_skill_list(value):
    if isinstance(value, str):
        values = re.split(r"[,;\n]+", value)
    else:
        values = value or []
    canonical = {skill.lower(): skill for skills in SKILL_CATEGORIES.values() for skill in skills}
    aliases = {key.lower(): val for key, val in SYNONYMS.items()}
    normalized = []
    for item in values:
        raw = str(item).strip()
        if not raw:
            continue
        mapped = aliases.get(raw.lower(), canonical.get(raw.lower(), raw))
        if mapped.lower() not in {skill.lower() for skill in normalized}:
            normalized.append(mapped)
    return normalized


def important_terms(text, limit=20):
    tokens = preprocess_text(text).split()
    return [word for word, _count in Counter(tokens).most_common(limit)]


def _safe_clean_line(value):
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    return cleaned.strip(".,;:- ")


def _extract_role(description):
    text = description or ""
    for pattern in [
        r"(?:looking for|seeking|hiring|role of|position for|joining as)\s+(?:an?\s+)?([A-Z][A-Za-z0-9+/.-]*(?:\s+[A-Z][A-Za-z0-9+/.-]*){0,5})",
        r"(?:we are looking for a|we are hiring a|we are seeking a)\s+([A-Z][A-Za-z0-9+/.-]*(?:\s+[A-Z][A-Za-z0-9+/.-]*){0,5})",
    ]:
        match = re.search(pattern, text)
        if match:
            return _safe_clean_line(match.group(1))
    cap_phrases = re.findall(r"\b[A-Z][A-Za-z0-9+/.-]*(?:\s+[A-Z][A-Za-z0-9+/.-]*)+\b", text)
    if cap_phrases:
        return _safe_clean_line(cap_phrases[0])
    return "Not specified"


def _extract_minimum_experience(description):
    text = description or ""
    patterns = [
        r"(?:at\s+least|minimum|minimum of|min\s*\+?|>=)\s*(\d+(?:\.\d+)?)\s*(?:to\s*(\d+(?:\.\d+)?))?\s*(?:years?|yrs?|y)\s*(?:of\s*)?(?:experience|exp)",
        r"(\d+(?:\.\d+)?)\s*(?:\+|to\s*\d+(?:\.\d+)?)?\s*(?:years?|yrs?|y)\s*(?:of\s*)?(?:experience|exp)",
        r"(\d+(?:\.\d+)?)\s*(?:\+|to\s*\d+(?:\.\d+)?)?\s*(?:years?|yrs?|y)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = float(match.group(1) or 0)
            return int(value) if value.is_integer() else round(value, 1)
    return None


def _extract_education(description):
    text = description or ""
    patterns = [
        r"(?:b\.sc|bsc|b\.tech|btech|bachelor(?:'s)?|undergraduate|degree)\b[\w\s-]*",
        r"(?:master(?:'s)?|m\.tech|mtech|postgraduate|mba|phd|doctorate)\b[\w\s-]*",
        r"(?:diploma|associate degree|engineering degree|computer science degree)\b[\w\s-]*",
    ]
    matches = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = _safe_clean_line(match.group(0))
            if value and value.lower() not in {item.lower() for item in matches}:
                matches.append(value)
    if matches:
        return matches
    return []


def _extract_soft_skills(description):
    text = description or ""
    matches = []
    for skill in SOFT_SKILLS:
        if re.search(rf"\b{re.escape(skill)}\b", text, re.I):
            matches.append(skill)
    return matches


def _extract_responsibilities(description):
    text = description or ""
    candidates = []
    patterns = [
        r"(?:key\s+)?(?:responsibilities|duties|you\s+will|the\s+candidate\s+will)\s*[:\-]?\s*(.*)",
        r"(?:role\s+includes|includes|responsible\s+for)\s*[:\-]?\s*(.*)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            body = match.group(1)
            pieces = re.split(r"(?<=[.;])\s+|\n+", body)
            for piece in pieces:
                value = _safe_clean_line(piece)
                if value and len(value.split()) >= 3:
                    candidates.append(value)
    if not candidates:
        for sentence in re.split(r"(?<=[.;])\s+|\n+", text):
            sentence = _safe_clean_line(sentence)
            if not sentence:
                continue
            lowered = sentence.lower()
            if any(keyword in lowered for keyword in ["build", "design", "develop", "manage", "analyze", "coordinate", "lead", "work", "support", "deliver", "maintain"]):
                candidates.append(sentence)
    return candidates[:6]


def _extract_keywords(description):
    text = description or ""
    tokens = [token for token in important_terms(text, limit=25) if len(token) > 2 and token not in STOPWORDS]
    searchable = {token.lower() for token in tokens}
    if not searchable:
        return []
    tracked = []
    for skill in [skill for skills in SKILL_CATEGORIES.values() for skill in skills]:
        if skill.lower() in searchable or skill.lower().replace("-", " ") in " ".join(tokens):
            tracked.append(skill)
    for token in tokens:
        if token.lower() not in {item.lower() for item in tracked} and token.lower() not in {"python", "developer", "engineer", "candidate", "team", "work", "role", "experience", "skills", "knowledge", "using", "with"}:
            tracked.append(token)
    return tracked[:12]


def analyze_job_requirements(description):
    """Suggest skills from a job description; recruiters can edit the suggestions."""
    text = description or ""
    all_skills = list(extract_skills(text))
    preferred_text = []
    required_text = []
    in_preferred = False
    in_responsibilities = False
    for line in text.splitlines():
        lowered = line.lower()
        if re.search(r"\b(preferred|nice to have|good to have|bonus|advantage)\b", lowered):
            in_preferred = True
            in_responsibilities = False
        elif re.search(r"\b(responsibilities|duties|what you'll do|you will)\b", lowered):
            in_preferred = False
            in_responsibilities = True
        elif re.search(r"\b(required|must have|mandatory|qualifications|minimum qualifications)\b", lowered):
            in_preferred = False
            in_responsibilities = False
        if in_preferred:
            preferred_text.append(line)
        elif in_responsibilities:
            required_text.append(line)
        else:
            required_text.append(line)
    preferred_skills = list(extract_skills("\n".join(preferred_text)))
    preferred_lower = {skill.lower() for skill in preferred_skills}
    required_skills = [skill for skill in all_skills if skill.lower() not in preferred_lower]
    if not required_skills:
        required_skills = list(extract_skills("\n".join(required_text)))

    education = _extract_education(text)
    minimum_experience = _extract_minimum_experience(text)
    role = _extract_role(text)
    soft_skills = _extract_soft_skills(text)
    responsibilities = _extract_responsibilities(text)
    technical_keywords = _extract_keywords(text)
    return {
        "role": role,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "mandatory_skills": required_skills,
        "preferred_technical_skills": preferred_skills,
        "education_requirements": education,
        "minimum_experience": minimum_experience,
        "experience": minimum_experience,
        "job_responsibilities": responsibilities,
        "responsibilities": responsibilities,
        "important_technical_keywords": technical_keywords,
        "technical_keywords": technical_keywords,
        "soft_skills": soft_skills,
        "education": education,
        "confidence": "medium" if text else "low",
    }
