"""
ExpenseTrack - SQLAlchemy 2.0 Session & Transaction Management

Provides unit-of-work session lifecycle helpers, dialect-aware row locking
(MariaDB FOR UPDATE vs. SQL Server WITH (UPDLOCK, ROWLOCK)), deadlock retries,
and clean integration with Flask app contexts without ever auto-creating
databases or running Alembic migrations on application startup.
"""

from __future__ import annotations

import logging
import random
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional, TypeVar

from flask import current_app, has_app_context
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Select

from database.engine import check_db_connection, get_engine
from database.exceptions import (
    DatabaseError,
    is_retryable_db_exception,
    translate_db_exception,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def bind_app_engine(flask_app, engine: Optional[Engine]) -> None:
    """Attach or clear a specific SQLAlchemy Engine on a Flask app instance."""
    if not hasattr(flask_app, "extensions") or flask_app.extensions is None:
        flask_app.extensions = {}
    if engine is None:
        flask_app.extensions.pop("db_engine", None)
    else:
        flask_app.extensions["db_engine"] = engine


def get_active_engine(engine: Optional[Engine] = None) -> Engine:
    """
    Resolve the SQLAlchemy Engine for repository operations.

    Resolution priority:
    1. Explicit ``engine`` passed by the caller or repository instance.
    2. Engine bound to the current Flask application (isolated/multi-backend tests).
    3. Global lazy-initialized engine configured from environment variables.
    """
    if engine is not None:
        return engine
    if has_app_context():
        bound_engine = current_app.extensions.get("db_engine")
        if bound_engine is not None:
            return bound_engine
    return get_engine()


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Return a configured SQLAlchemy 2.0 sessionmaker for the active engine."""
    target_engine = get_active_engine(engine)
    return sessionmaker(
        bind=target_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def session_scope(
    engine: Optional[Engine] = None,
    *,
    translate_exceptions: bool = True,
) -> Iterator[Session]:
    """
    Provide a transactional SQLAlchemy Session scope.

    Commits cleanly on exit, rolls back unconditionally on any exception,
    optionally normalizes SQLAlchemy/driver exceptions into DatabaseError
    subclasses, and always closes the session in ``finally``.
    """
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except DatabaseError:
        session.rollback()
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        if translate_exceptions:
            raise translate_db_exception(exc) from exc
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def apply_row_lock(stmt: Select[Any], *entities: Any) -> Select[Any]:
    """
    Apply pessimistic row-level write locking across supported dialects.

    - MariaDB / MySQL: emits ``FOR UPDATE``.
    - SQL Server / Azure SQL: emits ``WITH (UPDLOCK, ROWLOCK)`` on each target
      table/entity, because SQLAlchemy's generic ``with_for_update()`` emits
      no locking hint on the ``mssql`` dialect.
    """
    locked_stmt = stmt.with_for_update()
    for entity in entities:
        locked_stmt = locked_stmt.with_hint(
            entity,
            "WITH (UPDLOCK, ROWLOCK)",
            dialect_name="mssql",
        )
    return locked_stmt


def lock_user_row(session: Session, user_id: int) -> bool:
    """
    Acquire a pessimistic lock on a user row inside an active transaction.

    Used to serialize concurrent operations per tenant (e.g., budget upserts,
    receipt deduplication) on both MariaDB and SQL Server, preventing phantom
    duplicate inserts and gap-lock deadlocks.
    """
    from sqlalchemy import select
    from database.models import User

    stmt = apply_row_lock(select(User.id).where(User.id == user_id), User)
    return session.scalar(stmt) is not None


def run_with_deadlock_retry(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.04,
) -> T:
    """
    Execute a transactional callable with bounded retries on retryable DB errors
    (MariaDB 1213/1205 and SQL Server 1205/1222).
    """
    if max_attempts < 1:
        max_attempts = 1

    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not is_retryable_db_exception(exc):
                raise
            sleep_for = base_delay_seconds * attempt + random.uniform(0.0, 0.03)
            time.sleep(sleep_for)

    assert last_exc is not None
    raise last_exc


def check_active_db_connection(engine: Optional[Engine] = None) -> tuple[bool, str]:
    """Run ``SELECT 1`` health verification against the active engine."""
    return check_db_connection(get_active_engine(engine))

