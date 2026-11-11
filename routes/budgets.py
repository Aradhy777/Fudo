"""
ExpenseTrack - Budget Management Routes & API
Supports total monthly budget & category-specific limits with real-time 80% and 100% threshold alerts.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template
from database.db import query_db, execute_db
from routes.auth_helper import login_required, get_current_user_id

budgets_bp = Blueprint("budgets", __name__)


@budgets_bp.route("/budgets")
@login_required
def budgets_page():
    return render_template("budgets.html")


@budgets_bp.route("/api/budgets", methods=["GET"])
@login_required
def get_budgets():
    user_id = get_current_user_id()
    now = datetime.now()
    month = int(request.args.get("month", now.month))
    year = int(request.args.get("year", now.year))

    # 1. Total Monthly Overall Budget
    overall_budget_row = query_db(
        """
        SELECT id, amount, created_at, updated_at
        FROM budgets
        WHERE user_id = %s AND category_id IS NULL AND month = %s AND year = %s;
        """,
        (user_id, month, year),
        one=True,
    )
    overall_budget = float(overall_budget_row["amount"]) if overall_budget_row else 0.00
    overall_budget_id = overall_budget_row["id"] if overall_budget_row else None

    # Total actual expenses for this month
    total_spent_row = query_db(
        """
        SELECT COALESCE(SUM(amount), 0.00) AS total_spent
        FROM expenses
        WHERE user_id = %s AND MONTH(expense_date) = %s AND YEAR(expense_date) = %s;
        """,
        (user_id, month, year),
        one=True,
    )
    total_spent = float(total_spent_row["total_spent"])

    overall_pct = (total_spent / overall_budget * 100) if overall_budget > 0 else 0
    overall_status = "normal"
    if overall_budget > 0:
        if total_spent > overall_budget:
            overall_status = "exceeded"
        elif overall_pct >= 80.0:
            overall_status = "warning"

    # 2. Category-Specific Budgets
    category_rows = query_db(
        """
        SELECT c.id AS category_id, c.name, c.icon, c.color,
               b.id AS budget_id,
               b.amount AS budget_limit,
               COALESCE(e.total_spent, 0.00) AS total_spent
        FROM categories c
        LEFT JOIN budgets b
               ON c.id = b.category_id
              AND b.user_id = %s
              AND b.month = %s
              AND b.year = %s
        LEFT JOIN (
            SELECT category_id, SUM(amount) AS total_spent
            FROM expenses
            WHERE user_id = %s
              AND MONTH(expense_date) = %s
              AND YEAR(expense_date) = %s
            GROUP BY category_id
        ) e ON c.id = e.category_id
        ORDER BY c.id ASC;
        """,
        (user_id, month, year, user_id, month, year),
    )

    category_budgets = []
    for row in category_rows:
        limit = float(row["budget_limit"]) if row["budget_limit"] is not None else None
        spent = float(row["total_spent"])
        pct = (spent / limit * 100) if limit and limit > 0 else 0
        rem = max(0.00, limit - spent) if limit is not None else None

        status = "none"
        if limit is not None and limit > 0:
            if spent > limit:
                status = "exceeded"
            elif pct >= 80.0:
                status = "warning"
            else:
                status = "normal"

        category_budgets.append({
            "category_id": row["category_id"],
            "category_name": row["name"],
            "icon": row["icon"],
            "color": row["color"],
            "budget_id": row["budget_id"],
            "budget_limit": limit,
            "total_spent": spent,
            "remaining": rem,
            "percentage": round(pct, 1),
            "status": status,
        })

    return jsonify({
        "month": month,
        "year": year,
        "overall": {
            "budget_id": overall_budget_id,
            "budget_limit": overall_budget,
            "total_spent": total_spent,
            "remaining": max(0.00, overall_budget - total_spent) if overall_budget > 0 else 0.00,
            "percentage": round(overall_pct, 1),
            "status": overall_status,
        },
        "categories": category_budgets,
    })


@budgets_bp.route("/api/budgets", methods=["POST"])
@login_required
def set_budget():
    user_id = get_current_user_id()
    data = request.get_json() or {}

    category_id = data.get("category_id")  # None or int
    month = data.get("month")
    year = data.get("year")
    amount = data.get("amount")

    # Validation
    try:
        month = int(month)
        year = int(year)
        if not (1 <= month <= 12) or year < 2020:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"error": "Validation Error", "message": "Invalid month or year."}), 400

    try:
        amount_val = float(amount)
        if amount_val <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"error": "Validation Error", "message": "Budget amount must be a positive number."}), 400

    if category_id:
        # Validate category exists
        cat = query_db("SELECT id FROM categories WHERE id = %s;", (category_id,), one=True)
        if not cat:
            return jsonify({"error": "Validation Error", "message": "Invalid category."}), 400

    try:
        # Check if record already exists
        if category_id is None:
            existing = query_db(
                "SELECT id FROM budgets WHERE user_id = %s AND category_id IS NULL AND month = %s AND year = %s;",
                (user_id, month, year),
                one=True,
            )
        else:
            existing = query_db(
                "SELECT id FROM budgets WHERE user_id = %s AND category_id = %s AND month = %s AND year = %s;",
                (user_id, category_id, month, year),
                one=True,
            )

        if existing:
            execute_db(
                "UPDATE budgets SET amount = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                (round(amount_val, 2), existing["id"]),
            )
            budget_id = existing["id"]
        else:
            _, budget_id = execute_db(
                """
                INSERT INTO budgets (user_id, category_id, month, year, amount)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (user_id, category_id, month, year, round(amount_val, 2)),
            )

        return jsonify({"message": "Budget configured successfully.", "budget_id": budget_id}), 200

    except Exception as e:
        return jsonify({"error": "Database Error", "message": f"Failed to save budget: {str(e)}"}), 500


@budgets_bp.route("/api/budgets/<int:budget_id>", methods=["DELETE"])
@login_required
def delete_budget(budget_id: int):
    user_id = get_current_user_id()
    rowcount, _ = execute_db("DELETE FROM budgets WHERE id = %s AND user_id = %s;", (budget_id, user_id))
    if rowcount == 0:
        return jsonify({"error": "Not Found", "message": "Budget not found or unauthorized."}), 404

    return jsonify({"message": "Budget removed successfully."})

