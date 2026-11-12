import json
from pathlib import Path

from modules.ranking_engine import rank_candidate
from modules.resume_parser import (
    extract_pdf_document,
    is_valid_candidate_name,
    parse_resume,
)


def _job_data(row):
    job = dict(row)
    job["required_skills"] = json.loads(job["required_skills"] or "[]")
    job["preferred_skills"] = json.loads(job["preferred_skills"] or "[]")
    job["job_text"] = " ".join(
        [job["job_title"], job["department"], job["job_description"],
         " ".join(job["required_skills"]), " ".join(job["preferred_skills"])]
    )
    return job


def _persist_analysis(db, application_id, candidate_id, current_name, analysis, ranking, text):
    if not is_valid_candidate_name(current_name):
        db.execute(
            "UPDATE candidates SET candidate_name=? WHERE id=?",
            (analysis["candidate_name"], candidate_id),
        )
    db.execute(
        """UPDATE applications SET extracted_text=?,analysis_json=?,overall_score=?,similarity_score=?,
           skill_score=?,experience_score=?,education_score=?,preferred_skill_score=?,
           matching_skills=?,missing_skills=? WHERE id=?""",
        (text, json.dumps(analysis), ranking["overall_score"], ranking["similarity_score"],
         ranking["skill_score"], ranking["experience_score"], ranking["education_score"],
         ranking["preferred_skill_score"], json.dumps(ranking["matching_skills"]),
         json.dumps(ranking["missing_skills"]), application_id),
    )


def reprocess_existing_applications(db, upload_folder, user_id=None, dry_run=True):
    """Re-extract derived resume data in place; preserve IDs, statuses, notes and files."""
    params = []
    where = ""
    if user_id is not None:
        where = "AND j.user_id=?"
        params.append(user_id)
    rows = db.execute(
        f"""SELECT a.id AS application_id,a.candidate_id,a.resume_path,a.extracted_text,
                   c.candidate_name,j.* FROM applications a
            JOIN candidates c ON c.id=a.candidate_id JOIN jobs j ON j.id=a.job_id
            WHERE c.user_id=j.user_id {where}
            ORDER BY a.id""",
        params,
    ).fetchall()
    root = Path(upload_folder).resolve()
    results = []
    for row in rows:
        path = (root / row["resume_path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"Resume file for application {row['application_id']} is missing or unsafe.")
        text, document_lines = extract_pdf_document(path)
        analysis = parse_resume(text, document_lines)
        ranking = rank_candidate(text, analysis, _job_data(row))
        analysis["preferred_matching_skills"] = ranking["preferred_matching_skills"]
        if not dry_run:
            _persist_analysis(
                db, row["application_id"], row["candidate_id"], row["candidate_name"], analysis, ranking, text
            )
        results.append({
            "application_id": row["application_id"],
            "candidate_name": analysis["candidate_name"],
            "name_detected": is_valid_candidate_name(analysis["candidate_name"]),
            "score": ranking["overall_score"],
        })
    return results


def refresh_job_application_scores(db, job_id, job):
    """Recompute cached scores after vacancy criteria change without creating applications."""
    rows = db.execute(
        """SELECT a.id AS application_id,a.candidate_id,a.extracted_text,c.candidate_name
           FROM applications a JOIN candidates c ON c.id=a.candidate_id
           WHERE a.job_id=? ORDER BY a.id""",
        (job_id,),
    ).fetchall()
    for row in rows:
        analysis = parse_resume(row["extracted_text"])
        analysis["candidate_name"] = row["candidate_name"]
        ranking = rank_candidate(row["extracted_text"], analysis, job)
        analysis["preferred_matching_skills"] = ranking["preferred_matching_skills"]
        _persist_analysis(
            db, row["application_id"], row["candidate_id"], row["candidate_name"],
            analysis, ranking, row["extracted_text"],
        )
    return len(rows)
