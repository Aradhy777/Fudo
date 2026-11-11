"""
ExpenseTrack - SQLAlchemy 2.0 Database Engine & Pool Abstraction Foundation
Provides environment-driven engine construction, connection pooling,
Azure SQL / SQL Server LocalDB (pyodbc) and MariaDB (PyMySQL) compatibility,
credential redaction, and safe lifecycle / health verification helpers.

Note: Existing runtime code in database/db.py remains operational alongside this
foundation until subsequent repository migration phases are approved.
"""

from __future__ import annotations

import logging
import os
import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, unquote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.pool import QueuePool

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

logger = logging.getLogger(__name__)

_SUPPORTED_BACKENDS = {
    "mariadb": "mariadb",
    "mysql": "mariadb",
    "mssql": "mssql",
    "sqlserver": "mssql",
    "azure_sql": "mssql",
    "azuresql": "mssql",
    "localdb": "mssql",
}
_SUPPORTED_AUTH_MODES = {"password", "trusted", "managed_identity"}
_DEFAULT_POOL_SIZE = 5
_DEFAULT_MAX_OVERFLOW = 10
_DEFAULT_POOL_TIMEOUT = 30
_DEFAULT_POOL_RECYCLE = 1800
_DEFAULT_CONNECT_TIMEOUT = 5
_SQL_COPT_SS_ACCESS_TOKEN = 1256
_AZURE_SQL_SCOPE = "https://database.windows.net/.default"

_engine_lock = threading.Lock()
_engine: Optional[Engine] = None


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _parse_int_env(name: str, default: int, min_val: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        val = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer.") from exc
    if val < min_val:
        raise ValueError(f"Environment variable {name} must be at least {min_val}.")
    return val


def normalize_backend(raw_backend: Optional[str], database_url: Optional[str] = None) -> str:
    """Resolve and validate the target database backend ('mariadb' or 'mssql')."""
    candidate = (raw_backend or "").strip().lower()
    if candidate:
        if candidate not in _SUPPORTED_BACKENDS:
            raise ValueError(
                f"Unsupported DB_BACKEND '{raw_backend}'. Supported values: mariadb, mssql."
            )
        return _SUPPORTED_BACKENDS[candidate]

    if database_url:
        lowered = database_url.strip().lower()
        if lowered.startswith(("mssql", "mssql+pyodbc")):
            return "mssql"
        if lowered.startswith(("mysql", "mariadb")):
            return "mariadb"

    return "mariadb"


def normalize_auth_mode(raw_auth_mode: Optional[str]) -> str:
    """Resolve and validate DB_AUTH_MODE ('password', 'trusted', 'managed_identity')."""
    mode = (raw_auth_mode or "password").strip().lower() or "password"
    if mode not in _SUPPORTED_AUTH_MODES:
        raise ValueError(
            f"Unsupported DB_AUTH_MODE '{raw_auth_mode}'. "
            "Supported values: password, trusted, managed_identity."
        )
    return mode


def resolve_mssql_driver(explicit_driver: Optional[str] = None) -> str:
    """
    Pick an installed Microsoft SQL Server ODBC driver cleanly across Windows dev
    (Driver 17/18) and Linux production containers (Driver 18).
    """
    driver = (explicit_driver or os.getenv("DB_DRIVER", "")).strip()
    if driver:
        return driver

    try:
        import pyodbc

        available = set(pyodbc.drivers())
        for preferred in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"):
            if preferred in available:
                return preferred
    except Exception:
        pass

    return "ODBC Driver 18 for SQL Server"


def _is_local_mssql_host(host: str) -> bool:
    lowered = host.strip().lower()
    return (
        lowered.startswith("(localdb)\\")
        or lowered in ("localhost", "127.0.0.1", ".")
        or lowered.startswith("localhost\\")
        or lowered.startswith(".\\")
    )


def redact_database_url(url: URL | str) -> str:
    """
    Return a safe printable string of a SQLAlchemy URL with passwords,
    embedded ODBC PWD attributes, and access tokens masked.
    """
    try:
        parsed = url if isinstance(url, URL) else make_url(str(url))
        rendered = parsed.render_as_string(hide_password=True)
    except Exception:
        rendered = str(url)

    # Mask URL-encoded or plain secrets in pyodbc odbc_connect query segments
    def _scrub_odbc_param(match: re.Match) -> str:
        prefix, raw_val = match.group(1), match.group(2)
        decoded = unquote_plus(raw_val)
        cleaned = re.sub(
            r"(?i)(PWD|Password|AccessToken)\s*=\s*(?:\{(?:[^}]|\}\})*\}|[^;]*)",
            r"\1=***",
            decoded,
        )
        return prefix + quote_plus(cleaned)

    rendered = re.sub(r"(odbc_connect=)([^&]+)", _scrub_odbc_param, rendered)
    rendered = re.sub(
        r"(?i)(PWD|Password|AccessToken)\s*=\s*[^;&]+",
        r"\1=***",
        rendered,
    )
    rendered = re.sub(r"://([^:@/]+):[^@/]+@", r"://\1:***@", rendered)
    return rendered


@dataclass(frozen=True)
class DatabaseSettings:
    backend: str
    auth_mode: str
    url: URL
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    pool_pre_ping: bool
    connect_timeout: int
    echo: bool

    @property
    def redacted_url(self) -> str:
        return redact_database_url(self.url)


def _normalize_explicit_url(raw_url: str, backend: str) -> URL:
    parsed = make_url(raw_url.strip())
    driver = parsed.drivername.lower()

    if driver in ("mysql", "mariadb", "mariadb+pymysql", "mysql+mysqldb"):
        parsed = parsed.set(drivername="mysql+pymysql")
    elif driver in ("mssql", "sqlserver", "mssql+pymssql"):
        parsed = parsed.set(drivername="mssql+pyodbc")

    resolved_driver = parsed.drivername.lower()
    if backend == "mariadb" and not resolved_driver.startswith("mysql"):
        raise ValueError("DATABASE_URL dialect conflicts with DB_BACKEND='mariadb'.")
    if backend == "mssql" and not resolved_driver.startswith("mssql"):
        raise ValueError("DATABASE_URL dialect conflicts with DB_BACKEND='mssql'.")

    return parsed


def _build_mariadb_url(auth_mode: str) -> URL:
    if auth_mode != "password":
        raise ValueError(f"DB_BACKEND='mariadb' does not support DB_AUTH_MODE='{auth_mode}'.")

    host = os.getenv("DB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = _parse_int_env("DB_PORT", 3306, min_val=1)
    user = os.getenv("DB_USER", "").strip()
    if not user:
        raise ValueError("DB_USER must be set when constructing a MariaDB connection URL.")
    password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "expensetrack").strip() or "expensetrack"

    return URL.create(
        drivername="mysql+pymysql",
        username=user,
        password=password if password != "" else None,
        host=host,
        port=port,
        database=db_name,
        query={"charset": "utf8mb4"},
    )


def _build_mssql_url(auth_mode: str, connect_timeout: int) -> URL:
    host = os.getenv("DB_HOST", "").strip()
    if not host:
        raise ValueError("DB_HOST must be set when DB_BACKEND='mssql' without DATABASE_URL.")

    raw_port = os.getenv("DB_PORT", "").strip()
    server_spec = host
    if raw_port and not host.lower().startswith("(localdb)\\") and "\\" not in host and "," not in host:
        try:
            port_num = int(raw_port)
        except ValueError as exc:
            raise ValueError("DB_PORT must be a valid integer.") from exc
        if port_num < 1 or port_num > 65535:
            raise ValueError("DB_PORT must be between 1 and 65535.")
        server_spec = f"{host},{port_num}"

    db_name = os.getenv("DB_NAME", "expensetrack").strip() or "expensetrack"
    odbc_driver = resolve_mssql_driver()
    is_local = _is_local_mssql_host(host)

    encrypt_default = "no" if is_local else "yes"
    trust_cert_default = "yes" if is_local else "no"
    encrypt = (os.getenv("DB_ENCRYPT", encrypt_default).strip().lower() or encrypt_default)
    trust_cert = (
        os.getenv("DB_TRUST_SERVER_CERTIFICATE", trust_cert_default).strip().lower()
        or trust_cert_default
    )

    odbc_parts = [
        f"DRIVER={{{odbc_driver}}}",
        f"SERVER={server_spec}",
        f"DATABASE={db_name}",
        f"Encrypt={encrypt}",
        f"TrustServerCertificate={trust_cert}",
        f"Connection Timeout={connect_timeout}",
    ]

    if auth_mode == "trusted":
        odbc_parts.append("Trusted_Connection=yes")
    elif auth_mode == "password":
        user = os.getenv("DB_USER", "").strip()
        password = os.getenv("DB_PASSWORD", "")
        if not user:
            raise ValueError("DB_USER must be set for DB_BACKEND='mssql' with password auth.")
        odbc_parts.append(f"UID={user}")
        if password:
            safe_pw = (
                "{" + password.replace("}", "}}") + "}"
                if any(ch in password for ch in ";{}")
                else password
            )
            odbc_parts.append(f"PWD={safe_pw}")
    elif auth_mode == "managed_identity":
        # Token is injected dynamically on pyodbc do_connect via DefaultAzureCredential
        pass

    odbc_connect = ";".join(odbc_parts) + ";"
    return URL.create(
        drivername="mssql+pyodbc",
        query={"odbc_connect": odbc_connect},
    )


def build_database_url(
    *,
    database_url: Optional[str] = None,
    backend: Optional[str] = None,
    auth_mode: Optional[str] = None,
    connect_timeout: int = _DEFAULT_CONNECT_TIMEOUT,
) -> tuple[str, str, URL]:
    """
    Construct a sanitized, dialect-appropriate SQLAlchemy URL from explicit arguments
    or environment variables without storing or printing plaintext credentials.
    Returns (resolved_backend, resolved_auth_mode, sqlalchemy_url).
    """
    raw_url = database_url if database_url is not None else os.getenv("DATABASE_URL", "")
    raw_url = (raw_url or "").strip()

    resolved_backend = normalize_backend(
        backend if backend is not None else os.getenv("DB_BACKEND"),
        database_url=raw_url or None,
    )
    resolved_auth = normalize_auth_mode(
        auth_mode if auth_mode is not None else os.getenv("DB_AUTH_MODE")
    )

    if raw_url:
        url_obj = _normalize_explicit_url(raw_url, resolved_backend)
        return resolved_backend, resolved_auth, url_obj

    if resolved_backend == "mariadb":
        return resolved_backend, resolved_auth, _build_mariadb_url(resolved_auth)

    return resolved_backend, resolved_auth, _build_mssql_url(resolved_auth, connect_timeout)


def load_database_settings(
    *,
    database_url: Optional[str] = None,
    backend: Optional[str] = None,
    auth_mode: Optional[str] = None,
    pool_size: Optional[int] = None,
    max_overflow: Optional[int] = None,
    pool_timeout: Optional[int] = None,
    pool_recycle: Optional[int] = None,
    pool_pre_ping: Optional[bool] = None,
    connect_timeout: Optional[int] = None,
    echo: Optional[bool] = None,
) -> DatabaseSettings:
    """Load validated SQLAlchemy engine and pool settings from overrides or env vars."""
    c_timeout = (
        connect_timeout
        if connect_timeout is not None
        else _parse_int_env("DB_CONNECT_TIMEOUT", _DEFAULT_CONNECT_TIMEOUT, min_val=1)
    )
    resolved_backend, resolved_auth, url_obj = build_database_url(
        database_url=database_url,
        backend=backend,
        auth_mode=auth_mode,
        connect_timeout=c_timeout,
    )

    p_size = (
        pool_size
        if pool_size is not None
        else _parse_int_env("DB_POOL_SIZE", _DEFAULT_POOL_SIZE, min_val=1)
    )
    p_overflow = (
        max_overflow
        if max_overflow is not None
        else _parse_int_env("DB_MAX_OVERFLOW", _DEFAULT_MAX_OVERFLOW, min_val=0)
    )
    p_timeout = (
        pool_timeout
        if pool_timeout is not None
        else _parse_int_env("DB_POOL_TIMEOUT", _DEFAULT_POOL_TIMEOUT, min_val=1)
    )
    p_recycle = (
        pool_recycle
        if pool_recycle is not None
        else _parse_int_env("DB_POOL_RECYCLE", _DEFAULT_POOL_RECYCLE, min_val=0)
    )
    p_pre_ping = (
        pool_pre_ping
        if pool_pre_ping is not None
        else _parse_bool_env("DB_POOL_PRE_PING", True)
    )
    echo_sql = echo if echo is not None else _parse_bool_env("DB_ECHO", False)

    return DatabaseSettings(
        backend=resolved_backend,
        auth_mode=resolved_auth,
        url=url_obj,
        pool_size=p_size,
        max_overflow=p_overflow,
        pool_timeout=p_timeout,
        pool_recycle=p_recycle,
        pool_pre_ping=p_pre_ping,
        connect_timeout=c_timeout,
        echo=echo_sql,
    )


def _acquire_azure_sql_access_token() -> bytes:
    """Obtain an Entra ID access token formatted for ODBC SQL_COPT_SS_ACCESS_TOKEN."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(
            "azure-identity package is required for DB_AUTH_MODE='managed_identity'."
        ) from exc

    credential = DefaultAzureCredential()
    access_token = credential.get_token(_AZURE_SQL_SCOPE).token
    encoded = access_token.encode("utf-16-le")
    return struct.pack(f"<I{len(encoded)}s", len(encoded), encoded)


def _attach_managed_identity_hook(engine: Engine) -> None:
    """Attach a pre-connect listener that injects fresh Entra tokens for Azure SQL."""

    @event.listens_for(engine, "do_connect")
    def _provide_token(dialect, conn_rec, cargs, cparams):
        attrs_before = dict(cparams.get("attrs_before") or {})
        attrs_before[_SQL_COPT_SS_ACCESS_TOKEN] = _acquire_azure_sql_access_token()
        cparams["attrs_before"] = attrs_before


def create_db_engine(
    settings: Optional[DatabaseSettings] = None,
    **overrides,
) -> Engine:
    """
    Create a configured SQLAlchemy 2.0 Engine with QueuePool pooling,
    pool_pre_ping=True, and pool_recycle=1800 defaults.
    """
    cfg = settings or load_database_settings(**overrides)

    connect_args: dict = {}
    if cfg.backend == "mariadb":
        connect_args["connect_timeout"] = cfg.connect_timeout
    elif cfg.backend == "mssql":
        connect_args["timeout"] = cfg.connect_timeout

    engine = create_engine(
        cfg.url,
        poolclass=QueuePool,
        pool_size=cfg.pool_size,
        max_overflow=cfg.max_overflow,
        pool_timeout=cfg.pool_timeout,
        pool_recycle=cfg.pool_recycle,
        pool_pre_ping=cfg.pool_pre_ping,
        echo=cfg.echo,
        connect_args=connect_args,
        future=True,
    )

    if cfg.backend == "mssql" and cfg.auth_mode == "managed_identity":
        _attach_managed_identity_hook(engine)

    return engine


def get_engine() -> Engine:
    """Return the process-wide lazy SQLAlchemy Engine singleton cleanly."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = create_db_engine()
    return _engine


def dispose_engine(target_engine: Optional[Engine] = None) -> None:
    """Dispose connection pool sockets for a specific engine or global singleton."""
    global _engine
    if target_engine is not None:
        try:
            target_engine.dispose()
        finally:
            with _engine_lock:
                if _engine is target_engine:
                    _engine = None
        return

    with _engine_lock:
        if _engine is not None:
            try:
                _engine.dispose()
            finally:
                _engine = None


def check_db_connection(engine: Optional[Engine] = None) -> tuple[bool, str]:
    """
    Verify SQLAlchemy database connectivity via read-only 'SELECT 1'.
    Never leaks credentials, tokens, or connection URLs in messages or exceptions.
    """
    eng = engine or get_engine()
    try:
        with eng.connect() as conn:
            val = conn.execute(text("SELECT 1")).scalar()
            if val == 1:
                return True, f"Connected via SQLAlchemy ({eng.dialect.name})."
        return False, "Unexpected SELECT 1 response from database."
    except Exception as exc:
        logger.error(
            "SQLAlchemy connectivity check failed (%s / %s): %s",
            eng.dialect.name,
            redact_database_url(eng.url),
            type(exc).__name__,
        )
        return False, "Database connectivity check failed. See server logs for details."


def get_pool_status(engine: Optional[Engine] = None) -> dict:
    """Return sanitized engine & connection pool metadata (zero credentials)."""
    eng = engine or get_engine()
    pool = eng.pool
    return {
        "dialect": eng.dialect.name,
        "driver": eng.dialect.driver,
        "redacted_url": redact_database_url(eng.url),
        "pool_class": type(pool).__name__,
        "pool_size": pool.size() if hasattr(pool, "size") else None,
        "checked_in": pool.checkedin() if hasattr(pool, "checkedin") else None,
        "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else None,
        "overflow": pool.overflow() if hasattr(pool, "overflow") else None,
        "pool_timeout": getattr(pool, "_timeout", None),
        "pool_recycle": getattr(pool, "_recycle", None),
        "pool_pre_ping": getattr(pool, "_pre_ping", None),
    }
