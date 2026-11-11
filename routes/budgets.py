"""
ExpenseTrack - Budget Management Routes & API
Supports total monthly budget & category-specific limits with real-time 80% and 100% threshold alerts.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, current_app, session
from repositories.base import InvalidCategoryError, UserAccountNotFoundError
from repositories.budget_repo import BudgetRepository
from routes.auth_helper import login_required, get_current_user_id
from routes.validators import (
    ZERO_DEC,
    TENTH_QUANT,
    HUNDRED_DEC,
    parse_int_param,
    validate_amount,
    to_decimal,
    get_json_dict,
    date_range_for_month,
)

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

    try:
        month = parse_int_param(request.args.get("month"), default=now.month, min_val=1, max_val=12, field_name="Month")
        year = parse_int_param(request.args.get("year"), default=now.year, min_val=2020, max_val=2100, field_name="Year")
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    budget_data = BudgetRepository().get_monthly_budget_data(user_id, month, year)
    overall_budget_row = budget_data["overall_budget"]
    overall_budget_dec = overall_budget_row["amount"] if overall_budget_row else ZERO_DEC
    overall_budget_id = overall_budget_row["id"] if overall_budget_row else None
    total_spent_dec = budget_data["total_spent"]
    category_rows = budget_data["categories"]

    overall_pct_dec = (
        (total_spent_dec / overall_budget_dec * HUNDRED_DEC).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP)
        if overall_budget_dec > ZERO_DEC
        else Decimal("0.0")
    )
    overall_status = "normal"
    if overall_budget_dec > ZERO_DEC:
        if total_spent_dec > overall_budget_dec:
            overall_status = "exceeded"
        elif overall_pct_dec >= Decimal("80.0"):
            overall_status = "warning"

    overall_rem_dec = max(ZERO_DEC, overall_budget_dec - total_spent_dec) if overall_budget_dec > ZERO_DEC else ZERO_DEC

    category_budgets = []
    for row in category_rows:
        limit_dec = to_decimal(row["budget_limit"]) if row["budget_limit"] is not None else None
        spent_dec = to_decimal(row["total_spent"])
        pct_dec = (
            (spent_dec / limit_dec * HUNDRED_DEC).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP)
            if (limit_dec is not None and limit_dec > ZERO_DEC)
            else Decimal("0.0")
        )
        rem_dec = max(ZERO_DEC, limit_dec - spent_dec) if limit_dec is not None else None

        status = "none"
        if limit_dec is not None and limit_dec > ZERO_DEC:
            if spent_dec > limit_dec:
                status = "exceeded"
            elif pct_dec >= Decimal("80.0"):
                status = "warning"
            else:
                status = "normal"

        category_budgets.append({
            "category_id": row["category_id"],
            "category_name": row["name"],
            "icon": row["icon"],
            "color": row["color"],
            "budget_id": row["budget_id"],
            "budget_limit": float(limit_dec) if limit_dec is not None else None,
            "total_spent": float(spent_dec),
            "remaining": float(rem_dec) if rem_dec is not None else None,
            "percentage": float(pct_dec),
            "status": status,
        })

    return jsonify({
        "month": month,
        "year": year,
        "overall": {
            "budget_id": overall_budget_id,
            "budget_limit": float(overall_budget_dec),
            "total_spent": float(total_spent_dec),
            "remaining": float(overall_rem_dec),
            "percentage": float(overall_pct_dec),
            "status": overall_status,
        },
        "categories": category_budgets,
    })


@budgets_bp.route("/api/budgets", methods=["POST"])
@login_required
def set_budget():
    user_id = get_current_user_id()
    repo = BudgetRepository()

    try:
        data = get_json_dict()
        month = parse_int_param(data.get("month"), default=None, min_val=1, max_val=12, required=True, field_name="Month")
        year = parse_int_param(data.get("year"), default=None, min_val=2020, max_val=2100, required=True, field_name="Year")
        amount_val = validate_amount(data.get("amount"))

        raw_cat = data.get("category_id")
        if raw_cat is not None and raw_cat != "":
            category_id = parse_int_param(raw_cat, default=None, min_val=1, field_name="Category ID")
            if not repo.category_exists(category_id):
                raise ValueError("Invalid category selected.")
        else:
            category_id = None
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    # Serialize concurrent budget writes per user across MariaDB and SQL Server
    try:
        budget_id = repo.upsert_budget(
            user_id=user_id,
            category_id=category_id,
            month=month,
            year=year,
            amount=amount_val,
        )
        return jsonify({"message": "Budget configured successfully.", "budget_id": budget_id}), 200
    except UserAccountNotFoundError:
        session.clear()
        return jsonify({"error": "Unauthorized", "message": "Account session is no longer valid."}), 401
    except InvalidCategoryError:
        return jsonify({"error": "Validation Error", "message": "Invalid category selected."}), 400
    except Exception as e:
        current_app.logger.error(f"DB error setting budget for user {user_id}: {e}")
        return jsonify({"error": "Database Error", "message": "An error occurred while saving the budget."}), 500


@budgets_bp.route("/api/budgets/<int:budget_id>", methods=["DELETE"])
@login_required
def delete_budget(budget_id: int):
    user_id = get_current_user_id()
    if not BudgetRepository().delete_budget(budget_id, user_id):
        return jsonify({"error": "Not Found", "message": "Budget not found or unauthorized."}), 404

    return jsonify({"message": "Budget removed successfully."})
