"""
ExpenseTrack Phase 1C - Dual-Backend Repository & Route Integration Tests

Verifies identical behavior across both MariaDB and SQL Server LocalDB using
isolated disposable databases provisioned via Alembic (never mutating the
live development `expensetrack` database).
"""

from __future__ import annotations

import io
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pyodbc
import pymysql
import pytest
from PIL import Image
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import event, select, text
from sqlalchemy.dialects import mssql, mysql
from sqlalchemy.engine import Engine

from app import create_app
from config import Config
from database.engine import create_db_engine, dispose_engine, get_engine
from database.models import Budget, Category, Expense, UploadedReceipt, User
from database.session import apply_row_lock, session_scope
from repositories.base import EntityNotFoundError
from repositories.budget_repo import BudgetRepository
from repositories.category_repo import CategoryRepository
from repositories.expense_repo import ExpenseRepository
from repositories.receipt_repo import ReceiptRepository
from repositories.user_repo import DuplicateAccountConflictError, UserRepository

DEFAULT_CATEGORIES = [
    ("Food", "utensils", "#10B981"),
    ("Travel", "car", "#3B82F6"),
    ("Shopping", "shopping-bag", "#EC4899"),
    ("Education", "book-open", "#8B5CF6"),
    ("Entertainment", "film", "#F59E0B"),
    ("Bills", "receipt", "#EF4444"),
    ("Healthcare", "heart-pulse", "#06B6D4"),
    ("Other", "circle-ellipsis", "#6B7280"),
]


def _run_alembic_upgrade(database_url: str, backend: str) -> None:
    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    prev_url = os.environ.get("DATABASE_URL")
    prev_backend = os.environ.get("DB_BACKEND")
    os.environ["DATABASE_URL"] = database_url
    os.environ["DB_BACKEND"] = backend
    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        if prev_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_url
        if prev_backend is None:
            os.environ.pop("DB_BACKEND", None)
        else:
            os.environ["DB_BACKEND"] = prev_backend


def _seed_default_categories(engine: Engine) -> None:
    with session_scope(engine) as session:
        for name, icon, color in DEFAULT_CATEGORIES:
            session.add(Category(name=name, icon=icon, color=color, is_system=True))


@contextmanager
def disposable_backend_env(backend: str) -> Iterator[tuple[str, Engine, object]]:
    """Provision an isolated MariaDB or SQL Server LocalDB database via Alembic."""
    db_name = f"et_p1c_test_{uuid.uuid4().hex[:10]}"
    engine: Engine | None = None

    if backend == "mariadb":
        admin_conn = pymysql.connect(
            host=Config.DB_HOST,
            port=int(Config.DB_PORT),
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
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

        auth = f"{Config.DB_USER}:{Config.DB_PASSWORD}" if Config.DB_PASSWORD else Config.DB_USER
        url = f"mysql+pymysql://{auth}@{Config.DB_HOST}:{int(Config.DB_PORT)}/{db_name}?charset=utf8mb4"
    elif backend == "localdb":
        master_conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=(localdb)\\MSSQLLocalDB;"
            "DATABASE=master;"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )
        admin_conn = pyodbc.connect(master_conn_str, autocommit=True)
        try:
            cur = admin_conn.cursor()
            cur.execute(f"CREATE DATABASE [{db_name}];")
            cur.close()
        finally:
            admin_conn.close()

        url = (
            f"mssql+pyodbc://@(localdb)\\MSSQLLocalDB/{db_name}"
            "?driver=ODBC+Driver+17+for+SQL+Server&Trusted_Connection=yes&TrustServerCertificate=yes"
        )
    else:
        raise ValueError(f"Unsupported test backend: {backend}")

    try:
        _run_alembic_upgrade(url, backend)
        engine = create_db_engine(database_url=url, pool_size=4, max_overflow=4)
        _seed_default_categories(engine)
        flask_app = create_app(db_engine=engine)
        flask_app.config["TESTING"] = True
        yield backend, engine, flask_app
    finally:
        if engine is not None:
            engine.dispose()
        if backend == "mariadb":
            cleanup_conn = pymysql.connect(
                host=Config.DB_HOST,
                port=int(Config.DB_PORT),
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                autocommit=True,
            )
            try:
                with cleanup_conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`;")
            finally:
                cleanup_conn.close()
        elif backend == "localdb":
            cleanup_conn_str = (
                "DRIVER={ODBC Driver 17 for SQL Server};"
                "SERVER=(localdb)\\MSSQLLocalDB;"
                "DATABASE=master;"
                "Trusted_Connection=yes;"
                "TrustServerCertificate=yes;"
            )
            cleanup_conn = pyodbc.connect(cleanup_conn_str, autocommit=True)
            try:
                cur = cleanup_conn.cursor()
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
                cleanup_conn.close()


@pytest.fixture(params=["mariadb", "localdb"])
def dual_backend(request):
    with disposable_backend_env(request.param) as env:
        yield env


def _seed_test_user(engine: Engine, suffix: str | None = None) -> int:
    tag = suffix or uuid.uuid4().hex[:8]
    with session_scope(engine) as session:
        user = User(
            username=f"p1c_{tag}",
            email=f"p1c_{tag}@student.edu",
            password_hash="scrypt:32768:8:1$placeholder$deadbeef",
            full_name=f"Student {tag}",
        )
        session.add(user)
        session.flush()
        return user.id


def _authed_client(flask_app, user_id: int, username: str = "tester"):
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = username
        sess["full_name"] = "Test Student"
        sess["email"] = f"{username}@student.edu"
    return client


# ---------------------------------------------------------------------------
# Step 1: Category Operations
# ---------------------------------------------------------------------------

def test_step1_categories_repo_and_route(dual_backend):
    backend, engine, flask_app = dual_backend
    repo = CategoryRepository(engine)

    cats = repo.list_categories()
    assert len(cats) == 8, f"Expected 8 default categories on {backend}"
    assert [c["name"] for c in cats] == [item[0] for item in DEFAULT_CATEGORIES]
    assert set(cats[0].keys()) == {"id", "name", "icon", "color"}
    assert repo.exists(cats[0]["id"]) is True
    assert repo.exists(999999) is False

    uid = _seed_test_user(engine, "cat")
    client = _authed_client(flask_app, uid, "p1c_cat")

    resp = client.get("/api/expenses/categories")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert len(payload["categories"]) == 8
    assert payload["categories"][0] == cats[0]


# ---------------------------------------------------------------------------
# Step 2: Expense Read Operations
# ---------------------------------------------------------------------------

def test_step2_expense_reads_pagination_filters_and_isolation(dual_backend):
    backend, engine, flask_app = dual_backend
    uid_a = _seed_test_user(engine, "read_a")
    uid_b = _seed_test_user(engine, "read_b")
    cats = CategoryRepository(engine).list_categories()
    cat_food = cats[0]["id"]
    cat_travel = cats[1]["id"]

    with session_scope(engine) as session:
        rec = UploadedReceipt(
            user_id=uid_a,
            file_name="coffee_receipt.png",
            file_path="uploads/receipts/coffee_receipt.png",
            file_size=1234,
            mime_type="image/png",
            ocr_status="success",
            file_hash="a" * 64,
        )
        session.add(rec)
        session.flush()

        session.add(
            Expense(
                user_id=uid_a,
                category_id=cat_food,
                amount=Decimal("125.50"),
                merchant="Bean 50%_Cafe",
                expense_date=date(2026, 10, 10),
                payment_method="UPI",
                notes="Morning coffee",
                receipt_id=rec.id,
            )
        )
        session.add(
            Expense(
                user_id=uid_a,
                category_id=cat_travel,
                amount=Decimal("310.75"),
                merchant="Metro Rail",
                expense_date=date(2026, 10, 15),
                payment_method="Debit Card",
                notes=None,
            )
        )
        session.add(
            Expense(
                user_id=uid_a,
                category_id=cat_food,
                amount=Decimal("99.99"),
                merchant="Canteen",
                expense_date=date(2026, 9, 25),
                payment_method="Cash",
                notes="Special discount item",
            )
        )
        # Other tenant expense that must remain invisible to user A
        session.add(
            Expense(
                user_id=uid_b,
                category_id=cat_food,
                amount=Decimal("500.00"),
                merchant="Secret Cafe",
                expense_date=date(2026, 10, 15),
                payment_method="UPI",
                notes="Other user",
            )
        )
        session.flush()

    client_a = _authed_client(flask_app, uid_a, "p1c_read_a")

    # Paginated list (ordered date DESC, id DESC)
    p1 = client_a.get("/api/expenses?page=1&limit=2")
    assert p1.status_code == 200
    d1 = p1.get_json()
    assert d1["pagination"] == {
        "page": 1,
        "limit": 2,
        "total_records": 3,
        "total_pages": 2,
    }
    assert len(d1["expenses"]) == 2
    assert d1["expenses"][0]["merchant"] == "Metro Rail"
    assert d1["expenses"][0]["notes"] == ""
    assert d1["expenses"][1]["merchant"] == "Bean 50%_Cafe"
    assert d1["expenses"][1]["receipt"] == {
        "file_name": "coffee_receipt.png",
        "azure_blob_url": None,
    }

    # Literal wildcard escaping in search (50%_ matches Bean 50%_Cafe only, not Canteen/Metro)
    escaped = client_a.get("/api/expenses?search=50%25_")
    assert escaped.status_code == 200
    assert escaped.get_json()["pagination"]["total_records"] == 1
    assert escaped.get_json()["expenses"][0]["merchant"] == "Bean 50%_Cafe"

    # Notes search & date range filter
    notes_hit = client_a.get("/api/expenses?search=discount&start_date=2026-09-01&end_date=2026-09-30")
    assert notes_hit.status_code == 200
    assert notes_hit.get_json()["pagination"]["total_records"] == 1

    # Single expense GET + tenant isolation
    target_id = d1["expenses"][0]["id"]
    single = client_a.get(f"/api/expenses/{target_id}")
    assert single.status_code == 200
    assert single.get_json()["expense"]["amount"] == 310.75
    assert single.get_json()["expense"]["notes"] == ""

    client_b = _authed_client(flask_app, uid_b, "p1c_read_b")
    assert client_b.get(f"/api/expenses/{target_id}").status_code == 404

    # Repository returns clean Decimal-compatible float & counts on both backends
    repo_res = ExpenseRepository(engine).list_expenses(uid_a, category_id=cat_food)
    assert repo_res["total_records"] == 2, f"Category filter mismatch on {backend}"


# ---------------------------------------------------------------------------
# Step 3: Expense Write Operations & Row-Level Locking
# ---------------------------------------------------------------------------

def test_apply_row_lock_dialect_compilation():
    stmt = apply_row_lock(select(User.id).where(User.id == 1), User)
    mysql_sql = str(stmt.compile(dialect=mysql.dialect()))
    mssql_sql = str(stmt.compile(dialect=mssql.dialect()))
    assert "FOR UPDATE" in mysql_sql
    assert "WITH (UPDLOCK, ROWLOCK)" in mssql_sql


def test_step3_expense_writes_locking_and_isolation(dual_backend):
    backend, engine, flask_app = dual_backend
    uid_a = _seed_test_user(engine, "write_a")
    uid_b = _seed_test_user(engine, "write_b")
    cats = CategoryRepository(engine).list_categories()
    cat_food, cat_travel = cats[0]["id"], cats[1]["id"]

    with session_scope(engine) as session:
        rec_b = UploadedReceipt(
            user_id=uid_b,
            file_name="b_receipt.png",
            file_path="uploads/receipts/b_receipt.png",
            file_size=500,
            mime_type="image/png",
            ocr_status="fallback",
            file_hash="b" * 64,
        )
        session.add(rec_b)
        session.flush()
        rec_b_id = rec_b.id

    client_a = _authed_client(flask_app, uid_a, "p1c_write_a")
    client_b = _authed_client(flask_app, uid_b, "p1c_write_b")
    headers = {"Origin": "http://127.0.0.1:5000"}

    # Create valid expense with Decimal precision boundary
    res = client_a.post(
        "/api/expenses",
        json={
            "amount": "0.01",
            "merchant": "Chai Point",
            "expense_date": "2026-10-12",
            "category_id": cat_food,
            "payment_method": "UPI",
            "notes": "Tea",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.get_json()
    eid = res.get_json()["expense_id"]

    # Invalid category rejected
    assert (
        client_a.post(
            "/api/expenses",
            json={
                "amount": 50,
                "merchant": "X",
                "expense_date": "2026-10-12",
                "category_id": 999999,
            },
            headers=headers,
        ).status_code
        == 400
    )

    # Receipt owned by user B rejected with 403
    assert (
        client_a.post(
            "/api/expenses",
            json={
                "amount": 50,
                "merchant": "X",
                "expense_date": "2026-10-12",
                "category_id": cat_food,
                "receipt_id": rec_b_id,
            },
            headers=headers,
        ).status_code
        == 403
    )

    # Update missing expense with invalid payload returns 404 before 400
    assert (
        client_a.put(
            "/api/expenses/999999",
            json={"amount": -10},
            headers=headers,
        ).status_code
        == 404
    )

    # Cross-tenant update & delete blocked
    assert (
        client_b.put(
            f"/api/expenses/{eid}",
            json={
                "amount": 100,
                "merchant": "Hack",
                "expense_date": "2026-10-12",
                "category_id": cat_food,
            },
            headers=headers,
        ).status_code
        == 404
    )
    assert client_b.delete(f"/api/expenses/{eid}", headers=headers).status_code == 404

    # Concurrent row-locked updates on the same expense serialize cleanly
    repo = ExpenseRepository(engine)
    errors = []

    def worker(val: Decimal):
        try:
            repo.update_expense(
                expense_id=eid,
                user_id=uid_a,
                category_id=cat_travel,
                amount=val,
                merchant="Concurrent Merchant",
                expense_date="2026-10-13",
                payment_method="Debit Card",
                notes="Updated",
            )
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(Decimal("111.11"),))
    t2 = threading.Thread(target=worker, args=(Decimal("222.22"),))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)
    assert not errors, f"Concurrent update failed on {backend}: {errors}"

    updated = repo.get_expense(eid, uid_a)
    assert updated["amount"] in (111.11, 222.22)
    assert updated["category_id"] == cat_travel

    # Concurrent update vs delete cleanly handles missing row via EntityNotFoundError
    assert client_a.delete(f"/api/expenses/{eid}", headers=headers).status_code == 200
    with pytest.raises(EntityNotFoundError):
        repo.update_expense(
            expense_id=eid,
            user_id=uid_a,
            category_id=cat_food,
            amount=Decimal("10.00"),
            merchant="Ghost",
            expense_date="2026-10-13",
            payment_method="Cash",
            notes=None,
        )

    # Stale deleted user session returns 401 on create_expense
    uid_stale = _seed_test_user(engine, "stale_w")
    client_stale = _authed_client(flask_app, uid_stale, "p1c_stale_w")
    with session_scope(engine) as session:
        session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid_stale})
    r_stale = client_stale.post(
        "/api/expenses",
        json={
            "amount": 25,
            "merchant": "Deleted",
            "expense_date": "2026-10-12",
            "category_id": cat_food,
        },
        headers=headers,
    )
    assert r_stale.status_code == 401


# ---------------------------------------------------------------------------
# Step 4: Budget Operations & Concurrency Locking
# ---------------------------------------------------------------------------

def test_step4_budgets_upsert_constraints_thresholds_and_concurrency(dual_backend):
    backend, engine, flask_app = dual_backend
    uid_a = _seed_test_user(engine, "bud_a")
    uid_b = _seed_test_user(engine, "bud_b")
    cats = CategoryRepository(engine).list_categories()
    cat_food = cats[0]["id"]
    cat_travel = cats[1]["id"]

    client_a = _authed_client(flask_app, uid_a, "p1c_bud_a")
    client_b = _authed_client(flask_app, uid_b, "p1c_bud_b")
    headers = {"Origin": "http://127.0.0.1:5000"}

    # Seed expenses in Oct 2026 and an adjacent month (Nov 2026 must NOT leak into Oct)
    with session_scope(engine) as session:
        session.add(
            Expense(
                user_id=uid_a,
                category_id=cat_food,
                amount=Decimal("850.00"),
                merchant="Mess",
                expense_date=date(2026, 10, 15),
                payment_method="UPI",
            )
        )
        session.add(
            Expense(
                user_id=uid_a,
                category_id=cat_travel,
                amount=Decimal("400.00"),
                merchant="Cab",
                expense_date=date(2026, 10, 16),
                payment_method="Cash",
            )
        )
        session.add(
            Expense(
                user_id=uid_a,
                category_id=cat_food,
                amount=Decimal("999.00"),
                merchant="Next Month",
                expense_date=date(2026, 11, 1),
                payment_method="UPI",
            )
        )

    # Set overall budget (warning >= 80%: 1250 / 1500 = 83.3%) and category budget (exceeded)
    r_ov = client_a.post(
        "/api/budgets",
        json={"month": 10, "year": 2026, "amount": "1500.00", "category_id": None},
        headers=headers,
    )
    assert r_ov.status_code == 200
    ov_id = r_ov.get_json()["budget_id"]

    r_cat = client_a.post(
        "/api/budgets",
        json={"month": 10, "year": 2026, "amount": "800.00", "category_id": cat_food},
        headers=headers,
    )
    assert r_cat.status_code == 200
    cat_budget_id = r_cat.get_json()["budget_id"]

    # Upsert same overall budget updates same row (critical for SQL Server filtered unique index!)
    r_ov2 = client_a.post(
        "/api/budgets",
        json={"month": 10, "year": 2026, "amount": "1500.00", "category_id": None},
        headers=headers,
    )
    assert r_ov2.status_code == 200
    assert r_ov2.get_json()["budget_id"] == ov_id

    get_res = client_a.get("/api/budgets?month=10&year=2026")
    assert get_res.status_code == 200
    bjson = get_res.get_json()
    assert bjson["overall"]["total_spent"] == 1250.0
    assert bjson["overall"]["status"] == "warning"
    assert bjson["overall"]["percentage"] == 83.3
    food_entry = next(c for c in bjson["categories"] if c["category_id"] == cat_food)
    assert food_entry["status"] == "exceeded"
    assert food_entry["total_spent"] == 850.0

    # Concurrent upserts across multiple threads on same (user, overall) & (user, category)
    repo = BudgetRepository(engine)
    concurrent_errors = []

    def upsert_worker(cat_val: int | None, amt: str):
        try:
            repo.upsert_budget(
                user_id=uid_a,
                category_id=cat_val,
                month=10,
                year=2026,
                amount=Decimal(amt),
            )
        except Exception as exc:  # pragma: no cover
            concurrent_errors.append(exc)

    threads = [
        threading.Thread(target=upsert_worker, args=(None, "2000.00")),
        threading.Thread(target=upsert_worker, args=(None, "2200.00")),
        threading.Thread(target=upsert_worker, args=(None, "2500.00")),
        threading.Thread(target=upsert_worker, args=(cat_travel, "600.00")),
        threading.Thread(target=upsert_worker, args=(cat_travel, "700.00")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not concurrent_errors, f"Concurrent budget upsert failed on {backend}: {concurrent_errors}"

    with session_scope(engine) as session:
        ov_rows = session.scalars(
            select(Budget).where(
                Budget.user_id == uid_a,
                Budget.category_id.is_(None),
                Budget.month == 10,
                Budget.year == 2026,
            )
        ).all()
        assert len(ov_rows) == 1
        assert ov_rows[0].amount in (Decimal("2000.00"), Decimal("2200.00"), Decimal("2500.00"))

    # Cross-tenant delete blocked; owner delete succeeds
    assert client_b.delete(f"/api/budgets/{cat_budget_id}", headers=headers).status_code == 404
    assert client_a.delete(f"/api/budgets/{cat_budget_id}", headers=headers).status_code == 200
    assert client_a.delete(f"/api/budgets/{cat_budget_id}", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Step 5: Receipt Operations & Transactional Deletion
# ---------------------------------------------------------------------------

def _make_test_png() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (40, 40), color=(16, 185, 129))
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_step5_receipts_dedup_serve_cleanup_and_transactional_delete(dual_backend, tmp_path, monkeypatch):
    backend, engine, flask_app = dual_backend
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    flask_app.config["UPLOAD_FOLDER"] = str(tmp_path)
    uid_a = _seed_test_user(engine, "rec_a")
    uid_b = _seed_test_user(engine, "rec_b")
    cats = CategoryRepository(engine).list_categories()
    cat_food = cats[0]["id"]

    client_a = _authed_client(flask_app, uid_a, "p1c_rec_a")
    client_b = _authed_client(flask_app, uid_b, "p1c_rec_b")
    headers = {"Origin": "http://127.0.0.1:5000"}
    png_bytes = _make_test_png()

    # Upload initial receipt
    r1 = client_a.post(
        "/api/receipts/scan",
        data={"receipt": (io.BytesIO(png_bytes), "bill1.png", "image/png")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert r1.status_code == 201, r1.get_json()
    d1 = r1.get_json()
    assert d1["is_duplicate"] is False
    rec_id_1 = d1["receipt_id"]
    file_name_1 = d1["file_name"]

    # Duplicate upload (same user, same file_hash) flagged accurately
    r2 = client_a.post(
        "/api/receipts/scan",
        data={"receipt": (io.BytesIO(png_bytes), "bill1_dup.png", "image/png")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert r2.status_code == 201, r2.get_json()
    d2 = r2.get_json()
    assert d2["is_duplicate"] is True
    assert "Receipt was already uploaded on" in (d2["duplicate_info"] or "")

    # Receipt ownership on file serving (owner allowed, another user 403)
    ok_resp = client_a.get(f"/uploads/receipts/{file_name_1}")
    assert ok_resp.status_code == 200
    ok_resp.close()
    assert client_b.get(f"/uploads/receipts/{file_name_1}").status_code == 403

    # Transactional receipt deletion preserves linked Expense row (critical for SQL Server NO ACTION FK!)
    exp_id = ExpenseRepository(engine).create_expense(
        user_id=uid_a,
        category_id=cat_food,
        amount=Decimal("45.00"),
        merchant="Snack Bar",
        expense_date="2026-10-18",
        payment_method="UPI",
        notes=None,
        receipt_id=rec_id_1,
    )
    rec_repo = ReceiptRepository(engine)
    # Wrong user cannot delete
    assert rec_repo.delete_receipt(rec_id_1, uid_b) is None
    # Owner deletes receipt cleanly; expense remains with receipt_id = None
    deleted_path = rec_repo.delete_receipt(rec_id_1, uid_a)
    assert deleted_path is not None
    exp_after = ExpenseRepository(engine).get_expense(exp_id, uid_a)
    assert exp_after is not None and exp_after["receipt_id"] is None

    # DB failure during scan_receipt cleans up newly written local file (zero orphans)
    before_files = {p.name for p in Path(tmp_path).glob("*")}
    with patch.object(
        ReceiptRepository,
        "record_receipt_with_dedup_check",
        side_effect=RuntimeError("Simulated DB crash"),
    ):
        fail_res = client_a.post(
            "/api/receipts/scan",
            data={"receipt": (io.BytesIO(png_bytes), "crash.png", "image/png")},
            content_type="multipart/form-data",
            headers=headers,
        )
        assert fail_res.status_code == 500
    after_files = {p.name for p in Path(tmp_path).glob("*")}
    assert after_files == before_files, f"Orphan upload left on {backend}: {after_files - before_files}"


# ---------------------------------------------------------------------------
# Step 6: User Operations, Auth/Profile, Diagnostics & Transactional User Delete
# ---------------------------------------------------------------------------

def test_step6_users_auth_profile_diagnostics_and_transactional_delete(dual_backend):
    backend, engine, flask_app = dual_backend
    headers = {"Origin": "http://127.0.0.1:5000"}
    client = flask_app.test_client()

    # 1. Full registration -> /api/auth/me -> logout -> login (username & uppercase email)
    reg = client.post(
        "/api/auth/register",
        json={
            "username": "student_one",
            "email": "Student.One@College.Edu",
            "password": "Password123!",
            "full_name": "Student One",
        },
        headers=headers,
    )
    assert reg.status_code == 201, reg.get_json()
    uid1 = reg.get_json()["user"]["id"]

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["user"]["email"] == "student.one@college.edu"
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    login_bad = client.post(
        "/api/auth/login",
        json={"identifier": "student_one", "password": "WrongPassword!"},
        headers=headers,
    )
    assert login_bad.status_code == 401

    login_email = client.post(
        "/api/auth/login",
        json={"identifier": "STUDENT.ONE@COLLEGE.EDU", "password": "Password123!"},
        headers=headers,
    )
    assert login_email.status_code == 200

    # 2. Diagnostics reports live backend status accurately
    diag = client.get("/api/system/diagnostics").get_json()["database"]
    assert diag["status"] == "connected"
    expected_label = "SQL Server / Azure SQL" if backend == "localdb" else "MySQL / MariaDB"
    assert diag["engine"] == expected_label

    # 3. Profile update & conflict checks against a second user
    client2 = flask_app.test_client()
    reg2 = client2.post(
        "/api/auth/register",
        json={
            "username": "student_two",
            "email": "student.two@college.edu",
            "password": "Password123!",
            "full_name": "Student Two",
        },
        headers=headers,
    )
    assert reg2.status_code == 201
    uid2 = reg2.get_json()["user"]["id"]

    assert (
        client.post(
            "/api/profile/update",
            json={"full_name": "Student One Updated", "email": "student.two@college.edu"},
            headers=headers,
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/profile/update",
            json={"full_name": "Student One Updated", "email": "student.one.new@college.edu"},
            headers=headers,
        ).status_code
        == 200
    )

    # 4. Password rotation invalidates old password
    assert (
        client.post(
            "/api/profile/change-password",
            json={"old_password": "Password123!", "new_password": "NewPassword456!"},
            headers=headers,
        ).status_code
        == 200
    )
    client.post("/api/auth/logout", headers=headers)
    assert (
        client.post(
            "/api/auth/login",
            json={"identifier": "student_one", "password": "Password123!"},
            headers=headers,
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"identifier": "student_one", "password": "NewPassword456!"},
            headers=headers,
        ).status_code
        == 200
    )

    # 5. Concurrent duplicate registrations yield clean conflict exceptions (never 500)
    repo = UserRepository(engine)
    reg_outcomes = []

    def concurrent_reg():
        try:
            uid = repo.register_user(
                username="race_user",
                email="race_user@college.edu",
                password_hash="scrypt:32768:8:1$x$y",
                full_name="Race User",
            )
            reg_outcomes.append(("created", uid))
        except Exception as exc:
            reg_outcomes.append(("conflict", type(exc).__name__))

    threads = [threading.Thread(target=concurrent_reg) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert sum(1 for k, _ in reg_outcomes if k == "created") == 1
    assert len(reg_outcomes) == 4

    # 6. Transactional user deletion clears NO ACTION receipt/expense FKs on SQL Server & MariaDB
    cats = CategoryRepository(engine).list_categories()
    cat_food = cats[0]["id"]
    rec_res = ReceiptRepository(engine).record_receipt_with_dedup_check(
        user_id=uid1,
        file_name="user_del.png",
        file_path="uploads/receipts/user_del.png",
        file_size=100,
        mime_type="image/png",
        azure_blob_url=None,
        ocr_raw_text=None,
        ocr_status="fallback",
        extracted_amount=None,
        extracted_merchant=None,
        extracted_date=None,
        extracted_payment_method=None,
        file_hash="c" * 64,
    )
    ExpenseRepository(engine).create_expense(
        user_id=uid1,
        category_id=cat_food,
        amount=Decimal("75.00"),
        merchant="Linked Receipt Expense",
        expense_date="2026-10-19",
        payment_method="UPI",
        notes="Testing user delete cascade",
        receipt_id=rec_res["receipt_id"],
    )
    BudgetRepository(engine).upsert_budget(
        user_id=uid1,
        category_id=None,
        month=10,
        year=2026,
        amount=Decimal("5000.00"),
    )

    assert repo.delete_user(uid1) is True
    assert repo.delete_user(uid1) is False
    with session_scope(engine) as session:
        assert session.scalar(select(User.id).where(User.id == uid1)) is None
        assert session.scalar(select(UploadedReceipt.id).where(UploadedReceipt.user_id == uid1)) is None
        assert session.scalar(select(Expense.id).where(Expense.user_id == uid1)) is None
        assert session.scalar(select(Budget.id).where(Budget.user_id == uid1)) is None


# ---------------------------------------------------------------------------
# Step 7: Analytics Operations (Dashboard Summary & Monthly Insights)
# ---------------------------------------------------------------------------

def test_step7_analytics_dashboard_insights_and_single_checkout(dual_backend):
    backend, engine, flask_app = dual_backend
    headers = {"Origin": "http://127.0.0.1:5000"}
    client = flask_app.test_client()

    reg = client.post(
        "/api/auth/register",
        json={
            "username": "analytics_student",
            "email": "analytics@college.edu",
            "password": "Password123!",
            "full_name": "Analytics Student",
        },
        headers=headers,
    )
    assert reg.status_code == 201
    cats = CategoryRepository(engine).list_categories()
    cat_food, cat_travel = cats[0]["id"], cats[1]["id"]

    # Empty state check
    empty_dash = client.get("/api/dashboard/summary?month=10&year=2026").get_json()
    assert empty_dash["is_empty_state"] is True
    assert empty_dash["total_spent"] == 0.0
    assert empty_dash["categories_breakdown"] == []

    # Populate prior month (Sep 2026) and current month (Oct 2026) expenses + budgets
    assert client.post("/api/budgets", json={"month": 10, "year": 2026, "amount": "1000.00", "category_id": None}, headers=headers).status_code == 200
    assert client.post("/api/budgets", json={"month": 10, "year": 2026, "amount": "500.00", "category_id": cat_food}, headers=headers).status_code == 200
    assert client.post("/api/expenses", json={"amount": "400.00", "merchant": "Sep Canteen", "category_id": cat_food, "expense_date": "2026-09-18", "payment_method": "UPI"}, headers=headers).status_code == 201
    assert client.post("/api/expenses", json={"amount": "600.00", "merchant": "Oct Mess", "category_id": cat_food, "expense_date": "2026-10-12", "payment_method": "UPI", "notes": ""}, headers=headers).status_code == 201
    assert client.post("/api/expenses", json={"amount": "250.00", "merchant": "Oct Metro", "category_id": cat_travel, "expense_date": "2026-10-20", "payment_method": "Debit Card"}, headers=headers).status_code == 201

    # Verify single pooled DBAPI connection checkout per /api/dashboard/summary request
    checkout_count = 0

    def count_checkout(dbapi_conn, conn_record, conn_proxy):
        nonlocal checkout_count
        checkout_count += 1

    event.listen(engine, "checkout", count_checkout)
    try:
        dash_res = client.get("/api/dashboard/summary?month=10&year=2026")
    finally:
        event.remove(engine, "checkout", count_checkout)

    assert dash_res.status_code == 200
    assert checkout_count == 1, f"Expected 1 checkout per dashboard request on {backend}, got {checkout_count}"
    djson = dash_res.get_json()
    assert djson["is_empty_state"] is False
    assert djson["total_spent"] == 850.0
    assert djson["monthly_budget"] == 1000.0
    assert djson["remaining_budget"] == 150.0
    assert djson["budget_used_percentage"] == 85.0
    assert djson["expense_count"] == 2
    assert djson["avg_transaction_amount"] == 425.0
    assert djson["prev_month_spent"] == 400.0
    assert djson["mom_percentage_change"] == 112.5
    assert [c["name"] for c in djson["categories_breakdown"]] == ["Food", "Travel"]
    assert djson["monthly_trend"]["data"][-2:] == [400.0, 850.0]
    assert len(djson["recent_transactions"]) == 2
    assert djson["recent_transactions"][0]["merchant"] == "Oct Metro"
    assert djson["recent_transactions"][0]["notes"] == ""

    # Insights endpoint verification (single checkout as well!)
    ins_checkout_count = 0

    def count_ins_checkout(dbapi_conn, conn_record, conn_proxy):
        nonlocal ins_checkout_count
        ins_checkout_count += 1

    event.listen(engine, "checkout", count_ins_checkout)
    try:
        ins_res = client.get("/api/insights?month=10&year=2026")
    finally:
        event.remove(engine, "checkout", count_ins_checkout)

    assert ins_res.status_code == 200
    assert ins_checkout_count == 1
    ij = ins_res.get_json()
    assert ij["total_spent"] == 850.0
    assert ij["overall_budget"] == 1000.0
    assert ij["budget_utilization"] == 85.0
    assert ij["prev_spent"] == 400.0
    assert ij["month_over_month_change"] == 112.5
    titles = {r["title"] for r in ij["recommendations"]}
    assert "High Budget Utilization (80%+ Alert)" in titles
    assert "Dominant Category: Food" in titles
    assert "Category Limit Breached: Food" in titles


# ---------------------------------------------------------------------------
# Task 6 & Transaction Rollback Verification
# ---------------------------------------------------------------------------

def test_session_rollback_on_mid_transaction_exception(dual_backend):
    backend, engine, _ = dual_backend
    uid = _seed_test_user(engine, "rollback")
    cats = CategoryRepository(engine).list_categories()

    with pytest.raises(RuntimeError, match="forced abort"):
        with session_scope(engine) as session:
            session.add(
                Expense(
                    user_id=uid,
                    category_id=cats[0]["id"],
                    amount=Decimal("88.88"),
                    merchant="ShouldRollback",
                    expense_date=date(2026, 10, 15),
                    payment_method="UPI",
                )
            )
            session.flush()
            raise RuntimeError("forced abort")

    res = ExpenseRepository(engine).list_expenses(uid)
    assert res["total_records"] == 0, f"Rollback failed on {backend}"


def test_env_selection_does_not_autocreate_or_automigrate(monkeypatch):
    missing_db = f"et_missing_{uuid.uuid4().hex[:8]}"
    missing_url = (
        f"mssql+pyodbc://@(localdb)\\MSSQLLocalDB/{missing_db}"
        "?driver=ODBC+Driver+17+for+SQL+Server&Trusted_Connection=yes&TrustServerCertificate=yes"
    )
    dispose_engine()
    monkeypatch.setenv("DB_BACKEND", "mssql")
    monkeypatch.setenv("DB_AUTH_MODE", "trusted")
    monkeypatch.setenv("DATABASE_URL", missing_url)
    try:
        unmigrated_app = create_app()
        assert unmigrated_app is not None
        active = get_engine()
        assert active.dialect.name == "mssql"
        with pytest.raises(Exception):
            with session_scope() as session:
                session.execute(text("SELECT 1"))
    finally:
        dispose_engine()
