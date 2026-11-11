"""
ExpenseTrack - Authentication & Authorization Middleware
Enforces server-side session checks, type safety, and resource ownership isolation.
"""

from functools import wraps
from flask import session, jsonify, redirect, url_for, request


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        uid = session.get("user_id")
        # Guard against missing or manipulated non-integer session values
        if not isinstance(uid, int) or isinstance(uid, bool) or uid < 1:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "message": "Please log in to continue."}), 401
            return redirect(url_for("auth.auth_page"))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user_id():
    """Retrieve the authenticated user's ID from session."""
    uid = session.get("user_id")
    if isinstance(uid, int) and not isinstance(uid, bool) and uid >= 1:
        return uid
    return None
