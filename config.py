"""
ExpenseTrack - Global Application Configuration
Loads settings from environment variables with safe development defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # Flask Settings
    SECRET_KEY = os.getenv("SECRET_KEY", "expensetrack-dev-secret-key-student-finance-2026")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    DEBUG = os.getenv("FLASK_DEBUG", "1") == "1"
    PORT = int(os.getenv("PORT", 5000))

    # MySQL Database Settings
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

    # Session Cookie Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False  # Set True in production with HTTPS
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours in seconds

    @classmethod
    def is_azure_configured(cls) -> bool:
        """Check if Azure Blob Storage is active and credentials are provided."""
        return bool(cls.AZURE_STORAGE_CONNECTION_STRING and cls.AZURE_STORAGE_CONTAINER_NAME)

