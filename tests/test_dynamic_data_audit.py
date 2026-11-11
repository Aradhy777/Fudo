"""
ExpenseTrack Phase 1D - Hardcoded Data Elimination & Dynamic Data Tests

Verifies across both MariaDB and SQL Server LocalDB (disposable DBs) that:
- Auth/UI pages expose zero hardcoded demo credentials or mock snapshot metrics.
- No hardcoded demo credentials authenticate in clean/unseeded databases.
- Dashboard, Expenses, Budgets, Categories, Analytics, and Insights are strictly
  user-scoped and dynamically driven from database records.
- Missing OCR / receipt fields never fabricate fake dates, merchants, or methods.
- Empty user states work cleanly without hardcoded fallback numbers.
"""

from __future__ import annotations

import importlib
import io
import os
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pyodbc
import pymysql
import pytest
from PIL import Image
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.engine import Engine

import config as config_mod
from app import create_app
from config import Config
from database.engine import create_db_engine
from database.models import Category, UploadedReceipt
from database.session import session_scope
from services.ocr_service import OCRService

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


def _run_alembic_0001(database_url: str, backend: str) -> None:
    """Provision base 0001 schema cleanly in isolated disposable test DBs."""
    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    prev_url = os.environ.get("DATABASE_URL")
    prev_backend = os.environ.get("DB_BACKEND")
    os.environ["DATABASE_URL"] = database_url
    os.environ["DB_BACKEND"] = backend
    try:
        command.upgrade(alembic_cfg, "20261112_0001")
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
def _isolated_backend(backend: str) -> Iterator[tuple[str, Engine, object]]:
    db_name = f"et_p1d_test_{uuid.uuid4().hex[:10]}"
    engine: Engine | None = None

    if backend == "mariadb":
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
    elif backend == "localdb":
        master = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=(localdb)\\MSSQLLocalDB;"
            "DATABASE=master;"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )
        admin = pyodbc.connect(master, autocommit=True)
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
    else:
        raise ValueError(backend)

    try:
        _run_alembic_0001(url, backend)
        engine = create_db_engine(database_url=url, pool_size=3, max_overflow=3)
        with session_scope(engine) as session:
            for name, icon, color in DEFAULT_CATEGORIES:
                session.add(Category(name=name, icon=icon, color=color, is_system=True))
        flask_app = create_app(db_engine=engine)
        flask_app.config["TESTING"] = True
        yield backend, engine, flask_app
    finally:
        if engine is not None:
            engine.dispose()
        if backend == "mariadb":
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
        else:
            master = (
                "DRIVER={ODBC Driver 17 for SQL Server};"
                "SERVER=(localdb)\\MSSQLLocalDB;"
                "DATABASE=master;"
                "Trusted_Connection=yes;"
                "TrustServerCertificate=yes;"
            )
            drop_conn = pyodbc.connect(master, autocommit=True)
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


@pytest.fixture(params=["mariadb", "localdb"])
def clean_backend(request):
    with _isolated_backend(request.param) as env:
        yield env


def _register_user(client, tag: str) -> dict:
    res = client.post(
        "/api/auth/register",
        json={
            "username": f"user_{tag}",
            "email": f"user_{tag}@campus.edu",
            "password": "StrongPass!987",
            "full_name": f"User {tag}",
        },
        headers={"Origin": "http://127.0.0.1:5000"},
    )
    assert res.status_code == 201, res.get_json()
    return res.get_json()["user"]


def test_auth_page_exposes_no_hardcoded_demo_credentials_or_fake_metrics(clean_backend):
    _, _, flask_app = clean_backend
    client = flask_app.test_client()

    auth_html = client.get("/auth").get_data(as_text=True)
    for forbidden in (
        "Password123!",
        "student@expensetrack.edu",
        "autoFillDemo",
        "70.6%",
        "7,058",
        "2,942",
        "Aarav Sharma",
        "1-Click Fast Pass",
    ):
        assert forbidden not in auth_html, f"Found hardcoded demo artifact {forbidden!r} in /auth"

    # Attempting to log in with legacy demo credentials must fail on unseeded databases
    for ident in ("demo_student", "student@expensetrack.edu"):
        r = client.post(
            "/api/auth/login",
            json={"identifier": ident, "password": "Password123!"},
            headers={"Origin": "http://127.0.0.1:5000"},
        )
        assert r.status_code == 401


def test_dashboard_html_and_api_have_no_hardcoded_demo_metrics(clean_backend):
    backend, engine, flask_app = clean_backend
    client = flask_app.test_client()
    _register_user(client, "empty")

    dash_html = client.get("/dashboard").get_data(as_text=True)
    for fake_metric in ("70.6% Budget Used", "₹1,471", "40.4%", "Financial Pulse: October 2026"):
        assert fake_metric not in dash_html

    # Empty state verified dynamically
    empty_summary = client.get("/api/dashboard/summary?month=10&year=2026").get_json()
    assert empty_summary["is_empty_state"] is True
    assert empty_summary["total_spent"] == 0.0
    assert empty_summary["monthly_budget"] == 0.0
    assert empty_summary["expense_count"] == 0
    assert empty_summary["categories_breakdown"] == []
    assert empty_summary["recent_transactions"] == []

    empty_insights = client.get("/api/insights?month=10&year=2026").get_json()
    assert empty_insights["total_spent"] == 0.0
    assert empty_insights["highest_category"] is None
    assert empty_insights["recommendations"] == []

    # Dynamic category addition in DB flows directly into /api/expenses/categories
    with session_scope(engine) as session:
        session.add(Category(name="Hostel Mess", icon="utensils", color="#14B8A6", is_system=False))
    cats_res = client.get("/api/expenses/categories").get_json()["categories"]
    assert any(c["name"] == "Hostel Mess" for c in cats_res), f"DB category missing on {backend}"


def test_user_isolation_and_dynamic_calculations_across_backends(clean_backend):
    _, _, flask_app = clean_backend
    headers = {"Origin": "http://127.0.0.1:5000"}
    client_a = flask_app.test_client()
    client_b = flask_app.test_client()

    _register_user(client_a, "tenant_a")
    _register_user(client_b, "tenant_b")

    cats = client_a.get("/api/expenses/categories").get_json()["categories"]
    cat_food, cat_travel = cats[0]["id"], cats[1]["id"]

    assert (
        client_a.post(
            "/api/budgets",
            json={"month": 10, "year": 2026, "amount": "2000.00", "category_id": None},
            headers=headers,
        ).status_code
        == 200
    )
    exp_a = client_a.post(
        "/api/expenses",
        json={
            "amount": "500.00",
            "merchant": "TenantA Diner",
            "category_id": cat_food,
            "expense_date": "2026-10-14",
            "payment_method": "UPI",
        },
        headers=headers,
    )
    assert exp_a.status_code == 201
    exp_a_id = exp_a.get_json()["expense_id"]

    # User B must see empty state with zero bleed from User A
    b_dash = client_b.get("/api/dashboard/summary?month=10&year=2026").get_json()
    assert b_dash["total_spent"] == 0.0
    assert b_dash["monthly_budget"] == 0.0
    assert b_dash["expense_count"] == 0

    b_budgets = client_b.get("/api/budgets?month=10&year=2026").get_json()
    assert b_budgets["overall"]["budget_limit"] == 0.0
    assert b_budgets["overall"]["total_spent"] == 0.0

    b_insights = client_b.get("/api/insights?month=10&year=2026").get_json()
    assert b_insights["total_spent"] == 0.0
    assert client_b.get(f"/api/expenses/{exp_a_id}").status_code == 404

    # Updating User A's expense dynamically changes dashboard + insights calculations
    assert (
        client_a.put(
            f"/api/expenses/{exp_a_id}",
            json={
                "amount": "1700.00",
                "merchant": "TenantA Travel",
                "category_id": cat_travel,
                "expense_date": "2026-10-14",
                "payment_method": "Debit Card",
            },
            headers=headers,
        ).status_code
        == 200
    )
    a_dash = client_a.get("/api/dashboard/summary?month=10&year=2026").get_json()
    assert a_dash["total_spent"] == 1700.0
    assert a_dash["remaining_budget"] == 300.0
    assert a_dash["budget_used_percentage"] == 85.0
    assert a_dash["highest_category"]["name"] == "Travel"


def test_missing_ocr_data_does_not_generate_fake_values(clean_backend, tmp_path, monkeypatch):
    _, engine, flask_app = clean_backend
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    flask_app.config["UPLOAD_FOLDER"] = str(tmp_path)

    # 1. Text lacking merchant, date, amount, or payment keyword yields None (never fake strings)
    extracted = OCRService.extract_financial_entities("Receipt printout without recognizable entities")
    assert extracted["extracted_amount"] is None
    assert extracted["extracted_merchant"] is None
    assert extracted["extracted_date"] is None
    assert extracted["extracted_payment_method"] is None

    # 2. Receipt scan in fallback/unavailable OCR mode persists NULL in DB
    client = flask_app.test_client()
    _register_user(client, "ocr_clean")
    monkeypatch.setattr(OCRService, "find_tesseract_binary", classmethod(lambda cls: None))

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color=(15, 23, 42)).save(buf, format="PNG")
    res = client.post(
        "/api/receipts/scan",
        data={"receipt": (io.BytesIO(buf.getvalue()), "blank.png", "image/png")},
        content_type="multipart/form-data",
        headers={"Origin": "http://127.0.0.1:5000"},
    )
    assert res.status_code == 201
    rid = res.get_json()["receipt_id"]
    ocr_payload = res.get_json()["ocr"]
    assert ocr_payload["extracted_amount"] is None
    assert ocr_payload["extracted_merchant"] is None
    assert ocr_payload["extracted_date"] is None
    assert ocr_payload["extracted_payment_method"] is None

    with session_scope(engine) as session:
        rec = session.get(UploadedReceipt, rid)
        assert rec is not None
        assert rec.extracted_amount is None
        assert rec.extracted_merchant is None
        assert rec.extracted_date is None
        assert rec.extracted_payment_method is None


def test_no_static_dev_secret_literal_and_prod_guard(monkeypatch):
    # Ensure config uses ephemeral random secret when SECRET_KEY env var is absent,
    # while production still rejects empty/ephemeral SECRET_KEY.
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("FLASK_ENV", "development")
    importlib.reload(config_mod)
    assert not hasattr(config_mod, "_DEV_DEFAULT_SECRET")
    assert len(config_mod.Config.SECRET_KEY) >= 32
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"FLASK_ENV": "production"})
    monkeypatch.delenv("FLASK_ENV", raising=False)
    importlib.reload(config_mod)

