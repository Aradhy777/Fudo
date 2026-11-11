"""
ExpenseTrack - User Repository

Manages user account registration, credential lookup, profile & password
updates, active database diagnostics, and safe cross-dialect user deletion
using SQLAlchemy 2.0.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, or_, select

from database.exceptions import DuplicateRecordError
from database.models import User, delete_user_transactional
from database.session import check_active_db_connection, get_active_engine
from repositories.base import (
    BaseRepository,
    DuplicateEmailError,
    DuplicateUsernameError,
    RepositoryError,
    UserAccountNotFoundError,
)


class DuplicateAccountConflictError(RepositoryError):
    """Raised on concurrent unique-constraint race during registration."""


class UserRepository(BaseRepository):
    """Repository for User account persistence and authentication lookups."""

    def register_user(
        self,
        *,
        username: str,
        email: str,
        password_hash: str,
        full_name: str,
    ) -> int:
        """
        Insert a new student user account atomically, surfacing deterministic
        conflict errors for duplicate usernames or emails under concurrency.
        """
        try:
            with self._session() as session:
                existing = session.execute(
                    select(User.id, User.username, User.email).where(
                        or_(User.username == username, User.email == email)
                    )
                ).first()
                if existing is not None:
                    if existing.username.lower() == username.lower():
                        raise DuplicateUsernameError("Username is already registered.")
                    raise DuplicateEmailError("Email is already registered.")

                user = User(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    full_name=full_name,
                )
                session.add(user)
                session.flush()
                return int(user.id)
        except DuplicateRecordError as exc:
            raise DuplicateAccountConflictError(
                "Username or Email is already registered."
            ) from exc

    def find_by_identifier(self, identifier: str) -> Optional[dict[str, Any]]:
        """Look up user login credentials by username or case-normalized email."""
        with self._session() as session:
            row = session.execute(
                select(
                    User.id,
                    User.username,
                    User.email,
                    User.password_hash,
                    User.full_name,
                ).where(
                    or_(
                        User.username == identifier,
                        User.email == identifier.lower(),
                    )
                )
            ).first()
            if row is None:
                return None
            return {
                "id": row.id,
                "username": row.username,
                "email": row.email,
                "password_hash": row.password_hash,
                "full_name": row.full_name,
            }

    def get_public_profile(self, user_id: int) -> Optional[dict[str, Any]]:
        """Fetch sanitized user profile metadata for ``/api/auth/me``."""
        with self._session() as session:
            row = session.execute(
                select(
                    User.id,
                    User.username,
                    User.email,
                    User.full_name,
                    User.created_at,
                ).where(User.id == user_id)
            ).first()
            if row is None:
                return None
            return {
                "id": row.id,
                "username": row.username,
                "email": row.email,
                "full_name": row.full_name,
                "created_at": row.created_at,
            }

    def update_profile(
        self,
        user_id: int,
        *,
        full_name: str,
        email: str,
    ) -> None:
        """Update user full name and unique email address atomically."""
        try:
            with self._session() as session:
                user = session.scalar(select(User).where(User.id == user_id))
                if user is None:
                    raise UserAccountNotFoundError(
                        "Account session is no longer valid."
                    )

                dup_email = session.scalar(
                    select(User.id).where(User.email == email, User.id != user_id)
                )
                if dup_email is not None:
                    raise DuplicateEmailError(
                        "Email is already taken by another user."
                    )

                user.full_name = full_name
                user.email = email
                user.updated_at = func.current_timestamp()
                session.flush()
        except DuplicateRecordError as exc:
            raise DuplicateEmailError(
                "Email is already taken by another user."
            ) from exc

    def get_password_hash(self, user_id: int) -> Optional[str]:
        """Retrieve a user's stored password hash."""
        with self._session() as session:
            return session.scalar(
                select(User.password_hash).where(User.id == user_id)
            )

    def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        """Persist a rotated password hash for an existing user."""
        with self._session() as session:
            user = session.scalar(select(User).where(User.id == user_id))
            if user is None:
                return False
            user.password_hash = password_hash
            user.updated_at = func.current_timestamp()
            session.flush()
            return True

    def delete_user(self, user_id: int) -> bool:
        """
        Delete a user and all dependent expenses, budgets, and receipts safely
        across MariaDB and SQL Server (using ``delete_user_transactional``).
        """
        with self._session() as session:
            return delete_user_transactional(session, user_id)

    def get_database_diagnostics(self) -> dict[str, Any]:
        """Return redacted database connection health and backend metadata."""
        try:
            engine = get_active_engine(self._engine)
            db_ok, _ = check_active_db_connection(engine)
            dialect_name = engine.dialect.name
            engine_label = (
                "SQL Server / Azure SQL"
                if dialect_name.startswith("mssql")
                else "MySQL / MariaDB"
            )
            url_host = engine.url.host or "localdb"
            url_port = engine.url.port or (1433 if dialect_name.startswith("mssql") else 3306)
            url_db = engine.url.database or ""
            return {
                "engine": engine_label,
                "status": "connected" if db_ok else "disconnected",
                "host": url_host,
                "port": url_port,
                "database_name": url_db,
                "message": "Connected successfully" if db_ok else "Connection failed",
            }
        except Exception:
            return {
                "engine": "SQLAlchemy",
                "status": "disconnected",
                "host": "unavailable",
                "port": None,
                "database_name": "",
                "message": "Connection failed",
            }
