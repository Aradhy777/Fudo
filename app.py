"""
ExpenseTrack - Smart Student Expense Manager
Application Entry Point & Flask Server Configuration
"""

import os
from pathlib import Path
from flask import Flask, jsonify, render_template, request, session
from flask_cors import CORS
from config import Config
from database.db import test_connection

# Import Blueprints
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.expenses import expenses_bp
from routes.budgets import budgets_bp
from routes.receipts import receipts_bp
from routes.insights import insights_bp
from routes.profile import profile_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Enable CORS for local API access
    CORS(app)

    # Ensure local upload directories exist
    upload_path = Path(Config.UPLOAD_FOLDER)
    upload_path.mkdir(parents=True, exist_ok=True)

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(budgets_bp)
    app.register_blueprint(receipts_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(profile_bp)

    # Global context processor for templates
    @app.context_processor
    def inject_user_context():
        return {
            "current_user": {
                "id": session.get("user_id"),
                "username": session.get("username"),
                "full_name": session.get("full_name"),
            } if "user_id" in session else None,
            "active_path": request.path,
        }

    # Custom Error Handlers
    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Bad Request", "message": str(e)}), 400
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
    print(f"Target Database: {Config.DB_HOST}:{Config.DB_PORT} / {Config.DB_NAME}")
    
    # Check Database connection
    db_ok, db_msg = test_connection()
    if db_ok:
        print(f"[+] MySQL Database Status: Connected ({db_msg})")
    else:
        print(f"[!] MySQL Database Warning: {db_msg}")
        print("    Run 'python database/init_db.py' after verifying MySQL service is running.")

    print(f"[*] Starting local web server on http://127.0.0.1:{Config.PORT}")
    print("=" * 60)
    app.run(host="127.0.0.1", port=Config.PORT, debug=Config.DEBUG)

