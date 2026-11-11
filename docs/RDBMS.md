# ExpenseTrack – Relational Database Management System (RDBMS) Specification

## 1. Database Overview & Normalization

The **ExpenseTrack** relational database is implemented on **MySQL 8.0+** using the **InnoDB** storage engine with `utf8mb4` character set and `utf8mb4_unicode_ci` collation.

### 1.1 Normalization (Third Normal Form - 3NF)
1. **1NF (Atomic Attributes):** All attributes store scalar values (e.g., currency is stored as `DECIMAL(10,2)`, timestamps are scalar temporal types, no multi-valued arrays).
2. **2NF (No Partial Key Dependency):** All non-key attributes are fully functionally dependent on the entire primary key.
3. **3NF (No Transitive Dependency):** Category metadata (e.g., category name, icon, color) is separated into a dedicated `categories` dimension table rather than redundantly duplicated in `expenses`.

---

## 2. DDL & Integrity Constraints

```sql
-- Category Table with Primary Key & Unique Constraints
CREATE TABLE `categories` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(50) NOT NULL UNIQUE,
  `icon` VARCHAR(50) NOT NULL DEFAULT 'tag',
  `color` VARCHAR(20) NOT NULL DEFAULT '#10B981',
  `is_system` BOOLEAN NOT NULL DEFAULT TRUE,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Expenses Table with Check Constraints & Foreign Keys
CREATE TABLE `expenses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL,
  `category_id` INT NOT NULL,
  `amount` DECIMAL(10,2) NOT NULL,
  `merchant` VARCHAR(100) NOT NULL,
  `expense_date` DATE NOT NULL,
  `payment_method` ENUM('UPI', 'Cash', 'Credit Card', 'Debit Card', 'Net Banking', 'Other') NOT NULL DEFAULT 'UPI',
  `notes` TEXT NULL,
  `receipt_id` INT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- Integrity Constraints
  CONSTRAINT `chk_expense_amount_positive` CHECK (`amount` > 0.00),
  CONSTRAINT `fk_expenses_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_expenses_category` FOREIGN KEY (`category_id`)
    REFERENCES `categories` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_expenses_receipt` FOREIGN KEY (`receipt_id`)
    REFERENCES `uploaded_receipts` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB;
```

---

## 3. Core SQL Operations (Tested on Project Schema)

### 3.1 Parameterized INSERT, UPDATE, and DELETE
```sql
-- 1. Insert a new student expense
INSERT INTO expenses (user_id, category_id, amount, merchant, expense_date, payment_method, notes)
VALUES (1, 1, 450.00, 'Subway Campus Center', '2026-10-29', 'UPI', 'Dinner combo after practical lab');

-- 2. Update an existing expense with ownership isolation
UPDATE expenses
SET amount = 420.00, notes = 'Discount applied'
WHERE id = 1 AND user_id = 1;

-- 3. Delete an expense with ownership verification
DELETE FROM expenses
WHERE id = 1 AND user_id = 1;
```

### 3.2 Relational INNER JOIN Query
```sql
SELECT e.id, e.amount, e.merchant, e.expense_date, e.payment_method,
       c.name AS category_name, c.color AS category_color,
       r.file_name AS receipt_image
FROM expenses e
INNER JOIN categories c ON e.category_id = c.id
LEFT JOIN uploaded_receipts r ON e.receipt_id = r.id
WHERE e.user_id = 1
ORDER BY e.expense_date DESC
LIMIT 10;
```

### 3.3 Aggregate Query (GROUP BY & SUM) for Category Distribution
```sql
SELECT c.name AS category_name,
       COUNT(e.id) AS transaction_count,
       COALESCE(SUM(e.amount), 0.00) AS total_expenditure
FROM categories c
INNER JOIN expenses e ON c.id = e.category_id
WHERE e.user_id = 1
  AND MONTH(e.expense_date) = 10
  AND YEAR(e.expense_date) = 2026
GROUP BY c.id, c.name
ORDER BY total_expenditure DESC;
```

### 3.4 Monthly Expense Aggregation (6-Month Trend)
```sql
SELECT YEAR(expense_date) AS yr,
       MONTH(expense_date) AS mo,
       COUNT(id) AS monthly_tx_count,
       SUM(amount) AS monthly_total
FROM expenses
WHERE user_id = 1
  AND expense_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
GROUP BY yr, mo
ORDER BY yr ASC, mo ASC;
```

### 3.5 Budget Utilization Calculation Query
```sql
SELECT b.id AS budget_id,
       b.amount AS budget_limit,
       COALESCE(SUM(e.amount), 0.00) AS actual_spent,
       (b.amount - COALESCE(SUM(e.amount), 0.00)) AS remaining_balance,
       ROUND((COALESCE(SUM(e.amount), 0.00) / b.amount) * 100, 1) AS utilization_percentage
FROM budgets b
LEFT JOIN expenses e
       ON e.user_id = b.user_id
      AND MONTH(e.expense_date) = b.month
      AND YEAR(e.expense_date) = b.year
WHERE b.user_id = 1
  AND b.category_id IS NULL -- Overall monthly budget
  AND b.month = 10
  AND b.year = 2026
GROUP BY b.id, b.amount;
```

---

## 4. Indexing & Query Optimization Strategy

| Index Name | Table | Columns | Purpose |
|------------|-------|---------|---------|
| `idx_expenses_user_date` | `expenses` | `(user_id, expense_date)` | Accelerates dashboard monthly summaries and chronological transaction feeds |
| `idx_expenses_user_category` | `expenses` | `(user_id, category_id)` | Optimizes category distribution aggregation queries |
| `idx_budgets_lookup` | `budgets` | `(user_id, year, month)` | Enables instant retrieval of monthly budget limits |
| `idx_receipts_hash` | `uploaded_receipts` | `(user_id, file_hash)` | O(1) duplicate detection for receipt uploads |

---

## 5. Atomic Transactions & ACID Properties

When an expense creation operation requires linking an uploaded receipt and updating budget state:
```sql
START TRANSACTION;

INSERT INTO uploaded_receipts (user_id, file_name, file_path, file_size, mime_type, file_hash)
VALUES (1, 'upi_receipt_01.png', 'uploads/receipts/upi_receipt_01.png', 241020, 'image/png', 'a3f5...hash');

SET @receipt_id = LAST_INSERT_ID();

INSERT INTO expenses (user_id, category_id, amount, merchant, expense_date, payment_method, receipt_id)
VALUES (1, 1, 450.00, 'Campus Canteen', '2026-10-29', 'UPI', @receipt_id);

COMMIT;
```
If any statement fails (e.g., invalid category or negative amount check), `ROLLBACK` is executed automatically by the `get_db()` context manager.

