"""
ExpenseTrack - Budget Repository

Handles SQLAlchemy 2.0 queries, pessimistic row locking, and atomic
overall/category budget upserts across MariaDB and SQL Server.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, delete, func, select

from database.models import Budget, Category, Expense
from database.session import (
    apply_row_lock,
    lock_user_row,
    run_with_deadlock_retry,
)
from repositories.base import (
    BaseRepository,
    InvalidCategoryError,
    UserAccountNotFoundError,
)


def _month_date_bounds(month: int, year: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        next_start = date(year + 1, 1, 1)
    else:
        next_start = date(year, month + 1, 1)
    return start, next_start


class BudgetRepository(BaseRepository):
    """Repository for monthly overall and per-category budget persistence."""

    def category_exists(self, category_id: int) -> bool:
        """Check whether a category ID exists."""
        with self._session() as session:
            return (
                session.scalar(
                    select(Category.id).where(Category.id == category_id)
                )
                is not None
            )

    def get_monthly_budget_data(
        self,
        user_id: int,
        month: int,
        year: int,
    ) -> dict[str, Any]:
        """
        Fetch raw overall budget, total monthly spend, and per-category budget
        + spend rows using a single transactional database connection.
        """
        month_start, next_month_start = _month_date_bounds(month, year)

        with self._session() as session:
            overall_row = session.execute(
                select(
                    Budget.id,
                    Budget.amount,
                    Budget.created_at,
                    Budget.updated_at,
                ).where(
                    Budget.user_id == user_id,
                    Budget.category_id.is_(None),
                    Budget.month == month,
                    Budget.year == year,
                )
            ).first()

            total_spent = session.scalar(
                select(
                    func.coalesce(func.sum(Expense.amount), Decimal("0.00"))
                ).where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= month_start,
                    Expense.expense_date < next_month_start,
                )
            )
            if total_spent is None:
                total_spent = Decimal("0.00")

            spend_subq = (
                select(
                    Expense.category_id.label("category_id"),
                    func.sum(Expense.amount).label("total_spent"),
                )
                .where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= month_start,
                    Expense.expense_date < next_month_start,
                )
                .group_by(Expense.category_id)
                .subquery()
            )

            cat_stmt = (
                select(
                    Category.id.label("category_id"),
                    Category.name,
                    Category.icon,
                    Category.color,
                    Budget.id.label("budget_id"),
                    Budget.amount.label("budget_limit"),
                    func.coalesce(
                        spend_subq.c.total_spent, Decimal("0.00")
                    ).label("total_spent"),
                )
                .outerjoin(
                    Budget,
                    and_(
                        Budget.category_id == Category.id,
                        Budget.user_id == user_id,
                        Budget.month == month,
                        Budget.year == year,
                    ),
                )
                .outerjoin(
                    spend_subq,
                    spend_subq.c.category_id == Category.id,
                )
                .order_by(Category.id.asc())
            )
            cat_rows = session.execute(cat_stmt).all()

        return {
            "overall_budget": (
                {
                    "id": overall_row.id,
                    "amount": Decimal(str(overall_row.amount)),
                }
                if overall_row
                else None
            ),
            "total_spent": Decimal(str(total_spent)),
            "categories": [
                {
                    "category_id": r.category_id,
                    "name": r.name,
                    "icon": r.icon,
                    "color": r.color,
                    "budget_id": r.budget_id,
                    "budget_limit": (
                        Decimal(str(r.budget_limit))
                        if r.budget_limit is not None
                        else None
                    ),
                    "total_spent": Decimal(str(r.total_spent)),
                }
                for r in cat_rows
            ],
        }

    def upsert_budget(
        self,
        *,
        user_id: int,
        category_id: Optional[int],
        month: int,
        year: int,
        amount: Decimal,
    ) -> int:
        """
        Atomically create or update an overall or category budget using
        tenant user row locking and bounded deadlock retries.
        """
        parsed_amount = Decimal(str(amount))

        def _op() -> int:
            with self._session() as session:
                if not lock_user_row(session, user_id):
                    raise UserAccountNotFoundError(
                        "Account session is no longer valid."
                    )

                if category_id is not None:
                    cat_ok = session.scalar(
                        select(Category.id).where(Category.id == category_id)
                    )
                    if cat_ok is None:
                        raise InvalidCategoryError(
                            "Invalid category selected."
                        )
                    find_stmt = select(Budget).where(
                        Budget.user_id == user_id,
                        Budget.category_id == category_id,
                        Budget.month == month,
                        Budget.year == year,
                    )
                else:
                    find_stmt = select(Budget).where(
                        Budget.user_id == user_id,
                        Budget.category_id.is_(None),
                        Budget.month == month,
                        Budget.year == year,
                    )

                existing = session.scalar(apply_row_lock(find_stmt, Budget))
                if existing is not None:
                    existing.amount = parsed_amount
                    existing.updated_at = func.current_timestamp()
                    session.flush()
                    return int(existing.id)

                new_budget = Budget(
                    user_id=user_id,
                    category_id=category_id,
                    month=month,
                    year=year,
                    amount=parsed_amount,
                )
                session.add(new_budget)
                session.flush()
                return int(new_budget.id)

        return run_with_deadlock_retry(_op, max_attempts=3)

    def delete_budget(self, budget_id: int, user_id: int) -> bool:
        """Delete a user-owned budget record, returning True if removed."""
        with self._session() as session:
            res = session.execute(
                delete(Budget).where(
                    Budget.id == budget_id, Budget.user_id == user_id
                )
            )
            return bool(res.rowcount and res.rowcount > 0)

