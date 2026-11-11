/**
 * ExpenseTrack - Spending Insights & Rule-Based Recommendations Controller
 */

let insightsChartInstance = null;
let cachedInsightsData = null;

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
    cachedInsightsData = data;

    // Update KPI Cards
    document.getElementById("insDailyAllowance").textContent = `${formatCurrency(data.safe_daily_allowance)} / day`;
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

    renderRecommendations(data.recommendations);
    renderCategoryComparisonChart(data.category_spending);
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
        No budget anomalies or warnings detected for this month. Log expenses or configure a budget to unlock tailored pacing insights.
      </div>
    `;
    return;
  }

  const styles = {
    danger: {
      bg: "var(--danger-subtle)",
      border: "var(--danger-border)",
      color: "var(--danger)",
      icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    },
    warning: {
      bg: "var(--warning-subtle)",
      border: "var(--warning-border)",
      color: "var(--warning)",
      icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    },
    info: {
      bg: "var(--info-subtle)",
      border: "var(--info-border)",
      color: "var(--info)",
      icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    },
    success: {
      bg: "var(--primary-subtle)",
      border: "var(--primary-border)",
      color: "var(--primary)",
      icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    },
  };

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 12px;">
      ${recommendations.map(r => {
        const s = styles[r.type] || styles.info;
        return `
          <div style="background: ${s.bg}; border: 1px solid ${s.border}; border-radius: var(--radius-md); padding: 14px 16px; display: flex; align-items: flex-start; gap: 12px;">
            <div style="color: ${s.color}; flex-shrink: 0; margin-top: 2px;">${s.icon}</div>
            <div style="flex: 1;">
              <div style="font-weight: 700; font-size: 0.9rem; color: ${s.color}; margin-bottom: 2px;">
                ${escapeHtml(r.title)}
              </div>
              <div style="font-size: 0.84rem; color: var(--text-main); line-height: 1.45;">
                ${escapeHtml(r.text)}
              </div>
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderCategoryComparisonChart(categories) {
  const canvas = document.getElementById("insightsCategoryChart");
  const wrap = document.getElementById("insightsChartWrap");
  const emptyEl = document.getElementById("insightsChartEmpty");
  if (!canvas || !wrap) return;

  if (insightsChartInstance) {
    insightsChartInstance.destroy();
    insightsChartInstance = null;
  }

  if (!categories || categories.length === 0) {
    wrap.style.display = "none";
    if (emptyEl) emptyEl.style.display = "block";
    return;
  }

  wrap.style.display = "block";
  if (emptyEl) emptyEl.style.display = "none";

  const dark = document.documentElement.getAttribute("data-theme") !== "light";
  const gridColor = dark ? "rgba(255, 255, 255, 0.06)" : "#E2E8F0";
  const tickColor = dark ? "#94A3B8" : "#64748B";

  insightsChartInstance = new Chart(canvas, {
    type: "bar",
    data: {
      labels: categories.map(c => c.name),
      datasets: [{
        label: "Expenditure",
        data: categories.map(c => c.amount),
        backgroundColor: categories.map(c => c.color),
        borderRadius: 6,
        barThickness: 18,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: dark ? "#1E293B" : "#0F172A",
          titleColor: "#FFFFFF",
          bodyColor: "#F8FAFC",
          padding: 10,
          cornerRadius: 8,
          displayColors: false,
          callbacks: {
            label: (ctx) => `Spent: ${formatCurrency(ctx.raw)}`,
          },
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          ticks: {
            callback: (val) => "₹" + val,
            color: tickColor,
            font: { size: 11 },
          },
          grid: { color: gridColor },
        },
        y: {
          ticks: {
            color: tickColor,
            font: { size: 11, weight: "700" },
          },
          grid: { display: false },
        },
      },
    },
  });
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
      <td style="font-weight: 700; color: var(--text-main); white-space: nowrap;">
        <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: ${c.color}; margin-right: 8px;"></span>
        ${escapeHtml(c.name)}
      </td>
      <td style="font-weight: 800; color: var(--text-main); font-variant-numeric: tabular-nums; white-space: nowrap;">
        ${formatCurrency(c.amount)}
      </td>
      <td style="color: var(--text-muted); font-size: 0.86rem; font-weight: 700; font-variant-numeric: tabular-nums;">
        ${c.share}%
      </td>
      <td style="min-width: 140px;">
        <div class="progress-bar-container" style="height: 8px;">
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

window.onThemeChanged = () => {
  if (cachedInsightsData) {
    renderCategoryComparisonChart(cachedInsightsData.category_spending);
  }
};

window.onExpenseCreated = () => loadInsights();

document.addEventListener("DOMContentLoaded", () => {
  initInsightsControls();
  loadInsights();
});
