"""
ExpenseTrack - Repository Base Types and Exceptions

Repositories isolate SQLAlchemy 2.0 persistence, locking, and transaction
management behind domain-focused interfaces without embedding HTTP or Flask logic.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from database.session import session_scope


class RepositoryError(Exception):
    """Base domain exception raised by repositories on integrity/lookup checks."""


class UserAccountNotFoundError(RepositoryError):
    """Raised when an authenticated user_id no longer exists in the database."""


class EntityNotFoundError(RepositoryError):
    """Raised when a target record is absent or not owned by the current user."""


class InvalidCategoryError(RepositoryError):
    """Raised when a supplied category_id does not exist."""


class ReceiptNotOwnedError(RepositoryError):
    """Raised when a receipt_id does not exist or belongs to another user."""


class DuplicateUsernameError(RepositoryError):
    """Raised when attempting to register an already taken username."""


class DuplicateEmailError(RepositoryError):
    """Raised when an email address is already registered to another user."""


class BaseRepository:
    """Base repository providing bound engine and transactional session scopes."""

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine = engine

    @contextmanager
    def _session(self, *, translate_exceptions: bool = True) -> Iterator[Session]:
        with session_scope(
            self._engine,
            translate_exceptions=translate_exceptions,
        ) as session:
            yield session

