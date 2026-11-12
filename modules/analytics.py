from modules.database import get_db


def dashboard_data(user_id):
    db = get_db()
    totals = db.execute(
        """SELECT
             (SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='Active') AS active_jobs,
             (SELECT COUNT(DISTINCT c.id) FROM candidates c JOIN applications a ON a.candidate_id=c.id
              JOIN jobs j ON j.id=a.job_id WHERE j.user_id=?) AS candidates,
             (SELECT COUNT(*) FROM applications a JOIN jobs j ON j.id=a.job_id
              WHERE j.user_id=?) AS processed,
             (SELECT COUNT(*) FROM applications a JOIN jobs j ON j.id=a.job_id
              WHERE j.user_id=? AND a.application_status='Shortlisted') AS shortlisted""",
        (user_id, user_id, user_id, user_id),
    ).fetchone()
    jobs = db.execute(
        """SELECT j.id,j.job_title,j.department,j.status,j.created_at,COUNT(a.id) AS applicants,
                  ROUND(AVG(a.overall_score),1) AS average_score
           FROM jobs j LEFT JOIN applications a ON a.job_id=j.id
           WHERE j.user_id=? GROUP BY j.id ORDER BY j.created_at DESC LIMIT 5""", (user_id,)
    ).fetchall()
    recent = db.execute(
        """SELECT a.id,c.candidate_name,j.job_title,a.application_status,a.overall_score,a.applied_at
           FROM applications a JOIN jobs j ON j.id=a.job_id JOIN candidates c ON c.id=a.candidate_id
           WHERE j.user_id=? ORDER BY a.applied_at DESC LIMIT 6""", (user_id,)
    ).fetchall()
    status_rows = db.execute(
        """SELECT a.application_status,COUNT(*) AS total FROM applications a JOIN jobs j ON j.id=a.job_id
           WHERE j.user_id=? GROUP BY a.application_status""", (user_id,)
    ).fetchall()
    activity_rows = db.execute(
        """SELECT substr(a.applied_at,1,10) AS day,COUNT(*) AS total FROM applications a
           JOIN jobs j ON j.id=a.job_id WHERE j.user_id=? GROUP BY day ORDER BY day DESC LIMIT 14""",
        (user_id,),
    ).fetchall()
    return {
        "totals": dict(totals),
        "jobs": jobs,
        "recent": recent,
        "statuses": {row["application_status"]: row["total"] for row in status_rows},
        "activity": list(reversed([dict(row) for row in activity_rows])),
    }


def analytics_data(user_id):
    db = get_db()
    totals = db.execute(
        """SELECT COUNT(DISTINCT j.id) jobs,COUNT(a.id) resumes,
           SUM(CASE WHEN a.application_status='Shortlisted' THEN 1 ELSE 0 END) shortlisted,
           SUM(CASE WHEN a.application_status='Under Review' THEN 1 ELSE 0 END) under_review,
           SUM(CASE WHEN a.application_status='Rejected' THEN 1 ELSE 0 END) rejected
           FROM jobs j LEFT JOIN applications a ON a.job_id=j.id WHERE j.user_id=?""", (user_id,)
    ).fetchone()
    per_job = db.execute(
        """SELECT j.job_title,COUNT(a.id) candidates,ROUND(AVG(a.overall_score),1) average_score
           FROM jobs j LEFT JOIN applications a ON a.job_id=j.id WHERE j.user_id=?
           GROUP BY j.id ORDER BY candidates DESC,j.created_at DESC""", (user_id,)
    ).fetchall()
    statuses = db.execute(
        """SELECT a.application_status,COUNT(*) total FROM applications a JOIN jobs j ON j.id=a.job_id
           WHERE j.user_id=? GROUP BY a.application_status""", (user_id,)
    ).fetchall()
    activity = db.execute(
        """SELECT substr(a.applied_at,1,10) day,COUNT(*) total FROM applications a JOIN jobs j ON j.id=a.job_id
           WHERE j.user_id=? GROUP BY day ORDER BY day DESC LIMIT 30""", (user_id,)
    ).fetchall()
    return dict(totals), per_job, statuses, list(reversed([dict(row) for row in activity]))
