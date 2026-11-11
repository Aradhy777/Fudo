"""
ExpenseTrack - Normalized Database Exception Layer
Translates raw PyMySQL, pyodbc, and SQLAlchemy exceptions into uniform
domain errors without exposing internal hostnames, SQL, or credentials.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    TimeoutError as SATimeoutError,
)


class DatabaseError(Exception):
    """Base domain exception for normalized database failures."""

    def __init__(
        self,
        user_message: str,
        *,
        backend: Optional[str] = None,
        code: Optional[int | str] = None,
        sqlstate: Optional[str] = None,
    ):
        super().__init__(user_message)
        self.user_message = user_message
        self.backend = backend
        self.code = code
        self.sqlstate = sqlstate


class DuplicateRecordError(DatabaseError):
    """Raised on UNIQUE / PRIMARY KEY violations (e.g. PyMySQL 1062, MSSQL 2627/2601)."""


class ForeignKeyViolationError(DatabaseError):
    """Raised on FOREIGN KEY constraint violations (e.g. PyMySQL 1451/1452, MSSQL 547)."""


class CheckConstraintViolationError(DatabaseError):
    """Raised on CHECK constraint violations (e.g. MariaDB 4025/3819, MSSQL 547 CHECK)."""


class DatabaseIntegrityError(DatabaseError):
    """Raised for non-unique/non-FK integrity failures such as NOT NULL violations."""


class TransientDeadlockError(DatabaseError):
    """Raised on transactional deadlock victim errors (PyMySQL 1213, MSSQL 1205)."""


class LockTimeoutError(DatabaseError):
    """Raised on lock wait or query timeout errors (PyMySQL 1205, MSSQL 1222 / HYT00)."""


class DatabaseConnectionError(DatabaseError):
    """Raised on broken, refused, or exhausted database connections/pools."""


def _extract_driver_metadata(exc: Exception) -> tuple[Optional[str], Optional[int], Optional[str], str]:
    """Safely extract (backend, errno, sqlstate, raw_msg_lower) from nested driver errors."""
    orig = getattr(exc, "orig", exc)
    mod_name = type(orig).__module__.lower()

    backend: Optional[str] = None
    if "pymysql" in mod_name:
        backend = "mariadb"
    elif "pyodbc" in mod_name:
        backend = "mssql"

    code: Optional[int] = None
    sqlstate: Optional[str] = None
    msg_parts: list[str] = []

    args = getattr(orig, "args", ()) or ()
    for item in args:
        if isinstance(item, int) and code is None:
            code = item
        elif isinstance(item, str):
            stripped = item.strip()
            if len(stripped) == 5 and stripped.isalnum() and sqlstate is None:
                sqlstate = stripped.upper()
            msg_parts.append(stripped)

    if not msg_parts:
        msg_parts.append(str(orig))

    combined = " ".join(msg_parts)

    # Extract SQL Server native error code when embedded in pyodbc message strings e.g. "(2627)"
    if backend == "mssql" and code is None:
        import re

        m = re.search(r"\((\d{3,5})\)\s*\(SQL\w+\)|\[SQL Server\].*?\((\d{3,5})\)", combined)
        if m:
            num_str = m.group(1) or m.group(2)
            if num_str:
                code = int(num_str)

    return backend, code, sqlstate, combined.lower()


def translate_db_exception(exc: Exception) -> DatabaseError:
    """
    Convert a raw SQLAlchemy / PyMySQL / pyodbc exception into a normalized
    DatabaseError subclass with a safe, user-facing message.
    """
    if isinstance(exc, DatabaseError):
        return exc

    if isinstance(exc, SATimeoutError):
        return LockTimeoutError(
            "Database pool or lock wait timed out. Please retry.",
            code="POOL_TIMEOUT",
        )

    backend, code, sqlstate, lower_msg = _extract_driver_metadata(exc)

    # 1. Deadlocks & Lock Timeouts (checked before generic OperationalError)
    if (
        (backend == "mariadb" and code == 1213)
        or (backend == "mssql" and (code == 1205 or sqlstate == "40001"))
        or "deadlock" in lower_msg
    ):
        return TransientDeadlockError(
            "A temporary database conflict occurred. Please retry the operation.",
            backend=backend,
            code=code,
            sqlstate=sqlstate,
        )

    if (
        (backend == "mariadb" and code == 1205)
        or (backend == "mssql" and code == 1222)
        or sqlstate == "HYT00"
        or "lock wait timeout" in lower_msg
        or "lock request time out" in lower_msg
    ):
        return LockTimeoutError(
            "Database lock timed out while waiting for another transaction.",
            backend=backend,
            code=code,
            sqlstate=sqlstate,
        )

    # 2. Integrity Violations (Unique, CHECK, Foreign Key, NOT NULL)
    if isinstance(exc, IntegrityError) or code in (
        1062, 1451, 1452, 1216, 1217, 4025, 3819, 1048,
        2627, 2601, 547, 515,
    ) or sqlstate == "23000":
        if (
            code in (1062, 2627, 2601)
            or "duplicate" in lower_msg
            or "unique" in lower_msg
        ):
            return DuplicateRecordError(
                "A conflicting record with identical unique values already exists.",
                backend=backend,
                code=code,
                sqlstate=sqlstate,
            )

        if code in (4025, 3819) or "check constraint" in lower_msg or "chk_" in lower_msg:
            return CheckConstraintViolationError(
                "Input value violates a database check constraint.",
                backend=backend,
                code=code,
                sqlstate=sqlstate,
            )

        if (
            code in (1451, 1452, 1216, 1217)
            or (code == 547 and ("foreign key" in lower_msg or "reference constraint" in lower_msg or "fk_" in lower_msg))
            or "foreign key" in lower_msg
        ):
            return ForeignKeyViolationError(
                "Operation references a missing or protected related record.",
                backend=backend,
                code=code,
                sqlstate=sqlstate,
            )

        return DatabaseIntegrityError(
            "Operation violates a database integrity rule.",
            backend=backend,
            code=code,
            sqlstate=sqlstate,
        )

    # 3. Connection / Network / Pool Outage Errors
    if isinstance(exc, (OperationalError, InterfaceError, DBAPIError)) or (
        sqlstate in ("08S01", "08001", "08004")
        or code in (2002, 2003, 2006, 2013, 1045)
    ):
        # Catch MariaDB OperationalError 4025 (CHECK violation surfaced as OperationalError)
        if code == 4025 or "check constraint" in lower_msg:
            return CheckConstraintViolationError(
                "Input value violates a database check constraint.",
                backend=backend,
                code=code,
                sqlstate=sqlstate,
            )
        return DatabaseConnectionError(
            "Database service is currently unreachable or encountered an operational error.",
            backend=backend,
            code=code,
            sqlstate=sqlstate,
        )

    return DatabaseError(
        "An unexpected database error occurred.",
        backend=backend,
        code=code,
        sqlstate=sqlstate,
    )


def is_retryable_db_exception(exc: Exception) -> bool:
    """Return True if a database failure is a safe-to-retry transient deadlock/lock timeout."""
    normalized = translate_db_exception(exc)
    return isinstance(normalized, (TransientDeadlockError, LockTimeoutError))

