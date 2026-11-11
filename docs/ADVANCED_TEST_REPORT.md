# ExpenseTrack: Advanced Backend Stress Test, Concurrency & Security Validation Report

**Audit Date:** 2026-11-11  
**Target Codebase:** `d:\3rd sem project` (Starting from 24-test Sprint 1 baseline)  
**Environment:** Python 3.14.2 · Flask 3.0.3 (`127.0.0.1:5000`) · MariaDB 10.11.8 (`127.0.0.1:3306`, DB `expensetrack`)  
**Isolation Policy:** Executed strictly with temporary ephemeral test accounts cleaned up via `finally` teardown. Zero user or demo records modified (`demo_student` remains intact at 12 Oct 2026 expenses = `₹7,058.00`).  

---

## 1. Executive Summary

Following the initial stabilization sprint (24 tests passing), an intensive second-level engineering audit probed the application under **boundary financial inputs, barrier-synchronized concurrency, security bypass vectors, corrupted/disguised receipt uploads, SQL `EXPLAIN` query plans, and frontend DOM integration checks**.

The stress probe **reproduced 13 real defects** that passed baseline testing—including an InnoDB `1213 Deadlock` under simultaneous overall budget creation, an `AttributeError` 500 crash on JSON array bodies (`[1,2,3]`), sub-cent SQL `CHECK` constraint 500 crashes (`0.001`), IEEE-754 float subtraction tails (`0.20000000000000284`), spoofed `X-Forwarded-For` rate-limit bypasses, cross-port CSRF tolerance, GIF/long-MIME receipt upload bugs, 4-digit OCR amount truncation (`1500.00 -> 150.0`), a 7-connection bottleneck (`~840ms`) on the dashboard summary endpoint, and a `showToast` DOM XSS injection risk.

All 13 confirmed defects were fixed cleanly in source code without schema resets or feature bloat. Regression tests covering every scenario were added in [`tests/test_advanced.py`](../tests/test_advanced.py), expanding the full automated suite to **37 passing pytest tests (0 failures)**.

---

## 2. Reproducible Defects Discovered During Stress Audit & Fixes Implemented

| ID | Category | Failure Discovered (Pre-Fix Evidence) | Root Cause | Implemented Fix |
| :--- | :--- | :--- | :--- | :--- |
| **ADV-01** | Concurrency | **Deadlock (`1213`):** 4 barrier-synchronized threads creating a new overall budget (`category_id=None`) returned `statuses=[200, 500, 500, 500]` (`Deadlock found when trying to get lock`). | Simultaneous `SELECT ... FOR UPDATE` on non-existent rows held InnoDB gap/insert-intention locks before `INSERT`, deadlocking when all 4 upgraded to X locks. | Serialized `set_budget()` per tenant via parent row lock `SELECT id FROM users WHERE id = %s FOR UPDATE` + 3-attempt transient deadlock (`1213`/`1205`) backoff retry in `routes/budgets.py`. Post-fix: `[200, 200, 200, 200]`, 1 row. |
| **ADV-02** | Concurrency | **Concurrent Receipt Race:** 4 barrier-synchronized identical receipt scans all returned `[(201, False), (201, False), (201, False), (201, False)]`. | Duplicate hash `SELECT` and `INSERT` ran on separate connections outside a lock, allowing parallel scans to miss prior inserts. | Wrapped hash duplicate check + metadata `INSERT` in `with get_db()` serialized per user via `users FOR UPDATE` in `routes/receipts.py` (with local file cleanup on DB error). Post-fix: `1 False, 3 True`. |
| **ADV-03** | Financial | **Sub-cent 500 Crash:** `POST /api/expenses` with `amount: 0.001` returned HTTP `500` (`CONSTRAINT chk_expense_amount_positive failed`). | `validate_amount()` checked `d > 0.00` *before* `round(d, 2)` rounded `0.001` to `0.00`. | Enforced `d < Decimal("0.01")` pre-rounding and `ROUND_HALF_UP` bounds validation cleanly in `routes/validators.py`. Returns HTTP `400`. |
| **ADV-04** | Financial | **Missing Budget Month/Year 500 Crash:** `POST /api/budgets` missing `month` returned HTTP `500` (`Column 'month' cannot be null`). | `parse_int_param(..., default=None)` returned `None` instead of raising `ValueError` for mandatory fields; `bool` (`True`) also passed `int()`. | Added `required=True` and boolean/float rejection in `parse_int_param()`, enforced for `month`, `year`, and `category_id`. Returns HTTP `400`. |
| **ADV-05** | Financial | **Float Precision Tail:** `budget=100.30, spent=100.10` returned JSON `"remaining": 0.20000000000000284`. | Raw Python float subtraction `limit - spent` without `round(..., 2)` in `budgets.py`, `dashboard.py`, and `insight_service.py`. | Applied `round(..., 2)` on all balance and breakdown metrics across `budgets.py`, `dashboard.py`, and `insight_service.py`. Returns exact `0.2`. |
| **ADV-06** | Security / API | **Non-Dict JSON 500 Crash:** Sending `[1, 2, 3]` with `Content-Type: application/json` crashed with `AttributeError: 'list' object has no attribute 'get'`. | Routes relied on `request.get_json(silent=True) or {}`, passing valid non-dict JSON types (`list`, `int`, `str`). | Added `get_json_dict()` in `routes/validators.py` rejecting malformed JSON and non-object JSON with HTTP `400` across `auth.py`, `expenses.py`, `budgets.py`, `profile.py`. |
| **ADV-07** | API | **HTML `405` on `/api/*`:** `PATCH /api/expenses/1` returned `text/html; charset=utf-8` instead of JSON. | `app.py` defined error handlers for 400/403/404/413/500, omitting 405. | Added `@app.errorhandler(405)` in `app.py` returning JSON `405 Method Not Allowed` for `/api/*`. |
| **ADV-08** | Security | **Stale Deleted User Session 500 Crash:** Deleting a logged-in user and calling `POST /api/expenses` hit `IntegrityError (1452, fk_expenses_user)` (`500`). | `@login_required` checked key presence only; non-int session values also weren't type-guarded. | Hardened `@login_required` (`isinstance(uid, int)` check) in `routes/auth_helper.py` and detected missing parent users on auth/profile/budget/expense mutations, clearing session and returning `401`. |
| **ADV-09** | Security | **Rate Limit `X-Forwarded-For` Bypass:** 18 logins with rotating `X-Forwarded-For: 10.0.0.i` returned `0` HTTP `429` blocks. | `rate_limit()` read client-controlled `X-Forwarded-For` header directly without proxy trust verification. | Keyed rate-limiter strictly on `request.remote_addr` (unless `TRUST_PROXY_HEADERS` explicitly configured) with bucket pruning in `routes/validators.py`. |
| **ADV-10** | Security | **Cross-Port CSRF Origin & Missing `Referer` Check:** Origin check ignored port (`http://localhost:9999` allowed if targeting `127.0.0.1:5000`). | `check_csrf_origin()` compared `parsed.hostname` only, ignoring `netloc` port mismatches and missing `Referer` checks. | Updated `check_csrf_origin()` in `app.py` to enforce exact `parsed.netloc` host+port allowlists on both `Origin` and fallback `Referer`. |
| **ADV-11** | Receipt / Security | **Spoofed GIF Accepted / Unicode Extension Lost / Long MIME 500:** GIF renamed `.png` returned `201`; `🧾.png` saved extensionless; 126-char MIME crashed MySQL (`Data too long for column 'mime_type'`). | `Image.verify()` accepted GIF/BMP; `secure_filename("🧾.png")` became `"png"` (`Path("png").suffix == ""`); unverified `file.content_type` passed to DB. | Whitelisted strictly `img_probe.format in {"PNG","JPEG","WEBP"}` + 25MP resolution cap; derived extension & MIME solely from Pillow format (`routes/receipts.py`). |
| **ADV-12** | OCR | **4-Digit & Multi-Amount Truncation:** `"Paid Rs. 1500.00 to Swiggy"` returned `150.0`; `"Item: Rs. 200.00\nPaid Total: Rs. 1500.00"` returned `200.0`. | Regex `[0-9]{1,3}(?:,[0-9]{3})*` truncated uncomma'd 4+ digit numbers at 3 digits and lumped `"total\|paid"` with generic currency prefixes. | Rewrote patterns in `services/ocr_service.py` to `(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?` and prioritized `total`/`paid` labels above generic currency markers. |
| **ADV-13** | Performance & FE | **7-Connection Dashboard Overhead + Stale Bars + Toast XSS:** Dashboard executed 7 TCP connect handshakes (`839.53ms`), full table scans (`ALL`) on monthly filters, `showToast` interpolated `${message}` via `innerHTML`, and unbudgeted months kept prior progress bar widths. | `query_db()` opened/closed a new TCP connection per query; `MONTH()`/`YEAR()` bypassed `idx_expenses_user_date`; `dashboard.js` skipped `else` branch reset; `api.js` used `innerHTML`. | Reused 1 `with get_db()` connection + `date_range_for_month()` (`type='ref'`, **~96–124ms**); escaped `showToast` with `.textContent`; reset unbudgeted KPI bars; added double-submit `btn.disabled` guards + responsive header/toast CSS. |

---

## 3. Detailed Test Execution Matrix

All 37 tests below are automated in `tests/test_advanced.py` (13), `tests/test_app.py` (19), `tests/test_ocr.py` (4), and `tests/test_live_server.py` (1), and executed after final fixes.

### 3.1 Category 1: Financial Correctness
| Test Scenario | Expected | Actual Result | Status | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| Boundary `₹0.01`, `10.125`, `₹99,999,999.99` | Saved with exact `ROUND_HALF_UP` `DECIMAL(10,2)` precision | `0.01`, `10.13`, `99999999.99` saved & verified matching SQL `SUM()` | **PASS** | `test_fin_boundary_amounts_and_decimal_precision` |
| Out-of-bounds/invalid amounts (`0.001`, `0`, `-0.01`, `1e8`, `NaN`, `Infinity`, `True`) | Rejected with HTTP `400`, zero 500s | All 10 payloads returned `400 Validation Error` | **PASS** | `test_fin_boundary_amounts_and_decimal_precision` |
| Budget remaining IEEE-754 subtraction (`100.30 - 100.10`) | Exact `0.2`, never float tail | Both `/api/budgets` & `/api/dashboard/summary` returned `0.2` | **PASS** | `test_fin_float_subtraction_precision_and_budget_validation` |
| Budget POST missing `month` or `year` | HTTP `400` validation error | Returned `400` (`Month is required.`) | **PASS** | `test_fin_float_subtraction_precision_and_budget_validation` |
| Leap day (`2024-02-29`), non-leap (`2026-02-29`), invalid dates (`2026-04-31`, `2019-12-31`) | `2024-02-29` `201`; invalid dates `400` | `2024-02-29` totaled `290.0`; all 6 invalid dates returned `400` | **PASS** | `test_fin_calendar_transitions_leap_year_and_mutation_aggregates` |
| Month (`Jan 31`/`Feb 1`) & Year (`Dec 31`/`Jan 1`) boundaries | Strict isolation per month/year | Verified exact dashboard sums per boundary matching independent SQL | **PASS** | `test_fin_calendar_transitions_leap_year_and_mutation_aggregates` |
| Expense edit, category reassignment, & deletion recalculation | Aggregates update identically to DB | Shifted Travel->Education (`725.50`), deleted -> `0.0` matching SQL | **PASS** | `test_fin_calendar_transitions_leap_year_and_mutation_aggregates` |

### 3.2 Category 2: Database Concurrency (Barrier-Synchronized Threads)
| Test Scenario | Expected | Actual Result | Status | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| 4 simultaneous `POST /api/expenses` (`100.25` each) | 4x `201`, sum = `401.00` | `[201, 201, 201, 201]`, SQL sum `401.00`, count `4` | **PASS** | `test_conc_simultaneous_operations_and_deadlock_safety` |
| 4 simultaneous NEW overall budgets (`category_id=None`, `Barrier(4)`) | 4x `200`, 1 row, 0 deadlocks | `[200, 200, 200, 200]`, SQL count `1` | **PASS** | `test_conc_simultaneous_operations_and_deadlock_safety` |
| 4 simultaneous NEW category budgets (`Barrier(4)`) | 4x `200`, 1 row | `[200, 200, 200, 200]`, SQL count `1` | **PASS** | `test_conc_simultaneous_operations_and_deadlock_safety` |
| 4 simultaneous edits to same expense (`Barrier(4)`) | Serialized `200`, consistent row | `[200, 200, 200, 200]` | **PASS** | `test_conc_simultaneous_operations_and_deadlock_safety` |
| 4 simultaneous deletes on same expense (`Barrier(4)`) | 1x `200`, 3x `404` | `sorted == [200, 404, 404, 404]` | **PASS** | `test_conc_simultaneous_operations_and_deadlock_safety` |
| 4 simultaneous identical receipt uploads (`Barrier(4)`) | 1x `is_duplicate=False`, 3x `True` | All `201`; `dup_flags.count(False)==1`, `.count(True)==3` | **PASS** | `test_conc_simultaneous_operations_and_deadlock_safety` |
| Multi-step transaction rollback on exception (`with get_db()`) | Step 1 rolled back cleanly | `0` rows persisted after `RuntimeError` in step 2 | **PASS** | `test_conc_transaction_rollback_and_db_failure_handling` |
| Database connection outage (`OperationalError(2003, ...)`) | Generic `500` JSON, zero DB secrets | Returned `500` JSON; host/secret absent from response | **PASS** | `test_conc_transaction_rollback_and_db_failure_handling` |

### 3.3 Category 3: Security & Authorization Testing
| Test Scenario | Expected | Actual Result | Status | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| Cross-user CRUD (`GET`/`PUT`/`DELETE` expense/budget) & receipt attach | `404` for resources, `403` for receipt | All unauthorized IDs rejected `404`/`403` | **PASS** | `test_multi_user_isolation` (`test_app.py`) |
| Cross-user `/uploads/receipts/<file>` & traversal (`../../config.py`) | `403` / `404` blocked | Cross-user returned `403`; traversal blocked `403`/`404` | **PASS** | `test_sec_receipt_file_ownership_and_path_traversal` |
| ID tampering (`/expenses/-1`, `/expenses/abc`, `category_id=True`) | `404` / `400` cleanly | `-1`/`abc` -> `404`; `category_id=True` -> `400` | **PASS** | `test_sec_csrf_origin_xss_sqli_malformed_json_and_methods` |
| Missing cookies, tampered non-int session, expired TTL, deleted user session | `401` API / `302` HTML + cleared cookie | Expired `PERMANENT_SESSION_LIFETIME`, string ID, and stale deleted user all returned `401` | **PASS** | `test_sec_session_expiration_tampering_and_stale_account` |
| Login (`15/min`) & register (`10/min`) limits + `X-Forwarded-For` spoof | `429` despite rotating headers | 18 spoofed logins triggered 3x `429`; 12 registers -> 2x `429` | **PASS** | `test_sec_rate_limiting_and_xff_spoof_resistance` |
| Malicious `Origin`, `Origin: null`, cross-port `:9999`, malicious `Referer` | `403 Forbidden` | All 4 cross-origin/referers returned `403` | **PASS** | `test_sec_csrf_origin_xss_sqli_malformed_json_and_methods` |
| XSS & SQLi payloads (`<img onerror>`, `' OR '1'='1'; DROP TABLE...`) | Stored parameterized, no SQL damage | Saved cleanly; search returned `200`; `categories` intact | **PASS** | `test_sec_csrf_origin_xss_sqli_malformed_json_and_methods` |
| Malformed/non-dict JSON (`{bad`, `[1,2,3]`, `123`), 405 method, >5MB body | JSON `400`, `405`, `413` | All returned JSON with exact expected status codes | **PASS** | `test_sec_csrf_origin_xss_sqli_malformed_json_and_methods` |

### 3.4 Category 4: Receipt & OCR Testing
| Test Scenario | Expected | Actual Result | Status | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| Valid PNG, JPEG, WEBP, & Unicode `🧾.png` w/ long `Content-Type` | `201` with verified extension & MIME | All saved cleanly with `.png`/`.jpg`/`.webp` | **PASS** | `test_receipt_formats_validation_and_manual_confirmation_only` |
| Empty `0B`, corrupted binary, spoofed GIF `.png`, `.svg`, `.pdf` | Rejected `400` | All 5 returned `400 Validation Error` | **PASS** | `test_receipt_formats_validation_and_manual_confirmation_only` |
| Confirmation workflow integrity | Uploaded receipts do NOT auto-create expenses | DB `expenses` count remained `0` post-scan | **PASS** | `test_receipt_formats_validation_and_manual_confirmation_only` |
| OCR unavailable fallback, garbage text, missing amount, invalid date | Clean `fallback` / `None` / safe fallback date | Zero exceptions; fallback status returned | **PASS** | `test_ocr_resilient_fallback_on_missing_file`, `test_ocr_extraction_edge_cases` |
| Uncomma'd 4-digit & multiple amounts, >200-char merchant text | Extracts total `1500.0`, bounds merchant `<=50` chars | `"Grand Total: Rs. 1500.00"` -> `1500.0`; merchant `len <= 50` | **PASS** | `test_ocr_extraction_edge_cases` |

### 3.5 Category 5 & 6: API Reliability, Performance & MariaDB `EXPLAIN` Plans
* **Connection Lifecycle Measurement:**
  * Opening 7 separate TCP connections on Windows loopback measured `719.53 ms` (`~102 ms` per handshake).
  * Reusing 1 connection via `with get_db()` across all 7 queries measured `109.03 ms` (`~6.6x` faster).
* **Post-Fix Endpoint Measurements (`1` DB connection for dashboard):**
  * `/api/dashboard/summary?month=10&year=2026`: `200 OK`, **`1` connection**, `96.77 ms` – `124.70 ms` (down from **`839.53 ms`** / `7` connections!)
  * `/api/expenses?page=1&limit=20`: `200 OK`, **`1` connection**, `119.74 ms`
  * `/api/budgets?month=10&year=2026`: `200 OK`, **`1` connection**, `107.41 ms`
  * `/api/insights?month=10&year=2026`: `200 OK`, **`1` connection**, `132.22 ms`
* **MariaDB `EXPLAIN` Plan Verification:**
  * Non-sargable legacy `MONTH(expense_date) = 10 AND YEAR(expense_date) = 2026`: `type='ALL'`, `key=None`, `rows=23`, `Extra='Using where'` (full table scan).
  * Updated sargable `expense_date >= '2026-10-01' AND expense_date <= '2026-10-31'`: **`type='ref'`**, **`key='idx_expenses_user_date'`**, `rows=12`, `Extra='Using index condition'`!
  * Category Aggregation: `c` (`index` `PRIMARY`), `e` (`ref` `idx_expenses_user_category`).
  * Budgets Overall Lookup: `ref` `uk_user_category_month_year`.
  * Expenses Pagination (`LIMIT 20 OFFSET 0`): `e` uses `idx_expenses_user_category` (`ref`), ordered cleanly for UI.

### 3.6 Category 7: Frontend Integration & Assets Verification
* **JS Syntax Audit:** `node --check` v24.13.0 verified all 6 external `.js` files and all inline `<script>` blocks across all 8 templates with 0 syntax errors.
* **DOM Reference & Asset Completeness:** Verified all `getElementById` calls in `dashboard.js` (31), `expenses.js` (21), `budgets.js` (16), `scan.js` (18), and `insights.js` (12) exist in rendered HTML (`missing=set()`). All static assets across `/auth`, `/dashboard`, `/expenses`, `/budgets`, `/scan`, `/insights`, and `/profile` returned HTTP `200 OK`.
* **Headless Browser Render Check:** `msedge.exe --headless --dump-dom http://127.0.0.1:5000/auth` rendered full interactive DOM cleanly with zero JS runtime console errors.

---

## 4. Final Automated Regression Results

```text
$ python -m pytest -v
============================= 37 passed in 54.99s =============================
```

* `tests/test_advanced.py`: **13 / 13 passed**
* `tests/test_app.py`: **19 / 19 passed**
* `tests/test_live_server.py`: **1 / 1 passed**
* `tests/test_ocr.py`: **4 / 4 passed**

---

## 5. Remaining Risks & Production Notes

1. **In-Memory Rate Limit Store:** `_RATE_LIMIT_BUCKETS` lives in Python memory per worker process. Multi-worker production deployments (e.g., Gunicorn with >1 worker) should migrate this state to Redis (`Flask-Limiter`).
2. **Local Plaintext Transport (`HTTP`):** `SESSION_COOKIE_SECURE` stays `False` for `http://127.0.0.1:5000` academic demos; production cloud hosting behind TLS must set `SESSION_COOKIE_SECURE = True`.
3. **External Native OCR & Azure Blob Credentials:** Native `tesseract.exe` binary and remote `AZURE_STORAGE_CONNECTION_STRING` are absent in this offline workspace; both operate intentionally via tested fallback paths (`fallback` mode and local `uploads/receipts/` vault).
4. **Pagination `ORDER BY` Sort on Large Ledgers:** `expenses.py` filters dynamically with optional `LIKE '%search%'` and `ORDER BY e.expense_date DESC, e.id DESC`; if tables grow beyond ~100k rows per user, adding a covering index `(user_id, expense_date DESC, id DESC)` or full-text search would prevent filesorts on filtered pagination.

