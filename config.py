import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get("HIRERANK_SECRET_KEY", "change-this-development-key")
    DATABASE = os.environ.get("HIRERANK_DATABASE", str(BASE_DIR / "instance" / "hirerank.sqlite3"))
    UPLOAD_FOLDER = Path(os.environ.get("HIRERANK_UPLOAD_FOLDER", str(BASE_DIR / "instance" / "uploads")))
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    MAX_RESUME_SIZE = 5 * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("HIRERANK_SECURE_COOKIE", "0") == "1"
