"""
ExpenseTrack - Live Server HTTP Verification Test
"""

import requests

session = requests.Session()
BASE = "http://127.0.0.1:5000"

print("=" * 60)
print("ExpenseTrack - Live HTTP Integration Verification")
print("=" * 60)

# 1. Test Auth Page
r = session.get(f"{BASE}/auth")
assert r.status_code == 200, f"/auth failed: {r.status_code}"
print("[+] GET /auth: 200 OK")

# 2. Test Login
r = session.post(f"{BASE}/api/auth/login", json={
    "identifier": "student@expensetrack.edu",
    "password": "Password123!"
})
assert r.status_code == 200, f"login failed: {r.status_code}"
user = r.json()["user"]
print(f"[+] POST /api/auth/login: 200 OK (Logged in as: {user['full_name']} / {user['email']})")

# 3. Test Dashboard Page & Summary
r = session.get(f"{BASE}/dashboard")
assert r.status_code == 200, f"/dashboard failed: {r.status_code}"
r = session.get(f"{BASE}/api/dashboard/summary")
assert r.status_code == 200, f"/api/dashboard/summary failed: {r.status_code}"
data = r.json()
print(f"[+] Dashboard summary: Spent = Rs.{data['total_spent']}, Budget = Rs.{data['monthly_budget']}, Remaining = Rs.{data['remaining_budget']}")

# 4. Test Expenses Page & API
r = session.get(f"{BASE}/expenses")
assert r.status_code == 200
r = session.get(f"{BASE}/api/expenses")
assert r.status_code == 200
exp_data = r.json()
print(f"[+] Expenses API: {len(exp_data['expenses'])} records fetched (Total: {exp_data['pagination']['total_records']})")

# 5. Test Budgets Page & API
r = session.get(f"{BASE}/budgets")
assert r.status_code == 200
r = session.get(f"{BASE}/api/budgets?month=10&year=2026")
assert r.status_code == 200
bud_data = r.json()
print(f"[+] Budgets API: Overall budget = Rs.{bud_data['overall']['budget_limit']}, {len(bud_data['categories'])} category limits tracked")

# 6. Test Scan Page
r = session.get(f"{BASE}/scan")
assert r.status_code == 200
print("[+] GET /scan: 200 OK")

# 7. Test Insights Page & API
r = session.get(f"{BASE}/insights")
assert r.status_code == 200
r = session.get(f"{BASE}/api/insights?month=10&year=2026")
assert r.status_code == 200
ins_data = r.json()
print(f"[+] Insights API: {len(ins_data['recommendations'])} recommendations generated (Daily allowance: Rs.{ins_data['safe_daily_allowance']})")

# 8. Test Profile Page & Diagnostics API
r = session.get(f"{BASE}/profile")
assert r.status_code == 200
r = session.get(f"{BASE}/api/system/diagnostics")
assert r.status_code == 200
diag = r.json()
print(f"[+] Diagnostics API: Database: {diag['database']['engine']} [{diag['database']['status']}], OCR: {diag['ocr_engine']['status']}, Cloud: {diag['cloud_storage']['status']}")

print("=" * 60)
print("[SUCCESS] ALL 8 CORE APPLICATION PAGES & APIS OPERATIONAL")
print("=" * 60)

