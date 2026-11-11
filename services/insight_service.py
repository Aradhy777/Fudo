"""
ExpenseTrack - Rule-Based Financial Insights Service (AI-900 / Rule-Based Expert System)
Derives actionable, student-centric financial recommendations strictly from factual MySQL data.
Uses pure Decimal arithmetic internally for financial precision.
"""

from calendar import monthrange
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from repositories.analytics_repo import AnalyticsRepository
from routes.validators import (
    ZERO_DEC,
    CENT_QUANT,
    TENTH_QUANT,
    HUNDRED_DEC,
    date_range_for_month,
    subtract_months,
    to_decimal,
)


class InsightService:
    @classmethod
    def get_monthly_insights(cls, user_id: int, month: int, year: int) -> dict:
        """
        Analyze user spending patterns and produce explainable recommendations
        using a single database connection, sargable range queries, and Decimal arithmetic.
        """
        now = datetime.now()
        _, total_days_in_month = monthrange(year, month)
        current_day = now.day if (now.year == year and now.month == month) else total_days_in_month
        days_remaining = max(1, total_days_in_month - current_day)

        cur_start, cur_end = date_range_for_month(year, month)
        prev_year, prev_month = subtract_months(year, month, 1)
        prev_start, prev_end = date_range_for_month(prev_year, prev_month)

        insights_data = AnalyticsRepository().get_monthly_insights_data(
            user_id,
            month=month,
            year=year,
            start_date=cur_start,
            end_date=cur_end,
            prev_start=prev_start,
            prev_end=prev_end,
        )
        total_spending_row = insights_data["total_spending_row"]
        overall_budget_row = insights_data["overall_budget_row"]
        category_spending = insights_data["category_spending"]
        category_budgets = insights_data["category_budgets"]
        prev_spending_row = insights_data["prev_spending_row"]

        total_spent_dec = to_decimal(total_spending_row["total_spent"]) if total_spending_row else ZERO_DEC
        transaction_count = int(total_spending_row["transaction_count"]) if total_spending_row else 0
        overall_budget_dec = to_decimal(overall_budget_row["amount"]) if overall_budget_row else ZERO_DEC
        prev_spent_dec = to_decimal(prev_spending_row["prev_spent"]) if prev_spending_row else ZERO_DEC

        budget_util_dec = (
            (total_spent_dec / overall_budget_dec * HUNDRED_DEC).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP)
            if overall_budget_dec > ZERO_DEC
            else Decimal("0.0")
        )
        remaining_budget_dec = max(ZERO_DEC, overall_budget_dec - total_spent_dec) if overall_budget_dec > ZERO_DEC else ZERO_DEC
        safe_daily_dec = (
            (remaining_budget_dec / Decimal(days_remaining)).quantize(CENT_QUANT, rounding=ROUND_HALF_UP)
            if overall_budget_dec > ZERO_DEC
            else ZERO_DEC
        )
        avg_daily_burn_dec = (total_spent_dec / Decimal(max(1, current_day))).quantize(CENT_QUANT, rounding=ROUND_HALF_UP)

        recommendations = []
        raw_top = category_spending[0] if category_spending else None
        highest_category = {
            "id": raw_top["id"],
            "name": raw_top["name"],
            "color": raw_top["color"],
            "icon": raw_top["icon"],
            "category_spent": float(to_decimal(raw_top["category_spent"])),
            "tx_count": int(raw_top["tx_count"]),
        } if raw_top else None

        # Rule 1: Overall Budget Exhaustion & Thresholds
        if overall_budget_dec > ZERO_DEC:
            if total_spent_dec > overall_budget_dec:
                overage_dec = (total_spent_dec - overall_budget_dec).quantize(CENT_QUANT, rounding=ROUND_HALF_UP)
                recommendations.append({
                    "type": "danger",
                    "title": "Monthly Budget Exceeded",
                    "text": f"You have exceeded your overall monthly budget by ₹{overage_dec:,.2f} ({budget_util_dec:.1f}% used). Pause non-essential discretionary purchases immediately.",
                })
            elif budget_util_dec >= Decimal("80.0"):
                recommendations.append({
                    "type": "warning",
                    "title": "High Budget Utilization (80%+ Alert)",
                    "text": f"You have consumed {budget_util_dec:.1f}% of your monthly budget with {days_remaining} days remaining. Cap daily spending at ₹{safe_daily_dec:,.2f} to stay within limits.",
                })
            else:
                recommendations.append({
                    "type": "success",
                    "title": "Healthy Budget Pace",
                    "text": f"Your spending is well within budget ({budget_util_dec:.1f}% utilized). Your safe daily spending allowance is ₹{safe_daily_dec:,.2f}.",
                })

        # Rule 2: Dominant Category Spending
        if highest_category and total_spent_dec > ZERO_DEC:
            top_amt_dec = to_decimal(highest_category["category_spent"])
            cat_share_dec = (top_amt_dec / total_spent_dec * HUNDRED_DEC).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP)
            if cat_share_dec >= Decimal("35.0"):
                cat_name = highest_category["name"]
                advice = "Consider college meal plans or bulk purchases" if cat_name == "Food" else "Audit regular subscriptions and unplanned purchases"
                recommendations.append({
                    "type": "info",
                    "title": f"Dominant Category: {cat_name}",
                    "text": f"{cat_name} represents {cat_share_dec:.1f}% (₹{top_amt_dec:,.2f}) of your total expenses this month. {advice} to free up cash flow.",
                })

        # Rule 3: Category Limit Breaches
        for cb in category_budgets:
            c_spent_dec = to_decimal(cb["spent_amount"])
            c_limit_dec = to_decimal(cb["budget_amount"])
            c_name = cb["category_name"]
            if c_spent_dec > c_limit_dec:
                recommendations.append({
                    "type": "warning",
                    "title": f"Category Limit Breached: {c_name}",
                    "text": f"Spending on {c_name} (₹{c_spent_dec:,.2f}) has exceeded its set category budget of ₹{c_limit_dec:,.2f}.",
                })

        # Rule 4: Burn Rate Warning
        if overall_budget_dec > ZERO_DEC and days_remaining > 5 and avg_daily_burn_dec > (safe_daily_dec * Decimal("1.3")):
            recommendations.append({
                "type": "warning",
                "title": "Fast Daily Burn Rate",
                "text": f"Your average daily spending (₹{avg_daily_burn_dec:,.2f}/day) exceeds the recommended allowance of ₹{safe_daily_dec:,.2f}/day. At this rate, your budget will run out before month end.",
            })

        mom_change_dec = (
            ((total_spent_dec - prev_spent_dec) / prev_spent_dec * HUNDRED_DEC).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP)
            if prev_spent_dec > ZERO_DEC
            else Decimal("0.0")
        )

        return {
            "month": month,
            "year": year,
            "total_spent": float(total_spent_dec),
            "overall_budget": float(overall_budget_dec),
            "remaining_budget": float(remaining_budget_dec),
            "budget_utilization": float(budget_util_dec),
            "safe_daily_allowance": float(safe_daily_dec),
            "avg_daily_burn": float(avg_daily_burn_dec),
            "days_remaining": days_remaining,
            "transaction_count": transaction_count,
            "highest_category": highest_category,
            "category_spending": [
                {
                    "name": c["name"],
                    "amount": float(to_decimal(c["category_spent"])),
                    "color": c["color"],
                    "icon": c["icon"],
                    "share": float((to_decimal(c["category_spent"]) / total_spent_dec * HUNDRED_DEC).quantize(TENTH_QUANT, rounding=ROUND_HALF_UP))
                    if total_spent_dec > ZERO_DEC else 0.0,
                }
                for c in category_spending
            ],
            "prev_spent": float(prev_spent_dec),
            "month_over_month_change": float(mom_change_dec),
            "recommendations": recommendations,
        }
