# ExpenseTrack – System Design & Architecture Specification

## 1. Executive Summary & Objective

**ExpenseTrack** is a secure, multi-tenant web application engineered for college students to track personal expenditures, enforce category and monthly budget thresholds, scan payment receipts via OCR, and receive deterministic rule-based spending recommendations.

---

## 2. Requirements Analysis

### 2.1 Functional Requirements (FR)
- **FR-01 Authentication & Multi-Tenancy:** Secure user registration, credential verification via salted Scrypt hashing, session establishment, and strict tenant isolation so users only access their own data.
- **FR-02 Expense Management (CRUD):** Record, view, update, filter, and delete expenses with monetary amounts (`DECIMAL(10,2)`), transaction dates, merchant details, payment methods (UPI, Card, Cash, etc.), and optional notes.
- **FR-03 Budget Tracking & Alerts:** Configure overall monthly caps and category-level limits; compute real-time utilization percentages with automated 80% caution alerts and 100% breach notifications.
- **FR-04 Smart Screenshot Scanning:** Upload payment screenshot images (PNG, JPG, WEBP <= 5MB), compute cryptographic SHA-256 digests for duplicate detection, extract financial entities via OCR when available, and present fields in a human-in-the-loop verification form.
- **FR-05 Deterministic Insights:** Derive explainable recommendations from factual database records (e.g., top spending categories, average daily burn rate, safe remaining daily allowance).

### 2.2 Non-Functional Requirements (NFR)
- **NFR-01 Security & Integrity:** Enforce parameterized queries to eliminate SQL injection, secure HTTPOnly session cookies, server-side authorization checks on every endpoint, and safe receipt access controls.
- **NFR-02 Reliability & Graceful Degradation:** Resilient fallback handling when optional components (such as Tesseract OCR or Azure Blob Storage) are unconfigured or unavailable on the host machine.
- **NFR-03 Performance & Scalability:** Indexed relational lookups on user IDs and date ranges, responsive sub-100ms API response times under standard single-node student loads.

---

## 3. High-Level Component Architecture

```mermaid
graph TD
    Client["Client Browser (HTML5 / Vanilla JS / Chart.js)"]
    
    subgraph "Flask Application Server (Python 3.14)"
        AuthRouter["Auth Router (/api/auth)"]
        ExpenseRouter["Expense Router (/api/expenses)"]
        BudgetRouter["Budget Router (/api/budgets)"]
        ReceiptRouter["Receipt Router (/api/receipts)"]
        InsightRouter["Insight Router (/api/insights)"]
        DiagRouter["Diagnostics Router (/api/system)"]
        
        SessionAuth["Session & Authorization Middleware"]
        OCRService["OCR & Heuristics Service"]
        InsightEngine["Rule-Based Insights Engine"]
        AzureStorage["Azure Blob / Local Storage Service"]
        DBLayer["PyMySQL Connection & Transaction Layer"]
    end

    subgraph "Data & Storage Tier"
        MySQL[("MySQL 8.0+ Database (expensetrack)")]
        DiskStorage[("Local Disk (uploads/receipts)")]
        AzureBlob[("Azure Blob Storage (Cloud / DP-900)")]
    end

    Client -->|HTTP / JSON API| AuthRouter
    Client -->|HTTP / JSON API| ExpenseRouter
    Client -->|HTTP / JSON API| BudgetRouter
    Client -->|Multipart Upload| ReceiptRouter
    Client -->|HTTP / JSON API| InsightRouter
    Client -->|HTTP / JSON API| DiagRouter

    AuthRouter & ExpenseRouter & BudgetRouter & ReceiptRouter & InsightRouter --> SessionAuth
    SessionAuth --> DBLayer
    ReceiptRouter --> OCRService
    ReceiptRouter --> AzureStorage
    InsightRouter --> InsightEngine
    InsightEngine --> DBLayer
    
    DBLayer -->|Parameterized SQL (Port 3306)| MySQL
    AzureStorage -->|Local Fallback| DiskStorage
    AzureStorage -.->|Cloud Blob SDK| AzureBlob
```

---

## 4. Entity-Relationship (ER) Diagram

```mermaid
erDiagram
    USERS ||--o{ EXPENSES : "logs"
    USERS ||--o{ BUDGETS : "defines"
    USERS ||--o{ UPLOADED_RECEIPTS : "uploads"
    CATEGORIES ||--o{ EXPENSES : "classifies"
    CATEGORIES ||--o{ BUDGETS : "limits"
    UPLOADED_RECEIPTS ||--o| EXPENSES : "attaches to"

    USERS {
        int id PK
        string username UK
        string email UK
        string password_hash
        string full_name
        timestamp created_at
        timestamp updated_at
    }

    CATEGORIES {
        int id PK
        string name UK
        string icon
        string color
        boolean is_system
        timestamp created_at
    }

    EXPENSES {
        int id PK
        int user_id FK
        int category_id FK
        decimal amount
        string merchant
        date expense_date
        enum payment_method
        text notes
        int receipt_id FK
        timestamp created_at
        timestamp updated_at
    }

    BUDGETS {
        int id PK
        int user_id FK
        int category_id FK
        tinyint month
        smallint year
        decimal amount
        timestamp created_at
        timestamp updated_at
    }

    UPLOADED_RECEIPTS {
        int id PK
        int user_id FK
        string file_name
        string file_path
        int file_size
        string mime_type
        string azure_blob_url
        mediumtext ocr_raw_text
        enum ocr_status
        decimal extracted_amount
        string extracted_merchant
        date extracted_date
        string extracted_payment_method
        string file_hash
        timestamp created_at
    }
```

---

## 5. Use Case Diagram

```mermaid
flowchart LR
    Student((College Student))
    
    subgraph "ExpenseTrack System"
        UC1[Register & Sign In]
        UC2[View Dashboard Analytics & Charts]
        UC3[Record / Edit / Delete Expense]
        UC4[Search & Filter Transactions]
        UC5[Set Monthly & Category Budgets]
        UC6[Upload & Scan Payment Screenshot]
        UC7[Verify Extracted OCR Receipt Fields]
        UC8[View Explainable Spending Insights]
        UC9[Inspect System Health & Cloud Diagnostics]
    end

    Student --> UC1
    Student --> UC2
    Student --> UC3
    Student --> UC4
    Student --> UC5
    Student --> UC6
    Student --> UC7
    Student --> UC8
    Student --> UC9
```

---

## 6. Expense Creation Sequence Diagram (Human-in-the-Loop OCR Workflow)

```mermaid
sequenceDiagram
    autonumber
    actor User as College Student
    participant Browser as Web Browser (scan.js)
    participant Flask as Flask Server (receipts.py / expenses.py)
    participant OCR as OCR Service (Tesseract)
    participant Storage as Azure Storage / Disk
    participant MySQL as MySQL Database

    User->>Browser: Selects UPI screenshot image
    Browser->>Flask: POST /api/receipts/scan (Multipart Form)
    Flask->>Flask: Validate file size (<= 5MB) & extension
    Flask->>Flask: Compute SHA-256 hash & check duplicate
    Flask->>Storage: Store receipt image (Azure Blob or Local disk)
    Flask->>OCR: Execute Tesseract OCR & heuristic parsing
    OCR-->>Flask: Extracted amount, date, merchant, method
    Flask->>MySQL: INSERT INTO uploaded_receipts (...)
    Flask-->>Browser: JSON {receipt_id, ocr_status, extracted_fields, is_duplicate}
    Browser->>User: Renders editable verification form pre-filled with data
    User->>Browser: Modifies/confirms fields & clicks "Confirm Expense"
    Browser->>Flask: POST /api/expenses {amount, merchant, date, category_id, receipt_id}
    Flask->>Flask: Validate authorization & data constraints
    Flask->>MySQL: INSERT INTO expenses (user_id, amount, merchant, ...)
    MySQL-->>Flask: 201 Created (expense_id)
    Flask-->>Browser: Expense recorded successfully
    Browser->>User: Redirects to All Expenses with Toast Notification
```

---

## 7. Scalability & Future Improvements

1. **Connection Pooling:** Upgrade PyMySQL standalone context to SQLAlchemy pool (`QueuePool`) for high-concurrency production deployments.
2. **Asynchronous Background OCR:** Offload heavy Tesseract image processing to Celery/Redis background worker queue when throughput exceeds 100 uploads/min.
3. **Azure Blob SAS Tokens:** Generate short-lived Shared Access Signatures (SAS) for private receipt downloads rather than streaming through web server processes.

