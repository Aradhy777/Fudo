"""
ExpenseTrack - Comprehensive Automated Test & Regression Suite
Covers: Authentication, Authorization & Tenant Isolation, Input Validation,
Expense CRUD, Budget Engine, Dashboard Analytics, Receipt Security, and System Diagnostics.
"""

import sys
import io
from pathlib import Path
from PIL import Image
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from database.db import get_raw_connection, execute_db, query_db


@pytest.fixture(scope="session")
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["ENABLE_RATE_LIMIT_IN_TESTS"] = False
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


# =====================================================================
# 1. AUTHENTICATION & SESSION TESTS
# =====================================================================

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
    assert data["user"]["email"] == "student@expensetrack.edu"


def test_auth_login_invalid_credentials(client):
    """Test login failure on incorrect password."""
    res = client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "WrongPassword999!"
    })
    assert res.status_code == 401
    assert "Invalid credentials" in res.get_json()["message"]


def test_auth_login_missing_fields(client):
    """Test login failure with missing or non-string fields."""
    res = client.post("/api/auth/login", json={})
    assert res.status_code == 400


def test_registration_validation(client):
    """Test that invalid username, email, or short password are rejected."""
    # Short username
    res = client.post("/api/auth/register", json={
        "username": "ab",
        "email": "test@test.com",
        "password": "Password123!",
        "full_name": "Test User"
    })
    assert res.status_code == 400

    # Short password
    res = client.post("/api/auth/register", json={
        "username": "valid_user",
        "email": "test@test.com",
        "password": "123",
        "full_name": "Test User"
    })
    assert res.status_code == 400

    # Malformed email
    res = client.post("/api/auth/register", json={
        "username": "valid_user",
        "email": "not-an-email",
        "password": "Password123!",
        "full_name": "Test User"
    })
    assert res.status_code == 400


def test_duplicate_registration_rejected(client):
    """Test that existing username or email registration returns 409 Conflict."""
    res = client.post("/api/auth/register", json={
        "username": "demo_student",
        "email": "unique_email_123@test.com",
        "password": "Password123!",
        "full_name": "Duplicate Tester"
    })
    assert res.status_code == 409


def test_logout_and_unauthenticated_access(client):
    """Test logging out clears session and protected endpoints return 401/302."""
    # Login first
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Logout
    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200

    # API protected call must return 401
    api_res = client.get("/api/auth/me")
    assert api_res.status_code == 401

    # Page route must redirect to /auth
    page_res = client.get("/dashboard")
    assert page_res.status_code == 302
    assert "/auth" in page_res.headers["Location"]


# =====================================================================
# 2. AUTHORIZATION & MULTI-TENANT ISOLATION TESTS
# =====================================================================

def test_multi_user_isolation(client):
    """Test registering a second tenant and verifying strict resource isolation (expenses, budgets, receipts)."""
    u2_name = "tenant_two_isolation"
    u2_email = "tenant_two_isolation@university.edu"
    execute_db("DELETE FROM users WHERE username = %s OR email = %s;", (u2_name, u2_email))

    u2_receipt_path = None
    try:
        # 1. Register User 2
        reg = client.post("/api/auth/register", json={
            "username": u2_name,
            "email": u2_email,
            "password": "Password123!",
            "full_name": "Tenant Two"
        })
        assert reg.status_code == 201

        # User 2 logs an expense
        exp_res = client.post("/api/expenses", json={
            "amount": 350.00,
            "merchant": "User 2 Campus Books",
            "category_id": 1,
            "expense_date": "2026-10-25",
            "payment_method": "UPI",
            "notes": "User 2 isolated expense"
        })
        assert exp_res.status_code == 201
        u2_exp_id = exp_res.get_json()["expense_id"]

        # User 2 sets a budget
        bud_res = client.post("/api/budgets", json={
            "category_id": 1,
            "month": 10,
            "year": 2026,
            "amount": 2500.00
        })
        assert bud_res.status_code == 200
        u2_bud_id = bud_res.get_json()["budget_id"]

        # User 2 uploads a receipt
        img = Image.new("RGB", (50, 50), color=(59, 130, 246))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        rec_res = client.post(
            "/api/receipts/scan",
            data={"receipt": (io.BytesIO(buf.getvalue()), "u2_receipt.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert rec_res.status_code == 201
        u2_rec_id = rec_res.get_json()["receipt_id"]
        rec_row = query_db("SELECT file_path FROM uploaded_receipts WHERE id = %s", (u2_rec_id,), one=True)
        if rec_row:
            u2_receipt_path = PROJECT_ROOT / rec_row["file_path"]

        # 2. Switch context: Log in as User 1 (Demo Student)
        login_u1 = client.post("/api/auth/login", json={
            "identifier": "student@expensetrack.edu",
            "password": "Password123!"
        })
        assert login_u1.status_code == 200

        # User 1 attempts to READ User 2's expense -> 404
        assert client.get(f"/api/expenses/{u2_exp_id}").status_code == 404

        # User 1 attempts to UPDATE User 2's expense -> 404
        assert client.put(f"/api/expenses/{u2_exp_id}", json={
            "amount": 10.00,
            "merchant": "Tampered",
            "category_id": 1,
            "expense_date": "2026-10-25",
        }).status_code == 404

        # User 1 attempts to DELETE User 2's expense -> 404
        assert client.delete(f"/api/expenses/{u2_exp_id}").status_code == 404

        # User 1 attempts to DELETE User 2's budget -> 404
        assert client.delete(f"/api/budgets/{u2_bud_id}").status_code == 404

        # User 1 attempts to attach User 2's receipt_id -> 403 Forbidden
        attach_res = client.post("/api/expenses", json={
            "amount": 99.00,
            "merchant": "Receipt Steal Attempt",
            "category_id": 1,
            "expense_date": "2026-10-25",
            "receipt_id": u2_rec_id,
        })
        assert attach_res.status_code == 403
    finally:
        execute_db("DELETE FROM users WHERE username = %s OR email = %s;", (u2_name, u2_email))
        if u2_receipt_path and u2_receipt_path.exists():
            u2_receipt_path.unlink()


# =====================================================================
# 3. EXPENSE MANAGEMENT & INPUT VALIDATION TESTS
# =====================================================================

def test_expense_crud_workflow(client):
    """Test full create, read, update, and delete expense lifecycle."""
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
        "category_id": 2,
        "expense_date": "2026-10-28",
        "payment_method": "Debit Card",
        "notes": "Updated notes"
    })
    assert upd_res.status_code == 200

    # Verify update persisted
    verify_res = client.get(f"/api/expenses/{exp_id}")
    assert verify_res.get_json()["expense"]["amount"] == 800.00
    assert verify_res.get_json()["expense"]["category_id"] == 2

    # Delete
    del_res = client.delete(f"/api/expenses/{exp_id}")
    assert del_res.status_code == 200

    # Verify deletion
    assert client.get(f"/api/expenses/{exp_id}").status_code == 404


def test_expense_validation_edge_cases(client):
    """Test rejection of invalid amounts, dates, and non-existent categories."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Negative amount
    assert client.post("/api/expenses", json={
        "amount": -50.00,
        "merchant": "Negative Store",
        "category_id": 1,
        "expense_date": "2026-10-25"
    }).status_code == 400

    # Zero amount
    assert client.post("/api/expenses", json={
        "amount": 0.00,
        "merchant": "Zero Store",
        "category_id": 1,
        "expense_date": "2026-10-25"
    }).status_code == 400

    # Non-numeric NaN amount
    assert client.post("/api/expenses", json={
        "amount": "NaN",
        "merchant": "NaN Store",
        "category_id": 1,
        "expense_date": "2026-10-25"
    }).status_code == 400

    # Malformed date
    assert client.post("/api/expenses", json={
        "amount": 100.00,
        "merchant": "Bad Date Store",
        "category_id": 1,
        "expense_date": "invalid-date"
    }).status_code == 400

    # Non-existent category on create
    assert client.post("/api/expenses", json={
        "amount": 100.00,
        "merchant": "Bad Category Store",
        "category_id": 9999,
        "expense_date": "2026-10-25"
    }).status_code == 400


def test_expense_update_invalid_category_rejected(client):
    """Test that updating an expense with invalid category_id is rejected (ENG-001)."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Create temporary expense
    create_res = client.post("/api/expenses", json={
        "amount": 120.00,
        "merchant": "Category Test Store",
        "category_id": 1,
        "expense_date": "2026-10-25"
    })
    exp_id = create_res.get_json()["expense_id"]

    # Attempt PUT with category_id = 99999 -> must return 400, NOT 500
    bad_upd = client.put(f"/api/expenses/{exp_id}", json={
        "amount": 120.00,
        "merchant": "Category Test Store",
        "category_id": 99999,
        "expense_date": "2026-10-25"
    })
    assert bad_upd.status_code == 400
    assert "Invalid category" in bad_upd.get_json()["message"]

    # Clean up
    client.delete(f"/api/expenses/{exp_id}")


# =====================================================================
# 4. BUDGET CALCULATION ENGINE TESTS
# =====================================================================

def test_budget_calculations_and_thresholds(client):
    """Test setting budget and verifying percentage calculations and 80% threshold status."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Set overall budget for October 2026 to 10,000.00
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
    assert data["overall"]["total_spent"] > 0
    assert "percentage" in data["overall"]
    assert data["overall"]["status"] in ("normal", "warning", "exceeded")
    assert len(data["categories"]) > 0


def test_budget_upsert_atomic_update(client):
    """Test that posting to same month/category updates existing budget without duplicates (ENG-005)."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # First set
    r1 = client.post("/api/budgets", json={
        "category_id": 2,
        "month": 11,
        "year": 2026,
        "amount": 1500.00
    })
    assert r1.status_code == 200
    b_id1 = r1.get_json()["budget_id"]

    # Second set for identical category/month/year
    r2 = client.post("/api/budgets", json={
        "category_id": 2,
        "month": 11,
        "year": 2026,
        "amount": 1800.00
    })
    assert r2.status_code == 200
    b_id2 = r2.get_json()["budget_id"]

    assert b_id1 == b_id2, "Expected atomic UPDATE on existing budget ID"

    # Clean up
    client.delete(f"/api/budgets/{b_id1}")


# =====================================================================
# 5. DASHBOARD & ANALYTICS TESTS
# =====================================================================

def test_dashboard_summary_and_trend(client):
    """Test dashboard metrics, empty states, and optimized 6-month trend (ENG-008)."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    res = client.get("/api/dashboard/summary?month=10&year=2026")
    assert res.status_code == 200
    data = res.get_json()

    assert data["selected_month"] == 10
    assert data["selected_year"] == 2026
    assert "total_spent" in data
    assert "monthly_budget" in data
    assert "category_chart" in data
    assert len(data["monthly_trend"]["labels"]) == 6
    assert len(data["monthly_trend"]["data"]) == 6


def test_dashboard_invalid_query_params_rejected(client):
    """Test that malformed month/year query arguments return 400 Bad Request (ENG-007)."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    assert client.get("/api/dashboard/summary?month=15").status_code == 400
    assert client.get("/api/dashboard/summary?month=abc").status_code == 400
    assert client.get("/api/dashboard/summary?year=1990").status_code == 400
    assert client.get("/api/insights?month=15").status_code == 400
    assert client.get("/api/budgets?month=abc").status_code == 400


# =====================================================================
# 6. RECEIPT UPLOAD & SECURITY VALIDATION TESTS
# =====================================================================

def test_receipt_magic_byte_verification(client):
    """Test that spoofed non-image files renamed as .png are rejected (ENG-009)."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Fake PNG containing plain text script
    fake_png = io.BytesIO(b"alert('xss payload'); echo 'malicious';")
    data = {
        "receipt": (fake_png, "exploit.png", "image/png")
    }

    res = client.post("/api/receipts/scan", data=data, content_type="multipart/form-data")
    assert res.status_code == 400
    assert "Corrupted or invalid image" in res.get_json()["message"]


def test_receipt_valid_image_upload(client):
    """Test that genuine image file uploads successfully and detects duplicate hashes."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Generate a real in-memory 100x100 RGB image
    img = Image.new("RGB", (100, 100), color=(16, 185, 129))
    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    raw_png_bytes = img_buffer.getvalue()

    created_ids = []
    try:
        data = {
            "receipt": (io.BytesIO(raw_png_bytes), "test_receipt.png", "image/png")
        }

        res = client.post("/api/receipts/scan", data=data, content_type="multipart/form-data")
        assert res.status_code == 201
        out = res.get_json()
        assert "receipt_id" in out
        created_ids.append(out["receipt_id"])
        assert out["ocr"]["status"] in ("success", "fallback", "failed")

        # Second upload of identical bytes must trigger duplicate detection flag
        data_dup = {
            "receipt": (io.BytesIO(raw_png_bytes), "test_receipt.png", "image/png")
        }
        dup_res = client.post("/api/receipts/scan", data=data_dup, content_type="multipart/form-data")
        assert dup_res.status_code == 201
        dup_out = dup_res.get_json()
        created_ids.append(dup_out["receipt_id"])
        assert dup_out["is_duplicate"] is True
    finally:
        for rid in created_ids:
            row = query_db("SELECT file_path FROM uploaded_receipts WHERE id = %s", (rid,), one=True)
            execute_db("DELETE FROM uploaded_receipts WHERE id = %s", (rid,))
            if row:
                fpath = PROJECT_ROOT / row["file_path"]
                if fpath.exists():
                    fpath.unlink()


# =====================================================================
# 7. SYSTEM INTEGRATION & DIAGNOSTICS TESTS
# =====================================================================

def test_system_diagnostics_endpoint(client):
    """Test system diagnostics API returns database, OCR, and storage status."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    res = client.get("/api/system/diagnostics")
    assert res.status_code == 200
    data = res.get_json()
    assert data["database"]["status"] == "connected"
    assert "ocr_engine" in data
    assert "cloud_storage" in data
    assert "security" in data


def test_core_pages_render_for_authenticated_user(client):
    """Verify that all core Jinja2 template pages render with HTTP 200."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    for route in ["/dashboard", "/expenses", "/budgets", "/scan", "/insights", "/profile"]:
        res = client.get(route)
        assert res.status_code == 200, f"Failed on route {route}"


def test_security_headers_and_origin_guard(client):
    """Verify baseline HTTP security headers and cross-origin mutation rejection."""
    client.post("/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    })

    # Security headers attached to API responses
    diag = client.get("/api/system/diagnostics")
    assert diag.headers.get("X-Content-Type-Options") == "nosniff"
    assert diag.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "strict-origin" in diag.headers.get("Referrer-Policy", "")

    # Cross-origin mutation attempt rejected with 403 Forbidden
    evil_post = client.post(
        "/api/expenses",
        json={"amount": 50.0, "merchant": "CSRF Test", "category_id": 1, "expense_date": "2026-10-25"},
        headers={"Origin": "https://attacker.example.com"}
    )
    if evil_post.status_code == 201:
        bad_id = (evil_post.get_json() or {}).get("expense_id")
        if bad_id:
            execute_db("DELETE FROM expenses WHERE id = %s", (bad_id,))
    assert evil_post.status_code == 403
