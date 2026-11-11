/**
 * ExpenseTrack - Enhanced Obsidian & Platinum Dashboard Controller
 */

let trendChartInstance = null;
let categoryChartInstance = null;
let currentTrendType = "bar";
let cachedDashboardData = null;
let cachedRecentTransactions = [];

function isDarkMode() {
  return document.documentElement.getAttribute("data-theme") !== "light";
}

function initDashboardControls() {
  const now = new Date();
  const mSelect = document.getElementById("dashMonthSelect");
  const ySelect = document.getElementById("dashYearSelect");
  if (mSelect && !mSelect.value) mSelect.value = now.getMonth() + 1;
  if (ySelect && !ySelect.value) ySelect.value = now.getFullYear();
}

function handleDashboardMonthChange() {
  const month = document.getElementById("dashMonthSelect").value;
  const year = document.getElementById("dashYearSelect").value;
  loadDashboardData(month, year);
}

async function loadDashboardData(customMonth = null, customYear = null) {
  const month = customMonth || document.getElementById("dashMonthSelect")?.value || (new Date().getMonth() + 1);
  const year = customYear || document.getElementById("dashYearSelect")?.value || new Date().getFullYear();

  try {
    const data = await API.get(`/api/dashboard/summary?month=${month}&year=${year}`);
    cachedDashboardData = data;
    cachedRecentTransactions = data.recent_transactions || [];

    // 1. Update Command Strip
    updatePulseBanner(data);

    // 2. Update Bento Metric Cards
    updateKpiCards(data);

    // 3. Render Trajectory Chart
    renderTrendChart(data.monthly_trend);

    // 4. Render Category Donut & Breakdown
    renderCategoryDonut(data);

    // 5. Render Ledger
    renderRecentTable(cachedRecentTransactions, data.is_empty_state);

  } catch (err) {
    showToast(err.message || "Failed to load dashboard data.", "error");
  }
}

function updatePulseBanner(data) {
  const greetingEl = document.getElementById("pulseGreeting");
  const subEl = document.getElementById("pulseSub");
  const statusDot = document.getElementById("pulseStatusDot");
  const statusText = document.getElementById("pulseStatusText");
  const dailyEl = document.getElementById("pulseDailyAllowance");
  const topCatEl = document.getElementById("pulseTopCategory");

  if (greetingEl) {
    greetingEl.textContent = `Financial Pulse: ${data.current_month_name}`;
  }
  if (subEl) {
    subEl.textContent = `Tracking student expenditures and live budget pacing for ${data.current_month_name}`;
  }

  const usedPct = data.budget_used_percentage || 0;
  if (data.monthly_budget > 0) {
    statusText.textContent = `${usedPct}% Budget Used`;
    if (usedPct >= 100) {
      statusDot.className = "pulse-chip-dot amber";
      statusDot.style.background = "#EF4444";
      statusDot.style.boxShadow = "0 0 10px #EF4444";
    } else if (usedPct >= 80) {
      statusDot.className = "pulse-chip-dot amber";
      statusDot.style.background = "#F59E0B";
      statusDot.style.boxShadow = "0 0 10px #F59E0B";
    } else {
      statusDot.className = "pulse-chip-dot green";
      statusDot.style.background = "#10B981";
      statusDot.style.boxShadow = "0 0 10px #10B981";
    }
  } else {
    statusText.textContent = "No Budget Configured";
    statusDot.className = "pulse-chip-dot green";
  }

  if (dailyEl) {
    dailyEl.textContent = `Safe Daily: ${formatCurrency(data.safe_daily_allowance)}/day`;
  }

  if (topCatEl) {
    if (data.highest_category) {
      topCatEl.textContent = `Top: ${data.highest_category.name} (${data.highest_category.share}%)`;
    } else {
      topCatEl.textContent = "No spending recorded";
    }
  }
}

function updateKpiCards(data) {
  // Metric 1: Month Spending
  document.getElementById("kpiTotalSpent").textContent = formatCurrency(data.total_spent);
  document.getElementById("kpiMonthLabel").textContent = data.current_month_name;
  
  const momBadge = document.getElementById("kpiMoMBadge");
  if (momBadge) {
    const change = data.mom_percentage_change || 0;
    if (data.prev_month_spent > 0) {
      if (change < 0) {
        momBadge.className = "trend-badge down";
        momBadge.textContent = `↓ ${Math.abs(change)}% vs prior`;
      } else if (change > 0) {
        momBadge.className = "trend-badge up";
        momBadge.textContent = `↑ ${change}% vs prior`;
      } else {
        momBadge.className = "trend-badge neutral";
        momBadge.textContent = "0% vs prior";
      }
    } else {
      momBadge.className = "trend-badge neutral";
      momBadge.textContent = "Current Cycle";
    }
  }

  const spendFill = document.getElementById("kpiSpendFill");
  if (spendFill && data.monthly_budget > 0) {
    spendFill.style.width = `${Math.min(100, data.budget_used_percentage)}%`;
  }

  // Metric 2: Monthly Budget Cap
  document.getElementById("kpiMonthlyBudget").textContent = formatCurrency(data.monthly_budget);
  const capNotice = document.getElementById("kpiCapNotice");
  if (capNotice) {
    capNotice.textContent = data.monthly_budget > 0 ? "Overall monthly cap" : "No budget limit";
  }

  // Metric 3: Remaining Allowance
  document.getElementById("kpiRemainingBudget").textContent = formatCurrency(data.remaining_budget);
  const usedPct = data.budget_used_percentage || 0;
  document.getElementById("kpiBudgetUsed").textContent = data.monthly_budget > 0 ? `${usedPct}% Used` : "Unbudgeted";
  
  const daysLeftEl = document.getElementById("kpiDaysLeft");
  if (daysLeftEl) {
    daysLeftEl.textContent = `${data.days_remaining} days left`;
  }

  const remainingCard = document.getElementById("kpiRemainingCard");
  const remainingWrapper = document.getElementById("kpiRemainingWrapper");
  const remainingFill = document.getElementById("kpiRemainingFill");

  if (data.monthly_budget > 0) {
    if (usedPct >= 100) {
      remainingCard.className = "stat-card";
      remainingCard.style.borderTopColor = "#EF4444";
      remainingWrapper.className = "stat-icon-wrapper";
      remainingWrapper.style.background = "var(--danger-subtle)";
      remainingWrapper.style.color = "var(--danger)";
      if (remainingFill) {
        remainingFill.style.background = "#EF4444";
        remainingFill.style.width = "100%";
      }
    } else if (usedPct >= 80) {
      remainingCard.className = "stat-card card-accent-amber";
      remainingCard.style.borderTopColor = "#F59E0B";
      remainingWrapper.className = "stat-icon-wrapper amber";
      if (remainingFill) {
        remainingFill.style.background = "#F59E0B";
        remainingFill.style.width = `${100 - usedPct}%`;
      }
    } else {
      remainingCard.className = "stat-card card-accent-emerald";
      remainingCard.style.borderTopColor = "#10B981";
      remainingWrapper.className = "stat-icon-wrapper emerald";
      if (remainingFill) {
        remainingFill.style.background = "#10B981";
        remainingFill.style.width = `${100 - usedPct}%`;
      }
    }
  }

  // Metric 4: Transactions Count
  document.getElementById("kpiExpenseCount").textContent = data.expense_count;
  const avgEl = document.getElementById("kpiAvgTx");
  if (avgEl) {
    avgEl.textContent = `Avg: ${formatCurrency(data.avg_transaction_amount)}/tx`;
  }
}

function setTrendChartType(type) {
  currentTrendType = type;
  document.getElementById("btnTrendBar").classList.toggle("active", type === "bar");
  document.getElementById("btnTrendLine").classList.toggle("active", type === "line");
  if (cachedDashboardData) {
    renderTrendChart(cachedDashboardData.monthly_trend);
  }
}

function renderTrendChart(trend) {
  const ctx = document.getElementById("monthlyTrendChart");
  if (!ctx) return;

  if (trendChartInstance) {
    trendChartInstance.destroy();
  }

  const dark = isDarkMode();
  const gridColor = dark ? "rgba(255, 255, 255, 0.05)" : "#F1F5F9";
  const tickColor = dark ? "#94A3B8" : "#64748B";

  const isBar = currentTrendType === "bar";

  trendChartInstance = new Chart(ctx, {
    type: isBar ? "bar" : "line",
    data: {
      labels: trend.labels || [],
      datasets: [{
        label: "Expenditure",
        data: trend.data || [],
        backgroundColor: isBar 
          ? (dark ? "rgba(16, 185, 129, 0.85)" : "rgba(16, 185, 129, 0.8)")
          : (dark ? "rgba(16, 185, 129, 0.16)" : "rgba(16, 185, 129, 0.12)"),
        borderColor: "#10B981",
        borderWidth: isBar ? 0 : 2.5,
        hoverBackgroundColor: "#059669",
        borderRadius: isBar ? 8 : 0,
        fill: !isBar,
        tension: 0.35,
        pointBackgroundColor: "#10B981",
        pointBorderColor: dark ? "#0F172A" : "#FFFFFF",
        pointBorderWidth: 2,
        pointRadius: isBar ? 0 : 4,
        pointHoverRadius: isBar ? 0 : 6,
        barPercentage: 0.45,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: dark ? "#1E293B" : "#0F172A",
          titleColor: "#FFFFFF",
          bodyColor: "#F8FAFC",
          borderColor: dark ? "rgba(255, 255, 255, 0.1)" : "transparent",
          borderWidth: 1,
          titleFont: { family: "'Plus Jakarta Sans', sans-serif", size: 12, weight: "700" },
          bodyFont: { family: "'Plus Jakarta Sans', sans-serif", size: 12 },
          padding: 12,
          cornerRadius: 10,
          displayColors: false,
          callbacks: {
            label: (ctx) => `Spent: ${formatCurrency(ctx.raw)}`,
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            callback: (val) => "₹" + val,
            color: tickColor,
            font: { family: "'Plus Jakarta Sans', sans-serif", size: 11 },
          },
          grid: { color: gridColor },
          border: { dash: [4, 4] }
        },
        x: {
          ticks: {
            color: tickColor,
            font: { family: "'Plus Jakarta Sans', sans-serif", size: 11, weight: "700" }
          },
          grid: { display: false },
        },
      },
    },
  });
}

function renderCategoryDonut(data) {
  const ctx = document.getElementById("categoryChart");
  if (!ctx) return;

  if (categoryChartInstance) {
    categoryChartInstance.destroy();
  }

  const dark = isDarkMode();
  const categoryData = data.category_chart || {};
  const breakdownList = data.categories_breakdown || [];
  const hasData = categoryData.data && categoryData.data.length > 0;

  // Center Total Overlay Metric
  document.getElementById("donutCenterTotal").textContent = formatCurrency(data.total_spent);

  categoryChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: hasData ? categoryData.labels : ["No Spending"],
      datasets: [{
        data: hasData ? categoryData.data : [1],
        backgroundColor: hasData ? categoryData.colors : (dark ? ["#1E293B"] : ["#E2E8F0"]),
        borderWidth: 2.5,
        borderColor: dark ? "#0F172A" : "#FFFFFF",
        hoverOffset: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "75%",
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: hasData,
          backgroundColor: dark ? "#1E293B" : "#0F172A",
          titleColor: "#FFFFFF",
          bodyColor: "#F8FAFC",
          borderColor: dark ? "rgba(255, 255, 255, 0.1)" : "transparent",
          borderWidth: 1,
          titleFont: { family: "'Plus Jakarta Sans', sans-serif", size: 12, weight: "700" },
          bodyFont: { family: "'Plus Jakarta Sans', sans-serif", size: 12 },
          padding: 10,
          cornerRadius: 8,
          callbacks: {
            label: (ctx) => ` ${ctx.label}: ${formatCurrency(ctx.raw)}`,
          },
        },
      },
    },
  });

  // Render Category Breakdown List beside Donut
  const listContainer = document.getElementById("categoryBreakdownList");
  if (!listContainer) return;

  if (!hasData || breakdownList.length === 0) {
    listContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem; text-align: center; padding: 20px;">No expenses logged for this month.</div>';
    return;
  }

  listContainer.innerHTML = breakdownList.slice(0, 5).map(cat => `
    <div class="category-breakdown-item">
      <div class="cat-item-header">
        <div class="cat-item-left">
          <span class="cat-item-dot" style="background: ${cat.color};"></span>
          <span>${escapeHtml(cat.name)}</span>
        </div>
        <div class="cat-item-right">
          <span class="cat-item-amt">${formatCurrency(cat.amount)}</span>
          <span class="cat-item-pct">${cat.share}%</span>
        </div>
      </div>
      <div class="cat-bar-bg">
        <div class="cat-bar-fill" style="width: ${cat.share}%; background: ${cat.color};"></div>
      </div>
    </div>
  `).join("");
}

function filterRecentTable(query) {
  const q = (query || "").toLowerCase().trim();
  if (!q) {
    renderRecentTable(cachedRecentTransactions, cachedDashboardData?.is_empty_state);
    return;
  }
  const filtered = cachedRecentTransactions.filter(tx => 
    tx.merchant.toLowerCase().includes(q) ||
    tx.category_name.toLowerCase().includes(q) ||
    (tx.notes || "").toLowerCase().includes(q)
  );
  renderRecentTable(filtered, false);
}

function renderRecentTable(transactions, isEmpty) {
  const tbody = document.getElementById("recentTransactionsBody");
  const emptyState = document.getElementById("dashboardEmptyState");
  const table = document.getElementById("recentTransactionsTable");

  if (!tbody) return;

  if (isEmpty || !transactions || transactions.length === 0) {
    table.style.display = "none";
    emptyState.style.display = "block";
    return;
  }

  table.style.display = "table";
  emptyState.style.display = "none";

  tbody.innerHTML = transactions.map(tx => {
    // Generate initials for avatar
    const words = tx.merchant.trim().split(/\s+/);
    const initials = words.length >= 2 
      ? (words[0][0] + words[1][0]).toUpperCase()
      : tx.merchant.substring(0, 2).toUpperCase();

    // Payment method pill style
    const mLower = (tx.payment_method || "").toLowerCase().replace(/\s+/g, "");
    let methodClass = "other";
    if (mLower.includes("upi")) methodClass = "upi";
    else if (mLower.includes("cash")) methodClass = "cash";
    else if (mLower.includes("card")) methodClass = "card";
    else if (mLower.includes("bank") || mLower.includes("net")) methodClass = "netbanking";

    return `
      <tr>
        <td style="color: var(--text-muted); font-size: 0.84rem; white-space: nowrap; font-weight: 600;">
          ${tx.expense_date}
        </td>
        <td>
          <div class="merchant-cell">
            <div class="merchant-avatar" style="background: ${tx.category_color}18; color: ${tx.category_color};">
              ${initials}
            </div>
            <span class="merchant-name-text">${escapeHtml(tx.merchant)}</span>
          </div>
        </td>
        <td>
          <span class="category-pill" style="background: ${tx.category_color}18; color: ${tx.category_color};">
            ${escapeHtml(tx.category_name)}
          </span>
        </td>
        <td>
          <span class="method-pill ${methodClass}">
            ${escapeHtml(tx.payment_method)}
          </span>
        </td>
        <td style="color: var(--text-muted); font-size: 0.84rem;">
          ${escapeHtml(tx.notes || "-")}
        </td>
        <td style="text-align: right; font-weight: 800; color: var(--text-main); font-variant-numeric: tabular-nums; font-size: 0.95rem;">
          ${formatCurrency(tx.amount)}
        </td>
      </tr>
    `;
  }).join("");
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Hook when theme changes to re-theme charts
window.onThemeChanged = () => {
  if (cachedDashboardData) {
    renderTrendChart(cachedDashboardData.monthly_trend);
    renderCategoryDonut(cachedDashboardData);
  }
};

// Hook for refresh when quick modal adds an expense
window.onExpenseCreated = () => {
  const m = document.getElementById("dashMonthSelect")?.value;
  const y = document.getElementById("dashYearSelect")?.value;
  loadDashboardData(m, y);
};

document.addEventListener("DOMContentLoaded", () => {
  initDashboardControls();
  loadDashboardData();
});
