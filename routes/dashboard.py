"""
ExpenseTrack - Dashboard Routes & Analytics API
Provides aggregate metrics, visual chart data (Chart.js), recent transactions, and empty state metadata.
Uses pure Decimal arithmetic internally and stdlib calendar calculations.
"""

from calendar import monthrange
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, jsonify, render_template, request
from repositories.analytics_repo import AnalyticsRepository
from routes.auth_helper import login_required, get_current_user_id
from routes.validators import (
    ZERO_DEC,
    CENT_QUANT,
    TENTH_QUANT,
    HUNDRED_DEC,
    parse_int_param,
    to_decimal,
    date_range_for_month,
    subtract_months,
)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
@login_required
def dashboard_page():
    return render_template("dashboard.html")


@dashboard_bp.route("/api/dashboard/summary", methods=["GET"])
@login_required
def get_dashboard_summary():
    user_id = get_current_user_id()
    now = datetime.now()

    try:
        cur_month = parse_int_param(request.args.get("month"), default=now.month, min_val=1, max_val=12, field_name="Month")
        cur_year = parse_int_param(request.args.get("year"), default=now.year, min_val=2020, max_val=2100, field_name="Year")
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    _, total_days = monthrange(cur_year, cur_month)
    current_day = now.day if (now.year == cur_year and now.month == cur_month) else total_days
    days_remaining = max(1, total_days - current_day)

    cur_start, cur_end = date_range_for_month(cur_year, cur_month)
    prev_year, prev_month = subtract_months(cur_year, cur_month, 1)
    prev_start, prev_end = date_range_for_month(prev_year, prev_month)

    oldest_year, oldest_month = subtract_months(cur_year, cur_month, 5)
    trend_start = f"{oldest_year:04d}-{oldest_month:02d}-01"
    trend_end = cur_end

    # Reuse a single DB connection for all 7 analytical queries
    summary_data = AnalyticsRepository().get_dashboard_summary_data(
        user_id,
        month=cur_month,
        year=cur_year,
        start_date=cur_start,
        end_date=cur_end,
        prev_start=prev_start,
        prev_end=prev_end,
        trend_start=trend_start,
    )
    month_stats = summary_data["month_stats"]
    budget_row = summary_data["budget_row"]
    category_rows = summary_data["category_rows"]
    prev_month_row = summary_data["prev_month_row"]
    trend_rows = summary_data["trend_rows"]
    recent_tx = summary_data["recent_tx"]
    lifetime_row = summary_data["lifetime_row"]

    total_spent_dec = to_decimal(month_stats["total_spent"]) if month_stats else ZERO_DEC
    monthly_tx_count = int(month_stats["tx_count"]) if month_stats else 0
    avg_tx_dec = (
        (total_spent_dec / Decimal(monthly_tx_count)).quantize(CENT_QUANT, rounding=ROUND_HALF_UP)
        if monthly_tx_count > 0
        else ZERO_DEC
    )

    monthly_budget_dec = to_decimal(budget_row["amount"]) if budget_row else ZERO_DEC
    remaining_budget_dec = max(ZERO_DEC, monthly_budget_dec - total_spent_dec) if monthly_budget_dec > ZERO_DEC else ZERO_DEC
    budget_used_pct_dec = (
        (total_spent_dec / monthly_budget_dec * HUNDRED_DEC).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP)
        if monthly_budget_dec > ZERO_DEC
        else Decimal("0.0")
    )
    safe_daily_dec = (
        (remaining_budget_dec / Decimal(days_remaining)).quantize(CENT_QUANT, rounding=ROUND_HALF_UP)
        if monthly_budget_dec > ZERO_DEC
        else ZERO_DEC
    )

    categories_breakdown = []
    highest_category = None
    for r in category_rows:
        cat_amt_dec = to_decimal(r["category_total"])
        cat_share_dec = (
            (cat_amt_dec / total_spent_dec * HUNDRED_DEC).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP)
            if total_spent_dec > ZERO_DEC
            else Decimal("0.0")
        )
        cat_obj = {
            "id": r["id"],
            "name": r["name"],
            "amount": float(cat_amt_dec),
            "share": float(cat_share_dec),
            "color": r["color"],
            "icon": r["icon"],
            "count": int(r["count_tx"]),
        }
        categories_breakdown.append(cat_obj)
        if highest_category is None:
            highest_category = cat_obj

    category_chart = {
        "labels": [r["name"] for r in category_rows],
        "data": [float(to_decimal(r["category_total"])) for r in category_rows],
        "colors": [r["color"] for r in category_rows],
    }

    prev_month_spent_dec = to_decimal(prev_month_row["spent"]) if prev_month_row else ZERO_DEC
    if prev_month_spent_dec > ZERO_DEC:
        mom_change_dec = (
            (total_spent_dec - prev_month_spent_dec) / prev_month_spent_dec * HUNDRED_DEC
        ).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP)
    else:
        mom_change_dec = Decimal("0.0")

    trend_map = {f"{int(r['yr']):04d}-{int(r['mo']):02d}": float(to_decimal(r["spent"])) for r in trend_rows}
    trend_labels = []
    trend_data = []
    for i in range(5, -1, -1):
        ty, tm = subtract_months(cur_year, cur_month, i)
        ym_key = f"{ty:04d}-{tm:02d}"
        trend_labels.append(datetime(ty, tm, 1).strftime("%b %Y"))
        trend_data.append(trend_map.get(ym_key, 0.00))

    formatted_recent = [
        {
            "id": r["id"],
            "amount": float(to_decimal(r["amount"])),
            "merchant": r["merchant"],
            "expense_date": r["expense_date"].strftime("%Y-%m-%d"),
            "payment_method": r["payment_method"],
            "notes": r["notes"] or "",
            "category_name": r["category_name"],
            "category_color": r["category_color"],
            "category_icon": r["category_icon"],
        }
        for r in recent_tx
    ]

    is_empty_state = (lifetime_row["cnt"] == 0) if lifetime_row else True
    selected_dt = datetime(cur_year, cur_month, 1)

    return jsonify({
        "selected_month": cur_month,
        "selected_year": cur_year,
        "current_month_name": selected_dt.strftime("%B %Y"),
        "total_spent": float(total_spent_dec),
        "monthly_budget": float(monthly_budget_dec),
        "remaining_budget": float(remaining_budget_dec),
        "budget_used_percentage": float(budget_used_pct_dec),
        "expense_count": monthly_tx_count,
        "avg_transaction_amount": float(avg_tx_dec),
        "days_remaining": days_remaining,
        "safe_daily_allowance": float(safe_daily_dec),
        "prev_month_spent": float(prev_month_spent_dec),
        "mom_percentage_change": float(mom_change_dec),
        "highest_category": highest_category,
        "categories_breakdown": categories_breakdown,
        "category_chart": category_chart,
        "monthly_trend": {
            "labels": trend_labels,
            "data": trend_data,
        },
        "recent_transactions": formatted_recent,
        "is_empty_state": is_empty_state,
    })
