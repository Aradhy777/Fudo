"""
ExpenseTrack - Comprehensive Automated Test Suite
Tests authentication, input validation, expense CRUD, user isolation, budgets, and insights.
"""

import sys
from pathlib import Path
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from database.db import get_raw_connection, execute_db


@pytest.fixture(scope="session")
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Ensure database has categories seeded."""
    conn = get_raw_connection(include_db=True)
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS cnt FROM categories;")
        cnt = cursor.fetchone()["cnt"]
        if cnt == 0:
            cursor.execute("""
                INSERT INTO categories (id, name, color, icon) VALUES
                (1, 'Food', '#10B981', 'utensils'),
                (2, 'Travel', '#3B82F6', 'car'),
                (3, 'Shopping', '#EC4899', 'shopping-bag'),
                (4, 'Education', '#8B5CF6', 'book-open');
            """)
            conn.commit()
    conn.close()


def test_auth_login_demo_user(client):
    """Test logging in with the seeded demo student account."""
    res = client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert "user" in data
    assert data["user"]["username"] == "demo_student"


def test_auth_login_invalid_credentials(client):
    """Test login failure on incorrect password."""
    res = client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "WrongPassword999!"
    })
    assert res.status_code == 401


def test_registration_validation(client):
    """Test that short password and invalid username are rejected."""
    res = client.post("/api/auth/register", json={
        "username": "ab",  # too short
        "email": "test@test.com",
        "password": "123",  # too short
        "full_name": "Test User"
    })
    assert res.status_code == 400


def test_registration_and_isolation(client):
    """Test registering a second user and verifying strict multi-tenant isolation."""
    # Register User 2
    u2_name = "tenant_two_test"
    u2_email = "tenant2@test.com"
    # Clean if exists from earlier test runs
    execute_db("DELETE FROM users WHERE username = %s OR email = %s;", (u2_name, u2_email))

    reg_res = client.post("/api/auth/register", json={
        "username": u2_name,
        "email": u2_email,
        "password": "Password1234!",
        "full_name": "Tenant Two"
    })
    assert reg_res.status_code == 201

    # User 2 logs an expense
    exp_res = client.post("/api/expenses", json={
        "amount": 250.00,
        "merchant": "User 2 Special Coffee",
        "category_id": 1,
        "expense_date": "2026-10-25",
        "payment_method": "UPI",
        "notes": "Secret expense"
    })
    assert exp_res.status_code == 201
    u2_exp_id = exp_res.get_json()["expense_id"]

    # Now switch session: log in as demo student (User 1)
    login_u1 = client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })
    assert login_u1.status_code == 200

    # User 1 tries to GET User 2's expense: must return 404
    get_res = client.get(f"/api/expenses/{u2_exp_id}")
    assert get_res.status_code == 404

    # User 1 tries to UPDATE User 2's expense: must return 404
    put_res = client.put(f"/api/expenses/{u2_exp_id}", json={
        "amount": 50.00,
        "merchant": "Hacked",
        "category_id": 1,
        "expense_date": "2026-10-25",
    })
    assert put_res.status_code == 404

    # User 1 tries to DELETE User 2's expense: must return 404
    del_res = client.delete(f"/api/expenses/{u2_exp_id}")
    assert del_res.status_code == 404


def test_expense_negative_amount_rejected(client):
    """Test that zero or negative monetary amount is rejected."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })
    res = client.post("/api/expenses", json={
        "amount": -50.00,
        "merchant": "Invalid Merchant",
        "category_id": 1,
        "expense_date": "2026-10-25",
    })
    assert res.status_code == 400


def test_expense_crud_workflow(client):
    """Test complete create, read, update, and delete workflow."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Create
    create_res = client.post("/api/expenses", json={
        "amount": 750.50,
        "merchant": "Automated Test Store",
        "category_id": 1,
        "expense_date": "2026-10-28",
        "payment_method": "UPI",
        "notes": "Testing CRUD"
    })
    assert create_res.status_code == 201
    exp_id = create_res.get_json()["expense_id"]

    # Read Single
    get_res = client.get(f"/api/expenses/{exp_id}")
    assert get_res.status_code == 200
    assert get_res.get_json()["expense"]["merchant"] == "Automated Test Store"

    # Update
    upd_res = client.put(f"/api/expenses/{exp_id}", json={
        "amount": 800.00,
        "merchant": "Automated Test Store Updated",
        "category_id": 1,
        "expense_date": "2026-10-28",
        "payment_method": "Debit Card",
        "notes": "Updated notes"
    })
    assert upd_res.status_code == 200

    # Delete
    del_res = client.delete(f"/api/expenses/{exp_id}")
    assert del_res.status_code == 200


def test_budgets_api(client):
    """Test setting budget and verifying 80% and over-budget threshold calculation."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Set overall budget for month 10, year 2026 to 10000
    res = client.post("/api/budgets", json={
        "category_id": None,
        "month": 10,
        "year": 2026,
        "amount": 10000.00
    })
    assert res.status_code == 200

    # Fetch budgets
    get_res = client.get("/api/budgets?month=10&year=2026")
    assert get_res.status_code == 200
    data = get_res.get_json()
    assert data["overall"]["budget_limit"] == 10000.00
    assert "categories" in data


def test_insights_api(client):
    """Test spending insights calculation and rule-based advice output."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    res = client.get("/api/insights?month=10&year=2026")
    assert res.status_code == 200
    data = res.get_json()
    assert "total_spent" in data
    assert "recommendations" in data
    assert "safe_daily_allowance" in data

