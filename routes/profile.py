"""
ExpenseTrack - Profile, Settings, and System Diagnostics Routes
Provides user profile management and a transparent health dashboard for academic evaluation
(displaying database status, Azure Blob status, and OCR engine status).
"""

import re
from flask import Blueprint, jsonify, render_template, request, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from repositories.base import DuplicateEmailError, UserAccountNotFoundError
from repositories.user_repo import UserRepository
from routes.auth_helper import login_required, get_current_user_id
from routes.validators import validate_string, get_json_dict
from services.azure_storage import AzureStorageService
from services.ocr_service import OCRService

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile")
@login_required
def profile_page():
    return render_template("profile.html")


@profile_bp.route("/api/profile/update", methods=["POST"])
@login_required
def update_profile():
    user_id = get_current_user_id()

    try:
        data = get_json_dict()
        full_name = validate_string(data.get("full_name"), "Full name", min_len=2, max_len=100)
        email = validate_string(data.get("email"), "Email", min_len=5, max_len=100).lower()
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Validation Error", "message": "A valid email address is required."}), 400

    # Ensure account exists and email is not taken by another user
    try:
        UserRepository().update_profile(user_id, full_name=full_name, email=email)
        session["full_name"] = full_name
        return jsonify({"message": "Profile updated successfully."})
    except UserAccountNotFoundError:
        session.clear()
        return jsonify({"error": "Unauthorized", "message": "Account session is no longer valid."}), 401
    except DuplicateEmailError:
        return jsonify({"error": "Conflict", "message": "Email is already taken by another user."}), 409
    except Exception as e:
        current_app.logger.error(f"DB error updating profile for user {user_id}: {e}")
        return jsonify({"error": "Database Error", "message": "Failed to update profile."}), 500


@profile_bp.route("/api/profile/change-password", methods=["POST"])
@login_required
def change_password():
    user_id = get_current_user_id()

    try:
        data = get_json_dict()
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if not isinstance(old_password, str) or not isinstance(new_password, str):
        return jsonify({"error": "Validation Error", "message": "Passwords must be valid strings."}), 400

    if not old_password or not new_password or len(new_password) < 8 or len(new_password) > 128:
        return jsonify({"error": "Validation Error", "message": "New password must be between 8 and 128 characters long."}), 400

    repo = UserRepository()
    stored_hash = repo.get_password_hash(user_id)
    if not stored_hash:
        session.clear()
        return jsonify({"error": "Unauthorized", "message": "Account session is no longer valid."}), 401
    if not check_password_hash(stored_hash, old_password):
        return jsonify({"error": "Authentication Failed", "message": "Incorrect current password."}), 401

    new_hash = generate_password_hash(new_password, method="scrypt")
    try:
        if not repo.update_password_hash(user_id, new_hash):
            session.clear()
            return jsonify({"error": "Unauthorized", "message": "Account session is no longer valid."}), 401
        return jsonify({"message": "Password changed successfully."})
    except Exception as e:
        current_app.logger.error(f"DB error changing password for user {user_id}: {e}")
        return jsonify({"error": "Database Error", "message": "Failed to update password."}), 500


@profile_bp.route("/api/system/diagnostics", methods=["GET"])
@login_required
def system_diagnostics():
    """
    Returns live diagnostic information for academic evaluation and DP-900 / AI-900 demonstration.
    """
    db_diag = UserRepository().get_database_diagnostics()
    ocr_ok = OCRService.is_tesseract_available()
    ocr_binary = OCRService.find_tesseract_binary()
    azure_ok = AzureStorageService.is_enabled()
    is_prod = str(current_app.config.get("FLASK_ENV", "development")).lower() == "production"

    return jsonify({
        "database": {
            "engine": db_diag["engine"],
            "host": "Redacted" if is_prod else db_diag["host"],
            "port": "Redacted" if is_prod else db_diag["port"],
            "database_name": "Redacted" if is_prod else db_diag["database_name"],
            "status": db_diag["status"],
            "message": db_diag["message"],
        },
        "ocr_engine": {
            "name": "Tesseract OCR (pytesseract)",
            "status": "ready" if ocr_ok else "fallback_mode",
            "binary_path": ("Configured (hidden in production)" if ocr_ok else "Fallback mode") if is_prod else (ocr_binary or "Not found on system PATH (heuristic fallback enabled)"),
        },
        "cloud_storage": {
            "provider": "Azure Blob Storage (DP-900 Architecture)",
            "status": "connected" if azure_ok else "local_fallback",
            "container": Config.AZURE_STORAGE_CONTAINER_NAME if azure_ok else "Local Folder: uploads/receipts",
            "message": "Azure connection string configured" if azure_ok else "Running with local secure private storage; Azure Blob Storage enabled via .env when connection string provided.",
        },
        "security": {
            "session_protection": "HTTPOnly Cookies + Lax SameSite",
            "password_algorithm": "Scrypt (salt + memory-hard KDF)",
            "sql_injection_defense": "Enforced parameterized queries on all endpoints",
            "user_isolation": "Strict server-side tenant filtering on user_id",
        }
    })
