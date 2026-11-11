# ExpenseTrack: Professional Demonstration & Viva Presentation Guide

**Project Title:** ExpenseTrack – Smart Student Expense Manager  
**One-Line Elevator Pitch:** A production-grade, privacy-focused financial management web platform tailored for university students to track multi-channel spending (UPI/Cash/Card), enforce monthly budget discipline, digitize payment receipts via OCR, and gain actionable spending insights.

---

## 1. Executive Summary & Problem Statement

### The Problem
University students routinely struggle with financial self-discipline:
- **Dispersed Transaction Trails:** Payments are fragmented across multiple UPI apps (Google Pay, PhonePe, Paytm), cash, and debit cards.
- **Budget Blindness:** Students lack real-time visibility into their monthly burn rate, leading to early-month overspending and end-of-month crises.
- **Manual Data Entry Burden:** Manually logging every ₹20 chai or ₹150 canteen meal leads to user friction and abandoned tracking.
- **Privacy & Security Concerns:** Commercial apps often harvest financial data, require SMS scraping permissions, or expose user privacy.

### The Solution: ExpenseTrack
ExpenseTrack provides an intuitive, high-performance web platform featuring:
1. **Instant Overview:** A high-contrast Bento-grid financial dashboard showing month-to-date spending, remaining allowances, safe daily burn rates, and spending distributions.
2. **Robust Multi-Category Budgeting:** Overarching monthly caps and category-level limits with real-time threshold warnings (80% amber warning, 100% danger alert).
3. **Smart Screenshot Digitization:** Upload receipt/UPI screenshots to extract transaction amounts, merchants, and dates via OCR heuristics with a mandatory human-in-the-loop verification form.
4. **Algorithmic Financial Insights:** Explainable, rule-based financial advice highlighting top spending categories and daily pacing guidance without fabricating statistics.
5. **Secure Relational Architecture:** MySQL/MariaDB database with 3NF normalization, strict foreign key constraints, Scrypt password hashing, session-based isolation, and parameterised queries.

---

## 2. Technology Stack & Architecture Justification

| Layer | Technology | Engineering Justification |
| :--- | :--- | :--- |
| **Frontend** | Semantic HTML5, CSS3 Custom Properties, Vanilla JavaScript (ES6+) | Zero client-side bundle bloat, sub-100ms first paint, native browser reliability, and full control over animations without heavy framework overhead (React/Angular). |
| **Visualization** | Chart.js 4.4.1 (Canvas-based) | High-performance HTML5 2D canvas rendering for monthly bar/area trends and doughnut charts with dynamic center text overlays. |
| **Backend** | Python 3.14 + Flask 3.0.3 | Lightweight, deterministic WSGI micro-framework organized into modular Blueprints (`auth`, `dashboard`, `expenses`, `budgets`, `receipts`, `insights`, `profile`). |
| **Database** | MariaDB 10.11 / MySQL 8.0 Compatible | ACID-compliant relational storage, strict foreign key referential integrity, decimal precision for monetary fields, and indexed query performance. |
| **Security** | Werkzeug Security (Scrypt KDF), Session Cookies | Industry-standard password hashing with cryptographic salt and work factors, HttpOnly session cookies, parameterized SQL queries against SQL injection. |
| **Document OCR** | Tesseract OCR (`pytesseract`) + Heuristic Parser | Local optical character recognition with graceful fallback and human verification, preserving privacy without cloud vendor lock-in. |
| **Cloud Ready** | Azure Blob Storage & Azure SQL Architecture | Designed with direct integration hooks for cloud object storage and managed relational databases for production scaling. |

---

## 3. Verified Demo Environment Details

- **Local Application URL:** `http://127.0.0.1:5000`
- **Database Server:** `127.0.0.1:3306` (MariaDB/MySQL `expensetrack`)
- **Default Demo Account:**
  - **Email:** `student@expensetrack.edu`
  - **Password:** `Password123!`
  - **Account Name:** Aarav Sharma (`@demo_student`)
- **Pre-seeded Dataset:** 22 realistic student transactions across August, September, and October 2026, 6 active budget limits, and 8 standardized spending categories.

---

## 4. Timed 5-Minute Viva Demonstration Script

```
[0:00 - 0:45] Authentication & Multi-Tenant Security
[0:45 - 1:45] Executive Bento Dashboard & Analytics
[1:45 - 2:45] Live Expense CRUD & Real-Time Recalculation
[2:45 - 3:30] Budget Tracking & Threshold Warnings
[3:30 - 4:15] Smart Receipt Scanner (OCR + Verification)
[4:15 - 5:00] Financial Pulse Insights & Cloud Architecture
```

### Step 1: Authentication & Security (0:00 - 0:45)
1. **Action:** Navigate to `http://127.0.0.1:5000/auth` in Google Chrome or Edge.
2. **Narration:**
   > *"Good morning, respected examiners. ExpenseTrack starts with a secure authentication boundary. Passwords are never stored in plain text; they are hashed using the Scrypt key derivation function with unique cryptographic salts. Sessions are tracked via encrypted, HttpOnly cookies, ensuring complete tenant isolation where User B can never read or mutate User A's financial records."*
3. **Action:** Enter `student@expensetrack.edu` and `Password123!`, then click **Log In**.
4. **Expected Result:** Seamless login with redirect to `/dashboard`. Flash notification confirms successful session establishment.

### Step 2: Executive Dashboard & Dual-View Analytics (0:45 - 1:45)
1. **Narration:**
   > *"Upon login, the student arrives at the Executive Bento Dashboard. The top row provides four instant financial KPIs: Month Spending (₹7,058), Monthly Cap (₹10,000), Remaining Allowance (₹2,942), and Total Transactions logged this month (12)."*
2. **Action:** Point out the **Financial Pulse Banner**:
   - Status shows `70.6% Budget Used` (Healthy green status).
   - Dynamic pacing calculation: `Safe Daily: ₹1,471.00/day` remaining for the month.
   - Top spending category highlighted: `Food (40.4%)`.
3. **Action:** Demonstrate the **Dual-View Spending Trends**:
   - Click the **Area** toggle button in the Spending Trends card.
   - Observe the chart transition smoothly from a Bar chart to an Aurora Mint Area chart showing multi-month spending (Aug, Sep, Oct 2026).
4. **Action:** Hover over the **Category Breakdown Doughnut**:
   - The interactive doughnut chart displays the center metric (`₹7,058.00 Total Spent`), accompanied by a color-coded legend showing percentages and amounts (Food ₹2,850, Education ₹1,250, Shopping ₹1,199, etc.).
5. **Expected Result:** All metrics match underlying database records exactly without any hardcoded frontend numbers.

### Step 3: Expense Management (Live CRUD) (1:45 - 2:45)
1. **Action:** Click the top-right green **+ Add Expense** button (or navigate to `/expenses` and click **+ Add Expense**).
2. **Action:** Enter the following sample viva data:
   - **Amount:** `280.00`
   - **Merchant:** `Campus Book Depot`
   - **Category:** `Education`
   - **Payment Method:** `UPI`
   - **Expense Date:** Select today's date (`2026-10-29`)
   - **Notes:** `Semester 3 Algorithms Reference Guide`
3. **Action:** Click **Save Expense**.
4. **Expected Result:**
   - Toast notification appears: `Expense logged successfully.`
   - Expense list updates instantly showing the new entry at the top with a distinct `UPI` pill and `Education` badge.
5. **Action:** Filter by category `Education` using the dropdown filter.
   - Only Education expenses are shown.
6. **Action:** Click **Dashboard** in the sidebar.
   - Notice that **Month Spending** automatically updated from `₹7,058.00` to `₹7,338.00`.
   - Remaining Allowance adjusted to `₹2,662.00`.
   - Total transactions increased to `13`.
   - Education category slice on the doughnut chart dynamically expanded.

### Step 4: Budget Management & Threshold Alerts (2:45 - 3:30)
1. **Action:** Click **Monthly Budgets** (`/budgets`) in the left navigation sidebar.
2. **Narration:**
   > *"Budgeting in ExpenseTrack supports both an overarching monthly financial ceiling and granular category-specific caps. Each budget card computes the live utilization percentage, spent amount, and remaining headroom directly from the SQL database."*
3. **Action:** Point to the **Education** budget:
   - Notice that with the ₹280 purchase just added, Education spending reached `₹1,530.00` out of a `₹2,000.00` limit (`76.5%`).
4. **Action:** Click **Edit Budget** on Education, adjust the limit to `₹1,600.00`, and click **Save**.
5. **Expected Result:**
   - Education utilization jumps to `95.6%`.
   - The progress bar immediately transitions to an amber/orange warning color with an alert badge: `⚠️ Nearing Limit (>80%)`.
   - If spending exceeds 100%, the UI displays a high-visibility crimson alert `🚨 Budget Exceeded`.

### Step 5: Smart Receipt Scanner & Human-in-the-Loop OCR (3:30 - 4:15)
1. **Action:** Click **Screenshot OCR** (`/receipts`) in the sidebar.
2. **Narration:**
   > *"A common pain point in college budgeting is entering UPI transaction details manually. ExpenseTrack features a Smart Receipt Scanner. The user uploads a payment screenshot (Google Pay, PhonePe, or printed invoice). The backend hashes the file with SHA-256 to prevent duplicate processing, runs an OCR pipeline via Tesseract or regex heuristic parsing, and populates a mandatory human verification form."*
3. **Action:** Upload a payment receipt screenshot (or demonstrate manual entry trigger).
4. **Narration:**
   > *"Notice that we deliberately implement a Human-in-the-Loop design pattern. The application never silently writes unverified OCR output to the database. The student reviews the extracted amount, merchant, and date, confirms or edits the fields, and clicks 'Confirm & Save Expense'."*
5. **Expected Result:** The verified record is committed to the database and linked to the stored receipt image.

### Step 6: Spending Insights & System Diagnostics (4:15 - 5:00)
1. **Action:** Click **Spending Insights** (`/insights`).
2. **Narration:**
   > *"The Spending Insights engine applies deterministic, rule-based algorithms to student expenditure:*
   > *1. High Burn-Rate Alert: Identifies categories consuming >35% of total budget.*
   > *2. Pacing Guidance: Calculates daily safe spend based on calendar days remaining.*
   > *3. Budget Health Check: Compares current burn rate against the previous month.*
   > *Crucially, it does not fabricate statistics or invoke black-box LLMs where deterministic financial math is required."*
3. **Action:** Click **Profile & Cloud Diagnostics** (`/profile`).
   - Show the live database health: `MariaDB/MySQL Connected (expensetrack on port 3306)`.
   - Show the Azure architecture readiness indicators: Azure SQL Database connection strings and Azure Blob Storage container status.
4. **Concluding Statement:**
   > *"In summary, ExpenseTrack combines modern web aesthetics with rigorous relational database integrity, disciplined cybersecurity safeguards, and student-focused financial management. I am now pleased to take questions from the panel."*

---

## 5. Demonstration Troubleshooting Guide

| Issue | Root Cause | Immediate Fix |
| :--- | :--- | :--- |
| **Browser shows `Unable to connect` at `127.0.0.1:5000`** | Flask server stopped or terminal closed | Run `python app.py` in the project root directory. |
| **`Can't connect to MySQL server on '127.0.0.1:3306'`** | MariaDB background daemon not running | Run: `& ".\.mariadb_server\mariadb-10.11.8-winx64\bin\mariadbd.exe" --datadir=".\.mariadb_server\data" --port=3306 --console` |
| **Demo credentials rejected** | Modified or unseeded database | Run `python database/init_db.py` to re-seed demo account and sample data. |
| **OCR indicates "Fallback parsing active"** | Tesseract binary not detected on Windows system PATH | Expected behavior in environments without binary installation. Explain that the resilient architecture gracefully falls back to structured receipt entry without crashing. |
| **Old cached styles appearing** | Browser aggressive CSS caching | Press `Ctrl + Shift + R` (Hard Reload) in the browser. |

---

## 6. Implementation Status Matrix

### Fully Implemented & Verified (Production Ready)
- [x] User registration, login, logout, password hashing with Scrypt, and session protection.
- [x] Full multi-user isolation: SQL queries enforced with `WHERE user_id = :user_id`.
- [x] Interactive Bento Dashboard with dual-view Chart.js trend charts and category doughnut.
- [x] Full Expense CRUD: Create, Read, Update, Delete with category filtering, date filters, and merchant search.
- [x] Budget Management: Monthly overall cap, category limits, real-time threshold calculations, and 80%/100% visual warnings.
- [x] Receipt Upload with SHA-256 duplicate checking, secure filename sanitization, and storage tracking.
- [x] Deterministic Rule-Based Financial Insights.
- [x] 12/12 Automated Pytest Unit and Integration Tests passing.

### Graceful Fallback Features (Academic Integrity)
- **Tesseract OCR:** When Tesseract executable is not on PATH, backend falls back gracefully to structured receipt upload with human-in-the-loop review form without application crash.
- **Azure Cloud Storage:** Azure Blob and Azure SQL configuration hooks are fully implemented. When cloud connection strings are unset, the app defaults securely to local private storage (`uploads/receipts/`) and local MariaDB/MySQL.

### Future Roadmap Enhancements
- Automated SMS/UPI notification listener on Android via companion app.
- Multi-currency conversion for international students.
- Export to Excel/CSV and PDF financial statements.

