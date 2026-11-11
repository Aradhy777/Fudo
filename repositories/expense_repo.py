"""
ExpenseTrack - Expense Repository

Handles SQLAlchemy 2.0 persistence, filtering, pagination, ownership scoping,
and row-level locking for student expense records.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import delete, func, or_, select

from database.exceptions import ForeignKeyViolationError
from database.models import Category, Expense, UploadedReceipt, User
from database.session import apply_row_lock
from repositories.base import (
    BaseRepository,
    EntityNotFoundError,
    InvalidCategoryError,
    ReceiptNotOwnedError,
    UserAccountNotFoundError,
)


def _coerce_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val))


def _format_date(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return str(val)


def _format_timestamp(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


class ExpenseRepository(BaseRepository):
    """Repository for Expense read and transactional write operations."""

    def list_expenses(
        self,
        user_id: int,
        *,
        page: int = 1,
        limit: int = 20,
        category_id: Optional[int] = None,
        start_date: Any = None,
        end_date: Any = None,
        merchant: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return paginated, user-scoped expenses with category & receipt info."""
        conditions = [Expense.user_id == user_id]
        if category_id is not None:
            conditions.append(Expense.category_id == category_id)
        parsed_start = _coerce_date(start_date)
        parsed_end = _coerce_date(end_date)
        if parsed_start is not None:
            conditions.append(Expense.expense_date >= parsed_start)
        if parsed_end is not None:
            conditions.append(Expense.expense_date <= parsed_end)
        if merchant:
            conditions.append(Expense.merchant.icontains(merchant, autoescape=True))
        if search:
            conditions.append(
                or_(
                    Expense.merchant.icontains(search, autoescape=True),
                    Expense.notes.icontains(search, autoescape=True),
                )
            )

        offset = (page - 1) * limit
        with self._session() as session:
            count_stmt = select(func.count(Expense.id)).where(*conditions)
            total_records = int(session.scalar(count_stmt) or 0)

            data_stmt = (
                select(
                    Expense.id,
                    Expense.amount,
                    Expense.merchant,
                    Expense.expense_date,
                    Expense.payment_method,
                    Expense.notes,
                    Expense.receipt_id,
                    Expense.created_at,
                    Category.id.label("category_id"),
                    Category.name.label("category_name"),
                    Category.icon.label("category_icon"),
                    Category.color.label("category_color"),
                    UploadedReceipt.file_name.label("receipt_file"),
                    UploadedReceipt.azure_blob_url.label("azure_blob_url"),
                )
                .join(Category, Expense.category_id == Category.id)
                .outerjoin(
                    UploadedReceipt, Expense.receipt_id == UploadedReceipt.id
                )
                .where(*conditions)
                .order_by(Expense.expense_date.desc(), Expense.id.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = session.execute(data_stmt).all()

        formatted = []
        for row in rows:
            formatted.append(
                {
                    "id": row.id,
                    "amount": float(row.amount),
                    "merchant": row.merchant,
                    "expense_date": _format_date(row.expense_date),
                    "payment_method": row.payment_method,
                    "notes": row.notes or "",
                    "receipt_id": row.receipt_id,
                    "created_at": _format_timestamp(row.created_at),
                    "category": {
                        "id": row.category_id,
                        "name": row.category_name,
                        "icon": row.category_icon,
                        "color": row.category_color,
                    },
                    "receipt": (
                        {
                            "file_name": row.receipt_file,
                            "azure_blob_url": row.azure_blob_url,
                        }
                        if row.receipt_id
                        else None
                    ),
                }
            )

        return {
            "expenses": formatted,
            "total_records": total_records,
        }

    def get_expense(self, expense_id: int, user_id: int) -> Optional[dict[str, Any]]:
        """Fetch a single expense owned by ``user_id``."""
        with self._session() as session:
            stmt = (
                select(
                    Expense.id,
                    Expense.amount,
                    Expense.merchant,
                    Expense.expense_date,
                    Expense.payment_method,
                    Expense.notes,
                    Expense.category_id,
                    Expense.receipt_id,
                    Category.name.label("category_name"),
                )
                .join(Category, Expense.category_id == Category.id)
                .where(Expense.id == expense_id, Expense.user_id == user_id)
            )
            row = session.execute(stmt).first()
            if not row:
                return None
            return {
                "id": row.id,
                "amount": float(row.amount),
                "merchant": row.merchant,
                "expense_date": _format_date(row.expense_date),
                "payment_method": row.payment_method,
                "notes": row.notes or "",
                "category_id": row.category_id,
                "category_name": row.category_name,
                "receipt_id": row.receipt_id,
            }

    def expense_exists(self, expense_id: int, user_id: int) -> bool:
        """Check whether an expense belongs to ``user_id``."""
        with self._session() as session:
            stmt = select(Expense.id).where(
                Expense.id == expense_id, Expense.user_id == user_id
            )
            return session.scalar(stmt) is not None

    def create_expense(
        self,
        *,
        user_id: int,
        category_id: int,
        amount: Decimal,
        merchant: str,
        expense_date: Any,
        payment_method: str,
        notes: Optional[str],
        receipt_id: Optional[int],
    ) -> int:
        """
        Validate category and optional receipt ownership atomically and insert
        a new Expense row, converting stale-account FK failures cleanly.
        """
        parsed_date = _coerce_date(expense_date)
        parsed_amount = Decimal(str(amount))
        normalized_notes = notes if notes else None

        try:
            with self._session() as session:
                cat_exists = session.scalar(
                    select(Category.id).where(Category.id == category_id)
                )
                if cat_exists is None:
                    raise InvalidCategoryError("Invalid category selected.")

                if receipt_id is not None:
                    rec_exists = session.scalar(
                        select(UploadedReceipt.id).where(
                            UploadedReceipt.id == receipt_id,
                            UploadedReceipt.user_id == user_id,
                        )
                    )
                    if rec_exists is None:
                        raise ReceiptNotOwnedError(
                            "Receipt not found or unauthorized."
                        )

                expense = Expense(
                    user_id=user_id,
                    category_id=category_id,
                    amount=parsed_amount,
                    merchant=merchant,
                    expense_date=parsed_date,
                    payment_method=payment_method,
                    notes=normalized_notes,
                    receipt_id=receipt_id,
                )
                session.add(expense)
                session.flush()
                return int(expense.id)
        except ForeignKeyViolationError:
            with self._session() as check_session:
                user_exists = check_session.scalar(
                    select(User.id).where(User.id == user_id)
                )
            if user_exists is None:
                raise UserAccountNotFoundError(
                    "Account session is no longer valid."
                )
            raise

    def update_expense(
        self,
        *,
        expense_id: int,
        user_id: int,
        category_id: int,
        amount: Decimal,
        merchant: str,
        expense_date: Any,
        payment_method: str,
        notes: Optional[str],
    ) -> None:
        """
        Acquire a pessimistic row lock on the target Expense and update it
        atomically after verifying category existence.
        """
        parsed_date = _coerce_date(expense_date)
        parsed_amount = Decimal(str(amount))
        normalized_notes = notes if notes else None

        with self._session() as session:
            stmt = apply_row_lock(
                select(Expense).where(
                    Expense.id == expense_id, Expense.user_id == user_id
                ),
                Expense,
            )
            expense = session.scalar(stmt)
            if expense is None:
                raise EntityNotFoundError("Expense not found or unauthorized.")

            cat_exists = session.scalar(
                select(Category.id).where(Category.id == category_id)
            )
            if cat_exists is None:
                raise InvalidCategoryError("Invalid category selected.")

            expense.category_id = category_id
            expense.amount = parsed_amount
            expense.merchant = merchant
            expense.expense_date = parsed_date
            expense.payment_method = payment_method
            expense.notes = normalized_notes
            expense.updated_at = func.current_timestamp()
            session.flush()

    def delete_expense(self, expense_id: int, user_id: int) -> bool:
        """Delete a user-owned expense record, returning True if deleted."""
        with self._session() as session:
            res = session.execute(
                delete(Expense).where(
                    Expense.id == expense_id, Expense.user_id == user_id
                )
            )
            return bool(res.rowcount and res.rowcount > 0)
