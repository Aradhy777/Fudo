"""
ExpenseTrack - Step 4 Smoke Test:
Tests login, dashboard, expense creation, editing, deletion, budget calculations, charts, and user data isolation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from database.db import execute_db

BASE = "http://127.0.0.1:5000"
s = requests.Session()

print("=" * 60)
print("ExpenseTrack - Smoke Test Step 4")
print("=" * 60)

# 1. Login
res = s.post(f"{BASE}/api/auth/login", json={"identifier": "student@expensetrack.edu", "password": "Password123!"})
assert res.status_code == 200, f"Login failed: {res.text}"
print("[PASS] 1. Authentication: Login succeeded for student@expensetrack.edu")

# 2. Dashboard
res = s.get(f"{BASE}/api/dashboard/summary")
assert res.status_code == 200, "Dashboard summary failed"
dash = res.json()
assert "total_spent" in dash and "category_chart" in dash and "monthly_trend" in dash
print(f"[PASS] 2. Dashboard API: Total Spent = Rs.{dash['total_spent']}, Budget = Rs.{dash['monthly_budget']}, Remaining = Rs.{dash['remaining_budget']}")
print(f"     Category Chart Labels: {dash['category_chart']['labels']}")
print(f"     Monthly Trend Labels: {dash['monthly_trend']['labels']}")

# 3. Expense Creation
exp_payload = {
    "amount": 320.00,
    "merchant": "Smoke Test Canteen",
    "category_id": 1,
    "expense_date": "2026-10-29",
    "payment_method": "UPI",
    "notes": "End-to-end smoke test"
}
res = s.post(f"{BASE}/api/expenses", json=exp_payload)
assert res.status_code == 201, f"Create expense failed: {res.text}"
exp_id = res.json()["expense_id"]
print(f"[PASS] 3. Expense Creation: Created expense with ID {exp_id}")

# 4. Expense Editing
res = s.put(f"{BASE}/api/expenses/{exp_id}", json={
    "amount": 350.00,
    "merchant": "Smoke Test Canteen Updated",
    "category_id": 1,
    "expense_date": "2026-10-29",
    "payment_method": "UPI",
    "notes": "Updated in smoke test"
})
assert res.status_code == 200, "Update expense failed"
print(f"[PASS] 4. Expense Editing: Updated expense ID {exp_id}")

# 5. Verify Edit
res = s.get(f"{BASE}/api/expenses/{exp_id}")
assert res.status_code == 200
assert res.json()["expense"]["amount"] == 350.00
assert res.json()["expense"]["merchant"] == "Smoke Test Canteen Updated"
print(f"[PASS] 5. Expense Verification: Verified edited fields on ID {exp_id}")

# 6. Expense Deletion
res = s.delete(f"{BASE}/api/expenses/{exp_id}")
assert res.status_code == 200, "Delete expense failed"
res = s.get(f"{BASE}/api/expenses/{exp_id}")
assert res.status_code == 404, "Deleted expense should return 404"
print(f"[PASS] 6. Expense Deletion: Successfully deleted expense ID {exp_id}")

# 7. Budget Calculations
res = s.get(f"{BASE}/api/budgets?month=10&year=2026")
assert res.status_code == 200, "Budget query failed"
bdata = res.json()
overall = bdata["overall"]
assert overall["budget_limit"] > 0
print(f"[PASS] 7. Budget Calculations: Limit = Rs.{overall['budget_limit']}, Spent = Rs.{overall['total_spent']}, Util = {overall['percentage']}%, Status = {overall['status']}")

# 8. User Data Isolation Check
# Clean up isolation_tester if previously registered
execute_db("DELETE FROM users WHERE username = 'isolation_tester';")

s2 = requests.Session()
reg_res = s2.post(f"{BASE}/api/auth/register", json={
    "username": "isolation_tester",
    "email": "isolation@test.edu",
    "password": "Password123!",
    "full_name": "Isolation Tester"
})
assert reg_res.status_code == 201

# Create private expense for User 2
res = s2.post(f"{BASE}/api/expenses", json={
    "amount": 999.00,
    "merchant": "User 2 Secret Item",
    "category_id": 1,
    "expense_date": "2026-10-29",
    "payment_method": "Cash"
})
u2_exp_id = res.json()["expense_id"]

# Now User 1 attempts to access User 2 expense:
res_forbidden_get = s.get(f"{BASE}/api/expenses/{u2_exp_id}")
assert res_forbidden_get.status_code == 404, "Data leak! User 1 could access User 2 expense"
res_forbidden_del = s.delete(f"{BASE}/api/expenses/{u2_exp_id}")
assert res_forbidden_del.status_code == 404, "Data leak! User 1 could delete User 2 expense"
print(f"[PASS] 8. User Data Isolation: Enforced! User 1 cannot access or delete User 2 expense (ID {u2_exp_id})")

# Cleanup
execute_db("DELETE FROM users WHERE username = 'isolation_tester';")
print("=" * 60)
print("[SUCCESS] ALL STEP 4 SMOKE TEST CHECKS PASSED")
print("=" * 60)
