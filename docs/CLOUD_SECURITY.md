# ExpenseTrack – Cloud Security & Application Hardening Specification

## 1. Security Architecture & Threat Model

ExpenseTrack adopts a **Defense-in-Depth** security architecture aligned with the **OWASP Top 10 Web Application Security Risks** and Azure Cloud Security standards.

---

## 2. Authentication & Credential Storage

### 2.1 Cryptographic Password Hashing
- **Algorithm:** **Scrypt** (`scrypt:32768:8:1`).
- **Mechanism:** Passwords are never stored in plaintext. Scrypt provides computational and memory hardness, offering superior resilience against GPU-accelerated brute-force and dictionary attacks compared to legacy MD5 or SHA-1 hashes.
- **Salt:** A cryptographically random unique salt is generated per user hash, preventing precomputed rainbow table attacks.

### 2.2 Session Security
- **Cookie Security Attributes:**
  * `HttpOnly = True`: Prevents client-side JavaScript from accessing session cookies via `document.cookie`, mitigating Cross-Site Scripting (XSS) session hijacking.
  * `SameSite = 'Lax'`: Protects state-changing requests from Cross-Site Request Forgery (CSRF).
  * `Secure = True`: Enforced in production environments using HTTPS (TLS 1.3).
  * `Session Lifetime`: Expired after 24 hours of inactivity.

---

## 3. Authorization & Multi-Tenant Isolation

### 3.1 Server-Side Access Control
Every protected API endpoint and web route is guarded by the `@login_required` decorator.

### 3.2 Tenant Isolation Check
To prevent **Insecure Direct Object References (IDOR)**, all database mutations (`UPDATE`, `DELETE`) and queries (`SELECT`) strictly incorporate the authenticated user's ID:

```python
# Server-side ownership verification enforced in SQL
existing = query_db(
    "SELECT id FROM expenses WHERE id = %s AND user_id = %s;",
    (expense_id, current_user_id),
    one=True
)
if not existing:
    return jsonify({"error": "Not Found", "message": "Expense not found or unauthorized."}), 404
```
 даже if an attacker tampers with `expense_id` in request URLs or payloads, the server rejects the request with HTTP 404/403.

---

## 4. Input Validation & Safe File Processing

### 4.1 Strict Type & Range Verification
- Monetary amounts must be strictly positive: `amount > 0.00` enforced at both Python validation layer and MySQL `CHECK` constraint.
- Dates must conform to ISO 8601 `YYYY-MM-DD` and represent valid calendar dates (`datetime.strptime`).
- Usernames must conform to alphanumeric regex `^[A-Za-z0-9_]{3,30}$`.

### 4.2 File Upload Hardening
- **Size Limit:** Capped at 5 MB (`Config.MAX_CONTENT_LENGTH = 5242880`).
- **File Type Whitelisting:** Strictly limited to `{"png", "jpg", "jpeg", "webp"}`.
- **Directory Traversal Protection:** User filenames are sanitized using `werkzeug.utils.secure_filename` before disk operations.
- **Private Image Serving:** Receipt downloads (`/uploads/receipts/<filename>`) verify ownership in MySQL before serving content via `send_from_directory()`.

---

## 5. SQL Injection Prevention

ExpenseTrack enforces **100% Parameterized SQL Execution** across all database interactions. PyMySQL automatically escapes parameters using the `%s` format placeholder, guaranteeing that user input is treated strictly as data literals and never as executable SQL tokens:

```python
# SAFE: Parameterized Query
query_db(
    "SELECT * FROM expenses WHERE user_id = %s AND merchant LIKE %s;",
    (user_id, f"%{search}%")
)

# STRICTLY FORBIDDEN IN EXPENSETRACK:
# f"SELECT * FROM expenses WHERE merchant = '{search}'"  <-- ELIMINATED
```

---

## 6. Sensitive Financial Privacy Rules

- **Zero-Trust Payment Credentials:** ExpenseTrack never requests, parses, or stores UPI PINs, card CVVs, one-time passwords (OTPs), or banking passwords.
- **OCR Redaction:** Extracted OCR text is filtered to prevent accidental persistence of security codes.

