"""
ExpenseTrack - Financial Insights Routes & API
Returns rule-based analytics, budget progress, burn rate, and student recommendations.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template
from routes.auth_helper import login_required, get_current_user_id
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
    month = int(request.args.get("month", now.month))
    year = int(request.args.get("year", now.year))

    insights = InsightService.get_monthly_insights(user_id, month, year)
    return jsonify(insights)

