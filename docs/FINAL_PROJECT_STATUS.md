# ExpenseTrack: Final Project Status & Academic Evaluation Report

**Project Name:** ExpenseTrack – Smart Student Expense Manager  
**Project Category:** Full-Stack Web Application / Database Engineering / Cloud Systems  
**Evaluation Session:** 3rd Semester Project Viva & Demonstration  
**Date of Audit:** October 2026  
**Status:** **100% Complete, Fully Functional & Verified**

---

## 1. Executive Summary

ExpenseTrack is a production-grade, privacy-centric personal finance web platform architected specifically for university students. The application provides end-to-end functionality for multi-channel expense tracking (UPI, cash, card), dual-tier budget monitoring (overall monthly ceiling and category caps) with real-time threshold warnings, receipt screenshot ingestion with human-in-the-loop verification, and deterministic financial pacing insights.

All core features have been implemented directly in the workspace, tested against a real MySQL-compatible database (MariaDB 10.11 InnoDB engine on port 3306), and verified with an automated test suite comprising 12 comprehensive unit and integration tests.

---

## 2. Implemented Modules & Architecture Breakdown

| Module | Route / Files | Description | Status |
| :--- | :--- | :--- | :--- |
| **Authentication & IAM** | `routes/auth.py`<br>`routes/auth_helper.py`<br>`templates/auth.html` | Secure user registration and login with Scrypt password hashing, salt generation, session establishment, and `HttpOnly`/`SameSite=Lax` cookies. | **Verified Active** |
| **Executive Bento Dashboard** | `routes/dashboard.py`<br>`templates/dashboard.html` | Dynamic financial summary cards (Month Spending, Monthly Cap, Remaining Allowance, Transaction Count), dynamic monthly pacing banner, Chart.js dual-view Trends (Bar vs Area), and Category Doughnut with live center metrics. | **Verified Active** |
| **Expense CRUD & Search** | `routes/expenses.py`<br>`templates/expenses.html` | Full Create, Read, Update, Delete lifecycle for student expenses with positive decimal validation, category filtering, merchant search, and date filters. | **Verified Active** |
| **Multi-Tier Budgeting** | `routes/budgets.py`<br>`templates/budgets.html` | Overall monthly cap and category limits with real-time percentage utilization and color-coded threshold alerts (80% warning amber, 100% breach red). | **Verified Active** |
| **Smart Receipt Scanner** | `routes/receipts.py`<br>`services/ocr_service.py`<br>`templates/receipts.html` | Upload receipt screenshots with SHA-256 duplicate detection, optical character recognition with graceful fallback, and mandatory human review form before committing. | **Verified Active** |
| **Financial Insights** | `routes/insights.py`<br>`services/insight_service.py`<br>`templates/insights.html` | Deterministic, explainable financial rule engine computing safe daily burn rates, top expense drivers, and multi-month pacing analysis. | **Verified Active** |
| **Cloud Diagnostics & Profile** | `routes/profile.py`<br>`services/azure_storage.py`<br>`templates/profile.html` | User profile management, live database connectivity diagnostics, and Microsoft Azure cloud integration status monitoring. | **Verified Active** |

---

## 3. Database Layer & Schema Summary

- **Database Engine:** MariaDB 10.11.8 / MySQL 8.0 Wire-Compatible Daemon (InnoDB Storage Engine)
- **Port:** `127.0.0.1:3306`
- **Database Name:** `expensetrack`
- **Character Set:** `utf8mb4` with `utf8mb4_unicode_ci` collation

### Relational Schema (5 Normalized Tables):
1. **`users`:** Manages identity, email, username, Scrypt password hashes, and audit timestamps.
2. **`categories`:** Standardized spending categories (Food, Travel, Shopping, Education, Entertainment, Bills, Healthcare, Other) with UI colors and icons.
3. **`expenses`:** Individual spending transactions referencing `user_id`, `category_id`, and optional `receipt_id`. Enforces `amount > 0.00` via CHECK constraint.
4. **`budgets`:** Monthly financial limits per user, supporting both overall monthly limits (`category_id IS NULL`) and specific category limits.
5. **`uploaded_receipts`:** Image metadata, file storage paths, SHA-256 hashes, raw OCR payloads, and processing states (`pending`, `success`, `fallback`, `failed`).

### Seed Dataset:
- **Demo User:** `student@expensetrack.edu` / `Password123!` (Aarav Sharma)
- **22 Transactions:** Pre-seeded across August, September, and October 2026 for realistic historical trend rendering.
- **6 Active Budgets:** Overall limit of ₹10,000.00 plus granular category limits.

---

## 4. Test Suite Execution & Verification Results

The automated regression test suite was executed using pytest:

```bash
$ python -m pytest
============================= test session starts =============================
platform win32 -- Python 3.14.2, pytest-9.0.3, pluggy-1.6.0
rootdir: D:\3rd sem project
plugins: anyio-4.13.0, dash-4.1.0, asyncio-1.3.0
collected 12 items

tests\test_app.py ........                                               [ 66%]
tests\test_ocr.py ....                                                   [100%]

============================= 12 passed in 9.55s ==============================
```

### Coverage Highlights:
- **`tests/test_app.py`:**
  - `test_registration_and_login`: Verifies user creation, credential validation, and session cookies.
  - `test_unauthenticated_redirects`: Confirms `@login_required` blocks unauthorized access.
  - `test_expense_crud`: Verifies inserting, fetching, editing, and deleting expenses.
  - `test_user_data_isolation`: Proves that User B cannot read or mutate User A's expenses.
  - `test_budget_calculations`: Verifies monthly utilization math and 80%/100% threshold flags.
  - `test_dashboard_metrics`: Validates that KPI totals match database sums.
  - `test_insights_engine`: Validates deterministic daily safe spend calculations.
  - `test_duplicate_receipt_detection`: Confirms SHA-256 hash prevents duplicate image submissions.
- **`tests/test_ocr.py`:**
  - `test_ocr_fallback_when_binary_missing`: Confirms graceful degradation without application crash.
  - `test_ocr_extraction_heuristics_upi`: Tests regex extraction on UPI receipt text patterns.
  - `test_ocr_extraction_heuristics_card`: Tests regex extraction on POS card receipt patterns.
  - `test_ocr_invalid_amount_rejection`: Confirms negative or unreasonable amounts are rejected.

---

## 5. Transparent Capability & Fallback Matrix

In accordance with strict academic integrity standards:

| Capability | Current State | Operational Mode |
| :--- | :--- | :--- |
| **Relational Database** | Active (`127.0.0.1:3306`) | Native MariaDB 10.11 process executing `expensetrack` database. |
| **Web Server** | Active (`http://127.0.0.1:5000`) | Python Flask 3.0.3 application serving dynamic HTML templates and JSON APIs. |
| **User Data Isolation** | Active | Multi-tenant session enforcement (`WHERE user_id = :id`) across all routes. |
| **Tesseract OCR Engine** | Graceful Fallback Mode | When the external Tesseract binary is not on system PATH, the application gracefully saves the receipt, sets `ocr_status = 'fallback'`, and presents an editable verification form without crashing. |
| **Azure Blob Storage** | Local Storage Fallback Mode | Azure Blob SDK code is fully implemented in `services/azure_storage.py`. When cloud credentials are empty in `.env`, receipts are securely stored in the local private vault (`uploads/receipts/`). |

---

## 6. How to Run the Application

### 1. Start the MariaDB / MySQL Server
```powershell
& ".\.mariadb_server\mariadb-10.11.8-winx64\bin\mariadbd.exe" --datadir=".\.mariadb_server\data" --port=3306 --console
```

### 2. Start the Flask Application Server
```powershell
python app.py
```

### 3. Access in Browser
Open `http://127.0.0.1:5000` in Google Chrome or Microsoft Edge.  
**Login:** `student@expensetrack.edu` / `Password123!`

---

## 7. Submission Package Manifest

The documentation package is complete and ready for academic submission:

1. **`docs/DEMO_GUIDE.md`:** 5-minute viva demonstration script with step-by-step actions and narration.
2. **`docs/SYSTEM_DESIGN_VIVA.md`:** System architecture, requirements, and Mermaid UML diagrams.
3. **`docs/RDBMS_VIVA.md`:** Relational database theory, 3NF normalization, real SQL queries, and 15 viva Q&As.
4. **`docs/DP900_VIVA.md`:** Microsoft Azure Data Fundamentals, Blob storage tiers, and 10 viva Q&As.
5. **`docs/CLOUD_SECURITY_VIVA.md`:** IAM, Scrypt KDF, OWASP Top 10 defense, session flags, and 10 viva Q&As.
6. **`docs/AI900_VIVA.md`:** Computer Vision OCR, regex heuristics, Responsible AI, and 10 viva Q&As.
7. **`docs/FINAL_PROJECT_STATUS.md`:** This comprehensive status report and verification audit.

