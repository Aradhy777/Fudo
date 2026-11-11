"""
ExpenseTrack - Analytics Repository

Executes single-connection SQLAlchemy 2.0 aggregate queries powering the
Dashboard Summary and Insights engines cleanly across MariaDB and SQL Server.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, extract, func, select

from database.models import Budget, Category, Expense
from repositories.base import BaseRepository


def _to_date_obj(val: Any) -> date:
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val))


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        next_start = date(year + 1, 1, 1)
    else:
        next_start = date(year, month + 1, 1)
    return start, next_start


class AnalyticsRepository(BaseRepository):
    """Repository for read-only multi-query analytics snapshots."""

    def get_dashboard_summary_data(
        self,
        user_id: int,
        *,
        month: int,
        year: int,
        start_date: Any,
        end_date: Any,
        prev_start: Any,
        prev_end: Any,
        trend_start: Any,
    ) -> dict[str, Any]:
        """
        Execute all 7 dashboard aggregate/list queries on a single pooled DB
        connection cleanly across MariaDB and SQL Server.
        """
        s_date = _to_date_obj(start_date)
        e_date = _to_date_obj(end_date)
        ps_date = _to_date_obj(prev_start)
        pe_date = _to_date_obj(prev_end)
        ts_date = _to_date_obj(trend_start)

        with self._session() as session:
            # 1. Current month spending stats
            month_stats_row = session.execute(
                select(
                    func.coalesce(func.sum(Expense.amount), Decimal("0.00")).label(
                        "total_spent"
                    ),
                    func.count(Expense.id).label("tx_count"),
                ).where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= s_date,
                    Expense.expense_date <= e_date,
                )
            ).first()

            # 2. Overall budget for selected month
            budget_amt = session.scalar(
                select(Budget.amount).where(
                    Budget.user_id == user_id,
                    Budget.category_id.is_(None),
                    Budget.month == month,
                    Budget.year == year,
                )
            )

            # 3. Category breakdown (explicit aggregate in HAVING for T-SQL compatibility)
            cat_sum_expr = func.coalesce(func.sum(Expense.amount), Decimal("0.00"))
            category_rows = session.execute(
                select(
                    Category.id,
                    Category.name,
                    Category.color,
                    Category.icon,
                    cat_sum_expr.label("category_total"),
                    func.count(Expense.id).label("tx_count"),
                )
                .join(Expense, Expense.category_id == Category.id)
                .where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= s_date,
                    Expense.expense_date <= e_date,
                )
                .group_by(Category.id, Category.name, Category.color, Category.icon)
                .having(cat_sum_expr > Decimal("0.00"))
                .order_by(cat_sum_expr.desc())
            ).all()

            # 4. Prior month spent
            prev_spent = session.scalar(
                select(
                    func.coalesce(func.sum(Expense.amount), Decimal("0.00"))
                ).where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= ps_date,
                    Expense.expense_date <= pe_date,
                )
            )

            # 5. 6-month trend
            yr_expr = extract("year", Expense.expense_date)
            mo_expr = extract("month", Expense.expense_date)
            trend_rows = session.execute(
                select(
                    yr_expr.label("yr"),
                    mo_expr.label("mo"),
                    func.coalesce(func.sum(Expense.amount), Decimal("0.00")).label(
                        "total"
                    ),
                )
                .where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= ts_date,
                    Expense.expense_date <= e_date,
                )
                .group_by(yr_expr, mo_expr)
            ).all()

            # 6. Recent transactions (limit 6)
            recent_rows = session.execute(
                select(
                    Expense.id,
                    Expense.amount,
                    Expense.merchant,
                    Expense.expense_date,
                    Expense.payment_method,
                    Expense.notes,
                    Category.name.label("category_name"),
                    Category.color.label("category_color"),
                    Category.icon.label("category_icon"),
                )
                .join(Category, Expense.category_id == Category.id)
                .where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= s_date,
                    Expense.expense_date <= e_date,
                )
                .order_by(Expense.expense_date.desc(), Expense.id.desc())
                .limit(6)
            ).all()

            # 7. Lifetime expense count
            lifetime_count = int(
                session.scalar(
                    select(func.count(Expense.id)).where(Expense.user_id == user_id)
                )
                or 0
            )

        return {
            "month_stats": {
                "total_spent": (
                    Decimal(str(month_stats_row.total_spent))
                    if month_stats_row
                    else Decimal("0.00")
                ),
                "tx_count": int(month_stats_row.tx_count) if month_stats_row else 0,
            },
            "budget_row": (
                {"amount": Decimal(str(budget_amt))} if budget_amt is not None else None
            ),
            "category_rows": [
                {
                    "id": r.id,
                    "name": r.name,
                    "color": r.color,
                    "icon": r.icon,
                    "category_total": Decimal(str(r.category_total)),
                    "count_tx": int(r.tx_count),
                }
                for r in category_rows
            ],
            "prev_month_row": {
                "spent": (
                    Decimal(str(prev_spent)) if prev_spent is not None else Decimal("0.00")
                )
            },
            "trend_rows": [
                {
                    "yr": int(r.yr),
                    "mo": int(r.mo),
                    "spent": Decimal(str(r.total)),
                }
                for r in trend_rows
            ],
            "recent_tx": [
                {
                    "id": r.id,
                    "amount": Decimal(str(r.amount)),
                    "merchant": r.merchant,
                    "expense_date": _to_date_obj(r.expense_date),
                    "payment_method": r.payment_method,
                    "notes": r.notes,
                    "category_name": r.category_name,
                    "category_color": r.category_color,
                    "category_icon": r.category_icon,
                }
                for r in recent_rows
            ],
            "lifetime_row": {"cnt": lifetime_count},
        }

    def get_monthly_insights_data(
        self,
        user_id: int,
        *,
        month: int,
        year: int,
        start_date: Any,
        end_date: Any,
        prev_start: Any,
        prev_end: Any,
    ) -> dict[str, Any]:
        """
        Execute all 5 monthly insights queries inside a single SQLAlchemy
        transaction/connection cleanly across MariaDB and SQL Server.
        """
        s_date = _to_date_obj(start_date)
        e_date = _to_date_obj(end_date)
        ps_date = _to_date_obj(prev_start)
        pe_date = _to_date_obj(prev_end)

        with self._session() as session:
            # 1. Total spending for selected month
            total_row = session.execute(
                select(
                    func.coalesce(func.sum(Expense.amount), Decimal("0.00")).label(
                        "total_spent"
                    ),
                    func.count(Expense.id).label("tx_count"),
                ).where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= s_date,
                    Expense.expense_date <= e_date,
                )
            ).first()

            # 2. Overall budget for selected month
            overall_amt = session.scalar(
                select(Budget.amount).where(
                    Budget.user_id == user_id,
                    Budget.category_id.is_(None),
                    Budget.month == month,
                    Budget.year == year,
                )
            )

            # 3. Spending by category (explicit aggregate in HAVING for T-SQL)
            cat_spent_expr = func.coalesce(func.sum(Expense.amount), Decimal("0.00"))
            category_spending = session.execute(
                select(
                    Category.id,
                    Category.name,
                    Category.color,
                    Category.icon,
                    cat_spent_expr.label("category_spent"),
                    func.count(Expense.id).label("tx_count"),
                )
                .join(Expense, Expense.category_id == Category.id)
                .where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= s_date,
                    Expense.expense_date <= e_date,
                )
                .group_by(Category.id, Category.name, Category.color, Category.icon)
                .having(cat_spent_expr > Decimal("0.00"))
                .order_by(cat_spent_expr.desc())
            ).all()

            # 4. Category budgets paired with spending in selected month
            category_budgets = session.execute(
                select(
                    Budget.category_id,
                    Category.name.label("category_name"),
                    Budget.amount.label("budget_amount"),
                    func.coalesce(func.sum(Expense.amount), Decimal("0.00")).label(
                        "spent"
                    ),
                )
                .join(Category, Budget.category_id == Category.id)
                .outerjoin(
                    Expense,
                    and_(
                        Expense.category_id == Budget.category_id,
                        Expense.user_id == Budget.user_id,
                        Expense.expense_date >= s_date,
                        Expense.expense_date <= e_date,
                    ),
                )
                .where(
                    Budget.user_id == user_id,
                    Budget.month == month,
                    Budget.year == year,
                    Budget.category_id.is_not(None),
                )
                .group_by(Budget.category_id, Category.name, Budget.amount)
            ).all()

            # 5. Previous month total spent
            prev_spent = session.scalar(
                select(
                    func.coalesce(func.sum(Expense.amount), Decimal("0.00"))
                ).where(
                    Expense.user_id == user_id,
                    Expense.expense_date >= ps_date,
                    Expense.expense_date <= pe_date,
                )
            )

        return {
            "total_spending_row": {
                "total_spent": (
                    Decimal(str(total_row.total_spent))
                    if total_row
                    else Decimal("0.00")
                ),
                "transaction_count": int(total_row.tx_count) if total_row else 0,
            },
            "overall_budget_row": (
                {"amount": Decimal(str(overall_amt))}
                if overall_amt is not None
                else None
            ),
            "category_spending": [
                {
                    "id": r.id,
                    "name": r.name,
                    "color": r.color,
                    "icon": r.icon,
                    "category_spent": Decimal(str(r.category_spent)),
                    "tx_count": int(r.tx_count),
                }
                for r in category_spending
            ],
            "category_budgets": [
                {
                    "category_id": r.category_id,
                    "category_name": r.category_name,
                    "budget_amount": Decimal(str(r.budget_amount)),
                    "spent_amount": Decimal(str(r.spent)),
                }
                for r in category_budgets
            ],
            "prev_spending_row": {
                "prev_spent": (
                    Decimal(str(prev_spent)) if prev_spent is not None else Decimal("0.00")
                )
            },
        }
