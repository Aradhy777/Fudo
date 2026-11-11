"""
ExpenseTrack - Financial Insights Routes & API
Returns rule-based analytics, budget progress, burn rate, and student recommendations.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template
from routes.auth_helper import login_required, get_current_user_id
from routes.validators import parse_int_param
from services.insight_service import InsightService

insights_bp = Blueprint("insights", __name__)


@insights_bp.route("/insights")
@login_required
def insights_page():
    return render_template("insights.html")


@insights_bp.route("/api/insights", methods=["GET"])
@login_required
def get_insights():
    user_id = get_current_user_id()
    now = datetime.now()

    try:
        month = parse_int_param(request.args.get("month"), default=now.month, min_val=1, max_val=12)
        year = parse_int_param(request.args.get("year"), default=now.year, min_val=2020, max_val=2100)
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    insights = InsightService.get_monthly_insights(user_id, month, year)
    return jsonify(insights)
