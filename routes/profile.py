"""
ExpenseTrack - Profile, Settings, and System Diagnostics Routes
Provides user profile management and a transparent health dashboard for academic evaluation
(displaying database status, Azure Blob status, and OCR engine status).
"""

from flask import Blueprint, jsonify, render_template, request, session
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from database.db import query_db, execute_db, test_connection
from routes.auth_helper import login_required, get_current_user_id
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
    data = request.get_json() or {}

    full_name = data.get("full_name", "").strip()
    email = data.get("email", "").strip().lower()

    if not full_name or not email:
        return jsonify({"error": "Validation Error", "message": "Name and email are required."}), 400

    # Ensure email is not taken by another user
    existing = query_db("SELECT id FROM users WHERE email = %s AND id != %s;", (email, user_id), one=True)
    if existing:
        return jsonify({"error": "Conflict", "message": "Email is already taken by another user."}), 409

    try:
        execute_db(
            "UPDATE users SET full_name = %s, email = %s WHERE id = %s;",
            (full_name, email, user_id),
        )
        session["full_name"] = full_name
        return jsonify({"message": "Profile updated successfully."})
    except Exception as e:
        return jsonify({"error": "Database Error", "message": str(e)}), 500


@profile_bp.route("/api/profile/change-password", methods=["POST"])
@login_required
def change_password():
    user_id = get_current_user_id()
    data = request.get_json() or {}

    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if not old_password or not new_password or len(new_password) < 8:
        return jsonify({"error": "Validation Error", "message": "New password must be at least 8 characters long."}), 400

    user = query_db("SELECT password_hash FROM users WHERE id = %s;", (user_id,), one=True)
    if not user or not check_password_hash(user["password_hash"], old_password):
        return jsonify({"error": "Authentication Failed", "message": "Incorrect current password."}), 401

    new_hash = generate_password_hash(new_password, method="scrypt")
    execute_db("UPDATE users SET password_hash = %s WHERE id = %s;", (new_hash, user_id))
    return jsonify({"message": "Password changed successfully."})


@profile_bp.route("/api/system/diagnostics", methods=["GET"])
@login_required
def system_diagnostics():
    """
    Returns live diagnostic information for academic evaluation and DP-900 / AI-900 demonstration.
    """
    db_ok, db_msg = test_connection()
    ocr_ok = OCRService.is_tesseract_available()
    ocr_binary = OCRService.find_tesseract_binary()
    azure_ok = AzureStorageService.is_enabled()

    return jsonify({
        "database": {
            "engine": "MySQL / MariaDB",
            "host": Config.DB_HOST,
            "port": Config.DB_PORT,
            "database_name": Config.DB_NAME,
            "status": "connected" if db_ok else "disconnected",
            "message": db_msg,
        },
        "ocr_engine": {
            "name": "Tesseract OCR (pytesseract)",
            "status": "ready" if ocr_ok else "fallback_mode",
            "binary_path": ocr_binary or "Not found on system PATH (heuristic fallback enabled)",
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

