"""
ExpenseTrack - Smart Student Expense Manager
Application Entry Point & Flask Server Configuration
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, jsonify, render_template, request, session
from flask_cors import CORS
from config import Config
from database.session import bind_app_engine, check_active_db_connection

# Import Blueprints
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.expenses import expenses_bp
from routes.budgets import budgets_bp
from routes.receipts import receipts_bp
from routes.insights import insights_bp
from routes.profile import profile_bp
from routes.auth_helper import get_current_user_id


def create_app(config_override=None, db_engine=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_override:
        app.config.update(config_override)
    if db_engine is not None:
        bind_app_engine(app, db_engine)

    # Enforce strict production safety invariants (blocks dev secrets/debug in production)
    Config.validate_runtime_config(app.config)

    # Restrict CORS to explicit allowed origins (+ local origins in non-production)
    allowed_origins = list(app.config.get("ALLOWED_ORIGINS") or [])
    if str(app.config.get("FLASK_ENV", "development")).lower() != "production":
        port = app.config.get("PORT", Config.PORT)
        for local_origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            if local_origin not in allowed_origins:
                allowed_origins.append(local_origin)

    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

    # Ensure local upload directories exist
    upload_path = Path(app.config["UPLOAD_FOLDER"])
    upload_path.mkdir(parents=True, exist_ok=True)

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(budgets_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(profile_bp)

    # Same-Origin CSRF Guard on State-Changing API Requests
    @app.before_request
    def check_csrf_origin():
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.path.startswith("/api/"):
            port = app.config.get("PORT", Config.PORT)
            allowed_netlocs = {request.host}
            if str(app.config.get("FLASK_ENV", "development")).lower() != "production":
                allowed_netlocs.update({f"127.0.0.1:{port}", f"localhost:{port}"})
            for orig in app.config.get("ALLOWED_ORIGINS") or []:
                parsed_cfg = urlparse(orig)
                if parsed_cfg.netloc:
                    allowed_netlocs.add(parsed_cfg.netloc)

            origin = request.headers.get("Origin")
            if origin is not None:
                parsed = urlparse(origin)
                if not parsed.netloc or parsed.netloc not in allowed_netlocs:
                    return jsonify({"error": "Forbidden", "message": "Cross-origin state-changing request rejected."}), 403
            else:
                referer = request.headers.get("Referer")
                if referer:
                    parsed_ref = urlparse(referer)
                    if not parsed_ref.netloc or parsed_ref.netloc not in allowed_netlocs:
                        return jsonify({"error": "Forbidden", "message": "Cross-origin referer rejected."}), 403

    # Security Headers Middleware
    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    # Global context processor for templates
    @app.context_processor
    def inject_user_context():
        uid = get_current_user_id()
        now = datetime.now()
        return {
            "current_user": {
                "id": uid,
                "username": session.get("username"),
                "full_name": session.get("full_name"),
            } if uid is not None else None,
            "active_path": request.path,
            "current_month": now.month,
            "current_year": now.year,
            "available_years": list(range(now.year - 2, now.year + 2)),
            "is_production": Config.is_production(),
        }

    # Custom Error Handlers
    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Bad Request", "message": "Invalid or malformed request."}), 400
        return render_template("base.html", error_code=400, error_message="Bad Request"), 400

    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Forbidden", "message": "Access denied."}), 403
        return render_template("base.html", error_code=403, error_message="Forbidden"), 403

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not Found", "message": "The requested resource was not found."}), 404
        return render_template("base.html", error_code=404, error_message="Page Not Found"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Method Not Allowed", "message": "HTTP method is not allowed for this endpoint."}), 405
        return render_template("base.html", error_code=405, error_message="Method Not Allowed"), 405

    @app.errorhandler(413)
    def payload_too_large(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Payload Too Large", "message": "Uploaded file exceeds the 5MB size limit."}), 413
        return render_template("base.html", error_code=413, error_message="Payload Too Large"), 413

    @app.errorhandler(500)
    def internal_error(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal Server Error", "message": "An unexpected error occurred."}), 500
        return render_template("base.html", error_code=500, error_message="Internal Server Error"), 500

    return app


app = create_app()

if __name__ == "__main__":
    print("=" * 60)
    print("ExpenseTrack - Smart Student Expense Manager")
    print(f"Environment: {Config.FLASK_ENV} | Database: {Config.DB_NAME}")

    db_ok, db_msg = check_active_db_connection()
    if db_ok:
        print(f"[+] Database Status ({Config.DB_BACKEND}): Connected ({db_msg})")
    else:
        print(f"[!] Database Warning ({Config.DB_BACKEND}): {db_msg}")
        print("    Verify database service is running and schema migrations are applied.")

    print(f"[*] Starting local web server on http://{Config.FLASK_HOST}:{Config.PORT}")
    print("=" * 60)
    app.run(host=Config.FLASK_HOST, port=Config.PORT, debug=Config.DEBUG)
