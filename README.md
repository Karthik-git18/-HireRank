# HireRank

HireRank is a locally run recruitment management and resume-screening project. It helps an HR team organize vacancies, extract resume information, compare each application with job-specific criteria, and record human-reviewed recruitment decisions.

> **Decision support only:** matching is textual evidence, not the probability of getting hired. HireRank does not automatically accept or reject candidates. Recruiters must inspect the original resume and make every decision.

## Abstract

Organizations receive resumes in different formats and need a consistent way to review candidates against each vacancy. HireRank combines PDF text extraction, rule-based resume parsing, technical-skill matching, TF-IDF text similarity, and a configurable weighted score. Candidate data is stored in SQLite and isolated to the HR account that uploaded it. Scores and their contributing components are visible so that recruiters can challenge, verify, or disregard them.

## Problem statement and objectives

Manual resume review can be time-consuming and inconsistent. HireRank aims to:

- Manage job vacancies and their specific required and preferred skills.
- Process multiple text-based PDF resumes locally.
- Extract contact, education, skill, project, and explicit experience information without inventing missing facts.
- Rank applications consistently for the role they were submitted to.
- Explain matching and missing criteria and keep recruitment notes/history.
- Provide workspace analytics and CSV export while leaving decisions to people.

## Existing and proposed systems

In a manual process, HR teams may track roles and applicant status in separate documents and compare resumes by hand. HireRank brings vacancy management, resume text extraction, role-specific matching, comparison, status history, and aggregate reporting into one account-scoped application. It is not an applicant tracking or hiring decision replacement.

## Architecture

The Flask server renders HTML templates and handles authenticated form submissions. SQLite stores accounts, vacancies, candidate profiles, applications, notes, and activity. PyMuPDF extracts text from PDFs; the local NLP modules normalize text and identify dictionary skills; Scikit-learn creates TF-IDF vectors and computes cosine similarity. Candidate data and PDF files remain in the local application data directory.

### Folder structure

```text
HireRank/
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── modules/
│   ├── database.py
│   ├── resume_parser.py
│   ├── nlp_engine.py
│   ├── ranking_engine.py
│   ├── candidate_analyzer.py
│   └── analytics.py
├── templates/
├── static/
├── uploads/
├── instance/
└── tests/
```

## Technology stack

- Python 3.11+, Flask, Flask-WTF, Werkzeug sessions and password hashing.
- SQLite through Python's `sqlite3` module, parameterized SQL, foreign keys, and indexes.
- Scikit-learn TF-IDF and cosine similarity.
- NLTK's resource-free `RegexpTokenizer`, regular expressions, stopword filtering, and a custom technical-skill catalog.
- PyMuPDF (fitz) for PDF text extraction.
- HTML5, CSS3, Bootstrap 5, vanilla JavaScript, Font Awesome, and Chart.js.
- Pytest for automated tests.

The frontend framework and chart/icon stylesheets are loaded from public CDNs. Resume parsing and scoring do not call any network service or require any API keys.

## Database schema

- `users`: HR identity and Werkzeug password hash.
- `jobs`: account-owned vacancy and job-specific requirements.
- `candidates`: account-scoped profiles; an email address is unique per account where known.
- `applications`: one resume/application and score set per job and file digest.
- `candidate_notes`: private recruiter notes.
- `activity_logs`: status, upload, and note events.

Foreign keys cascade or detach dependent records as appropriate. Uploaded files are not stored in a public static directory.

## Local NLP and resume extraction

The parser extracts PDF text and applies focused regular expressions for email, phone, URLs, experience durations, and education terms. It reads labeled sections such as Education, Experience, Projects, and Certifications. Skill matching is phrase-aware with word boundaries and a small alias map (for example, `ML` and `Machine Learning`, `JS` and `JavaScript`). A built-in vocabulary avoids arbitrary substring matches. If information is not clearly present, HireRank represents it as unknown/not provided. Scanned/image-only PDFs are reported because OCR is intentionally not included.

Preprocessing lowercases text, normalizes symbols and whitespace, tokenizes with NLTK's local regular-expression tokenizer, removes a small built-in stopword list, and retains technical tokens such as `C++`, `C#`, and `Node.js`. It requires no downloadable NLTK corpora.

## TF-IDF, cosine similarity, and ranking

TF-IDF gives more weight to terms that are informative within the two documents being compared. HireRank fits one `TfidfVectorizer` on the resume and the vacancy text together, then computes cosine similarity between those vectors. The similarity is shown as a percentage; it measures textual alignment and is not a hiring probability.

The default score weights are:

| Component | Weight |
|---|---:|
| Job-description text similarity | 35% |
| Required-skill coverage | 30% |
| Explicit experience match | 20% |
| Education match | 10% |
| Preferred-skill coverage | 5% |

Required skill coverage is the number of detected required skills divided by the number of required skills. Preferred coverage is calculated separately. If a criterion cannot be evaluated, it is omitted and the remaining available weights are proportionally normalized; unknown information is not silently assigned full marks. If a skill list is empty, the corresponding coverage is unknown rather than 100%. The ranking excludes the parsed candidate name, contact details, and lines explicitly labeled with sensitive attributes from the similarity text. Names and other protected traits are not scoring features.

Scores use the same calculation for all candidates within a role and can be inspected component by component. They are intended to support—not determine—human evaluation.

## Features

- Registration, login, password hashing, CSRF-protected forms, and account-scoped routes.
- Job creation, editing, closing/reopening, deletion, and applicants per vacancy.
- Multi-PDF uploads, 5 MB per file, file signature checks, duplicate detection, safe random filenames, and private resume download.
- Local extraction, skill analysis, text similarity, transparent score components, and missing/matching skills.
- Candidate search, score/status/skill/experience filters, sorting, 2–5 candidate comparisons, and human-selected pipeline statuses.
- Recruiter notes and application activity history.
- Database-backed dashboard/analytics charts and CSV export.
- Explicitly labelled synthetic demonstration data.

## Installation and execution (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000), create an HR account, and create a vacancy. The SQLite database is initialized automatically on the first request. The default development secret key must be replaced for deployment:

```bash
export HIRERANK_SECRET_KEY="replace-with-a-long-random-secret"
```

By default, the database and uploaded PDFs are stored under `instance/`. Set `HIRERANK_DATABASE` and `HIRERANK_UPLOAD_FOLDER` to use other local paths. `HIRERANK_SECURE_COOKIE=1` enables secure cookies when serving behind HTTPS.

### Synthetic demo data

After registering, use the account email to add three clearly marked demo vacancies, five synthetic profiles, and synthetic PDFs:

```bash
python seed_demo.py your-account@example.com
```

The script refuses to seed an account that already has these demo vacancies. It does not create a demo password or mix records into another account.

## Testing

```bash
pytest -q
```

Tests create an isolated SQLite database and temporary upload directory. They cover authentication and hashing, job ownership, PDF upload/validation and duplicate detection, parser and ranking behavior, status/history/notes, comparison, and CSV export.

## Limitations and future enhancements

- OCR for image-only resumes is not supported.
- Resume extraction is rule-based and depends on clear section headings and explicit phrasing; results need human verification.
- The skill dictionary is intentionally finite and should be expanded for a specific industry.
- A textual score cannot measure judgment, potential, communication quality, or future performance. It may reflect wording choices and should never be used as an automatic rejection threshold.
- Education matching is a literal text check; equivalency needs human review.
- For a production deployment, add operational hardening such as a managed secret, HTTPS, retention/deletion policy, audit controls, backups, and security testing.
- Future work could add opt-in OCR, configurable vocabularies, richer skill aliases, configurable score weights, retention controls, and accessibility/usability testing—without removing human oversight.
