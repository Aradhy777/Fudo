"""
ExpenseTrack - Authentication Routes & Controllers
Handles user registration, login, logout, and profile queries with secure hashing and session management.
"""

import re
from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import query_db, execute_db
from routes.auth_helper import login_required, get_current_user_id

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register")
@auth_bp.route("/login")
@auth_bp.route("/auth")
def auth_page():
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard_page"))
    return render_template("auth.html")


@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    full_name = data.get("full_name", "").strip()

    # Input validation
    if not username or len(username) < 3 or len(username) > 30:
        return jsonify({"error": "Validation Error", "message": "Username must be between 3 and 30 characters."}), 400

    if not re.match(r"^[A-Za-z0-9_]+$", username):
        return jsonify({"error": "Validation Error", "message": "Username can only contain letters, numbers, and underscores."}), 400

    if not email or not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        return jsonify({"error": "Validation Error", "message": "A valid email address is required."}), 400

    if not password or len(password) < 8:
        return jsonify({"error": "Validation Error", "message": "Password must be at least 8 characters long."}), 400

    if not full_name:
        return jsonify({"error": "Validation Error", "message": "Full name is required."}), 400

    # Check for existing user
    existing = query_db(
        "SELECT id, username, email FROM users WHERE username = %s OR email = %s;",
        (username, email),
        one=True,
    )
    if existing:
        field = "Username" if existing["username"].lower() == username.lower() else "Email"
        return jsonify({"error": "Conflict", "message": f"{field} is already registered."}), 409

    # Hash password securely
    password_hash = generate_password_hash(password, method="scrypt")

    try:
        _, user_id = execute_db(
            """
            INSERT INTO users (username, email, password_hash, full_name)
            VALUES (%s, %s, %s, %s);
            """,
            (username, email, password_hash, full_name),
        )

        # Automatically log in the registered user
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

    except Exception as e:
        return jsonify({"error": "Database Error", "message": f"Failed to register user: {str(e)}"}), 500


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    identifier = data.get("identifier", "").strip()  # Can be username or email
    password = data.get("password", "")

    if not identifier or not password:
        return jsonify({"error": "Validation Error", "message": "Username/Email and Password are required."}), 400

    user = query_db(
        """
        SELECT id, username, email, password_hash, full_name
        FROM users
        WHERE username = %s OR email = %s;
        """,
        (identifier, identifier.lower()),
        one=True,
    )

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Authentication Failed", "message": "Invalid credentials. Please verify your details."}), 401

    # Establish session
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
    user = query_db(
        "SELECT id, username, email, full_name, created_at FROM users WHERE id = %s;",
        (get_current_user_id(),),
        one=True,
    )
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"user": user}), 200

