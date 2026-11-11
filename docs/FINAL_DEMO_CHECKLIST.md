# ExpenseTrack – Final Academic Demonstration Checklist

**Project:** ExpenseTrack – Smart Student Expense Manager  
**Local Application URL:** `http://127.0.0.1:5000`  
**Database Engine:** MariaDB `10.11.8` (`expensetrack` on `127.0.0.1:3306`)  
**Validation Status:** `READY FOR ACADEMIC DEMONSTRATION` (`43 / 43` automated pytest cases passing + full 15-step real-browser E2E journey, cross-tenant security check, and `375px` / `768px` / `1440px` dark/light UI audit passed with zero console or API errors)

---

## 1. Exact Startup Commands & Database Requirements

### Database Startup Requirements
- **Required Engine:** MySQL 8.0+ or MariaDB `10.11.x` listening on `127.0.0.1:3306` with database `expensetrack` (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` loaded from `.env`).
- **Local Workspace MariaDB Startup (Terminal 1):**
  ```powershell
  & "D:\3rd sem project\.mariadb_server\mariadb-10.11.8-winx64\bin\mariadbd.exe" --datadir="D:\3rd sem project\.mariadb_server\data" --port=3306 --console
  ```
- **Schema / Re-Seed Caution:** Do **not** run `python database/init_db.py` before a demonstration unless you intentionally want to wipe and reset the database—`database/schema.sql` executes `DROP TABLE IF EXISTS` across all 5 tables (`users`, `categories`, `uploaded_receipts`, `expenses`, `budgets`).

### Flask Web Application Startup (Terminal 2)
```powershell
cd "D:\3rd sem project"
pip install -r requirements.txt
python app.py
```
On startup, `app.py` must print `[+] MySQL Database Status: Connected` and `[*] Starting local web server on http://127.0.0.1:5000`.

### Pre-Demo Automated Sanity Check (Optional)
```powershell
python -m pytest -v
python tests/test_live_server.py
```

---

## 2. Demo Login Credentials (Local Demonstration Only)

> **Security Notice:** These credentials apply strictly to the pre-seeded local academic database for localhost viva demonstration. Never deploy default credentials or local development `.env` settings to production.

| Field | Value |
| :--- | :--- |
| **Account Holder** | Aarav Sharma (`@demo_student`) |
| **Email / Identifier** | `student@expensetrack.edu` (or `demo_student`) |
| **Password** | `Password123!` |
| **Auth Shortcut** | Click **1-Click Fast Pass ->** on `/auth` to auto-populate credentials |

---

## 3. Complete Application Routes Inventory

### Page & File Routes
| Route | Blueprint | Auth Required | Purpose |
| :--- | :--- | :--- | :--- |
| `/`, `/dashboard` | `dashboard` | Yes | Bento financial overview, KPIs, Chart.js Bar/Area & Donut charts |
| `/auth`, `/login`, `/register` | `auth` | Public | Student sign-in, account registration, 1-click demo autofill |
| `/expenses` | `expenses` | Yes | Search/category/date filtering, pagination, expense edit & delete modals |
| `/budgets` | `budgets` | Yes | Monthly overall cap & category limits, 80%/100% warnings, limit removal |
| `/scan` | `receipts` | Yes | Receipt image upload, SHA-256 duplicate flag, OCR / manual verification form |
| `/insights` | `insights` | Yes | Rule-based pacing advice, horizontal category comparison chart & share table |
| `/profile` | `profile` | Yes | Profile editing (live sidebar sync), password update, live diagnostics |
| `/uploads/receipts/<filename>` | `receipts` | Yes (Owner) | Authenticated private image delivery for local receipt files |

### JSON API Routes
| Method & Endpoint | Purpose |
| :--- | :--- |
| `POST /api/auth/register` | Register student account (Scrypt KDF, rate-limited `10/min`, HTTP `201` / `409`) |
| `POST /api/auth/login` | Authenticate user, rotate session (`HttpOnly`, `SameSite=Lax`, rate-limited `15/min`) |
| `POST /api/auth/logout` | Clear session state cleanly |
| `GET /api/auth/me` | Return current authenticated user profile |
| `GET /api/dashboard/summary` | Single-connection KPI, 6-month trend, category chart & recent ledger feed (`?month=&year=`) |
| `GET /api/expenses/categories` | Fetch the 8 standardized expense categories |
| `GET /api/expenses` | Paginated, filtered transaction listing (`page`, `limit`, `category_id`, `start_date`, `end_date`, `merchant`, `search`) |
| `POST /api/expenses` | Create expense with `Decimal` validation and optional owned `receipt_id` verification |
| `GET /api/expenses/<int:expense_id>` | Fetch single expense record scoped to authenticated `user_id` |
| `PUT /api/expenses/<int:expense_id>` | Atomic `FOR UPDATE` row-locked expense update scoped to `user_id` |
| `DELETE /api/expenses/<int:expense_id>` | Delete expense record scoped to `user_id` |
| `GET /api/budgets` | Fetch overall + per-category spending, limits, percentages, and threshold statuses (`?month=&year=`) |
| `POST /api/budgets` | Serialized atomic upsert (`users.id FOR UPDATE`) of overall or category monthly budget |
| `DELETE /api/budgets/<int:budget_id>` | Delete a configured budget limit scoped to `user_id` |
| `POST /api/receipts/scan` | Validate PNG/JPEG/WEBP magic bytes (<= 5MB, <= 25MP), hash SHA-256, run OCR/fallback, save metadata |
| `GET /api/insights` | Compute deterministic `Decimal` insights, burn rate, MoM delta, and rule-based alerts (`?month=&year=`) |
| `POST /api/profile/update` | Update `full_name` and `email` with duplicate-email conflict protection (`409`) |
| `POST /api/profile/change-password` | Verify current password and re-hash replacement password with Scrypt |
| `GET /api/system/diagnostics` | Live MariaDB, OCR engine, Azure/local storage, and security architecture status |

---

## 4. Verified Feature Status

### Fully Operational Features
- **Authentication & Multi-Tenant Isolation:** Registration, login, logout, 24h permanent session lifecycle, `HttpOnly` + `SameSite=Lax` cookies, Scrypt password hashing, same-origin CSRF enforcement, and strict `user_id` ownership isolation (`404`/`403` against foreign records).
- **Dashboard & Charts:** Bento KPI cards (`Decimal` accuracy), Financial Pulse chip strip, switchable Bar/Area 6-month spending trend chart, Category Breakdown Doughnut chart, recent ledger search, and empty-state guidance.
- **Expense Management:** Multi-criteria filtering (keyword, category, start/end date), pagination, Quick-Add modal from any page, in-page Edit modal, accessible in-app Delete confirmation modal (`#deleteConfirmModal`), and instant recalculation across Dashboard, Budgets, and Insights.
- **Budget Engine:** Overall monthly limit + 8 category limits with `80%` amber caution and `100%` danger over-budget indicators (`Overspent By` / `Over by ₹...`), plus modal editing and `Remove Limit` deletion.
- **Insights & Profile:** Explainable rule-based financial advice, theme-reactive horizontal bar comparison chart (`#insightsCategoryChart`), profile editing with immediate sidebar `.user-name` / `.user-avatar` sync, password rotation, and live System Diagnostics.
- **Responsive UI & Themes:** Obsidian Dark and Platinum Light themes with `localStorage` persistence; verified zero horizontal overflow (`scrollWidth <= innerWidth`) and clean chart/modal/drawer responsiveness at `375px`, `768px`, and `1440px`.

### Features Operating in Graceful Fallback Mode
- **Receipt OCR (`services/ocr_service.py`):** `tesseract.exe` is not installed on the local Windows `PATH`. Uploading a valid PNG/JPEG/WEBP receipt runs in **`fallback`** mode (`Manual Fallback` badge on `/scan`), hashes the file (`SHA-256` duplicate check), stores the image securely, and enables the human-in-the-loop verification form for manual entry/confirmation.
- **Cloud Receipt Storage (`services/azure_storage.py`):** `AZURE_STORAGE_CONNECTION_STRING` is intentionally blank in local `.env`. Uploaded receipts store securely on local disk (`uploads/receipts/`) and report **`local_fallback`** in `/api/system/diagnostics`.

### Known Limitations
1. **Calendar Month Default vs. Demo Seed Month:** Seeded transactions for `demo_student` span **August–October 2026**. `/dashboard` pre-selects **October 2026** by default, whereas `/budgets` and `/insights` default their selectors to the current system month (`November 2026`). During a demo of pre-seeded records on `/budgets` and `/insights`, switch the month selector to **October 2026**.
2. **Seed Script vs. Live DB Overall Budget:** `database/seed.sql` lists `12000.00` for October's overall limit, whereas the verified live demo database holds **`10000.00`** (matching the `/auth` preview snapshot: `₹7,058.00 / ₹10,000.00 = 70.6%`).
3. **Local Academic Runtime Configuration:** Runs via Flask's local development server (`FLASK_ENV=development`, `SESSION_COOKIE_SECURE=False`), unpooled PyMySQL socket connections, and in-memory IP rate-limiting buckets (`_RATE_LIMIT_BUCKETS`); not configured for multi-worker internet production deployment without a WSGI server, Redis limiter, and TLS.
4. **Unused `bcrypt` Requirement:** `requirements.txt` lists `bcrypt==4.0.1` alongside active Werkzeug `scrypt` password hashing.

---

## 5. Timed 5-Minute Live Demonstration Sequence

1. **[0:00 – 0:45] Sign In & Security Overview (`/auth`)**
   - Open `http://127.0.0.1:5000/auth`. Point out the seeded snapshot card, dark/light toggle pill, Scrypt hashing, and tenant isolation guarantees.
   - Click **1-Click Fast Pass ->**, then click **Authenticate & Open Dashboard**.
2. **[0:45 – 1:45] Financial Dashboard & Charts (`/dashboard`)**
   - Review October 2026 KPIs (`₹7,058.00` spent, `₹10,000.00` cap, `₹2,942.00` remaining, `12` transactions, `Avg: ₹588.17/tx`, `↓ 26.1% vs prior`).
   - Switch **Spending History & Trends** between **Bar** and **Area** (`Aug` ₹7,800 -> `Sep` ₹9,550 -> `Oct` ₹7,058).
   - Toggle Dark/Light theme via the header button and toggle back.
3. **[1:45 – 2:45] Live Expense CRUD & Consistency (`/expenses`)**
   - Click **+ Add Expense**, log `₹280.00` for **Campus Book Depot** under **Education** (`2026-10-29`, `UPI`), and save.
   - Open **All Expenses** (`/expenses`), search/filter by `Education`, edit or inspect the entry, then delete the temporary demo entry via the in-app **Delete Expense** modal (keeping demo totals clean afterward, or show `/dashboard` updating from `₹7,058.00` -> `₹7,338.00` -> `₹7,058.00`).
4. **[2:45 – 3:30] Monthly Budgets & Threshold Alerts (`/budgets`)**
   - Open **Monthly Budgets** and switch month dropdown to **October** (`2026`).
   - Point out **Overall Monthly Limit** (`70.6% Used`) and **Food** category limit (`₹2,850.00 / ₹3,500.00`, `81.4%` — `80% Alert` warning badge). Open **Edit Limit** to show `Remove Limit` modal support without altering demo caps.
5. **[3:30 – 4:15] Receipt Upload & Human-in-the-Loop OCR (`/scan`)**
   - Open **Screenshot OCR** (`/scan`). Point out the honest **Optical Character Recognition in Fallback Mode** (`Manual Fallback`) banner.
   - Upload a valid payment screenshot `.png`/`.jpg`, highlight preview rendering and manual verification form (never auto-writing unverified OCR data), and note the **Security Policy** notice.
6. **[4:15 – 5:00] Spending Insights & Cloud/DB Diagnostics (`/insights`, `/profile`)**
   - Open **Spending Insights** (`/insights`) -> select **October 2026** -> review rule-based advice (`Healthy Budget Pace`, `Dominant Category: Food`), horizontal **Category Spend Comparison** chart, and category weight table.
   - Finish at **Profile & Cloud Diagnostics** (`/profile`) to show live MariaDB `connected`, DP-900 `local_fallback`, AI-900 `fallback_mode`, and Scrypt/session security summary.

---

## 6. Expected Demo Data & Verified Calculations (`demo_student`)

### Multi-Month Summary
| Month | Transactions | Total Spent | Notes |
| :--- | :--- | :--- | :--- |
| **August 2026** | `4` | `₹7,800.00` | Historical trend baseline |
| **September 2026** | `6` | `₹9,550.00` | Prior month baseline |
| **October 2026** | `12` | `₹7,058.00` | `-26.1%` vs September (`(7058 - 9550) / 9550`); Avg `₹588.17/tx` |

### October 2026 Budgets & Category Breakdown (Live DB Truth)
| Category | Tx Count | Spent | Share of Spend | Budget Limit | Utilization | Remaining / Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Overall Monthly** | `12` | `₹7,058.00` | `100.0%` | `₹10,000.00` | `70.6%` | `₹2,942.00` remaining (`Healthy Pace`) |
| **Food** | `5` | `₹2,850.00` | `40.4%` | `₹3,500.00` | `81.4%` | `₹650.00` remaining (`80% Alert`) |
| **Education** | `1` | `₹1,250.00` | `17.7%` | `₹2,500.00` | `50.0%` | `₹1,250.00` remaining (`Normal`) |
| **Shopping** | `1` | `₹1,199.00` | `17.0%` | None | `—` | `No Limit` |
| **Bills** | `1` | `₹699.00` | `9.9%` | `₹1,500.00` | `46.6%` | `₹801.00` remaining (`Normal`) |
| **Travel** | `2` | `₹460.00` | `6.5%` | `₹1,500.00` | `30.7%` | `₹1,040.00` remaining (`Normal`) |
| **Entertainment** | `1` | `₹360.00` | `5.1%` | `₹1,200.00` | `30.0%` | `₹840.00` remaining (`Normal`) |
| **Healthcare** | `1` | `₹240.00` | `3.4%` | None | `—` | `No Limit` |

*Note on October 2026 Insights (`/api/insights?month=10&year=2026`):* Since October is a past month (`current_day` resolves to `31`, `days_remaining = max(1, 31 - 31) = 1`), `avg_daily_burn` is `₹227.68/day` (`7058 / 31`), `safe_daily_allowance` is `₹2,942.00/day`, and recommendations list **Healthy Budget Pace** and **Dominant Category: Food**.

---

## 7. Quick Troubleshooting Guide

| Symptom | Likely Cause | Immediate Resolution |
| :--- | :--- | :--- |
| Browser cannot reach `http://127.0.0.1:5000` | Flask process not running | Run `python app.py` in `D:\3rd sem project` and confirm port `5000` startup line. |
| `Can't connect to MySQL server on '127.0.0.1:3306'` / Profile shows `disconnected` | MariaDB daemon stopped | Start `& "D:\3rd sem project\.mariadb_server\mariadb-10.11.8-winx64\bin\mariadbd.exe" --datadir="D:\3rd sem project\.mariadb_server\data" --port=3306 --console`. |
| `/budgets` or `/insights` shows `₹0.00` on initial open | Selectors default to current calendar month (`November 2026`) | Switch the Month selector in the top-right header to **October** (`2026`). |
| `HTTP 429 Too Many Requests` on `/api/auth/login` or `/register` | In-memory IP rate limiter triggered (`15/min` login, `10/min` register) | Wait up to `60s` or restart `python app.py` (clears in-memory buckets). |
| `/scan` shows **Optical Character Recognition in Fallback Mode** | Tesseract binary missing from `PATH` | Expected local fallback behavior; upload a valid PNG/JPEG/WEBP and complete the manual verification form. |
| Stale CSS or chart layout after edits | Browser cache | Press `Ctrl + Shift + R` for a hard reload. |

