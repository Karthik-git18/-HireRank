import io
import json
import re

import fitz
import pytest
from werkzeug.security import check_password_hash

from app import create_app
from modules.database import get_db
from modules.nlp_engine import analyze_job_requirements, extract_skills
from modules.ranking_engine import rank_candidate, text_similarity
from modules.resume_parser import parse_resume


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-key",
        "DATABASE": str(tmp_path / "test.sqlite3"),
        "UPLOAD_FOLDER": tmp_path / "uploads",
    })
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, email="hr@example.com", password="secure-pass-123"):
    return client.post("/register", data={
        "full_name": "Test Recruiter",
        "company_name": "Example Co",
        "email": email,
        "password": password,
        "confirm_password": password,
    }, follow_redirects=True)


def make_pdf(text):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def create_job(client, title="Python Engineer"):
    return client.post("/jobs/create", data={
        "job_title": title,
        "department": "Engineering",
        "location": "Remote",
        "employment_type": "Full-time",
        "required_experience": "2",
        "education_requirement": "Bachelor",
        "job_description": "We need a Python engineer using Flask and SQL. Preferred Docker.",
        "required_skills": "Python, Flask, SQL",
        "preferred_skills": "Docker",
        "status": "Active",
    }, follow_redirects=True)


def upload_pdf(client, job_id, name, content=None):
    return client.post(
        f"/jobs/{job_id}/upload",
        data={"resumes": (io.BytesIO(content or make_pdf(
            "Alex Morgan\nalex@example.com\nPython Flask SQL Docker\n"
            "Experience\n3 years of professional experience\nEducation\nBachelor of Science\n"
            "Projects\nBuilt a Flask application."
        )), name)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_registration_password_hash_login_logout_and_protection(client, app):
    response = client.get("/dashboard")
    assert response.status_code == 302
    response = register(client)
    assert response.status_code == 200
    assert b"Dashboard" in response.data
    with app.app_context():
        user = get_db().execute("SELECT * FROM users WHERE email=?", ("hr@example.com",)).fetchone()
        assert check_password_hash(user["password_hash"], "secure-pass-123")
        assert user["password_hash"] != "secure-pass-123"
    client.post("/logout", follow_redirects=True)
    response = client.post("/login", data={"email": "hr@example.com", "password": "secure-pass-123"},
                           follow_redirects=True)
    assert response.status_code == 200
    assert b"Good work starts with clarity" in response.data


def test_duplicate_registration_and_invalid_login(client):
    register(client)
    client.post("/logout")
    response = client.post("/register", data={
        "full_name": "Another Recruiter", "company_name": "Elsewhere", "email": "hr@example.com",
        "password": "secure-pass-123", "confirm_password": "secure-pass-123",
    }, follow_redirects=True)
    assert b"already exists" in response.data
    response = client.post("/login", data={"email": "hr@example.com", "password": "wrong-password"},
                           follow_redirects=True)
    assert b"incorrect" in response.data


def test_job_ownership_and_resume_upload(client, app):
    register(client)
    response = create_job(client)
    assert response.status_code == 200
    with app.app_context():
        job = get_db().execute("SELECT id FROM jobs").fetchone()
        job_id = job["id"]
    candidate_pdf = make_pdf(
        "Alex Morgan\nalex@example.com\nPython Flask SQL Docker\n"
        "Experience\n3 years of professional experience\nEducation\nBachelor of Science\n"
        "Projects\nBuilt a Flask application."
    )
    response = upload_pdf(client, job_id, "candidate.pdf", candidate_pdf)
    assert b"uploaded and screened successfully" in response.data
    with app.app_context():
        row = get_db().execute("SELECT * FROM applications").fetchone()
        assert row["overall_score"] is not None
        assert row["skill_score"] == 100
        assert json.loads(row["matching_skills"]) == ["Python", "Flask", "SQL"]
    duplicate = upload_pdf(client, job_id, "candidate-copy.pdf", candidate_pdf)
    assert b"already uploaded" in duplicate.data
    invalid = upload_pdf(client, job_id, "invalid.pdf", b"not a pdf")
    assert b"not a valid PDF" in invalid.data

    client.post("/logout")
    register(client, email="other@example.com")
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.get(f"/jobs/{job_id}/candidates").status_code == 404


def test_status_history_notes_comparison_and_csv(client, app):
    register(client)
    create_job(client)
    with app.app_context():
        job_id = get_db().execute("SELECT id FROM jobs").fetchone()["id"]
    upload_pdf(client, job_id, "one.pdf", make_pdf(
        "Jamie Lee\njamie@example.com\nPython Flask SQL\nExperience\n3 years experience\nEducation\nBachelor"
    ))
    upload_pdf(client, job_id, "two.pdf", make_pdf(
        "Taylor Kim\ntaylor@example.com\nPython SQL Docker\nExperience\n2 years experience\nEducation\nBachelor"
    ))
    with app.app_context():
        ids = [row["id"] for row in get_db().execute("SELECT id FROM applications ORDER BY id")]
    response = client.post(f"/applications/{ids[0]}/status",
                           data={"status": "Shortlisted"}, follow_redirects=True)
    assert b"Candidate status updated" in response.data
    client.post(f"/applications/{ids[0]}/notes", data={"note": "Review project portfolio."})
    detail = client.get(f"/applications/{ids[0]}")
    assert b"Review project portfolio." in detail.data
    comparison = client.post("/compare", data={"application_ids": [str(item) for item in ids]})
    assert comparison.status_code == 200
    assert b"Candidate comparison" in comparison.data
    exported = client.get("/reports/candidates.csv")
    assert exported.status_code == 200
    assert b"Jamie Lee" in exported.data
    with app.app_context():
        actions = get_db().execute("SELECT COUNT(*) AS n FROM activity_logs").fetchone()["n"]
        assert actions >= 3


def test_nlp_job_analysis_parser_and_ranking():
    skills = extract_skills("Experience with ML, NLP, JS, PostgreSQL and C++.")
    assert "Machine Learning" in skills
    assert "Natural Language Processing" in skills
    assert "JavaScript" in skills
    assert "C++" in skills
    assert "C" not in skills
    suggestions = analyze_job_requirements(
        "Required: Python and Flask.\nPreferred skills: Docker and AWS."
    )
    assert set(suggestions["required_skills"]) == {"Python", "Flask"}
    assert set(suggestions["preferred_skills"]) == {"Docker", "AWS"}

    resume = "Jordan Smith\njordan@example.test\nPython Flask\nExperience\n3 years of experience\nEducation\nBachelor of Science"
    analysis = parse_resume(resume)
    assert analysis["candidate_name"] == "Jordan Smith"
    assert analysis["email"] == "jordan@example.test"
    assert analysis["experience_years"] == 3
    assert text_similarity(resume, "Python developer using Flask") > 0
    ranking = rank_candidate(resume, analysis, {
        "required_skills": ["Python", "Flask", "Docker"],
        "preferred_skills": [],
        "required_experience": 2,
        "education_requirement": "Bachelor",
        "job_text": "Python developer using Flask and Docker",
    })
    assert ranking["skill_score"] == pytest.approx(200 / 3, abs=0.01)
    assert ranking["experience_score"] == 100
    assert ranking["missing_skills"] == ["Docker"]
    assert ranking["overall_score"] is not None

    unknown = rank_candidate("some resume", {"skills": {}, "experience_years": None, "education": {}}, {
        "required_skills": [], "preferred_skills": [], "required_experience": 2,
        "education_requirement": "Bachelor", "job_text": "some role",
    })
    assert unknown["skill_score"] is None
    assert unknown["experience_score"] is None
    assert unknown["education_score"] is None
    assert unknown["overall_score"] is not None
    no_experience_required = rank_candidate("internship", {
        "skills": {}, "experience_years": 0, "education": {},
    }, {
        "required_skills": [], "preferred_skills": [], "required_experience": 0,
        "education_requirement": "", "job_text": "internship",
    })
    assert no_experience_required["experience_score"] == 100


def test_job_analysis_extracts_description_requirements():
    description = """We are looking for a Python Developer.

Mandatory Qualifications:

- Strong knowledge of Python.
- Experience with SQL.
- Knowledge of Flask.
- Understanding of REST API development.

Preferred Qualifications:

- Knowledge of Docker.
- Familiarity with AWS.

Minimum 1 year of professional experience.

Bachelor’s degree in Computer Science.

Responsibilities:

- Develop backend applications.
- Design and manage databases.
- Build REST APIs.
- Debug applications.

Soft Skills:

- Communication.
- Teamwork.
- Problem Solving."""

    analysis = analyze_job_requirements(description)

    assert analysis["role"] == "Python Developer"
    assert analysis["required_skills"] == ["Python", "SQL", "Flask", "REST API"]
    assert analysis["preferred_skills"] == ["Docker", "AWS"]
    assert analysis["minimum_experience"] == 1
    assert analysis["education_requirements"] == ["Bachelor’s degree in Computer Science"]
    assert set(analysis["job_responsibilities"]) == {
        "Develop backend applications",
        "Design and manage databases",
        "Build REST APIs",
        "Debug applications",
    }
    assert analysis["soft_skills"] == ["Communication", "Teamwork", "Problem Solving"]


def test_job_analysis_endpoint_validates_inputs_and_authentication(client, monkeypatch, caplog):
    register(client)
    description = "We are looking for a Python Developer. Mandatory skills: Python, SQL, Flask, REST API."

    response = client.post("/jobs/analyze", json={"description": description})
    assert response.status_code == 200
    assert response.is_json
    assert response.get_json()["required_skills"] == ["Python", "SQL", "Flask", "REST API"]

    empty = client.post("/jobs/analyze", json={"description": "  "})
    assert empty.status_code == 400
    assert empty.get_json()["error"] == "invalid_description"

    invalid_json = client.post("/jobs/analyze", data="{", content_type="application/json")
    assert invalid_json.status_code == 400
    assert invalid_json.get_json()["error"] == "invalid_json"

    def fail_analysis(_description):
        raise RuntimeError("analyzer failure")

    monkeypatch.setattr("app.analyze_job_requirements", fail_analysis)
    failed = client.post("/jobs/analyze", json={"description": description})
    assert failed.status_code == 500
    assert failed.get_json()["error"] == "analysis_failed"
    assert "analyzer failure" in caplog.text

    client.post("/logout")
    unauthenticated = client.post("/jobs/analyze", json={"description": description})
    assert unauthenticated.status_code == 401
    assert unauthenticated.is_json
    assert unauthenticated.get_json()["error"] == "authentication_required"


def test_job_analysis_endpoint_accepts_csrf_token(tmp_path):
    csrf_app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": True,
        "SECRET_KEY": "csrf-test-key",
        "DATABASE": str(tmp_path / "csrf-test.sqlite3"),
        "UPLOAD_FOLDER": tmp_path / "uploads",
    })
    csrf_client = csrf_app.test_client()

    login_page = csrf_client.get("/login")
    token = re.search(rb'name="csrf_token" value="([^"]+)"', login_page.data).group(1).decode()
    csrf_client.post("/register", data={
        "csrf_token": token,
        "full_name": "Test Recruiter",
        "company_name": "Example Co",
        "email": "csrf@example.com",
        "password": "secure-pass-123",
        "confirm_password": "secure-pass-123",
    })

    job_form = csrf_client.get("/jobs/create")
    token = re.search(rb'name="csrf_token" value="([^"]+)"', job_form.data).group(1).decode()
    payload = {"description": "Python Developer using Flask"}

    missing_token = csrf_client.post("/jobs/analyze", json=payload)
    assert missing_token.status_code == 400
    assert missing_token.is_json
    assert missing_token.get_json()["error"] == "request_validation_failed"

    valid_token = csrf_client.post(
        "/jobs/analyze",
        json=payload,
        headers={"X-CSRFToken": token},
    )
    assert valid_token.status_code == 200
    assert valid_token.is_json
    assert valid_token.get_json()["role"] == "Python Developer"


def test_invalid_and_oversized_pdf_messages(client, app):
    register(client)
    create_job(client)
    with app.app_context():
        job_id = get_db().execute("SELECT id FROM jobs").fetchone()["id"]
    corrupt = upload_pdf(client, job_id, "corrupt.pdf", b"%PDF-1.4\nthis is not a valid document")
    assert b"corrupted or invalid" in corrupt.data
    response = upload_pdf(client, job_id, "large.pdf", b"%PDF-" + b"x" * (5 * 1024 * 1024 + 1))
    assert b"5 MB per-file limit" in response.data


def test_workspace_pages_and_profile_update(client):
    register(client)
    assert client.get("/jobs").status_code == 200
    assert client.get("/candidates").status_code == 200
    assert client.get("/analytics").status_code == 200
    assert client.get("/profile").status_code == 200
    assert client.get("/jobs/create").status_code == 200
    response = client.post("/profile", data={
        "full_name": "Updated Recruiter", "company_name": "Updated Company",
    }, follow_redirects=True)
    assert b"Profile updated" in response.data
    assert b"Updated Company" in response.data
