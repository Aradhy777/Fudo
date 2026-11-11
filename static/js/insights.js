/**
 * ExpenseTrack - Spending Insights & Rule-Based Recommendations Controller
 */

function initInsightsControls() {
  const now = new Date();
  const mSelect = document.getElementById("insightsMonthSelect");
  const ySelect = document.getElementById("insightsYearSelect");
  if (mSelect) mSelect.value = now.getMonth() + 1;
  if (ySelect) ySelect.value = now.getFullYear();
}

async function loadInsights() {
  const month = document.getElementById("insightsMonthSelect").value;
  const year = document.getElementById("insightsYearSelect").value;

  try {
    const data = await API.get(`/api/insights?month=${month}&year=${year}`);

    // Update KPI Cards
    document.getElementById("insDailyAllowance").textContent = formatCurrency(data.safe_daily_allowance);
    document.getElementById("insDaysRemaining").textContent = `${data.days_remaining} days left in cycle`;

    if (data.highest_category) {
      document.getElementById("insTopCategory").textContent = data.highest_category.name;
      const share = data.total_spent > 0 
        ? ((data.highest_category.category_spent / data.total_spent) * 100).toFixed(1) 
        : 0;
      document.getElementById("insTopCategoryShare").textContent = `${share}% of total spend (${formatCurrency(data.highest_category.category_spent)})`;
    } else {
      document.getElementById("insTopCategory").textContent = "None";
      document.getElementById("insTopCategoryShare").textContent = "No expenses recorded";
    }

    document.getElementById("insDailyBurn").textContent = `${formatCurrency(data.avg_daily_burn)} / day`;
    const mom = data.month_over_month_change;
    const momLabel = mom > 0 ? `+${mom}% vs last month` : `${mom}% vs last month`;
    document.getElementById("insMoMChange").textContent = data.prev_spent > 0 ? momLabel : "No previous month data";

    document.getElementById("insBudgetUtil").textContent = `${data.budget_utilization}%`;
    document.getElementById("insRemainingBudget").textContent = data.overall_budget > 0 
      ? `${formatCurrency(data.remaining_budget)} remaining` 
      : "No budget configured";

    // Render Recommendations
    renderRecommendations(data.recommendations);

    // Render Category Table
    renderCategoryTable(data.category_spending);

  } catch (err) {
    showToast(err.message || "Failed to load financial insights.", "error");
  }
}

function renderRecommendations(recommendations) {
  const container = document.getElementById("recommendationsContainer");
  if (!container) return;

  if (!recommendations || recommendations.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 20px; color: var(--text-muted);">
        No budget anomalies or warnings detected for this month. Keep logging your daily expenses!
      </div>
    `;
    return;
  }

  const styles = {
    danger: { bg: "#FEF2F2", border: "#FECACA", color: "#991B1B", icon: "🚨" },
    warning: { bg: "#FFFBEB", border: "#FDE68A", color: "#92400E", icon: "⚠️" },
    info: { bg: "#EFF6FF", border: "#BFDBFE", color: "#1E40AF", icon: "💡" },
    success: { bg: "#ECFDF5", border: "#A7F3D0", color: "#065F46", icon: "✅" },
  };

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 12px;">
      ${recommendations.map(r => {
        const s = styles[r.type] || styles.info;
        return `
          <div style="background: ${s.bg}; border: 1px solid ${s.border}; border-radius: var(--radius-md); padding: 14px 18px; display: flex; align-items: flex-start; gap: 12px;">
            <div style="font-size: 1.2rem; line-height: 1.2;">${s.icon}</div>
            <div style="flex: 1;">
              <div style="font-weight: 700; font-size: 0.92rem; color: ${s.color}; margin-bottom: 2px;">
                ${escapeHtml(r.title)}
              </div>
              <div style="font-size: 0.85rem; color: ${s.color}; line-height: 1.4;">
                ${escapeHtml(r.text)}
              </div>
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderCategoryTable(categories) {
  const tbody = document.getElementById("categoryDistributionBody");
  if (!tbody) return;

  if (!categories || categories.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align: center; padding: 24px; color: var(--text-muted);">
          No expenses recorded for this month.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = categories.map(c => `
    <tr>
      <td style="font-weight: 600; color: #1E293B;">
        <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: ${c.color}; margin-right: 8px;"></span>
        ${escapeHtml(c.name)}
      </td>
      <td style="font-weight: 700; color: #0F172A; font-variant-numeric: tabular-nums;">
        ${formatCurrency(c.amount)}
      </td>
      <td style="color: #64748B; font-size: 0.86rem; font-weight: 600;">
        ${c.share}%
      </td>
      <td style="width: 250px;">
        <div class="progress-bar-container" style="height: 6px; margin: 0;">
          <div class="progress-bar-fill" style="width: ${c.share}%; background: ${c.color};"></div>
        </div>
      </td>
    </tr>
  `).join("");
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

document.addEventListener("DOMContentLoaded", () => {
  initInsightsControls();
  loadInsights();
});

