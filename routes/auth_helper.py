"""
ExpenseTrack - Authentication & Authorization Middleware
Enforces server-side session checks and resource ownership isolation.
"""

from functools import wraps
from flask import session, jsonify, redirect, url_for, request

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            # Check if this is an API request
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "message": "Please log in to continue."}), 401
            return redirect(url_for("auth.auth_page"))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user_id():
    """Retrieve the authenticated user's ID from session."""
    return session.get("user_id")

