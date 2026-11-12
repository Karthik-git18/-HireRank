"""Add clearly labelled synthetic examples to an existing HireRank account."""
import argparse
import hashlib
import json
import uuid
from pathlib import Path

import fitz

from app import create_app
from modules.database import get_db, init_db
from modules.ranking_engine import rank_candidate


JOBS = [
    {
        "job_title": "SYNTHETIC DEMO: Python Web Developer",
        "department": "Product Engineering",
        "location": "Remote",
        "employment_type": "Full-time",
        "required_experience": 2,
        "education_requirement": "Bachelor",
        "job_description": "Build maintainable Python web services with Flask, SQL and Git. "
                           "Preferred: Docker and AWS.",
        "required_skills": ["Python", "Flask", "SQL", "Git"],
        "preferred_skills": ["Docker", "AWS"],
    },
    {
        "job_title": "SYNTHETIC DEMO: Data Analyst",
        "department": "Analytics",
        "location": "Hybrid",
        "employment_type": "Full-time",
        "required_experience": 1,
        "education_requirement": "Bachelor",
        "job_description": "Analyze business data using Python, SQL, Pandas and clear communication. "
                           "Preferred: Tableau.",
        "required_skills": ["Python", "SQL", "Pandas", "Communication"],
        "preferred_skills": [],
    },
    {
        "job_title": "SYNTHETIC DEMO: Machine Learning Intern",
        "department": "Applied AI",
        "location": "Bengaluru",
        "employment_type": "Internship",
        "required_experience": 0,
        "education_requirement": "Bachelor",
        "job_description": "Support machine learning experiments with Python, Scikit-learn and data analysis.",
        "required_skills": ["Python", "Machine Learning", "Scikit-learn"],
        "preferred_skills": ["Pandas", "NumPy"],
    },
]

CANDIDATES = [
    ("Synthetic Candidate 01", ["Python", "Flask", "SQL", "Git", "Docker"], 3, "Bachelor of Science",
     "Built a Flask service with a SQL database. Used Docker and Git."),
    ("Synthetic Candidate 02", ["Python", "SQL", "Pandas", "Communication"], 2, "Bachelor of Analytics",
     "Analyzed datasets with Python, SQL and Pandas; presented findings to teammates."),
    ("Synthetic Candidate 03", ["Python", "Machine Learning", "Scikit-learn", "NumPy"], 1, "Bachelor of Technology",
     "Completed a machine learning project using Scikit-learn and NumPy."),
    ("Synthetic Candidate 04", ["Python", "Flask", "Git", "AWS"], 2, "Bachelor of Engineering",
     "Created a Python and Flask web application. Deployed a sample service to AWS."),
    ("Synthetic Candidate 05", ["Python", "SQL", "Pandas", "Machine Learning"], 0, "Bachelor of Science",
     "Coursework and projects in data analysis and machine learning with Python."),
]


def build_pdf(candidate, email, skills, years, education, details):
    text = (
        f"{candidate}\n{email}\nSynthetic demonstration resume - not a real person.\n"
        f"Skills\n{', '.join(skills)}\nExperience\n{years} years of experience\n"
        f"Education\n{education}\nProjects\n{details}\n"
    )
    document = fitz.open()
    document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data, text


def seed(email):
    app = create_app()
    with app.app_context():
        init_db()
        db = get_db()
        user = db.execute("SELECT id FROM users WHERE email=?", (email.lower(),)).fetchone()
        if user is None:
            raise SystemExit(f"No HireRank account found for {email}. Register in the app first.")
        if db.execute(
            "SELECT 1 FROM jobs WHERE user_id=? AND job_title LIKE 'SYNTHETIC DEMO:%' LIMIT 1",
            (user["id"],),
        ).fetchone():
            raise SystemExit("Synthetic demo records already exist for this account; no records were changed.")

        job_ids = []
        for job in JOBS:
            cursor = db.execute(
                """INSERT INTO jobs(user_id,job_title,department,location,employment_type,required_experience,
                   education_requirement,job_description,required_skills,preferred_skills)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (user["id"], job["job_title"], job["department"], job["location"], job["employment_type"],
                 job["required_experience"], job["education_requirement"], job["job_description"],
                 json.dumps(job["required_skills"]), json.dumps(job["preferred_skills"])),
            )
            job_ids.append(cursor.lastrowid)

        profiles = []
        upload_root = Path(app.config["UPLOAD_FOLDER"]) / str(user["id"])
        upload_root.mkdir(parents=True, exist_ok=True)
        for index, (name, skills, years, education, details) in enumerate(CANDIDATES, 1):
            email_address = f"synthetic{index}@example.invalid"
            cursor = db.execute(
                """INSERT INTO candidates(user_id,candidate_name,email) VALUES(?,?,?)""",
                (user["id"], name, email_address),
            )
            profiles.append((cursor.lastrowid, name, skills, years, education, details, email_address))

        assignments = [(0, 0), (0, 3), (1, 1), (1, 4), (2, 2), (2, 4)]
        for job_index, candidate_index in assignments:
            job = JOBS[job_index]
            candidate_id, name, skills, years, education, details, email_address = profiles[candidate_index]
            pdf_data, text = build_pdf(name, email_address, skills, years, education, details)
            filename = f"demo-{uuid.uuid4().hex}.pdf"
            (upload_root / filename).write_bytes(pdf_data)
            analysis = {
                "candidate_name": name,
                "email": email_address,
                "phone": None,
                "linkedin": None,
                "github": None,
                "portfolio": None,
                "education": {"degrees": [education], "graduation_years": [], "details": education},
                "experience_years": years,
                "experience_details": f"{years} years of experience",
                "skills": {skill: "Synthetic demo" for skill in skills},
                "projects": details,
                "certifications": "",
            }
            ranking = rank_candidate(text, analysis, {
                "required_skills": job["required_skills"],
                "preferred_skills": job["preferred_skills"],
                "required_experience": job["required_experience"],
                "education_requirement": job["education_requirement"],
                "job_text": f"{job['job_title']} {job['job_description']}",
            })
            analysis["preferred_matching_skills"] = ranking["preferred_matching_skills"]
            db.execute(
                """INSERT INTO applications(job_id,candidate_id,resume_path,resume_sha256,extracted_text,
                   analysis_json,overall_score,similarity_score,skill_score,experience_score,education_score,
                   preferred_skill_score,matching_skills,missing_skills)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_ids[job_index], candidate_id, f"{user['id']}/{filename}", hashlib.sha256(pdf_data).hexdigest(),
                 text, json.dumps(analysis), ranking["overall_score"], ranking["similarity_score"],
                 ranking["skill_score"], ranking["experience_score"], ranking["education_score"],
                 ranking["preferred_skill_score"], json.dumps(ranking["matching_skills"]),
                 json.dumps(ranking["missing_skills"])),
            )
        db.commit()
        print(f"Added 3 synthetic vacancies and 5 synthetic profiles to {email}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="Email of an existing HireRank account")
    seed(parser.parse_args().email)
