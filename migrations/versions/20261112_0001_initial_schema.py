"""Initial ExpenseTrack schema (MariaDB & SQL Server / Azure SQL compatible)

Revision ID: 20261112_0001
Revises:
Create Date: 2026-11-12 01:18:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mssql import DATETIME2
from sqlalchemy.dialects.mysql import MEDIUMTEXT

# revision identifiers, used by Alembic.
revision = "20261112_0001"
down_revision = None
branch_labels = None
depends_on = None

UTCDateTime = sa.DateTime(timezone=False).with_variant(DATETIME2(), "mssql")
LongUnicodeText = sa.UnicodeText().with_variant(MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name

    # 1. users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.Unicode(length=50), nullable=False),
        sa.Column("email", sa.Unicode(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.Unicode(length=100), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=False)
    op.create_index("idx_users_username", "users", ["username"], unique=False)

    # 2. categories
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Unicode(length=50), nullable=False),
        sa.Column("icon", sa.String(length=50), server_default=sa.text("'tag'"), nullable=False),
        sa.Column("color", sa.String(length=20), server_default=sa.text("'#10B981'"), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("name", name="uq_categories_name"),
    )
    op.create_index("idx_categories_name", "categories", ["name"], unique=False)

    # 3. uploaded_receipts
    op.create_table(
        "uploaded_receipts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.Unicode(length=255), nullable=False),
        sa.Column("file_path", sa.Unicode(length=500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("azure_blob_url", sa.Unicode(length=500), nullable=True),
        sa.Column("ocr_raw_text", LongUnicodeText, nullable=True),
        sa.Column("ocr_status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("extracted_amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("extracted_merchant", sa.Unicode(length=100), nullable=True),
        sa.Column("extracted_date", sa.Date(), nullable=True),
        sa.Column("extracted_payment_method", sa.String(length=50), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ocr_status IN ('pending', 'success', 'failed', 'fallback')",
            name="chk_receipt_ocr_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_receipts_user",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_uploaded_receipts"),
    )
    op.create_index("idx_receipts_user", "uploaded_receipts", ["user_id", "created_at"], unique=False)
    op.create_index("idx_receipts_hash", "uploaded_receipts", ["user_id", "file_hash"], unique=False)

    # 4. expenses (NO ACTION on category & receipt avoids SQL Server Error 1785 cascade diamond)
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("merchant", sa.Unicode(length=100), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(length=30), server_default=sa.text("'UPI'"), nullable=False),
        sa.Column("notes", sa.UnicodeText(), nullable=True),
        sa.Column("receipt_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0.00", name="chk_expense_amount_positive"),
        sa.CheckConstraint(
            "payment_method IN ('UPI', 'Cash', 'Credit Card', 'Debit Card', 'Net Banking', 'Other')",
            name="chk_expense_payment_method",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_expenses_category",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["uploaded_receipts.id"],
            name="fk_expenses_receipt",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_expenses_user",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_expenses"),
    )
    op.create_index("fk_expenses_category", "expenses", ["category_id"], unique=False)
    op.create_index("fk_expenses_receipt", "expenses", ["receipt_id"], unique=False)
    op.create_index("idx_expenses_user_date", "expenses", ["user_id", "expense_date"], unique=False)
    op.create_index("idx_expenses_user_category", "expenses", ["user_id", "category_id"], unique=False)
    op.create_index("idx_expenses_merchant", "expenses", ["user_id", "merchant"], unique=False)

    # 5. budgets
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="chk_budget_month"),
        sa.CheckConstraint("year >= 2020", name="chk_budget_year"),
        sa.CheckConstraint("amount > 0.00", name="chk_budget_amount_positive"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_budgets_category",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_budgets_user",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_budgets"),
    )
    op.create_index("fk_budgets_category", "budgets", ["category_id"], unique=False)
    op.create_index("idx_budgets_lookup", "budgets", ["user_id", "year", "month"], unique=False)

    # Dialect-specific DB-enforced uniqueness for overall (NULL) & category budgets
    if dialect_name == "mssql":
        op.create_index(
            "uq_budgets_user_category_period",
            "budgets",
            ["user_id", "category_id", "month", "year"],
            unique=True,
            mssql_where=sa.text("category_id IS NOT NULL"),
        )
        op.create_index(
            "uq_budgets_user_overall_period",
            "budgets",
            ["user_id", "month", "year"],
            unique=True,
            mssql_where=sa.text("category_id IS NULL"),
        )
    else:
        op.execute(
            "ALTER TABLE budgets "
            "ADD COLUMN category_scope_key INT GENERATED ALWAYS AS (COALESCE(category_id, 0)) VIRTUAL, "
            "ADD UNIQUE KEY uq_budgets_user_scope_period (user_id, category_scope_key, month, year);"
        )


def downgrade() -> None:
    # Drop tables in reverse FK dependency order so DB engines remove
    # table-scoped indexes, constraints, and virtual columns atomically.
    op.drop_table("budgets")
    op.drop_table("expenses")
    op.drop_table("uploaded_receipts")
    op.drop_table("categories")
    op.drop_table("users")
