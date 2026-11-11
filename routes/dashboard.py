"""
ExpenseTrack - Dashboard Routes & Analytics API
Provides aggregate metrics, visual chart data (Chart.js), recent transactions, and empty state metadata.
"""

from calendar import monthrange
from datetime import datetime
from dateutil.relativedelta import relativedelta
from flask import Blueprint, jsonify, render_template, request
from database.db import query_db
from routes.auth_helper import login_required, get_current_user_id

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

    # Allow custom month/year or default to current
    cur_month = int(request.args.get("month", now.month))
    cur_year = int(request.args.get("year", now.year))

    # Calculate days in month and remaining
    _, total_days = monthrange(cur_year, cur_month)
    current_day = now.day if (now.year == cur_year and now.month == cur_month) else total_days
    days_remaining = max(1, total_days - current_day)

    # 1. Total spending & count for selected month
    month_stats = query_db(
        """
        SELECT COALESCE(SUM(amount), 0.00) AS total_spent,
               COUNT(id) AS tx_count
        FROM expenses
        WHERE user_id = %s
          AND MONTH(expense_date) = %s
          AND YEAR(expense_date) = %s;
        """,
        (user_id, cur_month, cur_year),
        one=True,
    )
    total_spent = float(month_stats["total_spent"])
    monthly_tx_count = int(month_stats["tx_count"])
    avg_tx = round(total_spent / monthly_tx_count, 2) if monthly_tx_count > 0 else 0.00

    # 2. Monthly Budget
    budget_row = query_db(
        """
        SELECT amount
        FROM budgets
        WHERE user_id = %s
          AND category_id IS NULL
          AND month = %s
          AND year = %s;
        """,
        (user_id, cur_month, cur_year),
        one=True,
    )
    monthly_budget = float(budget_row["amount"]) if budget_row else 0.00
    remaining_budget = max(0.00, monthly_budget - total_spent) if monthly_budget > 0 else 0.00
    budget_used_pct = round((total_spent / monthly_budget * 100), 1) if monthly_budget > 0 else 0.0
    safe_daily_allowance = round(remaining_budget / days_remaining, 2) if monthly_budget > 0 else 0.00

    # 3. Category Breakdown (for Doughnut Chart & Detail List)
    category_rows = query_db(
        """
        SELECT c.id, c.name, c.color, c.icon,
               COALESCE(SUM(e.amount), 0.00) AS category_total,
               COUNT(e.id) AS count_tx
        FROM categories c
        JOIN expenses e
          ON c.id = e.category_id
         AND e.user_id = %s
         AND MONTH(e.expense_date) = %s
         AND YEAR(e.expense_date) = %s
        GROUP BY c.id, c.name, c.color, c.icon
        HAVING category_total > 0
        ORDER BY category_total DESC;
        """,
        (user_id, cur_month, cur_year),
    )
    
    categories_breakdown = []
    highest_category = None
    for r in category_rows:
        cat_amount = float(r["category_total"])
        cat_share = round((cat_amount / total_spent * 100), 1) if total_spent > 0 else 0.0
        cat_obj = {
            "id": r["id"],
            "name": r["name"],
            "amount": cat_amount,
            "share": cat_share,
            "color": r["color"],
            "icon": r["icon"],
            "count": int(r["count_tx"]),
        }
        categories_breakdown.append(cat_obj)
        if highest_category is None:
            highest_category = cat_obj

    category_chart = {
        "labels": [r["name"] for r in category_rows],
        "data": [float(r["category_total"]) for r in category_rows],
        "colors": [r["color"] for r in category_rows],
    }

    # 4. Previous Month Comparison
    prev_date = datetime(cur_year, cur_month, 1) - relativedelta(months=1)
    prev_month_row = query_db(
        """
        SELECT COALESCE(SUM(amount), 0.00) AS spent
        FROM expenses
        WHERE user_id = %s
          AND MONTH(expense_date) = %s
          AND YEAR(expense_date) = %s;
        """,
        (user_id, prev_date.month, prev_date.year),
        one=True,
    )
    prev_month_spent = float(prev_month_row["spent"])
    if prev_month_spent > 0:
        mom_change = round(((total_spent - prev_month_spent) / prev_month_spent * 100), 1)
    else:
        mom_change = 0.0

    # 5. Monthly Trend (Past 6 months for Line/Bar Chart)
    trend_labels = []
    trend_data = []
    base_date = datetime(cur_year, cur_month, 1)
    for i in range(5, -1, -1):
        target_date = base_date - relativedelta(months=i)
        t_month = target_date.month
        t_year = target_date.year
        label_str = target_date.strftime("%b %Y")
        trend_labels.append(label_str)

        spent_row = query_db(
            """
            SELECT COALESCE(SUM(amount), 0.00) AS spent
            FROM expenses
            WHERE user_id = %s
              AND MONTH(expense_date) = %s
              AND YEAR(expense_date) = %s;
            """,
            (user_id, t_month, t_year),
            one=True,
        )
        trend_data.append(float(spent_row["spent"]))

    # 6. Recent 5 Transactions for this month (or latest)
    recent_tx = query_db(
        """
        SELECT e.id, e.amount, e.merchant, e.expense_date, e.payment_method, e.notes,
               c.name AS category_name, c.color AS category_color, c.icon AS category_icon
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.user_id = %s
        ORDER BY e.expense_date DESC, e.id DESC
        LIMIT 6;
        """,
        (user_id,),
    )
    formatted_recent = []
    for r in recent_tx:
        formatted_recent.append({
            "id": r["id"],
            "amount": float(r["amount"]),
            "merchant": r["merchant"],
            "expense_date": r["expense_date"].strftime("%Y-%m-%d"),
            "payment_method": r["payment_method"],
            "notes": r["notes"] or "",
            "category_name": r["category_name"],
            "category_color": r["category_color"],
            "category_icon": r["category_icon"],
        })

    # Total lifetime expenses for empty state detection
    lifetime_row = query_db("SELECT COUNT(id) AS cnt FROM expenses WHERE user_id = %s;", (user_id,), one=True)
    is_empty_state = (lifetime_row["cnt"] == 0)

    selected_dt = datetime(cur_year, cur_month, 1)
    return jsonify({
        "selected_month": cur_month,
        "selected_year": cur_year,
        "current_month_name": selected_dt.strftime("%B %Y"),
        "total_spent": total_spent,
        "monthly_budget": monthly_budget,
        "remaining_budget": remaining_budget,
        "budget_used_percentage": budget_used_pct,
        "expense_count": monthly_tx_count,
        "avg_transaction_amount": avg_tx,
        "days_remaining": days_remaining,
        "safe_daily_allowance": safe_daily_allowance,
        "prev_month_spent": prev_month_spent,
        "mom_percentage_change": mom_change,
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
