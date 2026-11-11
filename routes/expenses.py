"""
ExpenseTrack - Expense Management Routes & API
Supports full CRUD, multi-criteria filtering, search, pagination, and strict user ownership isolation.
"""

from flask import Blueprint, request, jsonify, render_template, current_app, session
from repositories.base import (
    InvalidCategoryError,
    ReceiptNotOwnedError,
    UserAccountNotFoundError,
    EntityNotFoundError,
)
from repositories.category_repo import CategoryRepository
from repositories.expense_repo import ExpenseRepository
from routes.auth_helper import login_required, get_current_user_id
from routes.validators import (
    parse_int_param,
    validate_amount,
    validate_date,
    validate_string,
    get_json_dict,
    to_decimal,
)

expenses_bp = Blueprint("expenses", __name__)

ALLOWED_PAYMENT_METHODS = {"UPI", "Cash", "Credit Card", "Debit Card", "Net Banking", "Other"}


@expenses_bp.route("/expenses")
@login_required
def expenses_page():
    return render_template("expenses.html")


@expenses_bp.route("/api/expenses/categories", methods=["GET"])
@login_required
def get_categories():
    categories = CategoryRepository().list_categories()
    return jsonify({"categories": categories})


@expenses_bp.route("/api/expenses", methods=["GET"])
@login_required
def list_expenses():
    user_id = get_current_user_id()

    try:
        page = parse_int_param(request.args.get("page"), default=1, min_val=1, max_val=10000)
        limit = parse_int_param(request.args.get("limit"), default=20, min_val=1, max_val=100)
        category_id_raw = request.args.get("category_id")
        category_id = parse_int_param(category_id_raw, default=None, min_val=1) if category_id_raw else None

        start_date_raw = request.args.get("start_date", "").strip()
        start_date = validate_date(start_date_raw) if start_date_raw else None

        end_date_raw = request.args.get("end_date", "").strip()
        end_date = validate_date(end_date_raw) if end_date_raw else None
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    merchant = request.args.get("merchant", "").strip()[:100]
    search = request.args.get("search", "").strip()[:100]

    result = ExpenseRepository().list_expenses(
        user_id,
        page=page,
        limit=limit,
        category_id=category_id,
        start_date=start_date,
        end_date=end_date,
        merchant=merchant or None,
        search=search or None,
    )
    total_records = result["total_records"]

    return jsonify({
        "expenses": result["expenses"],
        "pagination": {
            "page": page,
            "limit": limit,
            "total_records": total_records,
            "total_pages": (total_records + limit - 1) // limit if total_records > 0 else 1,
        }
    })


@expenses_bp.route("/api/expenses/<int:expense_id>", methods=["GET"])
@login_required
def get_expense(expense_id: int):
    user_id = get_current_user_id()
    expense = ExpenseRepository().get_expense(expense_id, user_id)
    if not expense:
        return jsonify({"error": "Not Found", "message": "Expense not found or unauthorized."}), 404

    return jsonify({"expense": expense})


@expenses_bp.route("/api/expenses", methods=["POST"])
@login_required
def create_expense():
    user_id = get_current_user_id()

    try:
        data = get_json_dict()
        amount_val = validate_amount(data.get("amount"))
        merchant = validate_string(data.get("merchant"), "Merchant name", min_len=1, max_len=100)
        expense_date = validate_date(data.get("expense_date"))
        notes = validate_string(data.get("notes"), "Notes", min_len=0, max_len=1000, required=False)

        raw_cat = data.get("category_id")
        category_id = parse_int_param(raw_cat, default=None, min_val=1, required=True, field_name="Category ID")
    except ValueError as ve:
        return jsonify({"error": "Validation Error", "message": str(ve)}), 400

    payment_method_raw = data.get("payment_method", "UPI")
    payment_method = payment_method_raw.strip() if isinstance(payment_method_raw, str) else "Other"
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        payment_method = "Other"

    # Category, optional receipt ownership, and insert executed on a single atomic DB connection
    receipt_id = data.get("receipt_id")
    if receipt_id is not None and receipt_id != "":
        try:
            receipt_id = parse_int_param(receipt_id, default=None, min_val=1, field_name="Receipt ID")
        except ValueError:
            return jsonify({"error": "Validation Error", "message": "Invalid receipt ID."}), 400
    else:
        receipt_id = None

    repo = ExpenseRepository()
    try:
        expense_id = repo.create_expense(
            user_id=user_id,
            category_id=category_id,
            amount=amount_val,
            merchant=merchant,
            expense_date=expense_date,
            payment_method=payment_method,
            notes=notes or None,
            receipt_id=receipt_id,
        )
        return jsonify({"message": "Expense recorded successfully.", "expense_id": expense_id}), 201
    except InvalidCategoryError:
        return jsonify({"error": "Validation Error", "message": "Invalid category selected."}), 400
    except ReceiptNotOwnedError:
        return jsonify({"error": "Forbidden", "message": "Receipt not found or unauthorized."}), 403
    except UserAccountNotFoundError:
        session.clear()
        return jsonify({"error": "Unauthorized", "message": "Account session is no longer valid."}), 401
    except Exception as e:
        current_app.logger.error(f"DB error creating expense for user {user_id}: {e}")
        return jsonify({"error": "Database Error", "message": "An error occurred while saving the expense."}), 500


@expenses_bp.route("/api/expenses/<int:expense_id>", methods=["PUT"])
@login_required
def update_expense(expense_id: int):
    user_id = get_current_user_id()
    repo = ExpenseRepository()

    try:
        data = get_json_dict()
        amount_val = validate_amount(data.get("amount"))
        merchant = validate_string(data.get("merchant"), "Merchant name", min_len=1, max_len=100)
        expense_date = validate_date(data.get("expense_date"))
        notes = validate_string(data.get("notes"), "Notes", min_len=0, max_len=1000, required=False)

        raw_cat = data.get("category_id")
        category_id = parse_int_param(raw_cat, default=None, min_val=1, required=True, field_name="Category ID")
    except ValueError as ve:
        # Distinguish malformed JSON vs missing expense if JSON is valid
        err_msg = str(ve)
        if "JSON" not in err_msg:
            if not repo.expense_exists(expense_id, user_id):
                return jsonify({"error": "Not Found", "message": "Expense not found or unauthorized."}), 404
        return jsonify({"error": "Validation Error", "message": err_msg}), 400

    payment_method_raw = data.get("payment_method", "UPI")
    payment_method = payment_method_raw.strip() if isinstance(payment_method_raw, str) else "Other"
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        payment_method = "Other"

    # Atomic check-lock-update eliminates TOCTOU race with concurrent deletes
    try:
        repo.update_expense(
            expense_id=expense_id,
            user_id=user_id,
            category_id=category_id,
            amount=amount_val,
            merchant=merchant,
            expense_date=expense_date,
            payment_method=payment_method,
            notes=notes or None,
        )
        return jsonify({"message": "Expense updated successfully."})
    except EntityNotFoundError:
        return jsonify({"error": "Not Found", "message": "Expense not found or unauthorized."}), 404
    except InvalidCategoryError:
        return jsonify({"error": "Validation Error", "message": "Invalid category selected."}), 400
    except Exception as e:
        current_app.logger.error(f"DB error updating expense {expense_id} for user {user_id}: {e}")
        return jsonify({"error": "Database Error", "message": "An error occurred while updating the expense."}), 500


@expenses_bp.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id: int):
    user_id = get_current_user_id()
    if not ExpenseRepository().delete_expense(expense_id, user_id):
        return jsonify({"error": "Not Found", "message": "Expense not found or unauthorized."}), 404

    return jsonify({"message": "Expense deleted successfully."})
