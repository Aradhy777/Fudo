# ExpenseTrack: Baseline Engineering Audit & Defect Analysis

**Audit Date:** 2026-11-11  
**Baseline Git Checkpoint:** `f9c6d4c`  
**Running Environment:** Python 3.14.2 / Flask 3.0.3 (`127.0.0.1:5000`), MariaDB 10.11.8 (`127.0.0.1:3306`)  
**Baseline Test Results:** 12 / 12 tests passing (`tests/test_app.py`, `tests/test_ocr.py`)

---

## 1. Current Architecture & Module Inventory

ExpenseTrack utilizes a classic monolithic layered architecture driven by Python Flask Blueprints and a relational MariaDB/MySQL persistence layer:

- **Application Core:** `app.py`, `config.py`
- **Database Layer:** `database/db.py` (PyMySQL parameterized execution + `@contextmanager get_db`), `database/schema.sql`, `database/seed.sql`
- **Flask Blueprints (`routes/`):**
  - `auth.py` & `auth_helper.py` (`/auth`, `/login`, `/register`, `/api/auth/*`)
  - `dashboard.py` (`/`, `/dashboard`, `/api/dashboard/summary`)
  - `expenses.py` (`/expenses`, `/api/expenses/*`)
  - `budgets.py` (`/budgets`, `/api/budgets/*`)
  - `receipts.py` (`/scan`, `/api/receipts/scan`, `/uploads/receipts/<filename>`)
  - `insights.py` (`/insights`, `/api/insights`)
  - `profile.py` (`/profile`, `/api/profile/*`, `/api/system/diagnostics`)
- **Services (`services/`):** `ocr_service.py`, `insight_service.py`, `azure_storage.py`
- **Frontend (`templates/` & `static/`):** Jinja2 templates, `api.js`, `dashboard.js`, `expenses.js`, `budgets.js`, `insights.js`, `scan.js`, `main.css`, `components.css`

---

## 2. Identified Bugs, Vulnerabilities & Optimization Opportunities

Every issue below is substantiated by direct source code inspection:

### HIGH SEVERITY

#### [ENG-001] Unvalidated `category_id` on Expense Update (`routes/expenses.py:228-259`)
- **Problem:** `POST /api/expenses` validates that `category_id` exists in the `categories` table before inserting. However, `PUT /api/expenses/<expense_id>` omits both presence and existence checks on `category_id`. Passing `category_id: 9999` or `null` throws an uncaught MySQL Foreign Key Constraint IntegrityError, triggering an HTTP 500 Internal Server Error instead of HTTP 400.
- **Recommended Fix:** Explicitly validate `category_id` is an integer and exists in `categories` before executing `UPDATE`.

#### [ENG-002] Missing Session Fixation Guard & Inactive Expiration (`routes/auth.py:71-114`)
- **Problem:** `config.py` defines `PERMANENT_SESSION_LIFETIME = 86400` (24 hours), but neither `register()` nor `login()` sets `session.permanent = True`. Consequently, Flask uses non-expiring browser-session cookies and ignores the lifetime limit. Furthermore, neither endpoint calls `session.clear()` before setting user identity keys, creating a minor session fixation window.
- **Recommended Fix:** Call `session.clear()`, set `session.permanent = True`, and rotate session context on authentication.

#### [ENG-003] Internal Database Exception Leakage (`routes/auth.py:86`, `expenses.py:212,263`, `budgets.py:197`, `receipts.py:130`, `profile.py:49`)
- **Problem:** Database catch blocks return raw exception strings directly in JSON responses (`f"Failed to ...: {str(e)}"`). In PyMySQL, `str(e)` discloses table names, schema structure, constraint names, and internal DB errors to external API clients.
- **Recommended Fix:** Log technical error details to server stdout/stderr via `app.logger.error()` and return sanitized generic error messages to HTTP clients.

#### [ENG-004] Lack of Rate Limiting & Broad Wildcard CORS (`app.py:28`, `routes/auth.py`)
- **Problem:** `CORS(app)` opens wildcard cross-origin API access, and `/api/auth/login` and `/api/auth/register` have no rate-limiting defenses against credential stuffing or automated brute-force enumeration. Additionally, state-changing requests lack CSRF/Same-Origin guards and HTTP security response headers (`X-Content-Type-Options`, `X-Frame-Options`).
- **Recommended Fix:** Restrict CORS, implement sliding-window IP rate limiting on auth endpoints, enforce Same-Origin/Referer checks on state-changing routes, and attach baseline HTTP security headers.

---

### MEDIUM SEVERITY

#### [ENG-005] SQL `NULL != NULL` Duplicate Overall Budget Race Condition (`database/schema.sql:114`, `routes/budgets.py:166-192`)
- **Problem:** In MySQL/MariaDB, `UNIQUE KEY (user_id, category_id, month, year)` allows multiple rows with `category_id = NULL` because `NULL` is never considered equal to `NULL` in SQL unique indexes. While `set_budget()` performs a `SELECT` before `INSERT`, concurrent submissions (e.g., double-clicking Save) can race past the check and insert duplicate monthly overall budgets.
- **Recommended Fix:** Perform the check-and-upsert inside a dedicated atomic transaction (`with get_db()`) with row locking (`FOR UPDATE`) and aggregate/deduplicate safely if multiple exist.

#### [ENG-006] Monetary Float Precision, `NaN`/`Infinity`, & Field Length Crashes (`routes/expenses.py`, `routes/budgets.py`, `routes/auth.py`)
- **Problem:** `float(amount)` accepts `"nan"`, `"inf"`, and amounts exceeding `DECIMAL(10,2)` upper bound (`99999999.99`), resulting in SQL `DataError` HTTP 500 crashes. Furthermore, calling `.strip()` on JSON inputs assumes strings—sending an integer/array triggers `AttributeError` HTTP 500. Long merchant names (`>100` chars) or full names (`>100` chars) also cause 500 DB errors instead of 400 validation errors.
- **Recommended Fix:** Create strict validation helpers checking string types, finite `Decimal` values (`0.01 <= amount <= 99999999.99`), valid dates, and max lengths matching schema columns.

#### [ENG-007] Uncaught Query Parameter `ValueError` & Month Out-of-Range 500s (`routes/dashboard.py:30-34`, `budgets.py:25-26`, `insights.py:25-26`, `expenses.py:40-41`)
- **Problem:** Endpoints call `int(request.args.get("month"))`, `int(request.args.get("page"))`, etc. Passing invalid query strings (e.g. `?month=abc` or `?month=15`) throws uncaught `ValueError` or `calendar.IllegalMonthError` (HTTP 500).
- **Recommended Fix:** Safely parse integer query parameters with explicit bounds (`1 <= month <= 12`, `2020 <= year <= 2100`, `page >= 1`) returning HTTP 400 on malformed values.

#### [ENG-008] N+1 Query Pattern in Dashboard 6-Month Trend (`routes/dashboard.py:139-157`)
- **Problem:** `get_dashboard_summary()` runs a Python loop of 6 sequential `query_db()` calls (creating and closing 6 separate TCP/DB connections) to construct the 6-month chart.
- **Recommended Fix:** Replace the loop with a single parameterized SQL query using `GROUP BY YEAR(expense_date), MONTH(expense_date)` across the 6-month window.

#### [ENG-009] File Upload Missing Magic-Byte Content Verification (`routes/receipts.py:42`)
- **Problem:** `scan_receipt()` relies strictly on the filename extension (`allowed_file`) and client-supplied `Content-Type` header. A malicious HTML, SVG, or script file renamed `.png` is accepted and stored on disk.
- **Recommended Fix:** Validate true image binary headers via Pillow (`Image.open(io.BytesIO(file_bytes)).verify()`), check `file_size > 0`, and reject corrupted or spoofed non-image binaries cleanly (HTTP 400).

#### [ENG-010] Hardcoded Light-Mode Colors & Emoji Icons in JS Controllers (`static/js/expenses.js`, `budgets.js`, `insights.js`)
- **Problem:** `expenses.js`, `budgets.js`, and `insights.js` inject hardcoded `#1E293B` and `#0F172A` inline CSS colors and light alert backgrounds (`#FEF2F2`), making text dark-on-dark when the user activates Dark Mode. `insights.js` also uses raw Unicode emojis (`🚨`, `⚠️`) instead of SVG icons.
- **Recommended Fix:** Replace hardcoded inline colors with semantic CSS variables (`var(--text-main)`, `var(--danger-subtle)`, etc.) and use crisp SVG vector icons consistently.

---

### LOW SEVERITY

#### [ENG-011] SQL `MONTH()`/`YEAR()` Wrapping Prevents Index Usage (`routes/dashboard.py`, `budgets.py`, `services/insight_service.py`)
- **Problem:** Filtering via `WHERE MONTH(expense_date) = %s AND YEAR(expense_date) = %s` prevents MariaDB from using the `idx_expenses_user_date` B-Tree composite index efficiently on large datasets.
- **Recommended Fix:** Refactor monthly date filters to half-open/closed sargable date ranges: `expense_date >= %s AND expense_date <= %s`.

#### [ENG-012] Inconsistent `highest_category` Decimal Serialization (`services/insight_service.py:117, 186`)
- **Problem:** `highest_category` returns a raw SQL `DictCursor` row containing a Python `Decimal` type while other fields convert to `float`.
- **Recommended Fix:** Explicitly normalize `highest_category` fields to JSON-native `float` and `int` types.

---

## 3. Verification Strategy

Following these findings, Phase 1 and Phase 2 will systematically implement each fix in clean, verifiable increments, followed by full unit and regression verification in Phase 5.

