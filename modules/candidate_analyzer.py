def explain_analysis(analysis, ranking):
    explanations = []
    matched = ranking.get("matching_skills", [])
    missing = ranking.get("missing_skills", [])
    if ranking.get("skill_score") is not None:
        total = len(matched) + len(missing)
        explanations.append(f"Candidate matches {len(matched)} of {total} required skills.")
    if matched:
        explanations.append("Detected required skills: " + ", ".join(matched) + ".")
    if missing:
        explanations.append("Not detected in the resume: " + ", ".join(missing) + ".")
    if analysis.get("internship_years") is not None:
        explanations.append(
            f"Internship duration was extracted separately: {analysis['internship_years']:g} years; "
            "it is not counted as full-time experience."
        )
    if ranking.get("experience_score") is None:
        explanations.append("Required full-time experience could not be verified from employment dates or an explicit duration.")
    else:
        explanations.append(f"Explicitly extracted experience: {analysis.get('experience_years'):g} years.")
    if analysis.get("projects"):
        explanations.append("A projects section was identified in the resume.")
    if analysis.get("education", {}).get("details"):
        explanations.append("An education section was identified; verify equivalency during human review.")
    if ranking.get("overall_score") is None:
        explanations.append("The overall match is unscored because at least one specified criterion could not be verified.")
    return explanations


def candidate_profile(analysis):
    return {
        "education": analysis.get("education", {}),
        "experience_years": analysis.get("experience_years"),
        "internship_years": analysis.get("internship_years"),
        "experience_details": analysis.get("experience_details", ""),
        "skills": analysis.get("skills", {}),
        "projects": analysis.get("projects", ""),
        "certifications": analysis.get("certifications", ""),
    }
