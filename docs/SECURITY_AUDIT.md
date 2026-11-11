# ExpenseTrack: Application & Cloud Security Audit Report

**Audit Date:** 2026-11-11  
**Compliance Standard:** OWASP Top 10 (2021), OWASP API Security Top 10  
**Target Environment:** Flask 3.0.3 + MariaDB 10.11 (`expensetrack`)

---

## 1. Executive Security Summary

During the Engineering Stabilization Sprint, the ExpenseTrack backend, database interface, session architecture, and file upload pipeline underwent a systematic security audit. All identified high and medium severity security weaknesses have been remediated directly in source code and verified with automated tests.

---

## 2. Implemented Protections & Remediated Vulnerabilities

### 2.1 Authentication & Session Lifecycle
- **Password Storage:** Passwords are hashed using **Scrypt KDF** (`werkzeug.security.generate_password_hash(..., method="scrypt")`), combining a unique cryptographic salt per account with memory-hard parameters resistant to GPU/ASIC brute forcing.
- **Session Fixation Prevention (Fixed):** Both `login()` and `register()` now invoke `session.clear()` before allocating session state (`user_id`, `username`, `full_name`).
- **Session Expiration (Fixed):** `session.permanent = True` is now activated upon login and registration so Flask strictly enforces the configured `PERMANENT_SESSION_LIFETIME = 86400` (24-hour TTL).
- **Cookie Security Directives:** Configured with `SESSION_COOKIE_HTTPONLY = True` (mitigates XSS session theft) and `SESSION_COOKIE_SAMESITE = "Lax"` (mitigates CSRF attacks).

### 2.2 Brute-Force & Credential Stuffing Mitigation (Fixed)
- Implemented a lightweight sliding-window IP rate limiter (`routes/validators.py: rate_limit`) protecting authentication endpoints:
  - `POST /api/auth/login`: Maximum 15 attempts per minute per IP.
  - `POST /api/auth/register`: Maximum 10 registrations per minute per IP.
  - Returns standard `429 Too Many Requests` with retry guidance when thresholds are tripped.

### 2.3 Cross-Origin & CSRF Guards (Fixed)
- **Tightened CORS Policy:** Replaced wildcard `CORS(app)` with explicit local origin allowances (`http://127.0.0.1:5000`, `http://localhost:5000`) and credential constraints.
- **Origin Verification Middleware:** Implemented `@app.before_request` verification rejecting cross-origin `POST`, `PUT`, `DELETE`, and `PATCH` requests carrying mismatched `Origin` headers with `403 Forbidden`.
- **Baseline Security Headers:** Added `@app.after_request` middleware attaching:
  - `X-Content-Type-Options: nosniff` (MIME confusion defense)
  - `X-Frame-Options: SAMEORIGIN` (Clickjacking defense)
  - `Referrer-Policy: strict-origin-when-cross-origin`

### 2.4 Broken Object-Level Authorization (BOLA / IDOR) Defense
- All resource-level CRUD routes bind database actions strictly to the server-side authenticated session ID (`get_current_user_id()`):
  - `GET / PUT / DELETE /api/expenses/<id>`: Enforces `WHERE id = %s AND user_id = %s`.
  - `DELETE /api/budgets/<id>`: Enforces `WHERE id = %s AND user_id = %s`.
  - `GET /uploads/receipts/<filename>`: Enforces receipt ownership lookup before streaming binary bytes (`abort(403)` otherwise).
  - `POST /api/expenses` (Fixed): Explicitly returns `403 Forbidden` if a user attempts to attach an unauthorized `receipt_id`.

### 2.5 Input Validation & SQL Injection Defense
- **100% Parameterized Queries:** All SQL executions use PyMySQL prepared parameterization (`%s` placeholders passed separately via DB-API tuples).
- **Strict Type & Boundary Validators (`routes/validators.py`):**
  - `validate_amount`: Enforces `Decimal` math, `0.01 <= amount <= 99999999.99`, rejecting `NaN`, `Infinity`, negative values, and column overflow bugs.
  - `validate_date`: Enforces strict `YYYY-MM-DD` date strings within `[2020..2050]`.
  - `validate_string`: Rejects non-string JSON types (`int`/`list` crashes) and constrains input widths matching MariaDB `VARCHAR` limits.
  - `parse_int_param`: Rejects malformed numeric query arguments cleanly with HTTP `400 Bad Request`.

### 2.6 File Upload Security (Fixed)
- **Extension Whitelisting:** Accepts only `.png`, `.jpg`, `.jpeg`, `.webp`.
- **Magic-Byte Content Verification (Fixed):** Uses Pillow `Image.open(io.BytesIO(...)).verify()` to validate genuine binary image headers, rejecting disguised executables or spoofed scripts renamed `.png`.
- **Path Traversal & Collision Defense:** Uses `werkzeug.utils.secure_filename` followed by `uuid.uuid4().hex` file renaming.
- **Size Guard:** Rejects empty (`0 byte`) uploads and payloads exceeding `5MB` (`413 Payload Too Large`).

### 2.7 Internal Information Leakage Prevention (Fixed)
- Removed all raw Python/PyMySQL exception strings (`str(e)`) from API error JSON responses across `auth.py`, `expenses.py`, `budgets.py`, `receipts.py`, and `profile.py`. Technical details are logged strictly server-side via `current_app.logger.error`.

---

## 3. Residual Risks & Production Recommendations

| Risk / Limitation | Current Mitigation / Context | Production Remediation |
| :--- | :--- | :--- |
| **HTTP Plaintext Transport (Local)** | Application runs on `http://127.0.0.1:5000` for offline viva portability; `SESSION_COOKIE_SECURE` is `False`. | Deploy behind TLS/HTTPS reverse proxy (Nginx / Azure App Service) and toggle `SESSION_COOKIE_SECURE = True`. |
| **In-Memory Rate Limiter** | Works well for single-process Flask runtime (`app.py`). | Replace in-memory bucket dictionary with Redis (`Flask-Limiter`) if deploying multiple worker containers. |
| **CSRF Token Absence for Form Submits** | JSON API endpoints validate Origin + SameSite cookies. | Add cryptographic CSRF double-submit cookies or `Flask-WTF` tokens if adding standard HTML form POST actions. |

