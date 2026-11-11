"""
ExpenseTrack - Expense Management Routes & API
Supports full CRUD, multi-criteria filtering, search, pagination, and strict user ownership isolation.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template
from database.db import query_db, execute_db
from routes.auth_helper import login_required, get_current_user_id

expenses_bp = Blueprint("expenses", __name__)

ALLOWED_PAYMENT_METHODS = {"UPI", "Cash", "Credit Card", "Debit Card", "Net Banking", "Other"}


@expenses_bp.route("/expenses")
@login_required
def expenses_page():
    return render_template("expenses.html")


@expenses_bp.route("/api/expenses/categories", methods=["GET"])
@login_required
def get_categories():
    categories = query_db("SELECT id, name, icon, color FROM categories ORDER BY id ASC;")
    return jsonify({"categories": categories})


@expenses_bp.route("/api/expenses", methods=["GET"])
@login_required
def list_expenses():
    user_id = get_current_user_id()

    # Query filters
    category_id = request.args.get("category_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    merchant = request.args.get("merchant", "").strip()
    search = request.args.get("search", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 20))))
    offset = (page - 1) * limit

    conditions = ["e.user_id = %s"]
    params = [user_id]

    if category_id:
        conditions.append("e.category_id = %s")
        params.append(category_id)

    if start_date:
        conditions.append("e.expense_date >= %s")
        params.append(start_date)

    if end_date:
        conditions.append("e.expense_date <= %s")
        params.append(end_date)

    if merchant:
        conditions.append("e.merchant LIKE %s")
        params.append(f"%{merchant}%")

    if search:
        conditions.append("(e.merchant LIKE %s OR e.notes LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_clause = " AND ".join(conditions)

    # 1. Total count query
    count_sql = f"SELECT COUNT(*) AS total FROM expenses e WHERE {where_clause};"
    total_row = query_db(count_sql, params, one=True)
    total_records = total_row["total"] if total_row else 0

    # 2. Fetch page records
    data_sql = f"""
        SELECT e.id, e.amount, e.merchant, e.expense_date, e.payment_method, e.notes,
               e.receipt_id, e.created_at,
               c.id AS category_id, c.name AS category_name, c.color AS category_color, c.icon AS category_icon,
               r.file_name AS receipt_file_name, r.azure_blob_url
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        LEFT JOIN uploaded_receipts r ON e.receipt_id = r.id
        WHERE {where_clause}
        ORDER BY e.expense_date DESC, e.id DESC
        LIMIT %s OFFSET %s;
    """
    records = query_db(data_sql, params + [limit, offset])

    # Convert Decimal amounts to float and format date for JSON
    formatted = []
    for r in records:
        formatted.append({
            "id": r["id"],
            "amount": float(r["amount"]),
            "merchant": r["merchant"],
            "expense_date": r["expense_date"].strftime("%Y-%m-%d") if r["expense_date"] else None,
            "payment_method": r["payment_method"],
            "notes": r["notes"] or "",
            "receipt_id": r["receipt_id"],
            "category": {
                "id": r["category_id"],
                "name": r["category_name"],
                "color": r["category_color"],
                "icon": r["category_icon"],
            },
            "receipt": {
                "file_name": r["receipt_file_name"],
                "azure_blob_url": r["azure_blob_url"],
            } if r["receipt_id"] else None,
            "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else None,
        })

    return jsonify({
        "expenses": formatted,
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
    sql = """
        SELECT e.id, e.amount, e.merchant, e.expense_date, e.payment_method, e.notes,
               e.receipt_id, e.category_id,
               c.name AS category_name, c.color AS category_color, c.icon AS category_icon
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.id = %s AND e.user_id = %s;
    """
    expense = query_db(sql, (expense_id, user_id), one=True)
    if not expense:
        return jsonify({"error": "Not Found", "message": "Expense not found or unauthorized."}), 404

    return jsonify({
        "expense": {
            "id": expense["id"],
            "amount": float(expense["amount"]),
            "merchant": expense["merchant"],
            "expense_date": expense["expense_date"].strftime("%Y-%m-%d"),
            "payment_method": expense["payment_method"],
            "notes": expense["notes"] or "",
            "category_id": expense["category_id"],
            "category_name": expense["category_name"],
            "receipt_id": expense["receipt_id"],
        }
    })


@expenses_bp.route("/api/expenses", methods=["POST"])
@login_required
def create_expense():
    user_id = get_current_user_id()
    data = request.get_json() or {}

    amount = data.get("amount")
    merchant = data.get("merchant", "").strip()
    category_id = data.get("category_id")
    expense_date = data.get("expense_date", "").strip()
    payment_method = data.get("payment_method", "UPI").strip()
    notes = data.get("notes", "").strip()
    receipt_id = data.get("receipt_id")

    # Validation
    try:
        amount_val = float(amount)
        if amount_val <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"error": "Validation Error", "message": "A valid positive monetary amount is required."}), 400

    if not merchant:
        return jsonify({"error": "Validation Error", "message": "Merchant name is required."}), 400

    if not category_id:
        return jsonify({"error": "Validation Error", "message": "Category selection is required."}), 400

    try:
        datetime.strptime(expense_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return jsonify({"error": "Validation Error", "message": "Date must be in valid YYYY-MM-DD format."}), 400

    if payment_method not in ALLOWED_PAYMENT_METHODS:
        payment_method = "Other"

    # Category validation
    category = query_db("SELECT id FROM categories WHERE id = %s;", (category_id,), one=True)
    if not category:
        return jsonify({"error": "Validation Error", "message": "Invalid category selected."}), 400

    # Receipt validation (if attached, must belong to the user)
    if receipt_id:
        rcpt = query_db("SELECT id FROM uploaded_receipts WHERE id = %s AND user_id = %s;", (receipt_id, user_id), one=True)
        if not rcpt:
            receipt_id = None

    try:
        _, expense_id = execute_db(
            """
            INSERT INTO expenses (user_id, category_id, amount, merchant, expense_date, payment_method, notes, receipt_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (user_id, category_id, round(amount_val, 2), merchant, expense_date, payment_method, notes or None, receipt_id),
        )
        return jsonify({"message": "Expense recorded successfully.", "expense_id": expense_id}), 201
    except Exception as e:
        return jsonify({"error": "Database Error", "message": f"Failed to record expense: {str(e)}"}), 500


@expenses_bp.route("/api/expenses/<int:expense_id>", methods=["PUT"])
@login_required
def update_expense(expense_id: int):
    user_id = get_current_user_id()
    data = request.get_json() or {}

    # Check ownership
    existing = query_db("SELECT id FROM expenses WHERE id = %s AND user_id = %s;", (expense_id, user_id), one=True)
    if not existing:
        return jsonify({"error": "Not Found", "message": "Expense not found or unauthorized."}), 404

    amount = data.get("amount")
    merchant = data.get("merchant", "").strip()
    category_id = data.get("category_id")
    expense_date = data.get("expense_date", "").strip()
    payment_method = data.get("payment_method", "UPI").strip()
    notes = data.get("notes", "").strip()

    try:
        amount_val = float(amount)
        if amount_val <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"error": "Validation Error", "message": "A valid positive monetary amount is required."}), 400

    if not merchant:
        return jsonify({"error": "Validation Error", "message": "Merchant name is required."}), 400

    try:
        datetime.strptime(expense_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return jsonify({"error": "Validation Error", "message": "Date must be in valid YYYY-MM-DD format."}), 400

    if payment_method not in ALLOWED_PAYMENT_METHODS:
        payment_method = "Other"

    try:
        execute_db(
            """
            UPDATE expenses
            SET category_id = %s, amount = %s, merchant = %s, expense_date = %s,
                payment_method = %s, notes = %s
            WHERE id = %s AND user_id = %s;
            """,
            (category_id, round(amount_val, 2), merchant, expense_date, payment_method, notes or None, expense_id, user_id),
        )
        return jsonify({"message": "Expense updated successfully."})
    except Exception as e:
        return jsonify({"error": "Database Error", "message": f"Failed to update expense: {str(e)}"}), 500


@expenses_bp.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id: int):
    user_id = get_current_user_id()
    rowcount, _ = execute_db("DELETE FROM expenses WHERE id = %s AND user_id = %s;", (expense_id, user_id))
    if rowcount == 0:
        return jsonify({"error": "Not Found", "message": "Expense not found or unauthorized."}), 404

    return jsonify({"message": "Expense deleted successfully."})

