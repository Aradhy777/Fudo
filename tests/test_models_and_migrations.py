"""
ExpenseTrack Phase 1B - ORM Models, Exception Normalization & Alembic Migration Tests
Runs schema migrations, constraint validation, uniqueness tests, Decimal precision checks,
and cascade/deletion behavior against isolated disposable test databases on BOTH:
  1. MariaDB 10.11+ (PyMySQL)
  2. Microsoft SQL Server LocalDB (pyodbc)

SAFETY INVARIANT: Never touches, drops, or migrates the existing 'expensetrack' database.
"""

from __future__ import annotations

import io
import os
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote_plus

import pyodbc
import pymysql
import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError as SATimeoutError
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config as AppConfig
from database.engine import create_db_engine, dispose_engine, resolve_mssql_driver
from database.exceptions import (
    CheckConstraintViolationError,
    DatabaseConnectionError,
    DatabaseIntegrityError,
    DuplicateRecordError,
    ForeignKeyViolationError,
    LockTimeoutError,
    TransientDeadlockError,
    is_retryable_db_exception,
    translate_db_exception,
)
from database.models import (
    Base,
    Budget,
    Category,
    Expense,
    UploadedReceipt,
    User,
    delete_receipt_transactional,
    delete_user_transactional,
)


def _alembic_cfg() -> AlembicConfig:
    return AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))


@contextmanager
def _temp_env(updates: dict[str, str | None]):
    saved = {k: os.environ.get(k) for k in updates}
    try:
        for k, v in updates.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, prev in saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def _assert_safe_disposable_name(db_name: str) -> None:
    assert db_name.startswith("et_p1b_test_")
    assert db_name != AppConfig.DB_NAME
    assert db_name not in ("expensetrack", "master", "mysql", "information_schema", "performance_schema")


@contextmanager
def _disposable_mariadb():
    db_name = f"et_p1b_test_{uuid.uuid4().hex[:10]}"
    _assert_safe_disposable_name(db_name)

    admin_conn = pymysql.connect(
        host=AppConfig.DB_HOST,
        port=AppConfig.DB_PORT,
        user=AppConfig.DB_USER,
        password=AppConfig.DB_PASSWORD,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
    finally:
        admin_conn.close()

    eng = None
    try:
        with _temp_env({
            "DATABASE_URL": None,
            "DB_BACKEND": "mariadb",
            "DB_AUTH_MODE": "password",
            "DB_HOST": AppConfig.DB_HOST,
            "DB_PORT": str(AppConfig.DB_PORT),
            "DB_USER": AppConfig.DB_USER,
            "DB_PASSWORD": AppConfig.DB_PASSWORD,
            "DB_NAME": db_name,
        }):
            eng = create_db_engine(pool_size=2, max_overflow=2)
            yield db_name, eng
    finally:
        if eng is not None:
            dispose_engine(eng)
        drop_conn = pymysql.connect(
            host=AppConfig.DB_HOST,
            port=AppConfig.DB_PORT,
            user=AppConfig.DB_USER,
            password=AppConfig.DB_PASSWORD,
            autocommit=True,
        )
        try:
            with drop_conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`;")
        finally:
            drop_conn.close()


@contextmanager
def _disposable_localdb():
    drivers = set(pyodbc.drivers())
    if "ODBC Driver 17 for SQL Server" not in drivers and "ODBC Driver 18 for SQL Server" not in drivers:
        pytest.skip("Microsoft SQL Server ODBC driver not installed.")

    db_name = f"et_p1b_test_{uuid.uuid4().hex[:10]}"
    _assert_safe_disposable_name(db_name)
    odbc_driver = resolve_mssql_driver()
    master_conn_str = (
        f"DRIVER={{{odbc_driver}}};"
        r"SERVER=(localdb)\MSSQLLocalDB;"
        "DATABASE=master;"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
        "Trusted_Connection=yes;"
        "Connection Timeout=5;"
    )

    try:
        master_conn = pyodbc.connect(master_conn_str, autocommit=True)
    except Exception as exc:
        pytest.skip(f"SQL Server LocalDB unavailable: {type(exc).__name__}")

    try:
        cur = master_conn.cursor()
        cur.execute(f"CREATE DATABASE [{db_name}];")
        cur.close()
    finally:
        master_conn.close()

    eng = None
    try:
        with _temp_env({
            "DATABASE_URL": None,
            "DB_BACKEND": "mssql",
            "DB_AUTH_MODE": "trusted",
            "DB_HOST": r"(localdb)\MSSQLLocalDB",
            "DB_PORT": None,
            "DB_NAME": db_name,
        }):
            eng = create_db_engine(pool_size=2, max_overflow=2)
            yield db_name, eng
    finally:
        if eng is not None:
            dispose_engine(eng)
        drop_conn = pyodbc.connect(master_conn_str, autocommit=True)
        try:
            cur = drop_conn.cursor()
            cur.execute(
                f"IF DB_ID('{db_name}') IS NOT NULL "
                f"BEGIN ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                f"DROP DATABASE [{db_name}]; END"
            )
            cur.close()
        finally:
            drop_conn.close()


@pytest.fixture(params=["mariadb", "localdb"])
def disposable_target(request):
    if request.param == "mariadb":
        with _disposable_mariadb() as pair:
            yield "mariadb", pair[0], pair[1]
    else:
        with _disposable_localdb() as pair:
            yield "mssql", pair[0], pair[1]


# =====================================================================
# 1. EXCEPTION NORMALIZATION TESTS (PYMYSQL + PYODBC)
# =====================================================================

def test_exception_normalization_pymysql_and_pyodbc():
    """Verify uniform domain exception mapping without raw error leakage."""
    # PyMySQL Integrity & Operational mappings
    dup_m = translate_db_exception(IntegrityError("stmt", {}, pymysql.err.IntegrityError(1062, "Duplicate entry 'x'")))
    assert isinstance(dup_m, DuplicateRecordError)

    fk_m = translate_db_exception(IntegrityError("stmt", {}, pymysql.err.IntegrityError(1452, "Cannot add or update child row")))
    assert isinstance(fk_m, ForeignKeyViolationError)

    chk_m = translate_db_exception(OperationalError("stmt", {}, pymysql.err.OperationalError(4025, "CONSTRAINT chk_expense_amount_positive failed")))
    assert isinstance(chk_m, CheckConstraintViolationError)

    dl_m = translate_db_exception(OperationalError("stmt", {}, pymysql.err.OperationalError(1213, "Deadlock found")))
    assert isinstance(dl_m, TransientDeadlockError)
    assert is_retryable_db_exception(dl_m) is True

    lt_m = translate_db_exception(OperationalError("stmt", {}, pymysql.err.OperationalError(1205, "Lock wait timeout exceeded")))
    assert isinstance(lt_m, LockTimeoutError)
    assert is_retryable_db_exception(lt_m) is True

    conn_m = translate_db_exception(OperationalError("stmt", {}, pymysql.err.OperationalError(2003, "Can't connect to 10.0.0.5 secret-db")))
    assert isinstance(conn_m, DatabaseConnectionError)
    assert "secret-db" not in str(conn_m) and "10.0.0.5" not in str(conn_m)

    # Mock pyodbc-like exceptions
    class _FakePyodbcError(Exception):
        __module__ = "pyodbc"

    dup_s = translate_db_exception(IntegrityError("stmt", {}, _FakePyodbcError("23000", "[SQL Server]Violation of UNIQUE KEY constraint (2627)")))
    assert isinstance(dup_s, DuplicateRecordError)

    fk_s = translate_db_exception(IntegrityError("stmt", {}, _FakePyodbcError("23000", "[SQL Server]The DELETE statement conflicted with the REFERENCE constraint fk_expenses_category (547)")))
    assert isinstance(fk_s, ForeignKeyViolationError)

    chk_s = translate_db_exception(IntegrityError("stmt", {}, _FakePyodbcError("23000", "[SQL Server]The INSERT statement conflicted with the CHECK constraint chk_expense_amount_positive (547)")))
    assert isinstance(chk_s, CheckConstraintViolationError)

    dl_s = translate_db_exception(OperationalError("stmt", {}, _FakePyodbcError("40001", "[SQL Server]Transaction was deadlocked (1205)")))
    assert isinstance(dl_s, TransientDeadlockError)

    lt_s = translate_db_exception(OperationalError("stmt", {}, _FakePyodbcError("HYT00", "[SQL Server]Lock request time out period exceeded (1222)")))
    assert isinstance(lt_s, LockTimeoutError)

    pool_t = translate_db_exception(SATimeoutError("QueuePool limit of size 5 overflow 10 reached"))
    assert isinstance(pool_t, LockTimeoutError)


# =====================================================================
# 2. OFFLINE ALEMBIC DDL GENERATION CHECK
# =====================================================================

def test_alembic_offline_sql_generation_for_both_dialects(monkeypatch, capsys):
    """Alembic offline migration generates clean SQL for MariaDB & SQL Server without touching live DB."""
    # MariaDB offline
    with _temp_env({
        "DATABASE_URL": None,
        "DB_BACKEND": "mariadb",
        "DB_HOST": "127.0.0.1",
        "DB_USER": "test_user",
        "DB_NAME": "offline_db",
    }):
        alembic_command.upgrade(_alembic_cfg(), "head", sql=True)
    maria_sql = capsys.readouterr().out
    assert "CREATE TABLE expenses" in maria_sql
    assert "chk_expense_amount_positive" in maria_sql
    assert "GENERATED ALWAYS AS" in maria_sql

    # SQL Server offline
    with _temp_env({
        "DATABASE_URL": None,
        "DB_BACKEND": "mssql",
        "DB_AUTH_MODE": "trusted",
        "DB_HOST": r"(localdb)\MSSQLLocalDB",
        "DB_NAME": "offline_db",
    }):
        alembic_command.upgrade(_alembic_cfg(), "head", sql=True)
    mssql_sql = capsys.readouterr().out
    assert "IDENTITY" in mssql_sql
    assert "DATETIME2" in mssql_sql
    assert "WHERE category_id IS NULL" in mssql_sql
    assert "ON DELETE NO ACTION" in mssql_sql


# =====================================================================
# 3. LIVE DISPOSABLE MIGRATION, SCHEMA, UNIQUENESS & CASCADE TESTS
# =====================================================================

def test_alembic_upgrade_downgrade_reupgrade_and_schema_inspection(disposable_target):
    """Verify full Alembic upgrade -> downgrade -> re-upgrade and schema parity on MariaDB & LocalDB."""
    dialect, _, eng = disposable_target
    cfg = _alembic_cfg()

    # 1. Upgrade
    from alembic.script import ScriptDirectory

    expected_head = ScriptDirectory.from_config(cfg).get_current_head()
    alembic_command.upgrade(cfg, "head")
    with eng.connect() as conn:
        ver = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        assert ver == expected_head

    insp = inspect(eng)
    expected_tables = {"users", "categories", "uploaded_receipts", "expenses", "budgets"}
    assert expected_tables.issubset(set(insp.get_table_names()))

    # Verify columns, DECIMAL(10,2), DATETIME2 (MSSQL), FKs, indexes
    exp_cols = {c["name"]: c for c in insp.get_columns("expenses")}
    assert exp_cols["amount"]["type"].precision == 10
    assert exp_cols["amount"]["type"].scale == 2
    assert exp_cols["receipt_id"]["nullable"] is True
    assert exp_cols["notes"]["nullable"] is True
    if dialect == "mssql":
        assert "DATETIME2" in str(exp_cols["created_at"]["type"]).upper()

    exp_fks = {fk["name"]: fk for fk in insp.get_foreign_keys("expenses")}
    assert exp_fks["fk_expenses_user"]["referred_table"] == "users"
    assert exp_fks["fk_expenses_receipt"]["referred_table"] == "uploaded_receipts"
    assert exp_fks["fk_expenses_category"]["referred_table"] == "categories"

    exp_idx = {idx["name"] for idx in insp.get_indexes("expenses")}
    assert {"idx_expenses_user_date", "idx_expenses_user_category", "idx_expenses_merchant"}.issubset(exp_idx)

    # 2. Downgrade to base
    alembic_command.downgrade(cfg, "base")
    insp_after_down = inspect(eng)
    remaining = set(insp_after_down.get_table_names())
    assert expected_tables.isdisjoint(remaining)

    # 3. Re-upgrade cleanly
    alembic_command.upgrade(cfg, "head")
    assert expected_tables.issubset(set(inspect(eng).get_table_names()))


def test_orm_crud_decimal_constraints_budget_uniqueness_and_cascades(disposable_target):
    """Test real SQL inserts, CHECK/FK constraints, NULL budget uniqueness, & receipt/user deletion."""
    dialect, _, eng = disposable_target
    alembic_command.upgrade(_alembic_cfg(), "head")

    with Session(eng) as session:
        u1 = User(username="mig_student_1", email="mig1@university.edu", password_hash="scrypt:hash1", full_name="Student One ₹")
        u2 = User(username="mig_student_2", email="mig2@university.edu", password_hash="scrypt:hash2", full_name="Student Two")
        cat_food = Category(name="Food", icon="utensils", color="#10B981", is_system=True)
        cat_travel = Category(name="Travel", icon="car", color="#3B82F6", is_system=True)
        session.add_all([u1, u2, cat_food, cat_travel])
        session.commit()

        assert u1.id >= 1 and cat_food.id >= 1

        # 1. Duplicate user email/username normalized -> DuplicateRecordError
        with pytest.raises(IntegrityError) as exc_u:
            session.add(User(username="mig_student_1", email="other@u.edu", password_hash="x", full_name="Dup"))
            session.flush()
        assert isinstance(translate_db_exception(exc_u.value), DuplicateRecordError)
        session.rollback()

        # Re-fetch after rollback
        u1 = session.query(User).filter_by(username="mig_student_1").one()
        u2 = session.query(User).filter_by(username="mig_student_2").one()
        cat_food = session.query(Category).filter_by(name="Food").one()
        cat_travel = session.query(Category).filter_by(name="Travel").one()

        # 2. Receipt + Expense + exact Decimal persistence & relationships
        rec = UploadedReceipt(
            user_id=u1.id,
            file_name="r1.png",
            file_path="uploads/receipts/r1.png",
            file_size=2048,
            mime_type="image/png",
            ocr_status="fallback",
            extracted_amount=Decimal("450.50"),
            file_hash="a" * 64,
        )
        session.add(rec)
        session.flush()

        exp = Expense(
            user_id=u1.id,
            category_id=cat_food.id,
            amount=Decimal("450.50"),
            merchant="Campus Canteen Café",
            expense_date=date(2026, 10, 15),
            payment_method="UPI",
            receipt_id=rec.id,
        )
        exp_max = Expense(
            user_id=u1.id,
            category_id=cat_travel.id,
            amount=Decimal("99999999.99"),
            merchant="Max Cap Check",
            expense_date=date(2026, 10, 16),
            payment_method="Cash",
        )
        session.add_all([exp, exp_max])
        session.commit()

        loaded_exp = session.get(Expense, exp.id)
        assert loaded_exp.amount == Decimal("450.50")
        assert loaded_exp.receipt.file_name == "r1.png"
        assert loaded_exp.user.username == "mig_student_1"
        assert session.get(Expense, exp_max.id).amount == Decimal("99999999.99")

        # 3. CHECK constraints (amount <= 0, invalid payment_method, invalid ocr_status, invalid budget month)
        with pytest.raises((IntegrityError, OperationalError)) as exc_amt:
            session.add(Expense(user_id=u1.id, category_id=cat_food.id, amount=Decimal("0.00"), merchant="Zero", expense_date=date(2026, 10, 15)))
            session.flush()
        assert isinstance(translate_db_exception(exc_amt.value), CheckConstraintViolationError)
        session.rollback()

        with pytest.raises((IntegrityError, OperationalError)) as exc_pm:
            session.add(Expense(user_id=u1.id, category_id=cat_food.id, amount=Decimal("10.00"), merchant="BadPM", expense_date=date(2026, 10, 15), payment_method="Crypto"))
            session.flush()
        assert isinstance(translate_db_exception(exc_pm.value), CheckConstraintViolationError)
        session.rollback()

        with pytest.raises((IntegrityError, OperationalError)) as exc_ocr:
            session.add(UploadedReceipt(user_id=u1.id, file_name="x.png", file_path="x", file_size=10, mime_type="image/png", ocr_status="bogus"))
            session.flush()
        assert isinstance(translate_db_exception(exc_ocr.value), CheckConstraintViolationError)
        session.rollback()

        with pytest.raises((IntegrityError, OperationalError)) as exc_bmo:
            session.add(Budget(user_id=u1.id, category_id=None, month=13, year=2026, amount=Decimal("100.00")))
            session.flush()
        assert isinstance(translate_db_exception(exc_bmo.value), CheckConstraintViolationError)
        session.rollback()

        # 4. Budget Uniqueness: Category AND Overall (category_id IS NULL) across BOTH MariaDB & SQL Server
        u1 = session.query(User).filter_by(username="mig_student_1").one()
        u2 = session.query(User).filter_by(username="mig_student_2").one()
        cat_food = session.query(Category).filter_by(name="Food").one()
        cat_travel = session.query(Category).filter_by(name="Travel").one()

        session.add(Budget(user_id=u1.id, category_id=None, month=10, year=2026, amount=Decimal("10000.00")))
        session.add(Budget(user_id=u1.id, category_id=cat_food.id, month=10, year=2026, amount=Decimal("3500.00")))
        session.add(Budget(user_id=u1.id, category_id=cat_travel.id, month=10, year=2026, amount=Decimal("1500.00")))
        session.add(Budget(user_id=u2.id, category_id=None, month=10, year=2026, amount=Decimal("8000.00")))
        session.commit()

        # Duplicate overall budget (NULL category_id) for same user/month/year MUST fail at DB level!
        with pytest.raises(IntegrityError) as exc_dup_overall:
            session.add(Budget(user_id=u1.id, category_id=None, month=10, year=2026, amount=Decimal("12000.00")))
            session.flush()
        assert isinstance(translate_db_exception(exc_dup_overall.value), DuplicateRecordError)
        session.rollback()

        # Duplicate category budget MUST fail at DB level!
        with pytest.raises(IntegrityError) as exc_dup_cat:
            session.add(Budget(user_id=u1.id, category_id=cat_food.id, month=10, year=2026, amount=Decimal("4000.00")))
            session.flush()
        assert isinstance(translate_db_exception(exc_dup_cat.value), DuplicateRecordError)
        session.rollback()

        # 5. Category deletion blocked by NO ACTION FK on referenced expenses
        with pytest.raises(IntegrityError) as exc_cat_fk:
            session.execute(text("DELETE FROM categories WHERE id = :cid"), {"cid": cat_food.id})
            session.flush()
        assert isinstance(translate_db_exception(exc_cat_fk.value), ForeignKeyViolationError)
        session.rollback()

        # 6. Direct DELETE on uploaded_receipts blocked while Expense points to it;
        # transactional helper cleanly unlinks Expense.receipt_id -> None and removes receipt.
        with pytest.raises(IntegrityError) as exc_rec_fk:
            session.execute(text("DELETE FROM uploaded_receipts WHERE id = :rid"), {"rid": rec.id})
            session.flush()
        assert isinstance(translate_db_exception(exc_rec_fk.value), ForeignKeyViolationError)
        session.rollback()

        unlinked_path = delete_receipt_transactional(session, rec.id, u1.id)
        session.commit()
        assert unlinked_path == "uploads/receipts/r1.png"
        assert session.get(UploadedReceipt, rec.id) is None
        assert session.get(Expense, exp.id).receipt_id is None

        # 7. Create another linked receipt + expense and verify delete_user_transactional cascades cleanly
        rec2 = UploadedReceipt(
            user_id=u1.id,
            file_name="r2.png",
            file_path="uploads/receipts/r2.png",
            file_size=512,
            mime_type="image/png",
            ocr_status="fallback",
        )
        session.add(rec2)
        session.flush()
        exp.receipt_id = rec2.id
        session.commit()

        assert delete_user_transactional(session, u1.id) is True
        session.commit()

        assert session.query(User).filter_by(id=u1.id).count() == 0
        assert session.query(Expense).filter_by(user_id=u1.id).count() == 0
        assert session.query(Budget).filter_by(user_id=u1.id).count() == 0
        assert session.query(UploadedReceipt).filter_by(user_id=u1.id).count() == 0
        assert session.query(Budget).filter_by(user_id=u2.id).count() == 1


def test_orm_metadata_create_all_parity(disposable_target):
    """Verify Base.metadata.create_all creates identical uniqueness & constraints cleanly."""
    _, _, eng = disposable_target
    Base.metadata.create_all(eng)

    with Session(eng) as session:
        u = User(username="meta_user", email="meta@u.edu", password_hash="x", full_name="Meta User")
        session.add(u)
        session.flush()
        session.add(Budget(user_id=u.id, category_id=None, month=11, year=2026, amount=Decimal("500.00")))
        session.commit()

        with pytest.raises(IntegrityError) as exc_d:
            session.add(Budget(user_id=u.id, category_id=None, month=11, year=2026, amount=Decimal("900.00")))
            session.flush()
        assert isinstance(translate_db_exception(exc_d.value), DuplicateRecordError)
        session.rollback()

