"""
ExpenseTrack - Global Application Configuration
Loads settings from environment variables with safe development defaults
and strict production fail-fast guards.
"""

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

_EPHEMERAL_DEV_SECRET = secrets.token_hex(32)
_PLACEHOLDER_SECRETS = {
    "",
    _EPHEMERAL_DEV_SECRET,
    "expensetrack-dev-secret-key-student-finance-2026",
    "change-this-to-a-cryptographically-secure-random-key-in-production",
    "secret",
    "changeme",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # Flask Settings
    FLASK_ENV = os.getenv("FLASK_ENV", "development").strip().lower() or "development"
    IS_PRODUCTION = FLASK_ENV == "production"

    # Never allow Werkzeug debug mode in production regardless of FLASK_DEBUG env var
    DEBUG = False if IS_PRODUCTION else _env_bool("FLASK_DEBUG", True)

    SECRET_KEY = os.getenv("SECRET_KEY", "").strip() or _EPHEMERAL_DEV_SECRET
    FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    PORT = int(os.getenv("PORT", 5000))

    # MySQL Database Settings
    DB_BACKEND = os.getenv("DB_BACKEND", "mariadb").strip().lower()
    DB_AUTH_MODE = os.getenv("DB_AUTH_MODE", "").strip().lower()
    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", 3306))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "expensetrack")

    # Uploads & Storage Settings
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads/receipts")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))  # 5MB
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

    # OCR Settings
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")

    # Azure Cloud Settings (DP-900 / Cloud Storage)
    AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    AZURE_STORAGE_CONTAINER_NAME = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "receipts").strip()

    # Session Cookie & Proxy Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
    PERMANENT_SESSION_LIFETIME = int(os.getenv("PERMANENT_SESSION_LIFETIME", 86400))
    TRUST_PROXY_HEADERS = _env_bool("TRUST_PROXY_HEADERS", False)
    ALLOW_DEMO_SEED = _env_bool("ALLOW_DEMO_SEED", False)

    # Comma-separated explicit origins (optional; local origins added automatically in dev)
    ALLOWED_ORIGINS = [
        o.strip().rstrip("/")
        for o in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    ]

    @classmethod
    def is_production(cls) -> bool:
        return cls.FLASK_ENV == "production"

    @classmethod
    def is_azure_configured(cls) -> bool:
        """Check if Azure Blob Storage is active and credentials are provided."""
        return bool(cls.AZURE_STORAGE_CONNECTION_STRING and cls.AZURE_STORAGE_CONTAINER_NAME)

    @classmethod
    def validate_runtime_config(cls, active_config=None) -> None:
        """
        Prevent insecure development settings from silently running in production.
        Raises RuntimeError on invalid production security configuration.
        """
        cfg = active_config or {}
        env = str(cfg.get("FLASK_ENV", cls.FLASK_ENV)).strip().lower()
        if env != "production":
            return

        secret = str(cfg.get("SECRET_KEY", cls.SECRET_KEY) or "")
        if secret in _PLACEHOLDER_SECRETS or len(secret) < 32:
            raise RuntimeError(
                "Production configuration error: a strong non-default SECRET_KEY (>= 32 chars) must be set."
            )

        if cfg.get("DEBUG", cls.DEBUG):
            raise RuntimeError(
                "Production configuration error: FLASK_DEBUG must be disabled in production."
            )
