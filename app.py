import csv
import hashlib
import io
import json
import os
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, g, jsonify, make_response, redirect, render_template, request,
    send_file, session, url_for,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import Config
from modules.analytics import analytics_data, dashboard_data
from modules.candidate_analyzer import explain_analysis
from modules.database import close_db, get_db, init_db
from modules.nlp_engine import analyze_job_requirements, normalize_skill_list, SKILL_CATEGORIES
from modules.ranking_engine import rank_candidate
from modules.resume_parser import extract_pdf_document, parse_resume
from modules.reprocessing import refresh_job_application_scores


ALLOWED_STATUSES = {"New", "Under Review", "Shortlisted", "Rejected", "Interview Scheduled", "Selected"}
EMPLOYMENT_TYPES = {"Full-time", "Part-time", "Contract", "Internship", "Temporary"}
csrf = CSRFProtect()


def safe_csv_cell(value):
    text = str(value or "")
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def csv_score(value):
    return "Unknown" if value is None else value


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    app.config.update(test_config or {})
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    csrf.init_app(app)
    app.teardown_appcontext(close_db)

    app.extensions["hirerank_db_initialized"] = False

    @app.before_request
    def ensure_database():
        if not app.extensions["hirerank_db_initialized"]:
            init_db()
            app.extensions["hirerank_db_initialized"] = True

    @app.before_request
    def load_user():
        g.user = None
        if session.get("user_id") is not None:
            g.user = get_db().execute(
                "SELECT id,full_name,company_name,email FROM users WHERE id=?", (session["user_id"],)
            ).fetchone()
            if g.user is None:
                session.clear()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    def owned_job(job_id):
        row = get_db().execute("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, g.user["id"])).fetchone()
        if row is None:
            abort(404)
        item = dict(row)
        item["required_skills"] = json.loads(item["required_skills"] or "[]")
        item["preferred_skills"] = json.loads(item["preferred_skills"] or "[]")
        item["job_text"] = " ".join(
            [item["job_title"], item["department"], item["job_description"],
             " ".join(item["required_skills"]), " ".join(item["preferred_skills"])]
        )
        return item

    def owned_application(application_id):
        row = get_db().execute(
            """SELECT a.*,c.candidate_name,c.email,c.phone,c.linkedin,c.github,c.user_id AS candidate_owner,
                      j.user_id AS job_owner,j.job_title
               FROM applications a JOIN candidates c ON c.id=a.candidate_id
               JOIN jobs j ON j.id=a.job_id WHERE a.id=?""", (application_id,)
        ).fetchone()
        if row is None or row["job_owner"] != g.user["id"] or row["candidate_owner"] != g.user["id"]:
            abort(404)
        return row

    def log_activity(application_id, action, description):
        get_db().execute(
            "INSERT INTO activity_logs(user_id,application_id,action,description) VALUES(?,?,?,?)",
            (g.user["id"], application_id, action, description),
        )

    def score_label(value):
        return "Unknown" if value is None else f"{value:.1f}%"

    @app.context_processor
    def template_helpers():
        return {"score_label": score_label}

    @app.template_filter("from_json")
    def from_json(value):
        try:
            return json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []

    @app.route("/")
    def landing():
        if g.user:
            return redirect(url_for("dashboard"))
        return render_template("landing.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            company = request.form.get("company_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            if not all([full_name, company, email, password, confirm]):
                flash("Complete all fields to create your account.", "danger")
            elif len(full_name) > 120 or len(company) > 120 or len(email) > 254 or "@" not in email:
                flash("Enter valid name, company and email values.", "danger")
            elif len(password) < 8:
                flash("Password must contain at least 8 characters.", "danger")
            elif password != confirm:
                flash("Passwords do not match.", "danger")
            else:
                db = get_db()
                try:
                    cursor = db.execute(
                        "INSERT INTO users(full_name,company_name,email,password_hash) VALUES(?,?,?,?)",
                        (full_name, company, email, generate_password_hash(password)),
                    )
                    db.commit()
                    session.clear()
                    session["user_id"] = cursor.lastrowid
                    flash("Your account is ready.", "success")
                    return redirect(url_for("dashboard"))
                except Exception as exc:
                    db.rollback()
                    if "UNIQUE constraint failed: users.email" in str(exc):
                        flash("An account with that email already exists.", "danger")
                    else:
                        raise
        return render_template("auth.html", mode="register")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("Email or password is incorrect.", "danger")
            else:
                session.clear()
                session["user_id"] = user["id"]
                flash(f"Welcome back, {user['full_name']}.", "success")
                return redirect(url_for("dashboard"))
        return render_template("auth.html", mode="login")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("landing"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html", data=dashboard_data(g.user["id"]))

    @app.route("/jobs")
    @login_required
    def jobs():
        rows = get_db().execute(
            """SELECT j.*,COUNT(a.id) AS applicant_count FROM jobs j
               LEFT JOIN applications a ON a.job_id=j.id WHERE j.user_id=?
               GROUP BY j.id ORDER BY j.created_at DESC""", (g.user["id"],)
        ).fetchall()
        return render_template("jobs.html", jobs=rows)

    @app.route("/jobs/analyze", methods=["GET", "POST"])
    @login_required
    def analyze_job_route():
        description = ""
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            description = str(payload.get("description", "") or request.form.get("description", "") or "")
        else:
            description = request.args.get("description", "")
        analysis = analyze_job_requirements(description)
        return jsonify({
            "role": analysis.get("role", "Not specified"),
            "required_skills": analysis.get("required_skills", []),
            "preferred_skills": analysis.get("preferred_skills", []),
            "minimum_experience": analysis.get("minimum_experience"),
            "education_requirements": analysis.get("education_requirements", []),
            "job_responsibilities": analysis.get("job_responsibilities", []),
            "important_technical_keywords": analysis.get("important_technical_keywords", []),
            "soft_skills": analysis.get("soft_skills", []),
            "confidence": analysis.get("confidence", "medium"),
        })

    @app.route("/jobs/create", methods=["GET", "POST"])
    @app.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
    @login_required
    def job_form(job_id=None):
        existing = owned_job(job_id) if job_id is not None else None
        if request.method == "POST":
            title = request.form.get("job_title", "").strip()
            department = request.form.get("department", "").strip()
            location = request.form.get("location", "").strip()
            employment = request.form.get("employment_type", "Full-time")
            education = request.form.get("education_requirement", "").strip()
            description = request.form.get("job_description", "").strip()
            status = request.form.get("status", "Active")
            raw_experience = request.form.get("required_experience", "").strip()
            try:
                experience = float(raw_experience) if raw_experience else None
                if experience is not None and not 0 <= experience <= 60:
                    raise ValueError
            except ValueError:
                experience = "invalid"
            required = normalize_skill_list(request.form.get("required_skills", ""))
            preferred = normalize_skill_list(request.form.get("preferred_skills", ""))
            suggested = analyze_job_requirements(description)
            if not required:
                required = suggested["required_skills"]
            if not preferred:
                preferred = suggested["preferred_skills"]
            if not education and suggested.get("education_requirements"):
                education = suggested["education_requirements"][0]
            if (raw_experience == "" or raw_experience is None) and suggested.get("minimum_experience") is not None:
                experience = float(suggested["minimum_experience"])
            if not title or not description:
                flash("Job title and full job description are required.", "danger")
            elif experience == "invalid":
                flash("Required experience must be between 0 and 60 years.", "danger")
            elif employment not in EMPLOYMENT_TYPES or status not in {"Active", "Closed"}:
                flash("Choose a valid employment type and job status.", "danger")
            else:
                db = get_db()
                values = (title, department, location, employment, experience, education, description,
                          json.dumps(required), json.dumps(preferred), status)
                if existing:
                    db.execute(
                        """UPDATE jobs SET job_title=?,department=?,location=?,employment_type=?,
                           required_experience=?,education_requirement=?,job_description=?,required_skills=?,
                           preferred_skills=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?""",
                        (*values, job_id, g.user["id"]),
                    )
                    updated_job = {
                        "job_title": title,
                        "department": department,
                        "job_description": description,
                        "required_skills": required,
                        "preferred_skills": preferred,
                        "required_experience": experience,
                        "education_requirement": education,
                    }
                    updated_job["job_text"] = " ".join(
                        [title, department, description, " ".join(required), " ".join(preferred)]
                    )
                    refresh_job_application_scores(db, job_id, updated_job)
                    flash("Job vacancy updated.", "success")
                    target = url_for("job_details", job_id=job_id)
                else:
                    cursor = db.execute(
                        """INSERT INTO jobs(user_id,job_title,department,location,employment_type,
                           required_experience,education_requirement,job_description,required_skills,
                           preferred_skills,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (g.user["id"], *values),
                    )
                    job_id = cursor.lastrowid
                    flash("Job vacancy created. Skills were suggested from the description where fields were left blank.", "success")
                    target = url_for("job_details", job_id=job_id)
                db.commit()
                return redirect(target)
        return render_template("job_form.html", job=existing, employment_types=sorted(EMPLOYMENT_TYPES),
                               skill_catalog=[skill for skills in SKILL_CATEGORIES.values() for skill in skills])

    @app.route("/jobs/<int:job_id>")
    @login_required
    def job_details(job_id):
        job = owned_job(job_id)
        applicants = get_db().execute(
            """SELECT a.id,a.overall_score,a.application_status,a.applied_at,c.candidate_name,c.email,
                      a.matching_skills,a.experience_score
               FROM applications a JOIN candidates c ON c.id=a.candidate_id
               WHERE a.job_id=? ORDER BY a.overall_score DESC,a.applied_at DESC""", (job_id,)
        ).fetchall()
        return render_template("job_details.html", job=job, applicants=applicants)

    @app.route("/jobs/<int:job_id>/delete", methods=["POST"])
    @login_required
    def delete_job(job_id):
        owned_job(job_id)
        db = get_db()
        rows = db.execute(
            """SELECT a.resume_path FROM applications a JOIN jobs j ON j.id=a.job_id
               WHERE j.id=? AND j.user_id=?""", (job_id, g.user["id"])
        ).fetchall()
        db.execute("DELETE FROM jobs WHERE id=? AND user_id=?", (job_id, g.user["id"]))
        db.commit()
        for row in rows:
            safe_delete_upload(row["resume_path"])
        flash("Job and its application records were deleted.", "info")
        return redirect(url_for("jobs"))

    def safe_delete_upload(relative_path):
        root = Path(app.config["UPLOAD_FOLDER"]).resolve()
        target = (root / relative_path).resolve()
        if root in target.parents and target.is_file():
            target.unlink()

    @app.route("/jobs/<int:job_id>/upload", methods=["GET", "POST"])
    @login_required
    def upload_resumes(job_id):
        job = owned_job(job_id)
        if request.method == "POST":
            if job["status"] != "Active":
                flash("Reopen this vacancy before uploading new resumes.", "warning")
                return redirect(url_for("job_details", job_id=job_id))
            files = request.files.getlist("resumes")
            if not files or all(not file.filename for file in files):
                flash("Choose one or more PDF resumes to upload.", "warning")
                return redirect(request.url)
            successes, failures = 0, []
            db = get_db()
            for file in files:
                original_name = secure_filename(file.filename or "")
                if not original_name:
                    failures.append("A selected file has no valid filename.")
                    continue
                if not original_name.lower().endswith(".pdf"):
                    failures.append(f"{original_name}: only PDF files are accepted.")
                    continue
                payload = file.read()
                if len(payload) > app.config["MAX_RESUME_SIZE"]:
                    failures.append(f"{original_name}: exceeds the 5 MB per-file limit.")
                    continue
                if not payload.startswith(b"%PDF-"):
                    failures.append(f"{original_name}: file content is not a valid PDF.")
                    continue
                digest = hashlib.sha256(payload).hexdigest()
                duplicate = db.execute(
                    "SELECT 1 FROM applications WHERE job_id=? AND resume_sha256=?", (job_id, digest)
                ).fetchone()
                if duplicate:
                    failures.append(f"{original_name}: this resume was already uploaded for this vacancy.")
                    continue
                user_dir = Path(str(g.user["id"]))
                stored_name = f"{uuid.uuid4().hex}.pdf"
                destination_dir = Path(app.config["UPLOAD_FOLDER"]) / user_dir
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination = destination_dir / stored_name
                relative_path = str(user_dir / stored_name)
                try:
                    destination.write_bytes(payload)
                    text, document_lines = extract_pdf_document(destination)
                    analysis = parse_resume(text, document_lines)
                    candidate = db.execute(
                        "SELECT id FROM candidates WHERE user_id=? AND email=?",
                        (g.user["id"], analysis["email"]),
                    ).fetchone() if analysis["email"] else None
                    if candidate:
                        candidate_id = candidate["id"]
                    else:
                        cursor = db.execute(
                            """INSERT INTO candidates(user_id,candidate_name,email,phone,linkedin,github)
                               VALUES(?,?,?,?,?,?)""",
                            (g.user["id"], analysis["candidate_name"], analysis["email"], analysis["phone"],
                             analysis["linkedin"], analysis["github"]),
                        )
                        candidate_id = cursor.lastrowid
                    ranking = rank_candidate(text, analysis, job)
                    analysis["preferred_matching_skills"] = ranking["preferred_matching_skills"]
                    cursor = db.execute(
                        """INSERT INTO applications(job_id,candidate_id,resume_path,resume_sha256,
                           extracted_text,analysis_json,overall_score,similarity_score,skill_score,
                           experience_score,education_score,preferred_skill_score,matching_skills,missing_skills)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (job_id, candidate_id, relative_path, digest, text, json.dumps(analysis),
                         ranking["overall_score"], ranking["similarity_score"], ranking["skill_score"],
                         ranking["experience_score"], ranking["education_score"],
                         ranking["preferred_skill_score"], json.dumps(ranking["matching_skills"]),
                         json.dumps(ranking["missing_skills"])),
                    )
                    log_activity(cursor.lastrowid, "Resume uploaded", f"Resume screened for {job['job_title']}.")
                    db.commit()
                    successes += 1
                except ValueError as exc:
                    db.rollback()
                    safe_delete_upload(relative_path)
                    failures.append(f"{original_name}: {exc}")
                except Exception:
                    db.rollback()
                    safe_delete_upload(relative_path)
                    raise
            if successes:
                flash(f"{successes} resume(s) uploaded and screened successfully.", "success")
            for failure in failures:
                flash(failure, "danger")
            return redirect(url_for("job_candidates", job_id=job_id))
        return render_template("upload_resumes.html", job=job)

    def get_candidates(job_id=None):
        params = [g.user["id"]]
        where = "j.user_id=?"
        if job_id is not None:
            where += " AND j.id=?"
            params.append(job_id)
        rows = get_db().execute(
            f"""SELECT a.*,c.candidate_name,c.email,c.phone,j.job_title,j.id AS job_id
                FROM applications a JOIN jobs j ON j.id=a.job_id JOIN candidates c ON c.id=a.candidate_id
                WHERE {where} ORDER BY a.overall_score DESC,a.applied_at DESC""", params
        ).fetchall()
        return rows

    @app.route("/jobs/<int:job_id>/candidates")
    @login_required
    def job_candidates(job_id):
        job = owned_job(job_id)
        candidates = get_candidates(job_id)
        return render_template("candidates.html", candidates=candidates, job=job)

    @app.route("/candidates")
    @login_required
    def candidates():
        return render_template("candidates.html", candidates=get_candidates(), job=None)

    @app.route("/applications/<int:application_id>")
    @login_required
    def application_details(application_id):
        application = owned_application(application_id)
        analysis = json.loads(application["analysis_json"] or "{}")
        ranking = {
            "overall_score": application["overall_score"],
            "similarity_score": application["similarity_score"],
            "skill_score": application["skill_score"],
            "experience_score": application["experience_score"],
            "education_score": application["education_score"],
            "preferred_skill_score": application["preferred_skill_score"],
            "matching_skills": json.loads(application["matching_skills"] or "[]"),
            "missing_skills": json.loads(application["missing_skills"] or "[]"),
            "available_components": [],
            "missing_components": [],
        }
        job = owned_job(application["job_id"])
        notes = get_db().execute(
            "SELECT note,created_at FROM candidate_notes WHERE application_id=? AND user_id=? ORDER BY created_at DESC",
            (application_id, g.user["id"]),
        ).fetchall()
        history = get_db().execute(
            "SELECT action,description,created_at FROM activity_logs WHERE application_id=? AND user_id=? ORDER BY created_at DESC",
            (application_id, g.user["id"]),
        ).fetchall()
        component_values = {
                "similarity": application["similarity_score"],
                "required_skills": application["skill_score"],
                "experience": application["experience_score"],
                "education": application["education_score"],
                "preferred_skills": application["preferred_skill_score"],
            }
        applicable_components = {
            "similarity": True,
            "required_skills": bool(job["required_skills"]),
            "experience": job["required_experience"] is not None,
            "education": bool(job["education_requirement"].strip()),
            "preferred_skills": bool(job["preferred_skills"]),
        }
        ranking["available_components"] = [
            key for key, applicable in applicable_components.items()
            if applicable and component_values[key] is not None
        ]
        ranking["missing_components"] = [
            key for key, applicable in applicable_components.items()
            if applicable and component_values[key] is None
        ]
        return render_template(
            "candidate_details.html", application=application, analysis=analysis, ranking=ranking,
            explanations=explain_analysis(analysis, ranking), notes=notes, history=history,
        )

    @app.route("/applications/<int:application_id>/resume")
    @login_required
    def serve_resume(application_id):
        application = owned_application(application_id)
        root = Path(app.config["UPLOAD_FOLDER"]).resolve()
        path = (root / application["resume_path"]).resolve()
        if root not in path.parents or not path.is_file():
            abort(404)
        return send_file(path, mimetype="application/pdf", as_attachment=True, download_name="candidate-resume.pdf")

    @app.route("/applications/<int:application_id>/status", methods=["POST"])
    @login_required
    def update_status(application_id):
        application = owned_application(application_id)
        status = request.form.get("status", "")
        reason = request.form.get("rejection_reason", "").strip()
        if status not in ALLOWED_STATUSES:
            abort(400)
        if status == "Rejected" and not reason:
            flash("Add a human-selected reason when marking a candidate rejected.", "danger")
            return redirect(url_for("application_details", application_id=application_id))
        db = get_db()
        db.execute(
            "UPDATE applications SET application_status=?,rejection_reason=? WHERE id=?",
            (status, reason if status == "Rejected" else "", application_id),
        )
        log_activity(application_id, f"Status changed to {status}", reason if status == "Rejected" else "")
        db.commit()
        flash("Candidate status updated.", "success")
        return redirect(url_for("application_details", application_id=application_id))

    @app.route("/applications/<int:application_id>/notes", methods=["POST"])
    @login_required
    def add_note(application_id):
        owned_application(application_id)
        note = request.form.get("note", "").strip()
        if not note or len(note) > 5000:
            flash("Notes must contain between 1 and 5,000 characters.", "danger")
        else:
            db = get_db()
            db.execute("INSERT INTO candidate_notes(application_id,user_id,note) VALUES(?,?,?)",
                       (application_id, g.user["id"], note))
            log_activity(application_id, "HR note added", "A recruiter added a private note.")
            db.commit()
            flash("Note added to recruitment history.", "success")
        return redirect(url_for("application_details", application_id=application_id))

    @app.route("/applications/<int:application_id>/delete", methods=["POST"])
    @login_required
    def delete_application(application_id):
        application = owned_application(application_id)
        path = application["resume_path"]
        db = get_db()
        db.execute("DELETE FROM applications WHERE id=?", (application_id,))
        db.commit()
        safe_delete_upload(path)
        flash("Resume and its application analysis were deleted.", "info")
        return redirect(url_for("job_candidates", job_id=application["job_id"]))

    @app.route("/compare", methods=["GET", "POST"])
    @login_required
    def compare():
        if request.method == "POST":
            ids = request.form.getlist("application_ids")
        else:
            ids = request.args.getlist("id")
        try:
            ids = list(dict.fromkeys(int(item) for item in ids))
        except ValueError:
            abort(400)
        if not 2 <= len(ids) <= 5:
            flash("Select between 2 and 5 candidates to compare.", "warning")
            return redirect(request.referrer or url_for("candidates"))
        placeholders = ",".join("?" for _ in ids)
        rows = get_db().execute(
            f"""SELECT a.*,c.candidate_name,c.email,c.phone,j.job_title,j.user_id AS job_owner,
                       c.user_id AS candidate_owner FROM applications a
                JOIN candidates c ON c.id=a.candidate_id JOIN jobs j ON j.id=a.job_id
                WHERE a.id IN ({placeholders})""", ids
        ).fetchall()
        if len(rows) != len(ids) or any(row["job_owner"] != g.user["id"] or row["candidate_owner"] != g.user["id"]
                                        for row in rows):
            abort(404)
        if len({row["job_id"] for row in rows}) != 1:
            flash("Candidates can only be compared within the same vacancy.", "warning")
            return redirect(url_for("candidates"))
        return render_template("compare_candidates.html", candidates=rows)

    @app.route("/analytics")
    @login_required
    def analytics():
        totals, per_job, statuses, activity = analytics_data(g.user["id"])
        return render_template("analytics.html", totals=dict(totals), per_job=per_job,
                               statuses=[dict(row) for row in statuses], activity=activity)

    @app.route("/reports/candidates.csv")
    @login_required
    def export_candidates():
        rows = get_candidates()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Job", "Candidate", "Email", "Overall match (%)", "Text similarity (%)",
                         "Required skill coverage (%)", "Experience score (%)", "Education score (%)",
                         "Status", "Applied at"])
        for row in rows:
            writer.writerow([safe_csv_cell(row["job_title"]), safe_csv_cell(row["candidate_name"]),
                             safe_csv_cell(row["email"] or ""),
                             csv_score(row["overall_score"]), csv_score(row["similarity_score"]),
                             csv_score(row["skill_score"]), csv_score(row["experience_score"]),
                             csv_score(row["education_score"]), row["application_status"],
                             row["applied_at"]])
        response = make_response(output.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = 'attachment; filename="hirerank-candidates.csv"'
        return response

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        if request.method == "POST":
            name = request.form.get("full_name", "").strip()
            company = request.form.get("company_name", "").strip()
            if not name or not company:
                flash("Name and company are required.", "danger")
            else:
                get_db().execute("UPDATE users SET full_name=?,company_name=? WHERE id=?",
                                 (name, company, g.user["id"]))
                get_db().commit()
                flash("Profile updated.", "success")
                return redirect(url_for("profile"))
        return render_template("profile.html", user=g.user)

    @app.errorhandler(413)
    def too_large(_error):
        flash("The selected files exceed the 25 MB total request limit.", "danger")
        return redirect(request.referrer or url_for("jobs"))

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="The requested page or record was not found."), 404

    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("error.html", code=400, message="The request could not be processed."), 400

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
