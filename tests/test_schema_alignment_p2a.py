"""
ExpenseTrack Phase 2A - Schema Alignment, Baseline Stamp & Idempotency Tests

Verifies non-destructive Alembic baseline stamping and schema-alignment migration
(`20261112_0002_align_existing_schema.py`) against:
1. A disposable MariaDB database reproducing the pre-Alembic `schema.sql` +
   `seed.sql` + representative receipt-linked expenses.
2. Duplicate overall-budget precondition safety guard.
3. Disposable SQL Server LocalDB databases upgraded across `0001 -> 0002 -> 0001 -> 0002`.
"""

from __future__ import annotations

import importlib.util
import os
import re
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pyodbc
import pymysql
import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from config import Config
from database.engine import create_db_engine
from database.exceptions import CheckConstraintViolationError
from database.init_db import split_sql_statements
from database.models import Budget, Category, Expense, UploadedReceipt, User
from database.session import session_scope
from repositories import AnalyticsRepository, BudgetRepository, ExpenseRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_0002_PATH = (
    PROJECT_ROOT / "migrations" / "versions" / "20261112_0002_align_existing_schema.py"
)


def _alembic_cfg_for(url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@contextmanager
def _env_target(url: str, backend: str) -> Iterator[None]:
    prev_url = os.environ.get("DATABASE_URL")
    prev_backend = os.environ.get("DB_BACKEND")
    os.environ["DATABASE_URL"] = url
    os.environ["DB_BACKEND"] = backend
    try:
        yield
    finally:
        if prev_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_url
        if prev_backend is None:
            os.environ.pop("DB_BACKEND", None)
        else:
            os.environ["DB_BACKEND"] = prev_backend


@contextmanager
def _disposable_mariadb() -> Iterator[tuple[str, str, Engine]]:
    db_name = f"et_p2a_maria_{uuid.uuid4().hex[:10]}"
    admin = pymysql.connect(
        host=Config.DB_HOST,
        port=int(Config.DB_PORT),
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with admin.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
    finally:
        admin.close()

    auth = f"{Config.DB_USER}:{Config.DB_PASSWORD}" if Config.DB_PASSWORD else Config.DB_USER
    url = f"mysql+pymysql://{auth}@{Config.DB_HOST}:{int(Config.DB_PORT)}/{db_name}?charset=utf8mb4"
    eng = create_db_engine(database_url=url, pool_size=2, max_overflow=2)
    try:
        yield db_name, url, eng
    finally:
        eng.dispose()
        drop_conn = pymysql.connect(
            host=Config.DB_HOST,
            port=int(Config.DB_PORT),
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            autocommit=True,
        )
        try:
            with drop_conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`;")
        finally:
            drop_conn.close()


@contextmanager
def _disposable_localdb() -> Iterator[tuple[str, str, Engine]]:
    db_name = f"et_p2a_mssql_{uuid.uuid4().hex[:10]}"
    master_conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=(localdb)\\MSSQLLocalDB;"
        "DATABASE=master;"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    admin = pyodbc.connect(master_conn_str, autocommit=True)
    try:
        cur = admin.cursor()
        cur.execute(f"CREATE DATABASE [{db_name}];")
        cur.close()
    finally:
        admin.close()

    url = (
        f"mssql+pyodbc://@(localdb)\\MSSQLLocalDB/{db_name}"
        "?driver=ODBC+Driver+17+for+SQL+Server&Trusted_Connection=yes&TrustServerCertificate=yes"
    )
    eng = create_db_engine(database_url=url, pool_size=2, max_overflow=2)
    try:
        yield db_name, url, eng
    finally:
        eng.dispose()
        drop_conn = pyodbc.connect(master_conn_str, autocommit=True)
        try:
            cur = drop_conn.cursor()
            cur.execute(
                f"""
                IF DB_ID(N'{db_name}') IS NOT NULL
                BEGIN
                    ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
                    DROP DATABASE [{db_name}];
                END
                """
            )
            cur.close()
        finally:
            drop_conn.close()


def _exec_legacy_sql_script(db_name: str, script_path: Path) -> None:
    """Execute schema.sql or seed.sql rewritten cleanly for ``db_name``."""
    raw = script_path.read_text(encoding="utf-8")
    rewritten = re.sub(r"`?expensetrack`?", f"`{db_name}`", raw, flags=re.IGNORECASE)
    stmts = split_sql_statements(rewritten)
    conn = pymysql.connect(
        host=Config.DB_HOST,
        port=int(Config.DB_PORT),
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=db_name,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            for stmt in stmts:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def _snapshot_counts_and_totals(eng: Engine) -> dict:
    with eng.connect() as conn:
        users = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        cats = conn.execute(text("SELECT COUNT(*) FROM categories")).scalar()
        budgets = conn.execute(text("SELECT COUNT(*) FROM budgets")).scalar()
        exps = conn.execute(text("SELECT COUNT(*) FROM expenses")).scalar()
        recs = conn.execute(text("SELECT COUNT(*) FROM uploaded_receipts")).scalar()
        total_amt = conn.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM expenses")
        ).scalar()
        budget_amt = conn.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM budgets")
        ).scalar()
        demo_id = conn.execute(
            text("SELECT id FROM users WHERE username = 'demo_student'")
        ).scalar()
    return {
        "users": int(users),
        "categories": int(cats),
        "budgets": int(budgets),
        "expenses": int(exps),
        "receipts": int(recs),
        "total_amt": Decimal(str(total_amt)),
        "budget_amt": Decimal(str(budget_amt)),
        "demo_id": int(demo_id) if demo_id is not None else None,
    }


def test_legacy_mariadb_schema_stamp_align_verify_idempotent_and_rollback():
    """
    Reproduce exact legacy MariaDB schema.sql + seed.sql + receipt link,
    stamp `20261112_0001`, run `0002` alignment, verify data preservation,
    duplicate overall budget blocking, idempotency, and downgrade rollback.
    """
    with _disposable_mariadb() as (db_name, url, eng):
        _exec_legacy_sql_script(db_name, PROJECT_ROOT / "database" / "schema.sql")
        _exec_legacy_sql_script(db_name, PROJECT_ROOT / "database" / "seed.sql")

        # Add a receipt + receipt-linked expense matching live demo footprint
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO uploaded_receipts "
                    "(user_id, file_name, file_path, file_size, mime_type, ocr_status, file_hash) "
                    "VALUES (1, 'demo_r.png', 'uploads/receipts/demo_r.png', 2048, 'image/png', 'fallback', :h)"
                ),
                {"h": "d" * 64},
            )
            rid = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
            conn.execute(
                text(
                    "UPDATE expenses SET receipt_id = :rid WHERE id = 1"
                ),
                {"rid": rid},
            )

        before = _snapshot_counts_and_totals(eng)
        assert before["demo_id"] == 1
        assert before["users"] == 1
        assert before["budgets"] == 6
        assert before["expenses"] == 22
        assert before["receipts"] == 1

        cfg = _alembic_cfg_for(url)
        with _env_target(url, "mariadb"):
            # Safe baseline step: stamp 0001 without altering pre-existing tables
            alembic_command.stamp(cfg, "20261112_0001")
            after_stamp = _snapshot_counts_and_totals(eng)
            assert after_stamp == before

            # Verify pre-alignment schema indeed lacks category_scope_key
            cols_pre = {c["name"] for c in inspect(eng).get_columns("budgets")}
            assert "category_scope_key" not in cols_pre

            # Execute alignment migration 0002
            alembic_command.upgrade(cfg, "head")

        with eng.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == "20261112_0002"

            # Verify generated column, unique index, widened month, DATETIME, portable CHECKs
            budget_cols = {
                r[0]: r[1].lower()
                for r in conn.execute(
                    text(
                        "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = 'budgets'"
                    ),
                    {"db": db_name},
                ).fetchall()
            }
            assert "category_scope_key" in budget_cols
            assert budget_cols["month"] == "smallint"
            assert budget_cols["created_at"] == "datetime"
            assert budget_cols["updated_at"] == "datetime"

            budget_idxs = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                        "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = 'budgets'"
                    ),
                    {"db": db_name},
                ).fetchall()
            }
            assert "uq_budgets_user_scope_period" in budget_idxs
            assert "uk_user_category_month_year" not in budget_idxs

            exp_col_pm = conn.execute(
                text(
                    "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = 'expenses' AND COLUMN_NAME = 'payment_method'"
                ),
                {"db": db_name},
            ).scalar()
            assert exp_col_pm.lower() == "varchar"

            user_idxs = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                        "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = 'users'"
                    ),
                    {"db": db_name},
                ).fetchall()
            }
            assert {"uq_users_username", "uq_users_email"}.issubset(user_idxs)

            # Verify fk_expenses_receipt stays ON DELETE SET NULL on MariaDB
            fk_del_rule = conn.execute(
                text(
                    "SELECT DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
                    "WHERE CONSTRAINT_SCHEMA = :db AND CONSTRAINT_NAME = 'fk_expenses_receipt'"
                ),
                {"db": db_name},
            ).scalar()
            assert fk_del_rule == "SET NULL"

        # 100% financial & record preservation
        after = _snapshot_counts_and_totals(eng)
        assert after == before

        # Duplicate overall monthly budget MUST now be rejected at database level!
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO budgets (user_id, category_id, month, year, amount) "
                        "VALUES (1, NULL, 10, 2026, 9999.00)"
                    )
                )

        # Invalid payment_method rejected by chk_expense_payment_method CHECK constraint
        with pytest.raises(CheckConstraintViolationError):
            with session_scope(eng) as s:
                s.execute(
                    text(
                        "INSERT INTO expenses (user_id, category_id, amount, merchant, expense_date, payment_method) "
                        "VALUES (1, 1, 10.00, 'BadPM', '2026-10-10', 'Crypto')"
                    )
                )

        # Verify SQLAlchemy 2.0 repositories operate cleanly against aligned schema
        exp_list = ExpenseRepository(eng).list_expenses(1, page=1, limit=5)
        assert exp_list["total_records"] == 22
        dash = AnalyticsRepository(eng).get_dashboard_summary_data(
            1,
            month=10,
            year=2026,
            start_date="2026-10-01",
            end_date="2026-10-31",
            prev_start="2026-09-01",
            prev_end="2026-09-30",
            trend_start="2026-05-01",
        )
        assert dash["month_stats"]["total_spent"] == Decimal("7058.00")
        BudgetRepository(eng).upsert_budget(
            user_id=1, category_id=None, month=11, year=2026, amount=Decimal("11000.00")
        )
        with eng.connect() as c:
            b11_id = c.execute(
                text(
                    "SELECT id FROM budgets WHERE user_id=1 AND category_id IS NULL AND month=11 AND year=2026"
                )
            ).scalar()
        BudgetRepository(eng).delete_budget(b11_id, 1)

        # Idempotency check: re-invoking 0002.upgrade() directly succeeds as a clean no-op
        spec = importlib.util.spec_from_file_location("mig_0002", MIGRATION_0002_PATH)
        mig_0002 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig_0002)
        with eng.begin() as conn:
            mc = MigrationContext.configure(conn)
            with Operations.context(mc):
                mig_0002.upgrade()
        assert _snapshot_counts_and_totals(eng) == before

        # Reversibility check: downgrade back to 20261112_0001 without losing any rows, then re-upgrade
        with _env_target(url, "mariadb"):
            alembic_command.downgrade(cfg, "20261112_0001")
            assert _snapshot_counts_and_totals(eng) == before
            cols_down = {c["name"] for c in inspect(eng).get_columns("budgets")}
            assert "category_scope_key" not in cols_down

            alembic_command.upgrade(cfg, "head")
            assert _snapshot_counts_and_totals(eng) == before
            cols_reup = {c["name"] for c in inspect(eng).get_columns("budgets")}
            assert "category_scope_key" in cols_reup


def test_legacy_mariadb_duplicate_overall_budgets_abort_safely():
    """
    If duplicate overall monthly budgets exist in a legacy MariaDB database,
    0002 must abort BEFORE modifying tables so no partial DDL or data loss occurs.
    """
    with _disposable_mariadb() as (db_name, url, eng):
        _exec_legacy_sql_script(db_name, PROJECT_ROOT / "database" / "schema.sql")
        _exec_legacy_sql_script(db_name, PROJECT_ROOT / "database" / "seed.sql")

        # Legacy unique key allows duplicate NULL category_id rows in MariaDB!
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO budgets (user_id, category_id, month, year, amount) "
                    "VALUES (1, NULL, 10, 2026, 8000.00)"
                )
            )
            cnt = conn.execute(text("SELECT COUNT(*) FROM budgets")).scalar()
            assert cnt == 7

        cfg = _alembic_cfg_for(url)
        with _env_target(url, "mariadb"):
            alembic_command.stamp(cfg, "20261112_0001")
            with pytest.raises(RuntimeError, match="duplicate budget scopes"):
                alembic_command.upgrade(cfg, "head")

        # Zero data loss & still cleanly at baseline revision
        with eng.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM budgets")).scalar() == 7
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "20261112_0001"


def test_sqlserver_localdb_alignment_idempotency_and_rollback():
    """
    Verify `0001 -> seed -> 0002 -> idempotent re-run -> downgrade 0001 -> re-upgrade head`
    on SQL Server LocalDB preserves all data and enforces filtered unique indexes.
    """
    with _disposable_localdb() as (db_name, url, eng):
        cfg = _alembic_cfg_for(url)
        with _env_target(url, "mssql"):
            alembic_command.upgrade(cfg, "20261112_0001")

        with session_scope(eng) as session:
            u = User(
                username="p2a_mssql_student",
                email="p2a_mssql@college.edu",
                password_hash="scrypt:hash",
                full_name="MSSQL Student",
            )
            cat = Category(name="Food", icon="utensils", color="#10B981", is_system=True)
            session.add_all([u, cat])
            session.flush()
            uid, cid = u.id, cat.id
            session.add(
                Budget(user_id=uid, category_id=None, month=10, year=2026, amount=Decimal("9000.00"))
            )
            session.add(
                Budget(user_id=uid, category_id=cid, month=10, year=2026, amount=Decimal("3000.00"))
            )
            session.add(
                Expense(
                    user_id=uid,
                    category_id=cid,
                    amount=Decimal("450.25"),
                    merchant="Campus Cafe",
                    expense_date=pytest.importorskip("datetime").date(2026, 10, 15),
                    payment_method="UPI",
                )
            )

        with _env_target(url, "mssql"):
            alembic_command.upgrade(cfg, "head")
            # Run 0002 again idempotently via upgrade module check
            spec = importlib.util.spec_from_file_location("mig_0002", MIGRATION_0002_PATH)
            mig_0002 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mig_0002)
            with eng.begin() as conn:
                mc = MigrationContext.configure(conn)
                with Operations.context(mc):
                    mig_0002.upgrade()

            # Duplicate overall budget blocked by filtered unique index uq_budgets_user_overall_period
            with pytest.raises(IntegrityError):
                with eng.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO budgets (user_id, category_id, month, year, amount) "
                            "VALUES (:uid, NULL, 10, 2026, 5000.00)"
                        ),
                        {"uid": uid},
                    )

            # Downgrade 0002 -> 0001 and re-upgrade head cleanly preserves all records
            alembic_command.downgrade(cfg, "20261112_0001")
            alembic_command.upgrade(cfg, "head")

        with eng.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "20261112_0002"
            assert conn.execute(text("SELECT SUM(amount) FROM expenses WHERE user_id = :u"), {"u": uid}).scalar() == Decimal("450.25")
            assert conn.execute(text("SELECT COUNT(*) FROM budgets WHERE user_id = :u"), {"u": uid}).scalar() == 2
