"""
ExpenseTrack - Category Repository

Provides read/lookup operations for expense categories using SQLAlchemy 2.0.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from database.models import Category
from repositories.base import BaseRepository


class CategoryRepository(BaseRepository):
    """Repository for expense category reads and existence checks."""

    def list_categories(self) -> list[dict[str, Any]]:
        """Return all categories ordered deterministically by primary key."""
        with self._session() as session:
            stmt = select(
                Category.id,
                Category.name,
                Category.icon,
                Category.color,
            ).order_by(Category.id.asc())
            rows = session.execute(stmt).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "icon": row.icon,
                    "color": row.color,
                }
                for row in rows
            ]

    def exists(self, category_id: int) -> bool:
        """Check whether a category with the given ID exists."""
        with self._session() as session:
            stmt = select(Category.id).where(Category.id == category_id)
            return session.scalar(stmt) is not None

