"""
ExpenseTrack - Advanced Backend Stress Test, Concurrency, Security & Integrity Suite
Verifies financial precision, SQL EXPLAIN index usage, real thread-barrier concurrency,
rollbacks, security edge cases, OCR heuristics, receipt guards, and static frontend safety.
"""

import io
import sys
import uuid
import time
import threading
import concurrent.futures
from decimal import Decimal
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import pymysql
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from config import Config
from database.db import execute_db, query_db, get_db
from routes.validators import _RATE_LIMIT_BUCKETS
from services.ocr_service import OCRService


def _make_image_bytes(fmt="PNG", color=(16, 185, 129), size=(60, 60)):
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def isolated_user():
    """Provision an isolated temporary student user and clean up all test rows/files afterward."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["ENABLE_RATE_LIMIT_IN_TESTS"] = False

    tag = uuid.uuid4().hex[:8]
    username = f"adv_{tag}"
    email = f"adv_{tag}@university.edu"
    password = "Password123!"

    with app.test_client() as client:
        reg = client.post("/api/auth/register", json={
            "username": username,
            "email": email,
            "password": password,
            "full_name": f"Adv User {tag}",
        })
        assert reg.status_code == 201
        user_id = reg.get_json()["user"]["id"]

        try:
            yield app, client, {"id": user_id, "username": username, "email": email, "password": password}
        finally:
            rows = query_db("SELECT file_path FROM uploaded_receipts WHERE user_id = %s;", (user_id,))
            for r in rows:
                p = PROJECT_ROOT / r["file_path"]
                if p.exists():
                    p.unlink()
            execute_db("DELETE FROM users WHERE id = %s;", (user_id,))


# =====================================================================
# 1. FINANCIAL CORRECTNESS & CALENDAR BOUNDARY TESTS
# =====================================================================

def test_fin_boundary_amounts_and_decimal_precision(isolated_user):
    """Verify minimum/max DECIMAL(10,2), sub-cent rejection, rounding, and independent SQL match."""
    _, client, user = isolated_user
    uid = user["id"]

    # Rejected invalid/overflow/sub-cent amounts -> must return 400 (never 500)
    for bad_amt in [0.001, 0.004, 0, -0.01, 100000000.00, 99999999.999, "NaN", "Infinity", "-Infinity", True]:
        res = client.post("/api/expenses", json={
            "amount": bad_amt, "merchant": "Invalid Amt", "category_id": 1, "expense_date": "2026-06-15"
        })
        assert res.status_code == 400, f"Expected 400 for amount={bad_amt!r}, got {res.status_code}"

    # Valid boundaries & ROUND_HALF_UP precision: 0.01, 10.125 -> 10.13, 99999999.99
    valid_cases = [(0.01, 0.01), (10.125, 10.13), (99999999.99, 99999999.99)]
    for raw_amt, expected in valid_cases:
        cr = client.post("/api/expenses", json={
            "amount": raw_amt, "merchant": f"Amt {raw_amt}", "category_id": 1, "expense_date": "2026-06-15"
        })
        assert cr.status_code == 201
        eid = cr.get_json()["expense_id"]
        got = client.get(f"/api/expenses/{eid}").get_json()["expense"]["amount"]
        assert got == expected

    # Independent SQL cross-check vs Dashboard & Budgets API
    sql_row = query_db(
        "SELECT SUM(amount) AS s, COUNT(*) AS c FROM expenses WHERE user_id = %s AND expense_date BETWEEN '2026-06-01' AND '2026-06-30';",
        (uid,),
        one=True,
    )
    dash = client.get("/api/dashboard/summary?month=6&year=2026").get_json()
    assert dash["total_spent"] == float(sql_row["s"])
    assert dash["expense_count"] == int(sql_row["c"])


def test_fin_float_subtraction_precision_and_budget_validation(isolated_user):
    """Ensure budget-remaining avoids IEEE-754 float artifacts (0.20000000000000284) and validates month/year."""
    _, client, _ = isolated_user

    # Missing month or year on POST /api/budgets must return 400 (never 500)
    assert client.post("/api/budgets", json={"category_id": 1, "amount": 500}).status_code == 400
    assert client.post("/api/budgets", json={"month": 10, "amount": 500}).status_code == 400
    assert client.post("/api/budgets", json={"month": 10, "year": 2026, "amount": 0.001}).status_code == 400

    # 100.30 - 100.10 must equal exact 0.2 (no float tail)
    assert client.post("/api/budgets", json={"category_id": None, "month": 7, "year": 2026, "amount": 100.30}).status_code == 200
    assert client.post("/api/expenses", json={"amount": 100.10, "merchant": "FP Test", "category_id": 1, "expense_date": "2026-07-10"}).status_code == 201

    bud = client.get("/api/budgets?month=7&year=2026").get_json()
    assert bud["overall"]["remaining"] == 0.2
    dash = client.get("/api/dashboard/summary?month=7&year=2026").get_json()
    assert dash["remaining_budget"] == 0.2


def test_fin_calendar_transitions_leap_year_and_mutation_aggregates(isolated_user):
    """Test leap-year dates, month/year boundaries, and edit/category/delete recalculations."""
    _, client, user = isolated_user
    uid = user["id"]

    # Invalid calendar dates rejected cleanly
    for bad_date in ["2026-02-29", "2026-13-01", "2026-04-31", "2019-12-31", "2051-01-01", "not-a-date"]:
        r = client.post("/api/expenses", json={"amount": 50, "merchant": "BadDate", "category_id": 1, "expense_date": bad_date})
        assert r.status_code == 400

    # Valid leap year (2024-02-29) & month/year transitions
    entries = [
        ("2024-02-29", 1, 290.00),  # Leap day
        ("2026-01-31", 1, 110.00),  # Jan end
        ("2026-02-01", 2, 220.00),  # Feb start
        ("2026-12-31", 3, 330.00),  # Dec end
        ("2027-01-01", 4, 440.00),  # Next year start
    ]
    created_ids = []
    for dt, cid, amt in entries:
        res = client.post("/api/expenses", json={"amount": amt, "merchant": f"Boundary {dt}", "category_id": cid, "expense_date": dt})
        assert res.status_code == 201
        created_ids.append(res.get_json()["expense_id"])

    assert client.get("/api/dashboard/summary?month=2&year=2024").get_json()["total_spent"] == 290.00
    assert client.get("/api/dashboard/summary?month=1&year=2026").get_json()["total_spent"] == 110.00
    assert client.get("/api/dashboard/summary?month=2&year=2026").get_json()["total_spent"] == 220.00
    assert client.get("/api/dashboard/summary?month=12&year=2026").get_json()["total_spent"] == 330.00
    assert client.get("/api/dashboard/summary?month=1&year=2027").get_json()["total_spent"] == 440.00

    # Edit Feb 2026 amount & category (Travel -> Education) and verify dashboard + budget recalculation
    target_id = created_ids[2]
    assert client.put(f"/api/expenses/{target_id}", json={
        "amount": 725.50, "merchant": "Shifted Cat", "category_id": 4, "expense_date": "2026-02-01"
    }).status_code == 200

    feb_dash = client.get("/api/dashboard/summary?month=2&year=2026").get_json()
    assert feb_dash["total_spent"] == 725.50
    assert feb_dash["categories_breakdown"][0]["name"] == "Education"

    # Delete it and confirm totals drop cleanly to zero matching independent SQL
    assert client.delete(f"/api/expenses/{target_id}").status_code == 200
    feb_after = client.get("/api/dashboard/summary?month=2&year=2026").get_json()
    sql_feb = query_db(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM expenses WHERE user_id = %s AND expense_date BETWEEN '2026-02-01' AND '2026-02-28';",
        (uid,),
        one=True,
    )
    assert feb_after["total_spent"] == float(sql_feb["s"]) == 0.0
    assert feb_after["expense_count"] == 0


# =====================================================================
# 2. DATABASE CONCURRENCY & TRANSACTION INTEGRITY TESTS
# =====================================================================

def test_conc_simultaneous_operations_and_deadlock_safety(isolated_user):
    """Run barrier-synchronized multi-threaded requests for expenses, budgets, edits, deletes, and receipts."""
    app, client, user = isolated_user
    uid = user["id"]

    clients = []
    for _ in range(4):
        cl = app.test_client()
        assert cl.post("/api/auth/login", json={"identifier": user["email"], "password": user["password"]}).status_code == 200
        clients.append(cl)

    # A. 4 simultaneous expense creations
    b_exp = threading.Barrier(4)
    def create_exp(idx_cl):
        idx, cl = idx_cl
        b_exp.wait()
        return cl.post("/api/expenses", json={
            "amount": 100.25, "merchant": f"ConcExp-{idx}", "category_id": 1, "expense_date": "2026-05-10"
        }).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        exp_codes = list(ex.map(create_exp, enumerate(clients)))
    assert exp_codes == [201, 201, 201, 201]
    sql_sum = query_db("SELECT COALESCE(SUM(amount), 0) AS s, COUNT(*) AS c FROM expenses WHERE user_id = %s;", (uid,), one=True)
    assert float(sql_sum["s"]) == 401.00 and sql_sum["c"] == 4

    # B. 4 simultaneous NEW overall budgets (category_id=None) -> zero 1213 deadlocks, 1 DB row
    b_ov = threading.Barrier(4)
    def set_overall(cl):
        b_ov.wait()
        return cl.post("/api/budgets", json={"category_id": None, "month": 5, "year": 2026, "amount": 5000.00}).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        ov_codes = list(ex.map(set_overall, clients))
    assert ov_codes == [200, 200, 200, 200]
    ov_cnt = query_db("SELECT COUNT(*) AS c FROM budgets WHERE user_id=%s AND category_id IS NULL AND month=5 AND year=2026;", (uid,), one=True)["c"]
    assert ov_cnt == 1

    # C. 4 simultaneous NEW category budgets -> zero deadlocks, 1 DB row
    b_cat = threading.Barrier(4)
    def set_cat(cl):
        b_cat.wait()
        return cl.post("/api/budgets", json={"category_id": 2, "month": 5, "year": 2026, "amount": 1500.00}).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        cat_codes = list(ex.map(set_cat, clients))
    assert cat_codes == [200, 200, 200, 200]
    cat_cnt = query_db("SELECT COUNT(*) AS c FROM budgets WHERE user_id=%s AND category_id=2 AND month=5 AND year=2026;", (uid,), one=True)["c"]
    assert cat_cnt == 1

    # D. 4 simultaneous edits and 4 simultaneous deletes to the same expense
    tid = client.post("/api/expenses", json={"amount": 50.0, "merchant": "Target", "category_id": 1, "expense_date": "2026-05-12"}).get_json()["expense_id"]
    b_edit = threading.Barrier(4)
    def edit_exp(idx_cl):
        idx, cl = idx_cl
        b_edit.wait()
        return cl.put(f"/api/expenses/{tid}", json={
            "amount": 60.0 + idx, "merchant": f"Edited-{idx}", "category_id": 1, "expense_date": "2026-05-12"
        }).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        assert list(ex.map(edit_exp, enumerate(clients))) == [200, 200, 200, 200]

    b_del = threading.Barrier(4)
    def del_exp(cl):
        b_del.wait()
        return cl.delete(f"/api/expenses/{tid}").status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        del_codes = sorted(list(ex.map(del_exp, clients)))
    assert del_codes == [200, 404, 404, 404]

    # E. 4 simultaneous duplicate receipt uploads -> strictly 1 original + 3 marked duplicate
    png_bytes = _make_image_bytes("PNG", color=(12, 34, 56))
    b_rec = threading.Barrier(4)
    def upload_dup(cl):
        b_rec.wait()
        resp = cl.post("/api/receipts/scan", data={"receipt": (io.BytesIO(png_bytes), "dup.png", "image/png")}, content_type="multipart/form-data")
        return resp.status_code, (resp.get_json() or {}).get("is_duplicate")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        rec_res = list(ex.map(upload_dup, clients))
    assert all(st == 201 for st, _ in rec_res)
    dup_flags = [d for _, d in rec_res]
    assert dup_flags.count(False) == 1 and dup_flags.count(True) == 3


def test_conc_transaction_rollback_and_db_failure_handling(isolated_user):
    """Verify failed multi-step transaction rolls back cleanly and DB drops return safe 500 JSON."""
    app, client, user = isolated_user
    uid = user["id"]

    # 1. Verify get_db() rollback on step 2 exception
    with pytest.raises(RuntimeError):
        with get_db() as (_, cursor):
            cursor.execute(
                "INSERT INTO expenses (user_id, category_id, amount, merchant, expense_date) VALUES (%s, 1, 99.00, 'RollbackTest', '2026-08-01');",
                (uid,),
            )
            raise RuntimeError("Simulated mid-transaction failure")

    leftover = query_db("SELECT id FROM expenses WHERE user_id = %s AND merchant = 'RollbackTest';", (uid,))
    assert len(leftover) == 0

    # 2. Simulate OperationalError during DB connection -> 500 JSON with zero internal secret leakage
    with patch("repositories.analytics_repo.AnalyticsRepository._session", side_effect=pymysql.err.OperationalError(2003, "Can't connect to 127.0.0.1 secret")):
        res = client.get("/api/dashboard/summary?month=10&year=2026")
        assert res.status_code == 500
        body = res.get_json()
        assert body["error"] == "Internal Server Error"
        assert "127.0.0.1" not in str(body) and "secret" not in str(body)


# =====================================================================
# 3. SECURITY EDGE-CASE TESTING
# =====================================================================

def test_sec_session_expiration_tampering_and_stale_account(isolated_user):
    """Test missing cookie, manipulated session values, expired TTL, and deleted account stale cookies."""
    app, _, user = isolated_user

    # 1. Tampered non-int session["user_id"] must be cleared -> 401
    with app.test_client() as bad_sess_client:
        with bad_sess_client.session_transaction() as sess:
            sess["user_id"] = "not-an-integer"
        assert bad_sess_client.get("/api/expenses").status_code == 401
        assert bad_sess_client.get("/dashboard").status_code == 302

    # 2. Expired PERMANENT_SESSION_LIFETIME rejects session cookie -> 401
    orig_lifetime = app.config["PERMANENT_SESSION_LIFETIME"]
    try:
        with app.test_client() as exp_client:
            assert exp_client.post("/api/auth/login", json={"identifier": user["email"], "password": user["password"]}).status_code == 200
            app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(seconds=-10)
            assert exp_client.get("/api/expenses").status_code == 401
    finally:
        app.config["PERMANENT_SESSION_LIFETIME"] = orig_lifetime

    # 3. Stale deleted user session returns 401 cleanly instead of 500 FK IntegrityError
    tag = uuid.uuid4().hex[:8]
    with app.test_client() as stale_c:
        r = stale_c.post("/api/auth/register", json={
            "username": f"stale_{tag}", "email": f"stale_{tag}@u.edu", "password": "Password123!", "full_name": "Stale"
        })
        assert r.status_code == 201
        sid = r.get_json()["user"]["id"]
        execute_db("DELETE FROM users WHERE id = %s;", (sid,))
        assert stale_c.get("/api/auth/me").status_code == 401
        # Re-establish session manually to test POST /api/expenses FK stale session check
        with stale_c.session_transaction() as sess:
            sess["user_id"] = sid
        res = stale_c.post("/api/expenses", json={"amount": 10, "merchant": "Ghost", "category_id": 1, "expense_date": "2026-10-15"})
        assert res.status_code == 401


def test_sec_csrf_origin_xss_sqli_malformed_json_and_methods(isolated_user):
    """Test CSRF cross-port/Referer blocks, XSS/SQLi safety, non-dict JSON, 405 JSON, 413 oversized."""
    app, client, user = isolated_user

    # Authenticated client using explicit host 127.0.0.1:5000
    with app.test_client() as c_host:
        assert c_host.post(
            "/api/auth/login",
            json={"identifier": user["email"], "password": user["password"]},
            base_url="http://127.0.0.1:5000",
        ).status_code == 200

        # Malicious Origin, Origin: null, Cross-port Origin, Malicious Referer -> 403
        for headers in [
            {"Origin": "https://evil.example.com"},
            {"Origin": "null"},
            {"Origin": "http://localhost:9999"},
            {"Referer": "https://evil.example.com/attack.html"},
        ]:
            r = c_host.post(
                "/api/expenses",
                json={"amount": 10, "merchant": "CSRF", "category_id": 1, "expense_date": "2026-10-15"},
                headers=headers,
                base_url="http://127.0.0.1:5000",
            )
            assert r.status_code == 403, f"Expected 403 for headers={headers}"

    # Malformed & non-dict JSON payloads -> 400 (never 500 AttributeError)
    for bad_body in ["{bad json", "[1, 2, 3]", "123", '"scalar"', "true"]:
        r = client.post("/api/expenses", data=bad_body, content_type="application/json")
        assert r.status_code == 400

    # Unexpected HTTP method returns consistent JSON 405
    r_405 = client.patch("/api/expenses/1")
    assert r_405.status_code == 405
    assert r_405.is_json

    # ID tampering
    assert client.get("/api/expenses/-1").status_code == 404
    assert client.get("/api/expenses/abc").status_code == 404
    assert client.post("/api/expenses", json={"amount": 10, "merchant": "BoolCat", "category_id": True, "expense_date": "2026-10-15"}).status_code == 400

    # XSS & SQL injection payloads parameterized safely
    xss_merch = "<img src=x onerror=alert(1)>"
    sqli_note = "' OR '1'='1'; DROP TABLE expenses;--"
    cr = client.post("/api/expenses", json={
        "amount": 42.0, "merchant": xss_merch, "category_id": 1, "expense_date": "2026-10-15", "notes": sqli_note
    })
    assert cr.status_code == 201
    assert client.get(f"/api/expenses?search={sqli_note}").status_code == 200
    assert query_db("SELECT COUNT(*) AS c FROM categories;", one=True)["c"] >= 8

    # Oversized body > Config.MAX_CONTENT_LENGTH -> 413 JSON
    oversized = b"x" * (Config.MAX_CONTENT_LENGTH + 1024)
    r_big = client.post("/api/expenses", data=oversized, content_type="application/json")
    assert r_big.status_code == 413
    assert r_big.is_json


def test_sec_rate_limiting_and_xff_spoof_resistance(isolated_user):
    """Verify login (15/min) and register (10/min) rate limits enforce 429 and resist X-Forwarded-For spoofing."""
    app, _, user = isolated_user
    _RATE_LIMIT_BUCKETS.clear()
    app.config["ENABLE_RATE_LIMIT_IN_TESTS"] = True

    try:
        with app.test_client() as rl_c:
            # 18 login attempts with rotating X-Forwarded-For headers must still trigger 429 after 15
            login_codes = [
                rl_c.post(
                    "/api/auth/login",
                    json={"identifier": user["email"], "password": "WrongPassword!"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"},
                ).status_code
                for i in range(18)
            ]
            assert login_codes.count(429) == 3

            # 12 register attempts -> triggers 429 after 10
            reg_codes = [
                rl_c.post("/api/auth/register", json={"username": "x"}).status_code
                for _ in range(12)
            ]
            assert reg_codes.count(429) == 2
    finally:
        app.config["ENABLE_RATE_LIMIT_IN_TESTS"] = False
        _RATE_LIMIT_BUCKETS.clear()


def test_sec_receipt_file_ownership_and_path_traversal(isolated_user):
    """Verify second tenant gets 403 accessing User 1's receipt URL and path traversal is neutralized."""
    app, client, _ = isolated_user
    png = _make_image_bytes("PNG")

    up = client.post(
        "/api/receipts/scan",
        data={"receipt": (io.BytesIO(png), "../../etc/passwd.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert up.status_code == 201
    fname = up.get_json()["file_name"]
    assert "/" not in fname and "\\" not in fname and ".." not in fname and fname.endswith(".png")

    # Separate temporary user attempts to read User 1's receipt file
    tag2 = uuid.uuid4().hex[:8]
    with app.test_client() as c2:
        r2 = c2.post("/api/auth/register", json={
            "username": f"u2_{tag2}", "email": f"u2_{tag2}@u.edu", "password": "Password123!", "full_name": "User Two"
        })
        u2_id = r2.get_json()["user"]["id"]
        try:
            assert c2.get(f"/uploads/receipts/{fname}").status_code == 403
            assert c2.get("/uploads/receipts/..%2F..%2Fconfig.py").status_code in (403, 404)
            assert c2.get("/uploads/receipts/..config.py").status_code == 403
        finally:
            execute_db("DELETE FROM users WHERE id = %s;", (u2_id,))


# =====================================================================
# 4. RECEIPT UPLOAD & OCR HEURISTICS TESTS
# =====================================================================

def test_receipt_formats_validation_and_manual_confirmation_only(isolated_user):
    """Test PNG/JPEG/WEBP, empty, corrupted, spoofed GIF, unsupported PDF/SVG, long MIME, Unicode name."""
    _, client, user = isolated_user
    uid = user["id"]

    # Valid PNG, JPEG, WEBP
    for fmt, ext, mime in [("PNG", "ok.png", "image/png"), ("JPEG", "ok.jpg", "image/jpeg"), ("WEBP", "ok.webp", "image/webp")]:
        raw = _make_image_bytes(fmt)
        r = client.post("/api/receipts/scan", data={"receipt": (io.BytesIO(raw), ext, mime)}, content_type="multipart/form-data")
        assert r.status_code == 201
        assert r.get_json()["file_name"].endswith(f".{ext.rsplit('.', 1)[1]}")

    # Unicode filename preserves canonical extension & absurd MIME header is sanitized
    r_uni = client.post(
        "/api/receipts/scan",
        data={"receipt": (io.BytesIO(_make_image_bytes("PNG")), "🧾.png", "image/" + "x" * 150)},
        content_type="multipart/form-data",
    )
    assert r_uni.status_code == 201
    assert r_uni.get_json()["file_name"].endswith(".png")

    # Empty, corrupted, spoofed GIF, unsupported SVG/PDF rejected with 400
    for data_bytes, name, mime in [
        (b"", "empty.png", "image/png"),
        (b"corrupted-not-image", "corrupt.jpg", "image/jpeg"),
        (_make_image_bytes("GIF"), "anim.png", "image/png"),
        (b"<svg><script>alert(1)</script></svg>", "bad.svg", "image/svg+xml"),
        (b"%PDF-1.4", "doc.pdf", "application/pdf"),
    ]:
        bad = client.post("/api/receipts/scan", data={"receipt": (io.BytesIO(data_bytes), name, mime)}, content_type="multipart/form-data")
        assert bad.status_code == 400, f"Expected 400 for {name}"

    # Verify scanning receipts NEVER auto-writes expenses (user confirmation mandatory)
    assert query_db("SELECT COUNT(*) AS c FROM expenses WHERE user_id = %s;", (uid,), one=True)["c"] == 0


def test_ocr_extraction_edge_cases():
    """Verify OCR heuristics on malformed text, missing amount, multiple amounts, invalid dates, long merchant."""
    # Uncomma'd 4+ digit & multiple amounts prioritize Total/Paid
    r_multi = OCRService.extract_financial_entities("Line Item: Rs. 200.00\nGrand Total: Rs. 1500.00\n24 Oct 2026")
    assert r_multi["extracted_amount"] == 1500.00
    assert r_multi["extracted_date"] == "2026-10-24"

    # Garbage malformed text returns None for missing OCR entities (no fabricated defaults)
    r_garbage = OCRService.extract_financial_entities("###@@@ !!! No numbers here $$$")
    assert r_garbage["extracted_amount"] is None
    assert r_garbage["extracted_merchant"] is None
    assert r_garbage["extracted_date"] is None
    assert r_garbage["extracted_payment_method"] is None

    # Invalid dates do not crash strptime or fabricate today's date
    r_bad_date = OCRService.extract_financial_entities("Paid ₹350.00 on 31/02/2026 via GPay")
    assert r_bad_date["extracted_amount"] == 350.00
    assert r_bad_date["extracted_date"] is None

    # Very long merchant string safely bounded well within VARCHAR(100)
    r_long = OCRService.extract_financial_entities("Paid to " + ("SuperLongMerchantName" * 15) + "\nAmount: Rs. 99.00")
    assert len(r_long["extracted_merchant"]) <= 50
    assert r_long["extracted_amount"] == 99.00


# =====================================================================
# 5. PERFORMANCE, CONNECTION LIFECYCLE & SQL EXPLAIN PLAN TESTS
# =====================================================================

def test_perf_dashboard_single_connection_and_index_explain(isolated_user):
    """Measure query connection count, execution time, and verify MariaDB uses idx_expenses_user_date."""
    app, client, user = isolated_user
    uid = user["id"]

    # Seed 10 expenses for user
    for i in range(10):
        client.post("/api/expenses", json={"amount": 100 + i, "merchant": f"Perf {i}", "category_id": 1, "expense_date": "2026-10-15"})

    from sqlalchemy import event
    from database.engine import get_engine

    active_engine = get_engine()
    conn_count = 0

    def on_checkout(dbapi_conn, conn_record, conn_proxy):
        nonlocal conn_count
        conn_count += 1

    event.listen(active_engine, "checkout", on_checkout)
    try:
        t0 = time.perf_counter()
        res = client.get("/api/dashboard/summary?month=10&year=2026")
        elapsed_ms = (time.perf_counter() - t0) * 1000
    finally:
        event.remove(active_engine, "checkout", on_checkout)

    assert res.status_code == 200
    assert conn_count == 1, f"Expected 1 DB connection per dashboard request, got {conn_count}"
    assert elapsed_ms < 1000, f"Dashboard exceeded latency budget: {elapsed_ms:.2f}ms"

    # EXPLAIN plan check on sargable dashboard range query
    explain_rows = query_db(
        "EXPLAIN SELECT COALESCE(SUM(amount), 0.00), COUNT(id) FROM expenses WHERE user_id = %s AND expense_date >= '2026-10-01' AND expense_date <= '2026-10-31';",
        (uid,),
    )
    assert explain_rows[0]["key"] == "idx_expenses_user_date"
    assert explain_rows[0]["type"] != "ALL"


# =====================================================================
# 6. FRONTEND ASSETS & DOM XSS SAFETY TESTS
# =====================================================================

def test_fe_static_assets_and_toast_xss_guard(isolated_user):
    """Verify all rendered static CSS/JS assets exist and serve 200 OK, and showToast avoids innerHTML XSS."""
    _, client, _ = isolated_user

    # Check static assets served 200
    for asset in [
        "/static/css/main.css",
        "/static/css/components.css",
        "/static/js/api.js",
        "/static/js/dashboard.js",
        "/static/js/expenses.js",
        "/static/js/budgets.js",
        "/static/js/scan.js",
        "/static/js/insights.js",
    ]:
        r = client.get(asset)
        assert r.status_code == 200, f"Missing asset {asset}"

    # Verify showToast uses safe .textContent assignment
    api_js = (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
    assert ".textContent = String(message" in api_js

    # Verify dashboard.js resets bars when monthly_budget == 0
    dash_js = (PROJECT_ROOT / "static/js/dashboard.js").read_text(encoding="utf-8")
    assert 'spendFill.style.width = data.monthly_budget > 0' in dash_js


# =====================================================================
# 7. RELEASE-READINESS REGRESSION TESTS
# =====================================================================

def test_rel_production_config_guards_and_diagnostics_redaction():
    """Verify production mode blocks default SECRET_KEY/DEBUG, sets Secure cookies, and redacts diagnostics."""
    import importlib
    import config as cfg_mod

    # 1. Production mode must reject missing/default SECRET_KEY and DEBUG=True
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"FLASK_ENV": "production"})

    with pytest.raises(RuntimeError, match="FLASK_DEBUG"):
        create_app({"FLASK_ENV": "production", "SECRET_KEY": "S" * 40, "DEBUG": True})

    # 2. Reloading Config with FLASK_ENV=production forces DEBUG=False & SESSION_COOKIE_SECURE=True
    try:
        with patch.dict("os.environ", {"FLASK_ENV": "production", "FLASK_DEBUG": "1", "SECRET_KEY": "P" * 48}, clear=False):
            importlib.reload(cfg_mod)
            assert cfg_mod.Config.DEBUG is False
            assert cfg_mod.Config.SESSION_COOKIE_SECURE is True
    finally:
        importlib.reload(cfg_mod)

    # 3. Diagnostics in production redacts DB host/port/name & binary path
    prod_app = create_app({
        "FLASK_ENV": "production",
        "SECRET_KEY": "P" * 48,
        "DEBUG": False,
        "SESSION_COOKIE_SECURE": False,
        "TESTING": True,
        "ENABLE_RATE_LIMIT_IN_TESTS": False,
    })
    tag = uuid.uuid4().hex[:8]
    uid = None
    try:
        with prod_app.test_client() as pc:
            reg = pc.post("/api/auth/register", json={
                "username": f"prod_{tag}", "email": f"prod_{tag}@u.edu", "password": "Password123!", "full_name": "Prod Check"
            })
            assert reg.status_code == 201
            uid = reg.get_json()["user"]["id"]
            diag = pc.get("/api/system/diagnostics").get_json()
            assert diag["database"]["host"] == "Redacted"
            assert diag["database"]["port"] == "Redacted"
            assert diag["database"]["database_name"] == "Redacted"
            assert "C:\\" not in diag["ocr_engine"]["binary_path"]

            # Simulated DB outage must NOT expose driver OperationalError details
            with patch("repositories.user_repo.check_active_db_connection", side_effect=pymysql.err.OperationalError(2003, "internal-secret-host:3306")):
                outage_diag = pc.get("/api/system/diagnostics").get_json()
                assert outage_diag["database"]["status"] == "disconnected"
                assert "internal-secret-host" not in outage_diag["database"]["message"]
    finally:
        if uid:
            execute_db("DELETE FROM users WHERE id = %s;", (uid,))


def test_rel_concurrent_duplicate_registration_returns_409():
    """Verify simultaneous duplicate registrations cleanly return 409 Conflict without 500 errors."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["ENABLE_RATE_LIMIT_IN_TESTS"] = False

    tag = uuid.uuid4().hex[:8]
    uname = f"creg_{tag}"
    uemail = f"creg_{tag}@u.edu"
    barrier = threading.Barrier(3)

    def try_reg():
        with app.test_client() as c:
            barrier.wait()
            return c.post("/api/auth/register", json={
                "username": uname, "email": uemail, "password": "Password123!", "full_name": "Concurrent Reg"
            }).status_code

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            codes = sorted(list(ex.map(lambda _: try_reg(), range(3))))
        assert codes == [201, 409, 409], f"Expected [201, 409, 409], got {codes}"
    finally:
        execute_db("DELETE FROM users WHERE username = %s;", (uname,))


def test_rel_connection_cleanup_and_receipt_file_cleanup_on_failure(isolated_user):
    """Verify socket/cursor cleanup after rollback errors and orphan receipt file deletion on DB write failure."""
    from unittest.mock import MagicMock

    _, client, _ = isolated_user

    # 1. Broken connection during rollback & cursor.close still guarantees conn.close() runs
    mock_cursor = MagicMock()
    mock_cursor.close.side_effect = RuntimeError("cursor already closed")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.rollback.side_effect = RuntimeError("broken pipe on rollback")

    with patch("database.db.get_raw_connection", return_value=mock_conn):
        with pytest.raises(ValueError, match="trigger failure"):
            with get_db() as (_, _):
                raise ValueError("trigger failure")
    assert mock_conn.close.called

    # 2. Failed DB insert during receipt scan deletes saved local image cleanly (zero orphans)
    upload_dir = PROJECT_ROOT / Config.UPLOAD_FOLDER
    before_files = set(p.name for p in upload_dir.glob("*")) if upload_dir.exists() else set()

    with patch("repositories.receipt_repo.ReceiptRepository.record_receipt_with_dedup_check", side_effect=RuntimeError("Simulated DB crash after upload")):
        res = client.post(
            "/api/receipts/scan",
            data={"receipt": (io.BytesIO(_make_image_bytes("PNG")), "cleanup_test.png", "image/png")},
            content_type="multipart/form-data",
        )
        assert res.status_code == 500

    after_files = set(p.name for p in upload_dir.glob("*")) if upload_dir.exists() else set()
    assert after_files == before_files, f"Orphan receipt file left on disk: {after_files - before_files}"


def test_rel_decimal_precision_accumulation_and_ocr_error_sanitization(isolated_user):
    """Verify exact Decimal arithmetic across multi-cent sums (0.10 + 0.20 == 0.30) and clean OCR error strings."""
    _, client, _ = isolated_user

    assert client.post("/api/budgets", json={"category_id": None, "month": 9, "year": 2026, "amount": 0.30}).status_code == 200
    assert client.post("/api/expenses", json={"amount": 0.10, "merchant": "D1", "category_id": 1, "expense_date": "2026-09-10"}).status_code == 201
    assert client.post("/api/expenses", json={"amount": 0.20, "merchant": "D2", "category_id": 1, "expense_date": "2026-09-12"}).status_code == 201

    dash = client.get("/api/dashboard/summary?month=9&year=2026").get_json()
    bud = client.get("/api/budgets?month=9&year=2026").get_json()
    assert dash["total_spent"] == 0.3
    assert dash["remaining_budget"] == 0.0
    assert dash["budget_used_percentage"] == 100.0
    assert bud["overall"]["remaining"] == 0.0

    # Sanitized OCR failure message when Tesseract/Pillow throws on corrupted stream
    with patch("services.ocr_service.OCRService.find_tesseract_binary", return_value="tesseract"), \
         patch("services.ocr_service.PYTESSERACT_AVAILABLE", True), \
         patch("services.ocr_service.Image.open", side_effect=OSError(r"C:\secret\uploads\receipt.png unreadable")):
        out = OCRService.process_receipt_image(r"C:\secret\uploads\receipt.png")
        assert out["ocr_status"] == "failed"
        assert r"C:\secret" not in out["message"]


def test_rel_comprehensive_two_tenant_api_isolation(isolated_user):
    """Test every tenant-scoped API endpoint across two separate users for BOLA/IDOR isolation."""
    app, client_a, user_a = isolated_user

    # User A creates expense, budget, and receipt
    rec_a = client_a.post(
        "/api/receipts/scan",
        data={"receipt": (io.BytesIO(_make_image_bytes("PNG", color=(99, 102, 241))), "tenant_a.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert rec_a.status_code == 201
    rid_a = rec_a.get_json()["receipt_id"]
    fname_a = rec_a.get_json()["file_name"]

    exp_a = client_a.post("/api/expenses", json={
        "amount": 1200.00, "merchant": "Secret Merchant A", "category_id": 1, "expense_date": "2026-08-15", "receipt_id": rid_a
    })
    assert exp_a.status_code == 201
    eid_a = exp_a.get_json()["expense_id"]

    bud_a = client_a.post("/api/budgets", json={"category_id": None, "month": 8, "year": 2026, "amount": 5000.00})
    assert bud_a.status_code == 200
    bid_a = bud_a.get_json()["budget_id"]

    # Register separate temporary User B
    tag_b = uuid.uuid4().hex[:8]
    uid_b = None
    try:
        with app.test_client() as client_b:
            rb = client_b.post("/api/auth/register", json={
                "username": f"tb_{tag_b}", "email": f"tb_{tag_b}@u.edu", "password": "Password123!", "full_name": "Tenant B"
            })
            assert rb.status_code == 201
            uid_b = rb.get_json()["user"]["id"]

            # Verify read endpoints do not leak User A's records
            assert client_b.get("/api/auth/me").get_json()["user"]["id"] == uid_b
            assert client_b.get("/api/dashboard/summary?month=8&year=2026").get_json()["total_spent"] == 0.0
            assert client_b.get("/api/expenses").get_json()["expenses"] == []
            assert client_b.get("/api/budgets?month=8&year=2026").get_json()["overall"]["budget_limit"] == 0.0
            assert client_b.get("/api/insights?month=8&year=2026").get_json()["total_spent"] == 0.0

            # Verify direct IDOR/BOLA manipulation attempts fail strictly
            assert client_b.get(f"/api/expenses/{eid_a}").status_code == 404
            assert client_b.put(f"/api/expenses/{eid_a}", json={
                "amount": 1.0, "merchant": "Hack", "category_id": 1, "expense_date": "2026-08-15"
            }).status_code == 404
            assert client_b.delete(f"/api/expenses/{eid_a}").status_code == 404
            assert client_b.delete(f"/api/budgets/{bid_a}").status_code == 404
            assert client_b.get(f"/uploads/receipts/{fname_a}").status_code == 403
            assert client_b.post("/api/expenses", json={
                "amount": 10.0, "merchant": "StealRcpt", "category_id": 1, "expense_date": "2026-08-15", "receipt_id": rid_a
            }).status_code == 403

            # Profile conflict check: B cannot take A's email
            assert client_b.post("/api/profile/update", json={"full_name": "Tenant B2", "email": user_a["email"]}).status_code == 409

        # Check A's profile after exiting client_b context stack cleanly
        assert client_a.get("/api/auth/me").get_json()["user"]["full_name"] != "Tenant B2"
    finally:
        if uid_b:
            execute_db("DELETE FROM users WHERE id = %s;", (uid_b,))


def test_rel_database_fk_cascade_and_constraints(isolated_user):
    """Verify live MySQL/MariaDB FK constraints (CASCADE, SET NULL, RESTRICT) and CHECK constraints."""
    _, client, user = isolated_user
    uid = user["id"]

    # Create receipt + linked expense + budget
    rec = client.post(
        "/api/receipts/scan",
        data={"receipt": (io.BytesIO(_make_image_bytes("PNG")), "fk_test.png", "image/png")},
        content_type="multipart/form-data",
    )
    rid = rec.get_json()["receipt_id"]
    exp = client.post("/api/expenses", json={
        "amount": 50.0, "merchant": "FK Merchant", "category_id": 1, "expense_date": "2026-08-18", "receipt_id": rid
    })
    eid = exp.get_json()["expense_id"]
    client.post("/api/budgets", json={"category_id": 1, "month": 8, "year": 2026, "amount": 500.0})

    # 1. FK RESTRICT prevents deleting referenced category
    with pytest.raises(pymysql.err.IntegrityError):
        execute_db("DELETE FROM categories WHERE id = 1;")

    # 2. CHECK constraint prevents non-positive DB inserts directly (MariaDB errno 4025 OperationalError)
    with pytest.raises((pymysql.err.IntegrityError, pymysql.err.OperationalError), match="chk_expense_amount_positive"):
        execute_db("INSERT INTO expenses (user_id, category_id, amount, merchant, expense_date) VALUES (%s, 1, 0.00, 'Bad', '2026-08-18');", (uid,))

    # 3. ON DELETE SET NULL preserves expense when receipt row deleted
    rec_path = query_db("SELECT file_path FROM uploaded_receipts WHERE id = %s;", (rid,), one=True)["file_path"]
    execute_db("DELETE FROM uploaded_receipts WHERE id = %s;", (rid,))
    (PROJECT_ROOT / rec_path).unlink(missing_ok=True)
    exp_row = query_db("SELECT receipt_id FROM expenses WHERE id = %s;", (eid,), one=True)
    assert exp_row["receipt_id"] is None

    # 4. ON DELETE CASCADE removes child expenses & budgets when parent user deleted
    execute_db("DELETE FROM users WHERE id = %s;", (uid,))
    assert query_db("SELECT COUNT(*) AS c FROM expenses WHERE user_id = %s;", (uid,), one=True)["c"] == 0
    assert query_db("SELECT COUNT(*) AS c FROM budgets WHERE user_id = %s;", (uid,), one=True)["c"] == 0



