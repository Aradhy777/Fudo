"""
ExpenseTrack Phase 1A - SQLAlchemy 2.0 Database Engine Foundation Tests
Covers environment URL resolution, MariaDB & SQL Server (LocalDB / Azure SQL)
engine construction, Managed Identity token hook, connection pooling,
SELECT 1 connectivity, failure sanitization, disposal, and credential redaction.
"""

import logging
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pyodbc
import pytest
from sqlalchemy.pool import QueuePool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import database.engine as engine_mod
from database.engine import (
    check_db_connection,
    create_db_engine,
    dispose_engine,
    get_engine,
    get_pool_status,
    load_database_settings,
    redact_database_url,
)


def _clear_db_env(monkeypatch):
    for key in (
        "DATABASE_URL",
        "DB_BACKEND",
        "DB_AUTH_MODE",
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
        "DB_DRIVER",
        "DB_ENCRYPT",
        "DB_TRUST_SERVER_CERTIFICATE",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
        "DB_POOL_PRE_PING",
        "DB_CONNECT_TIMEOUT",
        "DB_ECHO",
    ):
        monkeypatch.delenv(key, raising=False)


# =====================================================================
# 1. URL CONFIGURATION & VALIDATION TESTS
# =====================================================================

def test_database_url_explicit_normalization_and_validation(monkeypatch):
    """Explicit DATABASE_URL normalizes plain schemes and rejects dialect conflicts."""
    _clear_db_env(monkeypatch)

    monkeypatch.setenv("DATABASE_URL", "mysql://student:Secr3t@127.0.0.1:3306/expensetrack")
    cfg_m = load_database_settings()
    assert cfg_m.backend == "mariadb"
    assert cfg_m.url.drivername == "mysql+pymysql"

    monkeypatch.setenv("DATABASE_URL", "mariadb://student:Secr3t@localhost:3306/expensetrack")
    cfg_mdb = load_database_settings()
    assert cfg_mdb.backend == "mariadb"
    assert cfg_mdb.url.drivername == "mysql+pymysql"

    monkeypatch.setenv(
        "DATABASE_URL",
        "mssql://user:Secr3t@sql.database.windows.net:1433/expensetrack?driver=ODBC+Driver+18+for+SQL+Server",
    )
    cfg_s = load_database_settings()
    assert cfg_s.backend == "mssql"
    assert cfg_s.url.drivername == "mssql+pyodbc"

    # Mismatched backend vs URL rejected cleanly
    monkeypatch.setenv("DB_BACKEND", "mssql")
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pw@localhost/db")
    with pytest.raises(ValueError, match="conflicts"):
        load_database_settings()


def test_invalid_backend_auth_and_missing_required_fields(monkeypatch):
    """Invalid DB_BACKEND, DB_AUTH_MODE, or missing required fields raise ValueError."""
    _clear_db_env(monkeypatch)

    monkeypatch.setenv("DB_BACKEND", "postgres")
    with pytest.raises(ValueError, match="Unsupported DB_BACKEND"):
        load_database_settings()

    monkeypatch.setenv("DB_BACKEND", "mariadb")
    monkeypatch.setenv("DB_AUTH_MODE", "kerberos")
    with pytest.raises(ValueError, match="Unsupported DB_AUTH_MODE"):
        load_database_settings()

    monkeypatch.setenv("DB_BACKEND", "mariadb")
    monkeypatch.setenv("DB_AUTH_MODE", "managed_identity")
    with pytest.raises(ValueError, match="does not support"):
        load_database_settings()

    monkeypatch.setenv("DB_AUTH_MODE", "password")
    with pytest.raises(ValueError, match="DB_USER"):
        load_database_settings()

    monkeypatch.setenv("DB_BACKEND", "mssql")
    with pytest.raises(ValueError, match="DB_HOST"):
        load_database_settings()


# =====================================================================
# 2. ENGINE INITIALIZATION & CREDENTIAL REDACTION TESTS
# =====================================================================

def test_mariadb_engine_initialization_and_redaction(monkeypatch):
    """Verify MariaDB URL assembly, QueuePool defaults, and credential masking."""
    _clear_db_env(monkeypatch)
    secret = "Sup3r@Secret:Pw!"
    monkeypatch.setenv("DB_BACKEND", "mariadb")
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_USER", "app_user")
    monkeypatch.setenv("DB_PASSWORD", secret)
    monkeypatch.setenv("DB_NAME", "expensetrack_test")

    cfg = load_database_settings()
    assert cfg.backend == "mariadb"
    assert cfg.url.drivername == "mysql+pymysql"
    assert cfg.url.host == "db.internal"
    assert cfg.url.port == 3307
    assert cfg.url.query.get("charset") == "utf8mb4"
    assert secret not in cfg.redacted_url
    assert "***" in cfg.redacted_url

    eng = create_db_engine(cfg)
    try:
        status = get_pool_status(eng)
        assert status["dialect"] == "mysql"
        assert status["driver"] == "pymysql"
        assert status["pool_class"] == "QueuePool"
        assert status["pool_size"] == 5
        assert status["pool_recycle"] == 1800
        assert status["pool_pre_ping"] is True
        assert secret not in status["redacted_url"]
    finally:
        dispose_engine(eng)


def test_sqlserver_engine_initialization_azure_vs_localdb_and_redaction(monkeypatch):
    """Verify SQL Server URL defaults, ODBC semicolon escaping, and Managed Identity hook."""
    _clear_db_env(monkeypatch)
    pw_special = "Sec;ret{Brace}99!"

    # A. Remote Azure SQL password mode enforces Encrypt=yes & TrustServerCertificate=no
    monkeypatch.setenv("DB_BACKEND", "azure_sql")
    monkeypatch.setenv("DB_AUTH_MODE", "password")
    monkeypatch.setenv("DB_HOST", "sql-expensetrack-dev.database.windows.net")
    monkeypatch.setenv("DB_PORT", "1433")
    monkeypatch.setenv("DB_USER", "sqladmin")
    monkeypatch.setenv("DB_PASSWORD", pw_special)
    monkeypatch.setenv("DB_NAME", "sqldb-expensetrack")
    monkeypatch.setenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")

    cfg_azure = load_database_settings()
    odbc = cfg_azure.url.query["odbc_connect"]
    assert "SERVER=sql-expensetrack-dev.database.windows.net,1433;" in odbc
    assert "Encrypt=yes;" in odbc
    assert "TrustServerCertificate=no;" in odbc
    assert "Sec;ret" not in cfg_azure.redacted_url
    assert "Brace" not in cfg_azure.redacted_url
    assert "PWD=***" in cfg_azure.redacted_url or "PWD%3D%2A%2A%2A" in cfg_azure.redacted_url

    # Also test redact_database_url directly on arbitrary AccessToken / PWD strings
    scrubbed = redact_database_url("mssql+pyodbc:///?odbc_connect=SERVER=x;PWD=TopSecret1;AccessToken=eyJ0abc;")
    assert "TopSecret1" not in scrubbed
    assert "eyJ0abc" not in scrubbed

    # B. LocalDB trusted mode defaults to local encryption settings without UID/PWD
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_BACKEND", "mssql")
    monkeypatch.setenv("DB_AUTH_MODE", "trusted")
    monkeypatch.setenv("DB_HOST", r"(localdb)\MSSQLLocalDB")
    monkeypatch.setenv("DB_NAME", "master")
    cfg_local = load_database_settings()
    assert "Trusted_Connection=yes" in cfg_local.url.query["odbc_connect"]
    assert "Encrypt=no;" in cfg_local.url.query["odbc_connect"]
    assert "TrustServerCertificate=yes;" in cfg_local.url.query["odbc_connect"]

    # C. Azure Managed Identity mode injects UTF-16-LE token in do_connect attrs_before
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_BACKEND", "mssql")
    monkeypatch.setenv("DB_AUTH_MODE", "managed_identity")
    monkeypatch.setenv("DB_HOST", "sql-expensetrack-dev.database.windows.net")
    monkeypatch.setenv("DB_NAME", "sqldb-expensetrack")

    eng_mi = create_db_engine()
    try:
        odbc_mi = eng_mi.url.query["odbc_connect"]
        assert "UID=" not in odbc_mi and "PWD=" not in odbc_mi and "Trusted_Connection" not in odbc_mi

        captured_kwargs = {}

        def _fake_pyodbc_connect(*args, **kwargs):
            captured_kwargs.update(kwargs)
            raise RuntimeError("stop-after-token-capture")

        fake_cred = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="entra-test-token"))
        with patch("azure.identity.DefaultAzureCredential", return_value=fake_cred), \
             patch("pyodbc.connect", side_effect=_fake_pyodbc_connect):
            with pytest.raises(RuntimeError, match="stop-after-token-capture"):
                eng_mi.connect()
        token_struct = captured_kwargs["attrs_before"][1256]
        length, = struct.unpack("<I", token_struct[:4])
        assert token_struct[4:4 + length].decode("utf-16-le") == "entra-test-token"
    finally:
        dispose_engine(eng_mi)


# =====================================================================
# 3. POOL CONFIGURATION & LIFECYCLE TESTS
# =====================================================================

def test_pool_configuration_and_disposal(monkeypatch):
    """Verify pool parameters, validation bounds, singleton caching, and disposal cleanup."""
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_BACKEND", "mariadb")
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_USER", "root")
    monkeypatch.setenv("DB_POOL_SIZE", "8")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "4")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "15")
    monkeypatch.setenv("DB_POOL_RECYCLE", "900")
    monkeypatch.setenv("DB_POOL_PRE_PING", "true")

    dispose_engine()
    eng = get_engine()
    try:
        assert eng is get_engine()
        assert isinstance(eng.pool, QueuePool)
        status = get_pool_status(eng)
        assert status["pool_size"] == 8
        assert status["pool_timeout"] == 15
        assert status["pool_recycle"] == 900
        assert status["pool_pre_ping"] is True
        assert eng.pool._max_overflow == 4
    finally:
        dispose_engine()

    assert engine_mod._engine is None

    # Invalid pool integer checks
    monkeypatch.setenv("DB_POOL_SIZE", "0")
    with pytest.raises(ValueError, match="DB_POOL_SIZE"):
        load_database_settings()


# =====================================================================
# 4. LIVE CONNECTIVITY & FAILURE HANDLING TESTS (READ-ONLY)
# =====================================================================

def test_mariadb_live_connection_select_1_and_disposal():
    """Verify read-only SELECT 1 against local MariaDB using SQLAlchemy engine & clean disposal."""
    eng = create_db_engine(backend="mariadb", auth_mode="password")
    try:
        ok, msg = check_db_connection(eng)
        assert ok is True
        assert "mysql" in msg.lower()
        assert eng.pool.checkedin() >= 1
    finally:
        dispose_engine(eng)
    assert eng.pool.checkedin() == 0


def test_sqlserver_localdb_live_connection_select_1(monkeypatch):
    """Verify read-only SELECT 1 against local SQL Server LocalDB (master DB, zero mutations)."""
    if "ODBC Driver 17 for SQL Server" not in pyodbc.drivers() and "ODBC Driver 18 for SQL Server" not in pyodbc.drivers():
        pytest.skip("Microsoft ODBC Driver for SQL Server not installed.")

    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_BACKEND", "mssql")
    monkeypatch.setenv("DB_AUTH_MODE", "trusted")
    monkeypatch.setenv("DB_HOST", r"(localdb)\MSSQLLocalDB")
    monkeypatch.setenv("DB_NAME", "master")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "5")

    eng = create_db_engine()
    try:
        ok, msg = check_db_connection(eng)
        assert ok is True, f"LocalDB SELECT 1 failed: {msg}"
        assert "mssql" in msg.lower()
        assert eng.pool.checkedin() >= 1
    finally:
        dispose_engine(eng)
    assert eng.pool.checkedin() == 0


def test_connection_failure_handling_never_exposes_credentials(monkeypatch, caplog):
    """Verify failed DB connection returns safe message and logs zero plaintext secrets."""
    _clear_db_env(monkeypatch)
    leaked_pw = "DoNotLeakThisSecretPassword987"
    monkeypatch.setenv("DB_BACKEND", "mariadb")
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "19999")
    monkeypatch.setenv("DB_USER", "broken_user")
    monkeypatch.setenv("DB_PASSWORD", leaked_pw)
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "1")

    eng = create_db_engine()
    try:
        with caplog.at_level(logging.ERROR):
            ok, msg = check_db_connection(eng)
        assert ok is False
        assert "failed" in msg.lower()
        assert leaked_pw not in msg
        assert leaked_pw not in caplog.text
        assert "19999" not in msg
    finally:
        dispose_engine(eng)
