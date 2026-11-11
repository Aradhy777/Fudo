"""
ExpenseTrack - Rule-Based Financial Insights Service (AI-900 / Rule-Based Expert System)
Derives actionable, student-centric financial recommendations strictly from factual MySQL data.
"""

from calendar import monthrange
from datetime import datetime
from database.db import query_db


class InsightService:
    @classmethod
    def get_monthly_insights(cls, user_id: int, month: int, year: int) -> dict:
        """
        Analyze user spending patterns and produce explainable recommendations.
        """
        now = datetime.now()
        _, total_days_in_month = monthrange(year, month)
        current_day = now.day if (now.year == year and now.month == month) else total_days_in_month
        days_remaining = max(1, total_days_in_month - current_day)

        # 1. Total spending this month
        total_spending_row = query_db(
            """
            SELECT COALESCE(SUM(amount), 0.00) AS total_spent,
                   COUNT(id) AS transaction_count
            FROM expenses
            WHERE user_id = %s
              AND MONTH(expense_date) = %s
              AND YEAR(expense_date) = %s;
            """,
            (user_id, month, year),
            one=True,
        )
        total_spent = float(total_spending_row["total_spent"])
        transaction_count = int(total_spending_row["transaction_count"])

        # 2. Monthly Budget (overall budget has category_id IS NULL)
        overall_budget_row = query_db(
            """
            SELECT amount
            FROM budgets
            WHERE user_id = %s
              AND category_id IS NULL
              AND month = %s
              AND year = %s;
            """,
            (user_id, month, year),
            one=True,
        )
        overall_budget = float(overall_budget_row["amount"]) if overall_budget_row else 0.00

        # 3. Category-wise Spending
        category_spending = query_db(
            """
            SELECT c.id, c.name, c.color, c.icon,
                   COALESCE(SUM(e.amount), 0.00) AS category_spent,
                   COUNT(e.id) AS tx_count
            FROM categories c
            LEFT JOIN expenses e
                   ON c.id = e.category_id
                  AND e.user_id = %s
                  AND MONTH(e.expense_date) = %s
                  AND YEAR(e.expense_date) = %s
            GROUP BY c.id, c.name, c.color, c.icon
            HAVING category_spent > 0
            ORDER BY category_spent DESC;
            """,
            (user_id, month, year),
        )

        # 4. Category-wise Budgets & Threshold Checks
        category_budgets = query_db(
            """
            SELECT b.category_id, c.name AS category_name, b.amount AS budget_amount,
                   COALESCE(SUM(e.amount), 0.00) AS spent_amount
            FROM budgets b
            JOIN categories c ON b.category_id = c.id
            LEFT JOIN expenses e
                   ON e.category_id = b.category_id
                  AND e.user_id = b.user_id
                  AND MONTH(e.expense_date) = b.month
                  AND YEAR(e.expense_date) = b.year
            WHERE b.user_id = %s
              AND b.month = %s
              AND b.year = %s
              AND b.category_id IS NOT NULL
            GROUP BY b.category_id, c.name, b.amount;
            """,
            (user_id, month, year),
        )

        # 5. Prior Month Comparison
        prev_month = 12 if month == 1 else month - 1
        prev_year = year - 1 if month == 1 else year
        prev_spending_row = query_db(
            """
            SELECT COALESCE(SUM(amount), 0.00) AS prev_spent
            FROM expenses
            WHERE user_id = %s
              AND MONTH(expense_date) = %s
              AND YEAR(expense_date) = %s;
            """,
            (user_id, prev_month, prev_year),
            one=True,
        )
        prev_spent = float(prev_spending_row["prev_spent"])

        # Calculations
        budget_utilization = (total_spent / overall_budget * 100) if overall_budget > 0 else 0
        remaining_budget = max(0.00, overall_budget - total_spent) if overall_budget > 0 else 0.00
        safe_daily_allowance = round(remaining_budget / days_remaining, 2) if overall_budget > 0 else 0.00
        avg_daily_burn = round(total_spent / max(1, current_day), 2)

        # Generate Rule-Based Explanations & Advice
        recommendations = []
        highest_category = category_spending[0] if category_spending else None

        # Rule 1: Overall Budget Exhaustion & Thresholds
        if overall_budget > 0:
            if total_spent > overall_budget:
                overage = round(total_spent - overall_budget, 2)
                recommendations.append({
                    "type": "danger",
                    "title": "Monthly Budget Exceeded",
                    "text": f"You have exceeded your overall monthly budget by ₹{overage:,.2f} ({budget_utilization:.1f}% used). Pause non-essential discretionary purchases immediately.",
                })
            elif budget_utilization >= 80.0:
                recommendations.append({
                    "type": "warning",
                    "title": "High Budget Utilization (80%+ Alert)",
                    "text": f"You have consumed {budget_utilization:.1f}% of your monthly budget with {days_remaining} days remaining. Cap daily spending at ₹{safe_daily_allowance:,.2f} to stay within limits.",
                })
            else:
                recommendations.append({
                    "type": "success",
                    "title": "Healthy Budget Pace",
                    "text": f"Your spending is well within budget ({budget_utilization:.1f}% utilized). Your safe daily spending allowance is ₹{safe_daily_allowance:,.2f}.",
                })

        # Rule 2: Dominant Category Spending
        if highest_category and total_spent > 0:
            cat_share = (float(highest_category["category_spent"]) / total_spent) * 100
            if cat_share >= 35.0:
                cat_name = highest_category["name"]
                amt = float(highest_category["category_spent"])
                advice = "Consider college meal plans or bulk purchases" if cat_name == "Food" else "Audit regular subscriptions and unplanned purchases"
                recommendations.append({
                    "type": "info",
                    "title": f"Dominant Category: {cat_name}",
                    "text": f"{cat_name} represents {cat_share:.1f}% (₹{amt:,.2f}) of your total expenses this month. {advice} to free up cash flow.",
                })

        # Rule 3: Category Limit Breaches
        for cb in category_budgets:
            c_spent = float(cb["spent_amount"])
            c_limit = float(cb["budget_amount"])
            c_name = cb["category_name"]
            c_pct = (c_spent / c_limit * 100) if c_limit > 0 else 0
            if c_spent > c_limit:
                recommendations.append({
                    "type": "warning",
                    "title": f"Category Limit Breached: {c_name}",
                    "text": f"Spending on {c_name} (₹{c_spent:,.2f}) has exceeded its set category budget of ₹{c_limit:,.2f}.",
                })

        # Rule 4: Burn Rate Warning
        if overall_budget > 0 and days_remaining > 5 and avg_daily_burn > safe_daily_allowance * 1.3:
            recommendations.append({
                "type": "warning",
                "title": "Fast Daily Burn Rate",
                "text": f"Your average daily spending (₹{avg_daily_burn:,.2f}/day) exceeds the recommended allowance of ₹{safe_daily_allowance:,.2f}/day. At this rate, your budget will run out before month end.",
            })

        return {
            "month": month,
            "year": year,
            "total_spent": total_spent,
            "overall_budget": overall_budget,
            "remaining_budget": remaining_budget,
            "budget_utilization": round(budget_utilization, 1),
            "safe_daily_allowance": safe_daily_allowance,
            "avg_daily_burn": avg_daily_burn,
            "days_remaining": days_remaining,
            "transaction_count": transaction_count,
            "highest_category": highest_category,
            "category_spending": [
                {
                    "name": c["name"],
                    "amount": float(c["category_spent"]),
                    "color": c["color"],
                    "icon": c["icon"],
                    "share": round((float(c["category_spent"]) / total_spent * 100), 1) if total_spent > 0 else 0,
                }
                for c in category_spending
            ],
            "prev_spent": prev_spent,
            "month_over_month_change": round(((total_spent - prev_spent) / prev_spent * 100), 1) if prev_spent > 0 else 0.0,
            "recommendations": recommendations,
        }

