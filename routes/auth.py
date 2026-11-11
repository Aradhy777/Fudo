"""
ExpenseTrack - Authentication Routes & Controllers
Handles user registration, login, logout, and profile queries with secure hashing and session management.
"""

import re
from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from repositories.base import DuplicateEmailError, DuplicateUsernameError
from repositories.user_repo import DuplicateAccountConflictError, UserRepository
from routes.auth_helper import login_required, get_current_user_id
from routes.validators import rate_limit, validate_string, get_json_dict

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register")
@auth_bp.route("/login")
@auth_bp.route("/auth")
def auth_page():
    if get_current_user_id() is not None:
        return redirect(url_for("dashboard.dashboard_page"))
    return render_template("auth.html")


@auth_bp.route("/api/auth/register", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=60)
def register():
    try:
        data = get_json_dict()
        username = validate_string(data.get("username"), "Username", min_len=3, max_len=30)
        email = validate_string(data.get("email"), "Email", min_len=5, max_len=100).lower()
        full_name = validate_string(data.get("full_name"), "Full name", min_len=2, max_len=100)
        password = data.get("password")
        if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
            raise ValueError("Password must be between 8 and 128 characters long.")
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    if not re.match(r"^[A-Za-z0-9_]+$", username):
        return jsonify({"error": "Validation Error", "message": "Username can only contain letters, numbers, and underscores."}), 400

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Validation Error", "message": "A valid email address is required."}), 400

    # Hash password securely with Scrypt before acquiring DB connection
    password_hash = generate_password_hash(password, method="scrypt")

    try:
        user_id = UserRepository().register_user(
            username=username,
            email=email,
            password_hash=password_hash,
            full_name=full_name,
        )

        # Prevent session fixation and activate configured expiration lifetime
        session.clear()
        session.permanent = True
        session["user_id"] = user_id
        session["username"] = username
        session["full_name"] = full_name

        return jsonify({
            "message": "Registration successful.",
            "user": {
                "id": user_id,
                "username": username,
                "email": email,
                "full_name": full_name,
            }
        }), 201

    except DuplicateUsernameError:
        return jsonify({"error": "Conflict", "message": "Username is already registered."}), 409
    except DuplicateEmailError:
        return jsonify({"error": "Conflict", "message": "Email is already registered."}), 409
    except DuplicateAccountConflictError:
        return jsonify({"error": "Conflict", "message": "Username or Email is already registered."}), 409
    except Exception as e:
        current_app.logger.error(f"User registration DB failure: {e}")
        return jsonify({"error": "Database Error", "message": "An internal error occurred while creating your account."}), 500


@auth_bp.route("/api/auth/login", methods=["POST"])
@rate_limit(max_requests=15, window_seconds=60)
def login():
    try:
        data = get_json_dict()
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    identifier_raw = data.get("identifier")
    password = data.get("password")

    if not isinstance(identifier_raw, str) or not isinstance(password, str):
        return jsonify({"error": "Validation Error", "message": "Username/Email and Password must be valid text."}), 400

    identifier = identifier_raw.strip()
    if not identifier or not password:
        return jsonify({"error": "Validation Error", "message": "Username/Email and Password are required."}), 400

    user = UserRepository().find_by_identifier(identifier)

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Authentication Failed", "message": "Invalid credentials. Please verify your details."}), 401

    # Rotate/clear previous session and apply expiration window
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["full_name"] = user["full_name"]

    return jsonify({
        "message": "Login successful.",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "full_name": user["full_name"],
        }
    }), 200


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully."}), 200


@auth_bp.route("/api/auth/me", methods=["GET"])
@login_required
def get_current_user():
    user = UserRepository().get_public_profile(get_current_user_id())
    if not user:
        session.clear()
        return jsonify({"error": "Unauthorized", "message": "Session is no longer valid."}), 401
    return jsonify({"user": user}), 200
