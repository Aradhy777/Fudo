# ExpenseTrack: Final Independent Backend Release-Readiness Audit Report

**Audit Date:** 2026-11-11  
**Target Codebase:** `d:\3rd sem project`  
**Stack Verified:** Python 3.14.2 · Flask 3.0.3 · MariaDB 10.11.8 (`expensetrack`, port `3306`) · PyMySQL 1.2.3  
**Test Baseline After Audit Fixes:** **43 / 43 passing pytest cases** (`0` failures, `0` skipped) + **8 / 8 live HTTP routes operational**  

---

## 1. Executive Summary

An independent, code-level backend release-readiness audit was conducted across **database transactions & constraints, authentication & session security, multi-tenant authorization, receipt/OCR resilience, Decimal financial math, dependency & configuration hygiene, and test-suite quality**. Rather than trusting prior sprint reports, core implementation paths were inspected directly and edge cases were actively reproduced against live MariaDB and Flask processes using isolated temporary accounts.

Six real production-readiness gaps were surfaced and fixed during this final audit—including an undeclared dependency (`python-dateutil`) missing from `requirements.txt`, insecure production config defaults (`DEBUG=True`, hardcoded fallback `SECRET_KEY`, `SESSION_COOKIE_SECURE=False`), concurrent registration `1062` duplicate-key HTTP 500 crashes, `TOCTOU` locking gap on concurrent expense updates, `/api/system/diagnostics` and OCR internal path/error disclosure, non-defensive socket cleanup when `rollback()` fails, and `float`-based financial intermediate math.

### Final Verdict
> **READY FOR ACADEMIC DEMONSTRATION**
>
> ExpenseTrack is reliable, secure against OWASP multi-tenant/CSRF/SQLi/XSS/upload vectors, transactionally consistent, and financially accurate for an academic college project demonstration. However, **it is NOT yet classified as `READY FOR CONTROLLED DEPLOYMENT`** due to explicit infrastructure/runtime deployment blockers (missing production WSGI server, process-local in-memory rate-limit state, unpooled direct DB sockets, and local dev database/HTTP configuration) detailed in Section 9.

---

## 2. Verified Functionality

All core user workflows were verified end-to-end against live MariaDB `10.11.8` (`http://127.0.0.1:5000`):
- **Authentication & Sessions:** Registration, login (`demo_student` and isolated accounts), logout (`POST /api/auth/logout`), `GET /api/auth/me`, session fixation reset (`session.clear()`), 24h permanent session expiration (`PERMANENT_SESSION_LIFETIME`), and deleted/tampered session invalidation (`401`).
- **Dashboard & Insights Analytics:** Single-connection monthly summary aggregation, 6-month trend computation using stdlib calendar math (`subtract_months`), rule-based explainable insights (`/api/insights`), empty states, and prior-month comparisons.
- **Expense Lifecycle:** Paginated multi-filter listing (`/api/expenses`), single read, creation, atomic update (`FOR UPDATE` row lock), and deletion with strict `user_id` ownership checks.
- **Budget Engine:** Overall monthly limits (`category_id IS NULL`) and per-category caps serialized per tenant without deadlocks or duplicates, calculating `80%` warning and `100%` exceeded thresholds.
- **Receipt Ingestion & Fallback OCR:** Pillow binary format verification (`PNG`/`JPEG`/`WEBP`), pixel cap (`25MP`), SHA-256 duplicate flagging serialized per user, human-in-the-loop expense confirmation (never auto-creates expenses), safe local private storage fallback when Azure credentials are absent, and graceful OCR fallback when `tesseract.exe` is not on `PATH`.

---

## 3. Security Findings (Pre-Fix & Remediated)

| Finding | Severity | Verification & Remediation |
| :--- | :--- | :--- |
| **Production Config Silent Defaults (`config.py`, `app.py`)** | **Critical (Prod)** | **Pre-Fix:** Reloading with `FLASK_ENV=production` & `FLASK_DEBUG=1` left `DEBUG=True`, `SESSION_COOKIE_SECURE=False`, and the public dev `SECRET_KEY` active.<br>**Fix:** Forced `DEBUG = False` in `production`, defaulted `SESSION_COOKIE_SECURE = True` in `production`, added `Config.validate_runtime_config()` failing fast (`RuntimeError`) in `create_app()` if `SECRET_KEY` is default/placeholder/`<32` chars, and added `ALLOWED_ORIGINS` & `TRUST_PROXY_HEADERS` flags. |
| **Diagnostics & OCR Error/Path Disclosure (`database/db.py`, `profile.py`, `ocr_service.py`)** | **Medium** | **Pre-Fix:** Mocked `OperationalError` in `test_connection()` leaked `"MySQL Operational Error (2003): internal-secret-host:3306"` directly in `/api/system/diagnostics`; `OCRService` failed with raw OS path exceptions; internal `DB_HOST`/`PORT` displayed in all modes.<br>**Fix:** Sanitized `test_connection()` and `OCRService.process_receipt_image` error strings (logging details internally); redacted DB host/port/name and OS binary paths in `/api/system/diagnostics` when `FLASK_ENV=production`. |
| **Multi-Tenant API Authorization (`test_rel_comprehensive_two_tenant_api_isolation`)** | **Verified** | Tested **every** API route and `/uploads/receipts/<file>` with two separate accounts (`User A` vs `User B`). Confirmed `404` on foreign expenses/budgets, `403` on foreign receipt files/attachment, and `409` conflict protection on email collision. |
| **CSRF, Headers, Injection & Rate Limits** | **Verified** | Verified `SameSite=Lax`, `HttpOnly=True`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy`, `403` on cross-origin/cross-port `Origin` & `Referer` headers, `400` on malformed/non-dict JSON, `405` JSON, `413` >5MB upload rejection, path-traversal neutralization, parameterized SQL queries (`100%`), `15/min` login & `10/min` registration IP rate limits resisting `X-Forwarded-For` spoofing, and `.textContent` XSS safety in `showToast`. |

---

## 4. Database & Transaction Findings

* **Live Schema & Constraints (`SHOW CREATE TABLE` Verified):** All 5 InnoDB tables (`users`, `categories`, `uploaded_receipts`, `expenses`, `budgets`) use `utf8mb4_unicode_ci`. Verified active enforcement via tests:
  * Foreign Keys: `fk_expenses_user` (`CASCADE`), `fk_expenses_category` (`RESTRICT`), `fk_expenses_receipt` (`SET NULL`), `fk_budgets_user` (`CASCADE`), `fk_budgets_category` (`CASCADE`), `fk_receipts_user` (`CASCADE`).
  * `CHECK` Constraints: `chk_expense_amount_positive`, `chk_budget_amount_positive`, `chk_budget_month`, `chk_budget_year`.
* **Fixed Concurrent Duplicate Registration (`routes/auth.py`):** 3 barrier-synchronized threads registering the same `username` previously returned `[500, 500, 201]` due to `1062 Duplicate entry` uncaught between `SELECT` and `INSERT`. Now handled cleanly returning **`[201, 409, 409]`**.
* **Fixed Expense Update TOCTOU (`routes/expenses.py`):** Combined ownership check, category verification, and `UPDATE` inside one `with get_db()` transaction using `SELECT ... FOR UPDATE`.
* **Hardened Connection/Socket Cleanup (`database/db.py`):** Wrapped `conn.rollback()`, `cursor.close()`, and `conn.close()` in defensive handlers (`_safe_close`) so broken-pipe rollback failures cannot bypass socket closure (`test_rel_connection_cleanup_and_receipt_file_cleanup_on_failure`).
* **Transaction Rollback & Retry Idempotency:** Multi-step exceptions roll back cleanly; `set_budget()` retries transient InnoDB `1213`/`1205` deadlocks ONLY across atomic pre-commit transactions serialized by `users.id FOR UPDATE` (`[200, 200, 200, 200]` under `Barrier(4)`).
* **Orphan File Cleanup:** Verified failed DB inserts inside `scan_receipt()` unlink temporary local files cleanly (`0` orphaned disk artifacts).

---

## 5. Financial Correctness Findings

* **Transition to Pure `Decimal` Math:** Updated `validate_amount()` (`routes/validators.py`) to return `decimal.Decimal` quantized with `ROUND_HALF_UP` to `0.01`, and refactored `routes/budgets.py`, `routes/dashboard.py`, and `services/insight_service.py` to compute totals, remaining caps, overages, averages, safe daily allowances, and percentages using `Decimal` arithmetic (`ROUND_HALF_UP`), converting to `float` only at final JSON output serialization.
* **Verified Boundary & Calendar Scenarios:**
  * Accepted: `0.01`, `0.10 + 0.20 == 0.30` (zero IEEE-754 tail), `10.125 -> 10.13`, `99999999.99`, leap day `2024-02-29`, month transitions (`Jan 31` / `Feb 1`), year transitions (`Dec 31` / `Jan 1`).
  * Rejected (`400`): `0.001`, `0.004`, `0`, `-0.01`, `100000000.00`, `NaN`, `Infinity`, `-Infinity`, `True`, non-leap `2026-02-29`, invalid calendar dates.
  * Confirmed dashboard/budget/category aggregates match independent SQL `SUM()` queries after create, amount/category edit, and delete mutations.

---

## 6. Performance & Dependency Findings

* **Undeclared Dependency Eliminated (`routes/dashboard.py`, `requirements.txt`):** Replaced `dateutil.relativedelta` (imported in `dashboard.py` yet missing from `requirements.txt`) with pure standard-library `subtract_months()` (`routes/validators.py`). Verified `python -m pip check` passes with **`No broken requirements found`**. *(Note: `bcrypt==4.0.1` in `requirements.txt` is unused because password hashing uses Werkzeug `scrypt`.)*
* **Connection Lifecycle & Query Plans:**
  * Reusing single `with get_db()` connections keeps dashboard (`1` connection), expenses pagination (`1` connection), budgets (`1` connection), and insights (`1` connection) around **`~96–132 ms`** locally on Windows loopback (vs `~840 ms` with 7 separate TCP handshakes).
  * MariaDB `EXPLAIN` plans confirm `idx_expenses_user_date` (`type='ref'`), `idx_expenses_user_category` (`ref`), and `uk_user_category_month_year` (`ref`/`eq_ref`) handle monthly aggregations and category joins cleanly without full table scans.

---

## 7. Remaining Risks and Limitations

1. **External Services Operating in Fallback Mode:** Locally, `tesseract.exe` is absent on `PATH` (OCR runs cleanly in `fallback` manual-verification mode) and `AZURE_STORAGE_CONNECTION_STRING` is unset (receipts store in local `uploads/receipts/`). Neither live Tesseract OCR accuracy on real camera photos nor live Azure Blob Storage upload/SAS behavior can be claimed active without external credentials/binaries.
2. **In-Memory Rate Limiter Scope:** `_RATE_LIMIT_BUCKETS` is local to a single Python process and resets on server restart.
3. **Unpooled Database Sockets:** `database/db.py` creates 1 fresh TCP connection per request (acceptable for student/viva scale; lacks a warm connection pool for high-concurrency traffic).
4. **Local `.env` Development Configuration:** The workspace `.env` uses `FLASK_ENV=development`, empty local `root` DB password on `127.0.0.1`, and `SESSION_COOKIE_SECURE=False` for `http://127.0.0.1:5000` academic demonstration.
5. **Test Suite Honest Assessment:**
   * `tests/test_app.py` (19 tests) and `tests/test_live_server.py` (1 test) rely on pre-seeded `demo_student` (`student@expensetrack.edu`); `test_live_server.py` skips cleanly if Flask server is offline (passed when live).
   * `tests/test_advanced.py` (19 tests) uses isolated UUID-tagged temporary users cleaned up via `finally` teardown. Only failure-injection/outage simulation tests (`OperationalError`, DB insert failure file cleanup, OCR `Image.open` exception, `get_db()` rollback failure) use `unittest.mock.patch`; all concurrency tests run genuinely simultaneously via `threading.Barrier` against live MariaDB.

---

## 8. Test Results & Exact Verification Commands

| Command | Result | Scope & Notes |
| :--- | :--- | :--- |
| `python -m pytest -v` | **43 passed in 36.31s** (`0` failed, `0` skipped) | Executed after all code fixes across `test_advanced.py` (19), `test_app.py` (19), `test_live_server.py` (1), `test_ocr.py` (4). |
| `python tests/test_live_server.py` | **PASSED** (`8 / 8` endpoints `200 OK`) | Live HTTP login, Oct 2026 dashboard (`Rs.7058.0 / Rs.10000.0`), expenses (`22` total), budgets, scan, insights, diagnostics (`MariaDB connected`, `OCR fallback_mode`, `Cloud local_fallback`). |
| `python -m pip check` | **No broken requirements found.** | Verified installed Python dependency tree consistency. |
| `git ls-files` secret audit | **PASSED** | Confirmed `.env` and runtime DB/upload folders are excluded from Git tracking (`.env.example` only). |

*Pre-modification backups of all 13 backend/test files modified during this audit were saved in the agent scratch backup directory prior to editing; existing `demo_student` records (`12` Oct 2026 expenses = `₹7,058.00`) remain 100% preserved.*

---

## 9. Production Deployment Blockers

Before moving from **Academic Demonstration** to **Controlled Deployment**, the following blockers must be resolved:
1. **Production WSGI Server:** Replace Flask dev server (`app.run()`) with a production WSGI server (`waitress` / `gunicorn`) in `requirements.txt` and startup scripts.
2. **Distributed Rate Limit Backend:** Replace process-local `_RATE_LIMIT_BUCKETS` with Redis (`Flask-Limiter`) if running multi-worker processes.
3. **Production Environment Secrets & DB Credentials:** Provision a non-root least-privilege MySQL/MariaDB user with a strong password, set `FLASK_ENV=production`, generate a 64-byte random `SECRET_KEY`, and deploy behind HTTPS TLS termination so `SESSION_COOKIE_SECURE=True` applies on live traffic.
4. **DB Connection Pooling (Recommended):** Add PyMySQL connection pooling (e.g., `DBUtils.PooledDB` or SQLAlchemy queue pool) to remove ~100ms TCP handshake latency under higher user load.
5. **Optional Cloud/OCR Verification:** If OCR auto-fill or Azure Blob persistence is required in production, install Tesseract binary on the host image and configure & verify `AZURE_STORAGE_CONNECTION_STRING` before launch.

---

## 10. Final Readiness Verdict

**Verdict: `READY FOR ACADEMIC DEMONSTRATION`**

ExpenseTrack meets all functional, relational database, financial precision, security hardening, and UI/UX stability standards required for a college academic demonstration on localhost, with transparent documentation of its fallback integrations and clear infrastructure checklist before multi-user production deployment.

