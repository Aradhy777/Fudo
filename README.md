# ExpenseTrack – Smart Student Expense Manager

A full-stack, secure, multi-tenant academic web application engineered for college students to track expenses, enforce monthly and category budgets, scan payment receipts via OCR, and receive deterministic rule-based spending insights.

Built with Python Flask, MySQL / MariaDB, Chart.js, and vanilla HTML5/CSS3/JavaScript.

---

## 1. Quick Start & Execution

### Prerequisites
- Python 3.10+ (Tested on Python 3.14.2)
- MySQL 8.0+ or compatible MariaDB server on `127.0.0.1:3306`

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Initialize Database & Seed Demo Data
The project includes a self-contained initialization script that creates the `expensetrack` database, executes `database/schema.sql`, and populates realistic demo student data from `database/seed.sql`:
```bash
python database/init_db.py
```

### Step 3: Run Automated Test Suite
Run the 12 automated test cases covering authentication, expense CRUD, multi-tenant isolation, negative input validation, budgets, and OCR parsing:
```bash
python -m pytest tests/
```

### Step 4: Launch Web Application
```bash
python app.py
```
Open your browser and navigate to:
👉 **`http://127.0.0.1:5000`**

---

## 2. Demo Credentials for Evaluation

A pre-seeded college student account is ready for instant evaluation:
- **Email:** `student@expensetrack.edu` (or Username: `demo_student`)
- **Password:** `Password123!`
- *Tip:* The sign-in page features a **1-Click Fill** button for instant demonstration.

---

## 3. Core Feature Walkthrough

| Feature | Description | URL Route |
|---------|-------------|-----------|
| **Dashboard** | Total monthly spending, budget gauge, category doughnut chart, 6-month trend bar chart, and recent transaction table | `/dashboard` |
| **All Expenses** | Full CRUD data table with multi-criteria filtering (category, merchant, date range), receipt links, and pagination | `/expenses` |
| **Monthly Budgets** | Set and track overall monthly spending caps and category limits (Food, Travel, Books, etc.) with real-time 80% and 100% threshold alerts | `/budgets` |
| **Screenshot OCR** | Drag-and-drop payment screenshot upload (UPI/Card), SHA-256 duplicate detection, OCR entity extraction, and human-in-the-loop verification form | `/scan` |
| **Spending Insights** | Explainable, deterministic recommendations (top spending drivers, daily burn rate, safe remaining daily allowance) | `/insights` |
| **Profile & Diagnostics** | Account management and live academic diagnostics inspector (MySQL status, Azure Blob status, OCR engine status, Cloud Security) | `/profile` |

---

## 4. Academic Architecture & Viva Talking Points

### System Design
- **Architecture:** Multi-layered MVC with REST-style Flask JSON blueprints and decoupled vanilla JS frontend.
- **Data Flow:** Strict separation of concerns between storage (`database/db.py`), services (`services/`), and route controllers (`routes/`).
- **Complete Documentation & Mermaid Diagrams:** See [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) for Use Case, ER, Component, and Sequence diagrams.

### Relational Database Management System (RDBMS)
- **Engine:** MySQL 8.0+ / InnoDB with normalized 3NF schema.
- **Constraints:** Foreign keys with `ON DELETE CASCADE` / `ON DELETE RESTRICT`, `CHECK (amount > 0.00)`, `UNIQUE` constraints on user and email.
- **Indexes:** Multi-column composite indexes on `(user_id, expense_date)`, `(user_id, category_id)`, and `(user_id, month, year)`.
- **Transactions:** Atomic transactions via PyMySQL context manager with automatic rollback on exception.
- **Complete SQL Query Examples:** See [docs/RDBMS.md](docs/RDBMS.md).

### Microsoft Azure Data Fundamentals (DP-900)
- **Structured Data:** Direct architectural mapping between local MySQL and Azure SQL Database (PaaS), highlighting automated backups, Point-In-Time Restore (PITR), and high availability.
- **Unstructured Data:** Architecture maps receipt images to private Azure Blob Storage containers (Hot/Cool tiers) with transparent local disk fallback when cloud credentials are not supplied.
- **Complete Azure Guide:** See [docs/DP900_AZURE.md](docs/DP900_AZURE.md).

### Cloud Security & Hardening
- **Password Storage:** Modern salted **Scrypt** (`scrypt:32768:8:1`) memory-hard key derivation function.
- **Session Protection:** `HttpOnly=True` and `SameSite='Lax'` cookies to prevent XSS session theft and CSRF.
- **Multi-Tenant Isolation:** Strict server-side verification ensuring users can only read, update, or delete their own records.
- **SQL Injection Defense:** 100% parameterized queries using `%s` placeholders.
- **Complete Security Documentation:** See [docs/CLOUD_SECURITY.md](docs/CLOUD_SECURITY.md).

### Microsoft Azure AI Fundamentals (AI-900)
- **Computer Vision & OCR:** Tesseract OCR optical character recognition pipeline with graceful fallback to manual verification.
- **Entity Parsing:** Deterministic regex heuristic extractor parsing amounts, dates, merchants, and payment methods.
- **Responsible AI Principles:** Complete transparency (never hallucinates financial numbers), privacy protection (zero retention of UPI PINs or OTPs), and Human-in-the-Loop review.
- **Complete AI Guide:** See [docs/AI900_VISION.md](docs/AI900_VISION.md).

---

## 5. Environment Variables (`.env`)

```ini
FLASK_APP=app.py
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=expensetrack-dev-secret-key-student-finance-2026
PORT=5000

# MySQL Database Settings
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=expensetrack

# Storage & Uploads
UPLOAD_FOLDER=uploads/receipts
MAX_CONTENT_LENGTH=5242880

# Optional: Tesseract Binary (if not in system PATH)
TESSERACT_CMD=

# Optional: Azure Blob Storage (DP-900 Cloud Integration)
AZURE_STORAGE_CONNECTION_STRING=
AZURE_STORAGE_CONTAINER_NAME=receipts
```

---

## 6. Project Directory Structure

```
d:\3rd sem project\
├── app.py                      # Flask Application entry point & factory
├── config.py                   # Environment configuration loader
├── requirements.txt            # Python dependencies
├── .env.example                # Configuration template
├── .env                        # Local active configuration
├── database/
│   ├── db.py                   # PyMySQL parameterized execution & transactions
│   ├── schema.sql              # MySQL DDL schema (tables, keys, constraints)
│   ├── seed.sql                # Initial categories, demo student & expenses
│   └── init_db.py              # Self-contained database provisioning script
├── routes/
│   ├── auth.py                 # Registration, login, session management
│   ├── auth_helper.py          # @login_required decorator & user isolation
│   ├── dashboard.py            # Aggregate metrics, Chart.js feeds, recent list
│   ├── expenses.py             # Expense CRUD, multi-criteria filters, pagination
│   ├── budgets.py              # Overall & category monthly budgets, 80% warnings
│   ├── receipts.py             # Receipt upload, SHA-256 duplicate check, OCR
│   ├── insights.py             # Rule-based spending analytics & advice
│   └── profile.py              # Profile settings & live system diagnostics
├── services/
│   ├── ocr_service.py          # Tesseract OCR & heuristic financial parser
│   ├── insight_service.py      # Spending analytics & explainable advice
│   └── azure_storage.py        # Azure Blob Storage SDK with local fallback
├── static/
│   ├── css/
│   │   ├── main.css            # Dark navy sidebar & slate responsive layout
│   │   └── components.css      # Cards, modals, progress bars, tables, dropzone
│   └── js/
│       ├── api.js              # Fetch client, toast notifications, formatters
│       ├── dashboard.js        # Dashboard Chart.js charts & KPIs
│       ├── expenses.js         # Expenses table, search filters, modals
│       ├── budgets.js          # Budget progress bars & threshold alerts
│       ├── scan.js             # Drag-and-drop receipt OCR review workflow
│       └── insights.js         # Spending insights & recommendation UI
├── templates/
│   ├── base.html               # Responsive master layout & navigation
│   ├── auth.html               # Login / registration with 1-click demo fill
│   ├── dashboard.html          # Main student financial dashboard
│   ├── expenses.html           # Recorded expenses table & filters
│   ├── budgets.html            # Monthly & category budgets
│   ├── scan.html               # Screenshot scanner & OCR verification
│   ├── insights.html           # Financial recommendations & burn rate
│   └── profile.html            # Profile & system architecture diagnostics
├── tests/
│   ├── test_app.py             # Pytest suite for auth, CRUD, isolation, budgets
│   ├── test_ocr.py             # Unit tests for OCR entity extraction & hashing
│   └── test_live_server.py     # Live HTTP verification script across all 8 routes
└── docs/
    ├── SYSTEM_DESIGN.md        # Architecture, requirements, Mermaid diagrams
    ├── RDBMS.md                # 3NF schema, joins, aggregates, transactions
    ├── DP900_AZURE.md          # Azure SQL & Azure Blob Storage architecture
    ├── CLOUD_SECURITY.md       # Defense-in-depth, Scrypt, OWASP compliance
    └── AI900_VISION.md         # Computer vision, OCR pipeline, Responsible AI
```

