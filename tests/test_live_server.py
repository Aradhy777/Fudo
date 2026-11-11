"""
ExpenseTrack - Live HTTP Integration Verification Script
Can be run directly via `python tests/verify_live_server.py` against http://127.0.0.1:5000.
Also contains a pytest test case that skips gracefully if live server is not running.
"""

import pytest
import requests

BASE = "http://127.0.0.1:5000"


def run_live_verification():
    session = requests.Session()
    print("=" * 60)
    print("ExpenseTrack - Live HTTP Integration Verification")
    print("=" * 60)

    # 1. Test Auth Page
    r = session.get(f"{BASE}/auth", timeout=5)
    assert r.status_code == 200, f"/auth failed: {r.status_code}"
    print("[+] GET /auth: 200 OK")

    # 2. Test Login
    r = session.post(f"{BASE}/api/auth/login", json={
        "identifier": "student@expensetrack.edu",
        "password": "Password123!"
    }, timeout=5)
    assert r.status_code == 200, f"login failed: {r.status_code}"
    user = r.json()["user"]
    print(f"[+] POST /api/auth/login: 200 OK (Logged in as: {user['full_name']} / {user['email']})")

    # 3. Test Dashboard Page & Summary (both current month & seeded October 2026)
    r = session.get(f"{BASE}/dashboard", timeout=5)
    assert r.status_code == 200, f"/dashboard failed: {r.status_code}"

    r = session.get(f"{BASE}/api/dashboard/summary?month=10&year=2026", timeout=5)
    assert r.status_code == 200, f"/api/dashboard/summary?month=10&year=2026 failed: {r.status_code}"
    data = r.json()
    assert data["total_spent"] > 0, "Expected October spending from seed dataset"
    print(f"[+] Dashboard summary (Oct 2026): Spent = Rs.{data['total_spent']}, Budget = Rs.{data['monthly_budget']}, Remaining = Rs.{data['remaining_budget']}")

    # 4. Test Expenses Page & API
    r = session.get(f"{BASE}/expenses", timeout=5)
    assert r.status_code == 200
    r = session.get(f"{BASE}/api/expenses", timeout=5)
    assert r.status_code == 200
    exp_data = r.json()
    print(f"[+] Expenses API: {len(exp_data['expenses'])} records fetched (Total: {exp_data['pagination']['total_records']})")

    # 5. Test Budgets Page & API
    r = session.get(f"{BASE}/budgets", timeout=5)
    assert r.status_code == 200
    r = session.get(f"{BASE}/api/budgets?month=10&year=2026", timeout=5)
    assert r.status_code == 200
    bud_data = r.json()
    print(f"[+] Budgets API: Overall budget = Rs.{bud_data['overall']['budget_limit']}, {len(bud_data['categories'])} category limits tracked")

    # 6. Test Scan Page
    r = session.get(f"{BASE}/scan", timeout=5)
    assert r.status_code == 200
    print("[+] GET /scan: 200 OK")

    # 7. Test Insights Page & API
    r = session.get(f"{BASE}/insights", timeout=5)
    assert r.status_code == 200
    r = session.get(f"{BASE}/api/insights?month=10&year=2026", timeout=5)
    assert r.status_code == 200
    ins_data = r.json()
    print(f"[+] Insights API: {len(ins_data['recommendations'])} recommendations generated (Daily allowance: Rs.{ins_data['safe_daily_allowance']})")

    # 8. Test Profile Page & Diagnostics API
    r = session.get(f"{BASE}/profile", timeout=5)
    assert r.status_code == 200
    r = session.get(f"{BASE}/api/system/diagnostics", timeout=5)
    assert r.status_code == 200
    diag = r.json()
    print(f"[+] Diagnostics API: Database: {diag['database']['engine']} [{diag['database']['status']}], OCR: {diag['ocr_engine']['status']}, Cloud: {diag['cloud_storage']['status']}")

    print("=" * 60)
    print("[SUCCESS] ALL 8 CORE APPLICATION PAGES & APIS OPERATIONAL")
    print("=" * 60)
    return True


def test_live_server_endpoints():
    """Pytest test case that executes against live server if running."""
    try:
        r = requests.get(f"{BASE}/auth", timeout=2)
        if r.status_code != 200:
            pytest.skip("Live server returned non-200 on /auth")
    except Exception:
        pytest.skip("Live server is not currently running on http://127.0.0.1:5000")

    assert run_live_verification() is True


if __name__ == "__main__":
    run_live_verification()
