import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from modules.nlp_engine import extract_skills, normalize_skill_list
from modules.resume_parser import education_match_score


DEFAULT_WEIGHTS = {
    "similarity": 0.35,
    "required_skills": 0.30,
    "experience": 0.20,
    "education": 0.10,
    "preferred_skills": 0.05,
}
WEIGHT_TOLERANCE = 1e-9


def text_similarity(resume_text, job_text):
    if not (resume_text or "").strip() or not (job_text or "").strip():
        return None
    try:
        matrix = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit_transform([resume_text, job_text])
        return round(float(cosine_similarity(matrix[0:1], matrix[1:2])[0, 0]) * 100, 2)
    except ValueError:
        return 0.0


def _screening_text(resume_text, candidate_name):
    sensitive_labels = re.compile(
        r"\b(?:age|date of birth|dob|gender|sex|religion|caste|ethnicity|nationality|"
        r"marital status|race|photo|photograph)\b", re.I
    )
    lines = []
    for line in (resume_text or "").splitlines():
        if sensitive_labels.search(line):
            continue
        if candidate_name and line.strip().casefold() == candidate_name.strip().casefold():
            continue
        line = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", " ", line, flags=re.I)
        line = re.sub(r"https?://\S+", " ", line, flags=re.I)
        line = re.sub(r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,5}[\s.-]?\d{4}(?!\w)", " ", line)
        lines.append(line)
    return "\n".join(lines)


def _coverage(found, wanted):
    if not wanted:
        return None
    found_lower = {skill.lower() for skill in found}
    matched = [skill for skill in wanted if skill.lower() in found_lower]
    return round(len(matched) / len(wanted) * 100, 2), matched


def rank_candidate(resume_text, analysis, job, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    if set(weights) != set(DEFAULT_WEIGHTS) or any(value < 0 for value in weights.values()):
        raise ValueError("Ranking weights must define every component with a non-negative weight.")
    if abs(sum(weights.values()) - 1.0) > WEIGHT_TOLERANCE:
        raise ValueError("Ranking weights must add up to 100%.")
    required = normalize_skill_list(job.get("required_skills", []))
    preferred = normalize_skill_list(job.get("preferred_skills", []))
    candidate_skills = list((analysis.get("skills") or {}).keys())
    skill_catalog = extract_skills(resume_text or "")
    candidate_skills = list(dict.fromkeys(candidate_skills + list(skill_catalog)))
    required_cov = _coverage(candidate_skills, required)
    preferred_cov = _coverage(candidate_skills, preferred)
    similarity = text_similarity(_screening_text(resume_text, analysis.get("candidate_name")),
                                 job["job_text"])
    experience_years = analysis.get("experience_years")
    required_years = job.get("required_experience")
    experience_score = None
    if experience_years is not None and required_years is not None:
        experience_score = 100.0 if float(required_years) <= 0 else min(
            100.0, round(experience_years / float(required_years) * 100, 2)
        )
    education_score = education_match_score(
        analysis.get("education") or {}, job.get("education_requirement", "")
    )

    scores = {
        "similarity": similarity,
        "required_skills": required_cov[0] if required_cov else None,
        "experience": experience_score,
        "education": education_score,
        "preferred_skills": preferred_cov[0] if preferred_cov else None,
    }
    applicable = {
        "similarity": True,
        "required_skills": bool(required),
        "experience": required_years is not None,
        "education": bool((job.get("education_requirement") or "").strip()),
        "preferred_skills": bool(preferred),
    }
    available = {
        key: enabled and scores[key] is not None
        for key, enabled in applicable.items()
    }
    available_weights = [key for key, enabled in available.items() if enabled]
    active_weight = sum(weights[key] for key in available_weights)
    applied_weights = {
        key: round(weights[key] / active_weight, 6)
        for key in available_weights if active_weight
    }
    overall = None
    if active_weight and available_weights:
        overall = round(
            sum(applied_weights[key] * scores[key] for key in available_weights), 2
        )
    matched_required = required_cov[1] if required_cov else []
    missing = [skill for skill in required if skill.lower() not in {item.lower() for item in matched_required}]
    matched_preferred = preferred_cov[1] if preferred_cov else []
    return {
        "overall_score": overall,
        "similarity_score": similarity,
        "skill_score": required_cov[0] if required_cov else None,
        "experience_score": experience_score,
        "education_score": education_score,
        "preferred_skill_score": preferred_cov[0] if preferred_cov else None,
        "matching_skills": matched_required,
        "missing_skills": missing,
        "preferred_matching_skills": matched_preferred,
        "component_scores": scores,
        "applied_weights": applied_weights,
        "available_components": available_weights,
        "missing_components": [key for key, enabled in applicable.items() if enabled and scores[key] is None],
    }
