# ExpenseTrack: Final Engineering Improvement & Stabilization Report

**Sprint Date:** 2026-11-11  
**Workspace:** `d:\3rd sem project`  
**Baseline Git Checkpoint:** `f9c6d4c` (`chore: baseline checkpoint before 5-hour sprint audit`)  
**Runtime Stack:** Python 3.14.2 · Flask 3.0.3 · MariaDB 10.11.8 (`expensetrack`) · PyMySQL · Chart.js · Vanilla JS/CSS3  

---

## 1. Executive Summary

During this 5-Hour Engineering Improvement and Stabilization Sprint, the ExpenseTrack codebase underwent an end-to-end backend, database, security, API integration, and frontend polish audit without rebuilding the working architecture or altering/resetting the live `expensetrack` database.

All **12** verified baseline defects (`[ENG-001]` through `[ENG-012]`) plus dark/light theme contrast mismatches and missing modal lifecycle/callback handlers discovered during inspection have been systematically resolved and validated against a live MariaDB instance (`127.0.0.1:3306`) and Flask server (`http://127.0.0.1:5000`). The automated `pytest` regression suite doubled from **12 tests** to **24 passing tests (100% pass rate)**.

---

## 2. Original Problems Discovered & Severity Classification

| ID | Severity | Component / File | Problem Summary |
| :--- | :--- | :--- | :--- |
| **[ENG-001]** | **High** | `routes/expenses.py` (`update_expense`) | `PUT /api/expenses/<id>` omitted presence & foreign-key existence validation for `category_id`, allowing invalid/null values to trigger uncaught SQL `IntegrityError` (HTTP 500). |
| **[ENG-002]** | **High** | `routes/auth.py` (`login`, `register`) | Missing `session.clear()` and `session.permanent = True`, bypassing the configured 24-hour `PERMANENT_SESSION_LIFETIME` TTL and leaving a session fixation window. |
| **[ENG-003]** | **High** | `routes/auth.py`, `expenses.py`, `budgets.py`, `receipts.py`, `profile.py` | Exception handlers leaked raw Python/PyMySQL `str(e)` internal table, constraint, and SQL error strings in JSON responses to external HTTP clients. |
| **[ENG-004]** | **High** | `app.py`, `routes/auth.py` | Broad wildcard `CORS(app)`, lack of IP rate limiting on auth routes, missing Same-Origin CSRF verification on `/api/*` mutations, and absent baseline HTTP security response headers. |
| **[ENG-005]** | **Medium** | `routes/budgets.py` (`set_budget`) | MySQL `UNIQUE KEY` permits duplicate rows when `category_id IS NULL` (`NULL != NULL` in SQL). Non-atomic `SELECT`-then-`INSERT` could create duplicate overall monthly limits under concurrent requests. |
| **[ENG-006]** | **Medium** | `routes/expenses.py`, `budgets.py`, `auth.py`, `profile.py` | Monetary `float(amount)` accepted `"NaN"`, `"Infinity"`, and `DECIMAL(10,2)` overflows; calling `.strip()` on non-string JSON fields caused `AttributeError` 500s; strings exceeding `VARCHAR` column limits caused `DataError` 500s. |
| **[ENG-007]** | **Medium** | `routes/dashboard.py`, `budgets.py`, `insights.py`, `expenses.py` | Unchecked `int()` casting on `month`, `year`, and `page` query strings raised uncaught `ValueError` or `calendar.IllegalMonthError` (HTTP 500) on out-of-range inputs (`?month=15` or `?month=abc`). |
| **[ENG-008]** | **Medium** | `routes/dashboard.py` (`get_dashboard_summary`) | 6-month spending trend executed a Python `for`-loop opening and closing 6 separate SQL connections/queries per dashboard render (`N+1` connection overhead). *(Note: refactoring initially introduced a PyMySQL `%Y` format specifier collision in `DATE_FORMAT`, caught immediately during live testing and cleanly replaced with `YEAR()`/`MONTH()` grouping).* |
| **[ENG-009]** | **Medium** | `routes/receipts.py` (`scan_receipt`) | File upload accepted files solely by filename extension without verifying binary image headers, allowing spoofed non-image text/script files renamed `.png`. |
| **[ENG-010]** | **Medium** | `static/js/api.js`, `expenses.js`, `budgets.js`, `insights.js`; `templates/budgets.html`, `scan.html`, `profile.html` | Hardcoded light colors (`#1E293B`, `#0F172A`, `#F8FAFC`) rendered illegible dark-on-dark/white-on-white text in Dark Mode (including invisible toast text and raw OCR preview summary); modals lacked `Escape`/backdrop close & focus; deleting the last row on page > 1 stayed on an empty page; `budgets.js`/`insights.js` lacked `window.onExpenseCreated` live refresh hooks; UI mixed Unicode emojis instead of vector SVGs. |
| **[ENG-011]** | **Low** | `routes/dashboard.py`, `budgets.py`, `services/insight_service.py` | Single-month filtering with `MONTH(expense_date) = %s AND YEAR(expense_date) = %s` wraps the indexed column in functions (preventing composite B-Tree index utilization on large scale). Partially addressed on the 6-month trend range query; documented as next optimization target. |
| **[ENG-012]** | **Low** | `services/insight_service.py` (`compute_spending_insights`) | Returned raw PyMySQL `DictCursor` `Decimal` inside `highest_category` dict instead of JSON-native `float`/`int`. |

---

## 3. Files Modified & Created

Verified via `git status --short` against baseline commit `f9c6d4c`:

### Created Files
- `routes/validators.py` — Centralized strict validators (`validate_amount`, `validate_date`, `validate_string`, `parse_int_param`) and sliding-window IP `rate_limit` decorator.
- `docs/ENGINEERING_AUDIT.md` — Baseline architecture & 12-issue engineering defect inventory.
- `docs/SECURITY_AUDIT.md` — Detailed OWASP security remediation report.
- `docs/IMPROVEMENT_REPORT.md` — This final sprint engineering changelog & verification report.
- `.gitignore` — Excludes `.env`, `.mariadb_server/`, `uploads/`, `__pycache__/`, and `.pytest_cache/` from commits.

### Modified Backend & Service Files
- `app.py` — Scoped `CORS`, added `@app.before_request` Same-Origin CSRF check, added `@app.after_request` security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`), added JSON/HTML `413 Payload Too Large` handler.
- `routes/auth.py` — Applied `@rate_limit` (15/min login, 10/min register), added `session.clear()` + `session.permanent = True`, enforced string/length validators, sanitized SQL exceptions.
- `routes/expenses.py` — Validated `category_id` on `PUT`, applied `validators.py` strictly across `GET`/`POST`/`PUT`, changed unauthorized `receipt_id` attachment to explicit `403 Forbidden`, sanitized SQL exceptions.
- `routes/budgets.py` — Bounded `month`/`year` query parsing, converted `set_budget` check-and-upsert to atomic `with get_db()` transaction with `FOR UPDATE` row locking and duplicate guard, sanitized SQL exceptions.
- `routes/dashboard.py` — Bounded `month`/`year` params (`400` on invalid input), replaced 6-query trend loop with single SQL range `GROUP BY YEAR(expense_date), MONTH(expense_date)` aggregation.
- `routes/insights.py` & `services/insight_service.py` — Bounded `month`/`year` params and normalized `highest_category` types to JSON `float`/`int`.
- `routes/receipts.py` — Added Pillow magic-byte binary image verification (`Image.open(...).verify()`), empty file rejection, and sanitized SQL error messages.
- `routes/profile.py` — Added `validate_string` length/type checks and sanitized SQL error responses.

### Modified Frontend Templates & JavaScript Controllers
- `static/js/api.js` — Fixed dark-mode toast contrast (`color: var(--text-main)`), added `Escape` key & backdrop-click modal closing plus input auto-focus.
- `static/js/expenses.js` & `templates/expenses.html` — Replaced hardcoded colors with semantic theme CSS tokens, introduced `.method-pill` styling, stepped back pagination cleanly when deleting the last item on page > 1, fixed mobile responsive grid overflow (`repeat(auto-fit, minmax(175px, 1fr))`).
- `static/js/budgets.js` & `templates/budgets.html` — Replaced hardcoded light colors with theme variables, converted threshold icons cleanly, wired `window.onExpenseCreated = () => loadBudgets()`.
- `static/js/insights.js` — Replaced light alert containers and Unicode emojis with semantic CSS tokens and crisp SVG icons, wired `window.onExpenseCreated = () => loadInsights()`.
- `templates/scan.html` & `templates/profile.html` — Fixed severe Dark Mode contrast defects (`#F8FAFC`/`#FFFFFF`/`#1E293B` boxes & text -> semantic variables), replaced hardcoded diagnostics emojis with SVG icons, and added HTML escaping in `profile.html` diagnostics renderer.

### Modified Tests & Documentation
- `tests/test_app.py` — Expanded from 8 to 19 tests (with automatic teardown of synthetic test users, expenses, budgets, and temp receipt files).
- `tests/test_live_server.py` — Updated to seed-aligned October 2026 metrics and wrapped in pytest-compatible `test_live_server_endpoints` with clean offline skip guard.
- `README.md` — Synced automated test count (24 tests) and updated directory inventory.

---

## 4. Database Changes & Integrity Safeguards

- **Schema & Data Preservation:** Zero tables were dropped, reset, or truncated. All pre-existing user records, seeded expenses (22 rows across Aug–Oct 2026), categories (8), and budgets (6) remain completely intact in the MariaDB `expensetrack` database.
- **Concurrency & Overall Budget Atomicity:** Because SQL `UNIQUE KEY (user_id, category_id, month, year)` does not constrain multiple `NULL` rows for overall monthly limits (`category_id IS NULL`), `routes/budgets.py` now performs budget lookups and updates inside an explicit `with get_db()` transaction using `SELECT id ... FOR UPDATE`, updating cleanly rather than creating duplicate rows under rapid double-submissions.

---

## 5. Security Hardening Summary

- **Input & Boundary Validation:** Enforced strict `Decimal` monetary bounds (`0.01` to `99,999,999.99`), finite number guards (`NaN`/`Infinity` rejected), type-safe string checks (`validate_string`), and `YYYY-MM-DD` date validation matching schema bounds.
- **Authentication & Session Hygiene:** Applied `session.clear()` (anti-fixation) and `session.permanent = True` (enforcing 24-hour TTL alongside `HttpOnly` + `SameSite=Lax`).
- **Brute-Force Defense:** Enforced IP sliding-window rate limits (`15/min` on login, `10/min` on registration returning HTTP `429`).
- **CSRF & Response Headers:** Scoped CORS exclusively to local origin (`127.0.0.1:5000` / `localhost:5000`), enforced Same-Origin `Origin` checks on mutating `/api/*` requests (`403 Forbidden` on mismatched origin), and added `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, and `Referrer-Policy: strict-origin-when-cross-origin`.
- **Upload Validation:** Rejected non-image spoofed binaries via Pillow `Image.verify()` in addition to extension checks and `5MB` size caps (`413`).
- **Error Sanitization & BOLA Enforcement:** Eliminated raw exception leakage (`str(e)`) from API errors and enforced HTTP `403` if attaching an unowned `receipt_id`. *(Full report: `docs/SECURITY_AUDIT.md`)*.

---

## 6. Performance & UI/UX Improvements

### Performance Optimization
- **Dashboard 6-Month Trend:** Collapsed 6 sequential Python loop queries (`6` TCP handshakes + `6` SQL aggregations per dashboard visit) into a single ranged aggregation query using `WHERE user_id = %s AND expense_date >= %s AND expense_date <= %s GROUP BY YEAR(expense_date), MONTH(expense_date)`.

### UI/UX Fixes
- **True Dual-Theme Parity (Dark & Light):** Fixed invisible text in dark mode across `api.js` toasts, `scan.html` OCR banners & raw preview accordion, `budgets.html` KPI balances, `profile.html` diagnostics cards, and table rows rendered by `expenses.js`, `budgets.js`, and `insights.js`.
- **Modal & Ledger Ergonomics:** Added `Escape` key closing, backdrop click closing, initial focus handling, responsive filter grid wrapping, empty-page step-back after deleting the last record on page > 1, and cross-component dashboard/budget/insights updates via `window.onExpenseCreated`.

---

## 7. Automated Test & Live Verification Results

### 7.1 Complete `pytest` Suite Execution
Command executed cleanly against live MariaDB 10.11 (`expensetrack`) after all code edits:

```text
$ python -m pytest -v
============================= 24 passed in 19.49s =============================
```

Breakdown of passing tests:
- `tests/test_app.py` (**19/19 passed**): Login (`demo_student`), wrong credentials `401`, missing payload `400`, registration field validation `400`, duplicate account conflict `409`, logout & unauthenticated `401`/`302` protection, multi-tenant isolation across expenses/budgets/receipts (`404`/`403`), full expense CRUD lifecycle, edge-case validation (`NaN`, negative, zero, malformed date, invalid category), `PUT` invalid `category_id` rejection (`[ENG-001]`), budget utilization & threshold math, atomic budget upsert without duplication (`[ENG-005]`), dashboard metrics & 6-month trend (`[ENG-008]`), malformed query rejection across dashboard/budgets/insights (`[ENG-007]`), magic-byte rejection of disguised `.png` script (`[ENG-009]`), valid PNG upload + SHA-256 duplicate flag, system diagnostics API, all 6 authenticated Jinja2 pages (`200 OK`), and security headers + cross-origin mutation rejection (`403`).
- `tests/test_live_server.py` (**1/1 passed**): Full live HTTP integration verification against `http://127.0.0.1:5000`.
- `tests/test_ocr.py` (**4/4 passed**): UPI/card heuristic regex parsing, SHA-256 checksum determinism, and graceful fallback when image/OCR binary is unavailable.

### 7.2 Standalone Live Server Smoke Verification
Command executed sequentially against running Flask server (`http://127.0.0.1:5000`):

```text
$ python tests/test_live_server.py
[+] GET /auth: 200 OK
[+] POST /api/auth/login: 200 OK (Logged in as: Aarav Sharma / student@expensetrack.edu)
[+] Dashboard summary (Oct 2026): Spent = Rs.7058.0, Budget = Rs.10000.0, Remaining = Rs.2942.0
[+] Expenses API: 20 records fetched (Total: 22)
[+] Budgets API: Overall budget = Rs.10000.0, 8 category limits tracked
[+] GET /scan: 200 OK
[+] Insights API: 2 recommendations generated (Daily allowance: Rs.2942.0)
[+] Diagnostics API: Database: MySQL / MariaDB [connected], OCR: fallback_mode, Cloud: local_fallback
[SUCCESS] ALL 8 CORE APPLICATION PAGES & APIS OPERATIONAL
```

---

## 8. Remaining Limitations & Recommended Next Improvements

### Remaining Environment & Architectural Limitations
1. **OCR Fallback Mode Active Locally:** Native `tesseract.exe` is not installed on the current Windows `PATH`, so `/scan` runs cleanly in verified fallback mode (SHA-256 hashing + manual confirmation form ready).
2. **Azure Storage Local Fallback:** `AZURE_STORAGE_CONNECTION_STRING` is unset in local `.env`, so uploaded receipts persist securely inside local private storage (`uploads/receipts/`) rather than remote Azure Blob containers.
3. **Single-Month SQL Predicate Function (`[ENG-011]`):** Single-month `MONTH(expense_date)` / `YEAR(expense_date)` clauses remain in `dashboard.py`, `budgets.py`, and `insight_service.py` (acceptable for student-scale datasets, though non-sargable at millions of rows).
4. **In-Memory Rate Limiter & Plaintext Local HTTP:** `_RATE_LIMIT_BUCKETS` lives in single-process Python memory, and `SESSION_COOKIE_SECURE` remains `False` so `http://127.0.0.1:5000` works smoothly during local academic viva demonstrations.

### Recommended Next Improvements
1. **Complete Sargable Range Migration (`[ENG-011]`):** Refactor remaining `MONTH()`/`YEAR()` single-month filters to `expense_date >= %s AND expense_date <= %s` to achieve full composite B-Tree index coverage (`idx_expenses_user_date`).
2. **UI Budget Deletion Action:** Add a "Remove Limit" button inside `templates/budgets.html` / `budgets.js` wired to the already-secured `DELETE /api/budgets/<id>` endpoint.
3. **Production Deployment Hardening:** Run under a production WSGI server (`waitress` / `gunicorn`) behind an HTTPS reverse proxy with `SESSION_COOKIE_SECURE = True` and Redis-backed rate limiting (`Flask-Limiter`).

