"""Align existing pre-Alembic MariaDB schema and verify cross-dialect parity

Revision ID: 20261112_0002
Revises: 20261112_0001
Create Date: 2026-11-12 03:05:00

Purpose:
- Safely align an existing MariaDB `expensetrack` database (created from
  `database/schema.sql` and stamped at `20261112_0001`) without dropping tables,
  recreating tables, or modifying financial records.
- Add `budgets.category_scope_key` and unique index `uq_budgets_user_scope_period`
  after verifying no duplicate overall/category budget rows exist.
- Widen `budgets.month` (`TINYINT` -> `SMALLINT`), convert MariaDB `ENUM` columns
  (`uploaded_receipts.ocr_status`, `expenses.payment_method`) to portable
  `VARCHAR` columns guarded by named `CHECK` constraints, convert `TIMESTAMP`
  columns to `DATETIME`, and normalize unique index names on `users`/`categories`.
- Preserve existing foreign key actions on MariaDB (including `fk_expenses_receipt`
  `ON DELETE SET NULL`), while remaining idempotent on fresh databases created by
  `20261112_0001` across both MariaDB and SQL Server / Azure SQL.
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261112_0002"
down_revision = "20261112_0001"
branch_labels = None
depends_on = None


_OCR_STATUS_CHECK_SQL = "ocr_status IN ('pending', 'success', 'failed', 'fallback')"
_PAYMENT_METHOD_CHECK_SQL = (
    "payment_method IN ('UPI', 'Cash', 'Credit Card', 'Debit Card', 'Net Banking', 'Other')"
)

_TIMESTAMP_TABLES = (
    ("users", "created_at", False),
    ("users", "updated_at", True),
    ("categories", "created_at", False),
    ("uploaded_receipts", "created_at", False),
    ("expenses", "created_at", False),
    ("expenses", "updated_at", True),
    ("budgets", "created_at", False),
    ("budgets", "updated_at", True),
)


def _mysql_get_columns(conn, schema: str, table_name: str) -> dict[str, str]:
    rows = conn.execute(
        sa.text(
            "SELECT COLUMN_NAME, DATA_TYPE "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :tbl"
        ),
        {"schema": schema, "tbl": table_name},
    ).fetchall()
    return {r[0]: r[1].lower() for r in rows}


def _mysql_get_indexes(conn, schema: str, table_name: str) -> set[str]:
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT INDEX_NAME "
            "FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :tbl"
        ),
        {"schema": schema, "tbl": table_name},
    ).fetchall()
    return {r[0] for r in rows}


def _mysql_get_check_constraints(conn, schema: str, table_name: str) -> set[str]:
    rows = conn.execute(
        sa.text(
            "SELECT CONSTRAINT_NAME "
            "FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :tbl AND CONSTRAINT_TYPE = 'CHECK'"
        ),
        {"schema": schema, "tbl": table_name},
    ).fetchall()
    return {r[0] for r in rows}


def _mysql_validate_preconditions(conn) -> None:
    """Fail cleanly before altering schema if legacy data conflicts exist."""
    dup_budgets = conn.execute(
        sa.text(
            "SELECT user_id, COALESCE(category_id, 0) AS scope_key, month, year, COUNT(*) AS cnt "
            "FROM budgets "
            "GROUP BY user_id, COALESCE(category_id, 0), month, year "
            "HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if dup_budgets:
        sample = ", ".join(
            f"(user={r[0]}, scope={r[1]}, month={r[2]}, year={r[3]}, count={r[4]})"
            for r in dup_budgets[:5]
        )
        raise RuntimeError(
            "Cannot apply uq_budgets_user_scope_period while duplicate budget scopes exist: "
            + sample
        )

    bad_ocr = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM uploaded_receipts "
            f"WHERE ocr_status IS NULL OR ocr_status NOT IN ('pending', 'success', 'failed', 'fallback')"
        )
    ).scalar()
    if bad_ocr:
        raise RuntimeError(
            f"Found {bad_ocr} uploaded_receipts row(s) with invalid ocr_status values."
        )

    bad_pm = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM expenses "
            "WHERE payment_method IS NULL OR payment_method NOT IN "
            "('UPI', 'Cash', 'Credit Card', 'Debit Card', 'Net Banking', 'Other')"
        )
    ).scalar()
    if bad_pm:
        raise RuntimeError(
            f"Found {bad_pm} expenses row(s) with invalid payment_method values."
        )


def _upgrade_mysql_online(conn) -> None:
    schema = conn.execute(sa.text("SELECT DATABASE()")).scalar()
    _mysql_validate_preconditions(conn)

    # 1. Budgets: generated scope column + duplicate-safe unique index + month type
    budget_cols = _mysql_get_columns(conn, schema, "budgets")
    budget_idxs = _mysql_get_indexes(conn, schema, "budgets")

    if "category_scope_key" not in budget_cols:
        op.execute(
            "ALTER TABLE budgets "
            "ADD COLUMN category_scope_key INT GENERATED ALWAYS AS (COALESCE(category_id, 0)) VIRTUAL"
        )
    if "uq_budgets_user_scope_period" not in budget_idxs:
        op.execute(
            "ALTER TABLE budgets "
            "ADD UNIQUE KEY uq_budgets_user_scope_period (user_id, category_scope_key, month, year)"
        )
    if "uk_user_category_month_year" in budget_idxs:
        op.execute("ALTER TABLE budgets DROP INDEX uk_user_category_month_year")

    if budget_cols.get("month") == "tinyint":
        op.execute("ALTER TABLE budgets MODIFY COLUMN month SMALLINT NOT NULL")

    # 2. Portable VARCHAR + named CHECK constraints replacing MariaDB ENUMs
    receipt_cols = _mysql_get_columns(conn, schema, "uploaded_receipts")
    if receipt_cols.get("ocr_status") == "enum":
        op.execute(
            "ALTER TABLE uploaded_receipts "
            "MODIFY COLUMN ocr_status VARCHAR(20) NOT NULL DEFAULT 'pending'"
        )
    receipt_chks = _mysql_get_check_constraints(conn, schema, "uploaded_receipts")
    if "chk_receipt_ocr_status" not in receipt_chks:
        op.execute(
            f"ALTER TABLE uploaded_receipts "
            f"ADD CONSTRAINT chk_receipt_ocr_status CHECK ({_OCR_STATUS_CHECK_SQL})"
        )

    expense_cols = _mysql_get_columns(conn, schema, "expenses")
    if expense_cols.get("payment_method") == "enum":
        op.execute(
            "ALTER TABLE expenses "
            "MODIFY COLUMN payment_method VARCHAR(30) NOT NULL DEFAULT 'UPI'"
        )
    expense_chks = _mysql_get_check_constraints(conn, schema, "expenses")
    if "chk_expense_payment_method" not in expense_chks:
        op.execute(
            f"ALTER TABLE expenses "
            f"ADD CONSTRAINT chk_expense_payment_method CHECK ({_PAYMENT_METHOD_CHECK_SQL})"
        )
    if "chk_expense_amount_positive" not in expense_chks:
        op.execute(
            "ALTER TABLE expenses "
            "ADD CONSTRAINT chk_expense_amount_positive CHECK (amount > 0.00)"
        )

    budget_chks = _mysql_get_check_constraints(conn, schema, "budgets")
    if "chk_budget_month" not in budget_chks:
        op.execute(
            "ALTER TABLE budgets ADD CONSTRAINT chk_budget_month CHECK (month BETWEEN 1 AND 12)"
        )
    if "chk_budget_year" not in budget_chks:
        op.execute(
            "ALTER TABLE budgets ADD CONSTRAINT chk_budget_year CHECK (year >= 2020)"
        )
    if "chk_budget_amount_positive" not in budget_chks:
        op.execute(
            "ALTER TABLE budgets ADD CONSTRAINT chk_budget_amount_positive CHECK (amount > 0.00)"
        )

    # 3. TIMESTAMP -> DATETIME (aligns with UTCDateTime without altering values)
    col_cache: dict[str, dict[str, str]] = {
        "uploaded_receipts": receipt_cols,
        "expenses": expense_cols,
        "budgets": budget_cols,
    }
    for tbl, col_name, on_update in _TIMESTAMP_TABLES:
        cols = col_cache.setdefault(tbl, _mysql_get_columns(conn, schema, tbl))
        if cols.get(col_name) == "timestamp":
            default_clause = (
                "DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
                if on_update
                else "DEFAULT CURRENT_TIMESTAMP"
            )
            op.execute(
                f"ALTER TABLE {tbl} MODIFY COLUMN {col_name} DATETIME NOT NULL {default_clause}"
            )

    # 4. Normalize auto-named unique constraint indexes on users and categories
    user_idxs = _mysql_get_indexes(conn, schema, "users")
    if "username" in user_idxs and "uq_users_username" not in user_idxs:
        op.execute("ALTER TABLE users RENAME INDEX username TO uq_users_username")
    if "email" in user_idxs and "uq_users_email" not in user_idxs:
        op.execute("ALTER TABLE users RENAME INDEX email TO uq_users_email")

    cat_idxs = _mysql_get_indexes(conn, schema, "categories")
    if "name" in cat_idxs and "uq_categories_name" not in cat_idxs:
        op.execute("ALTER TABLE categories RENAME INDEX name TO uq_categories_name")


def _downgrade_mysql_online(conn) -> None:
    schema = conn.execute(sa.text("SELECT DATABASE()")).scalar()

    # 1. Revert unique constraint names on users and categories if aligned
    user_idxs = _mysql_get_indexes(conn, schema, "users")
    if "uq_users_username" in user_idxs and "username" not in user_idxs:
        op.execute("ALTER TABLE users RENAME INDEX uq_users_username TO username")
    if "uq_users_email" in user_idxs and "email" not in user_idxs:
        op.execute("ALTER TABLE users RENAME INDEX uq_users_email TO email")

    cat_idxs = _mysql_get_indexes(conn, schema, "categories")
    if "uq_categories_name" in cat_idxs and "name" not in cat_idxs:
        op.execute("ALTER TABLE categories RENAME INDEX uq_categories_name TO name")

    # 2. Revert DATETIME -> TIMESTAMP if table is currently DATETIME
    for tbl, col_name, on_update in _TIMESTAMP_TABLES:
        cols = _mysql_get_columns(conn, schema, tbl)
        if cols.get(col_name) == "datetime":
            default_clause = (
                "DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
                if on_update
                else "DEFAULT CURRENT_TIMESTAMP"
            )
            op.execute(
                f"ALTER TABLE {tbl} MODIFY COLUMN {col_name} TIMESTAMP NOT NULL {default_clause}"
            )

    # 3. Drop portable CHECK constraints added by 0002 & restore ENUM if VARCHAR
    receipt_chks = _mysql_get_check_constraints(conn, schema, "uploaded_receipts")
    if "chk_receipt_ocr_status" in receipt_chks:
        op.execute("ALTER TABLE uploaded_receipts DROP CONSTRAINT chk_receipt_ocr_status")
    receipt_cols = _mysql_get_columns(conn, schema, "uploaded_receipts")
    if receipt_cols.get("ocr_status") == "varchar":
        op.execute(
            "ALTER TABLE uploaded_receipts MODIFY COLUMN ocr_status "
            "ENUM('pending', 'success', 'failed', 'fallback') NOT NULL DEFAULT 'pending'"
        )

    expense_chks = _mysql_get_check_constraints(conn, schema, "expenses")
    if "chk_expense_payment_method" in expense_chks:
        op.execute("ALTER TABLE expenses DROP CONSTRAINT chk_expense_payment_method")
    expense_cols = _mysql_get_columns(conn, schema, "expenses")
    if expense_cols.get("payment_method") == "varchar":
        op.execute(
            "ALTER TABLE expenses MODIFY COLUMN payment_method "
            "ENUM('UPI', 'Cash', 'Credit Card', 'Debit Card', 'Net Banking', 'Other') NOT NULL DEFAULT 'UPI'"
        )

    # 4. Revert budgets: restore uk_user_category_month_year before removing scope key
    budget_cols = _mysql_get_columns(conn, schema, "budgets")
    budget_idxs = _mysql_get_indexes(conn, schema, "budgets")
    if budget_cols.get("month") == "smallint":
        op.execute("ALTER TABLE budgets MODIFY COLUMN month TINYINT NOT NULL")
    if "uk_user_category_month_year" not in budget_idxs:
        op.execute(
            "ALTER TABLE budgets "
            "ADD UNIQUE KEY uk_user_category_month_year (user_id, category_id, month, year)"
        )
    if "uq_budgets_user_scope_period" in budget_idxs:
        op.execute("ALTER TABLE budgets DROP INDEX uq_budgets_user_scope_period")
    if "category_scope_key" in budget_cols:
        op.execute("ALTER TABLE budgets DROP COLUMN category_scope_key")


def _upgrade_mssql_online(conn) -> None:
    """Idempotently verify/ensure SQL Server filtered unique indexes & CHECKs."""
    dup_overall = conn.execute(
        sa.text(
            "SELECT user_id, month, year, COUNT(*) AS cnt "
            "FROM dbo.budgets WHERE category_id IS NULL "
            "GROUP BY user_id, month, year HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if dup_overall:
        raise RuntimeError(
            "Cannot ensure uq_budgets_user_overall_period while duplicate overall budgets exist."
        )

    dup_cat = conn.execute(
        sa.text(
            "SELECT user_id, category_id, month, year, COUNT(*) AS cnt "
            "FROM dbo.budgets WHERE category_id IS NOT NULL "
            "GROUP BY user_id, category_id, month, year HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if dup_cat:
        raise RuntimeError(
            "Cannot ensure uq_budgets_user_category_period while duplicate category budgets exist."
        )

    existing_idxs = {
        r[0]
        for r in conn.execute(
            sa.text(
                "SELECT name FROM sys.indexes WHERE object_id = OBJECT_ID(N'dbo.budgets') AND name IS NOT NULL"
            )
        ).fetchall()
    }
    if "uq_budgets_user_category_period" not in existing_idxs:
        op.create_index(
            "uq_budgets_user_category_period",
            "budgets",
            ["user_id", "category_id", "month", "year"],
            unique=True,
            mssql_where=sa.text("category_id IS NOT NULL"),
        )
    if "uq_budgets_user_overall_period" not in existing_idxs:
        op.create_index(
            "uq_budgets_user_overall_period",
            "budgets",
            ["user_id", "month", "year"],
            unique=True,
            mssql_where=sa.text("category_id IS NULL"),
        )


def _is_offline_mode() -> bool:
    try:
        return context.is_offline_mode()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if _is_offline_mode():
        if dialect_name == "mssql":
            op.execute("-- Phase 2A schema alignment check (SQL Server / Azure SQL: no-op on fresh 0001)")
        else:
            op.execute("-- Phase 2A schema alignment migration (MariaDB / MySQL)")
        return

    if dialect_name == "mssql":
        _upgrade_mssql_online(bind)
    else:
        _upgrade_mysql_online(bind)


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if _is_offline_mode():
        op.execute("-- Phase 2A schema alignment downgrade")
        return

    if dialect_name == "mssql":
        # Fresh 0001 SQL Server schema matches target already; no destructive teardown here
        # (revisions down to `base` are cleanly dropped by 20261112_0001.downgrade).
        return

    _downgrade_mysql_online(bind)

