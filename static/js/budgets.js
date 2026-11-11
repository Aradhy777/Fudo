/**
 * ExpenseTrack - Budget Planning & Threshold Alert Controller
 */

let currentOverallLimit = 0;
let currentOverallBudgetId = null;

function initBudgetControls() {
  const now = new Date();
  const mSelect = document.getElementById("budgetMonthSelect");
  const ySelect = document.getElementById("budgetYearSelect");
  if (mSelect) mSelect.value = now.getMonth() + 1;
  if (ySelect) ySelect.value = now.getFullYear();
}

async function loadBudgets() {
  const mSelect = document.getElementById("budgetMonthSelect");
  const ySelect = document.getElementById("budgetYearSelect");
  const month = mSelect.value;
  const year = ySelect.value;
  const mName = mSelect.options[mSelect.selectedIndex].text;

  document.getElementById("overallMonthSubtitle").textContent = `Spending allocation for ${mName} ${year}`;

  try {
    const data = await API.get(`/api/budgets?month=${month}&year=${year}`);
    renderOverallBudget(data.overall);
    renderCategoryBudgets(data.categories);
  } catch (err) {
    showToast(err.message || "Failed to load budget data.", "error");
  }
}

function renderOverallBudget(overall) {
  currentOverallLimit = overall.budget_limit || 0;
  currentOverallBudgetId = overall.budget_id || null;

  document.getElementById("overallLimitVal").textContent = formatCurrency(overall.budget_limit);
  document.getElementById("overallSpentVal").textContent = formatCurrency(overall.total_spent);

  const remLabelEl = document.getElementById("overallRemainingLabel");
  const remValEl = document.getElementById("overallRemainingVal");

  if (overall.budget_limit > 0 && overall.total_spent > overall.budget_limit) {
    const overage = overall.total_spent - overall.budget_limit;
    remLabelEl.textContent = "Overspent By";
    remValEl.textContent = formatCurrency(overage);
    remValEl.className = "budget-metric-value danger";
  } else {
    remLabelEl.textContent = "Remaining Balance";
    remValEl.textContent = formatCurrency(overall.remaining);
    remValEl.className = overall.budget_limit > 0 ? "budget-metric-value success" : "budget-metric-value";
  }

  const pct = overall.percentage || 0;
  document.getElementById("overallPercentageLabel").textContent = `${pct}% Used`;

  const bar = document.getElementById("overallProgressBar");
  bar.style.width = overall.budget_limit > 0 ? `${Math.min(100, pct)}%` : "0%";
  bar.className = `progress-bar-fill ${overall.status}`;

  const alertBox = document.getElementById("overallThresholdAlert");
  const badge = document.getElementById("overallStatusBadge");

  if (overall.budget_limit <= 0) {
    badge.innerHTML = `<span class="badge neutral">Not Configured</span>`;
    alertBox.style.display = "none";
  } else if (overall.status === "exceeded") {
    badge.innerHTML = `<span class="badge exceeded">Budget Exceeded</span>`;
    alertBox.style.display = "block";
    alertBox.style.background = "var(--danger-subtle)";
    alertBox.style.color = "var(--danger)";
    alertBox.style.border = "1px solid var(--danger-border)";
    const overage = overall.total_spent - overall.budget_limit;
    alertBox.innerHTML = `<strong>Over Budget:</strong> You have exceeded your monthly limit by <strong>${formatCurrency(overage)}</strong>. Please review discretionary spending.`;
  } else if (overall.status === "warning") {
    badge.innerHTML = `<span class="badge warning">80% Threshold Reached</span>`;
    alertBox.style.display = "block";
    alertBox.style.background = "var(--warning-subtle)";
    alertBox.style.color = "var(--warning)";
    alertBox.style.border = "1px solid var(--warning-border)";
    alertBox.innerHTML = `<strong>Budget Caution:</strong> You have reached <strong>${pct}%</strong> of your monthly limit.`;
  } else {
    badge.innerHTML = `<span class="badge normal">Healthy Pace (${pct}%)</span>`;
    alertBox.style.display = "none";
  }
}

function renderCategoryBudgets(categories) {
  const grid = document.getElementById("categoryBudgetsGrid");
  if (!grid) return;

  if (!categories || categories.length === 0) {
    grid.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted);">No categories available.</div>';
    return;
  }

  grid.innerHTML = categories.map(c => {
    const hasLimit = c.budget_limit !== null && c.budget_limit > 0;
    const pct = c.percentage || 0;
    const isExceeded = hasLimit && c.total_spent > c.budget_limit;

    let statusPill = `<span class="badge neutral">No Limit</span>`;
    if (hasLimit) {
      if (c.status === "exceeded") {
        statusPill = `<span class="badge exceeded">Exceeded (${pct}%)</span>`;
      } else if (c.status === "warning") {
        statusPill = `<span class="badge warning">80% Alert (${pct}%)</span>`;
      } else {
        statusPill = `<span class="badge normal">${pct}% Used</span>`;
      }
    }

    let remainingHtml = `<span style="font-size: 0.78rem; color: var(--text-muted);">No limit set</span>`;
    if (hasLimit && isExceeded) {
      remainingHtml = `<span style="font-size: 0.78rem; font-weight: 700; color: var(--danger);">Over by ${formatCurrency(c.total_spent - c.budget_limit)}</span>`;
    } else if (hasLimit) {
      remainingHtml = `<span style="font-size: 0.78rem; color: var(--text-muted);">Remaining: ${formatCurrency(c.remaining)}</span>`;
    }

    return `
      <div class="stat-card" style="border-top: 3px solid ${c.color};">
        <div class="stat-header">
          <div style="display: flex; align-items: center; gap: 8px;">
            <div style="width: 10px; height: 10px; border-radius: 3px; background: ${c.color};"></div>
            <span style="font-weight: 700; font-size: 0.95rem; color: var(--text-main);">${escapeHtml(c.category_name)}</span>
          </div>
          ${statusPill}
        </div>

        <div style="margin: 10px 0;">
          <div style="display: flex; justify-content: space-between; font-size: 0.82rem; color: var(--text-muted); margin-bottom: 6px; font-variant-numeric: tabular-nums;">
            <span>Spent: <strong style="color: var(--text-main);">${formatCurrency(c.total_spent)}</strong></span>
            <span>Limit: <strong style="color: var(--text-main);">${hasLimit ? formatCurrency(c.budget_limit) : "None"}</strong></span>
          </div>
          <div class="progress-bar-container" style="height: 6px;">
            <div class="progress-bar-fill ${c.status}" style="width: ${hasLimit ? Math.min(100, pct) : 0}%;"></div>
          </div>
        </div>

        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px;">
          ${remainingHtml}
          <button class="btn btn-secondary btn-sm" onclick="openBudgetModal(${c.category_id}, '${escapeHtml(c.category_name)}', ${c.budget_limit || 0}, ${c.budget_id || 'null'})">
            ${hasLimit ? "Edit Limit" : "Set Limit"}
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function openOverallBudgetModal() {
  openBudgetModal(null, "Overall Monthly Budget", currentOverallLimit, currentOverallBudgetId);
}

function openBudgetModal(categoryId, name, currentLimit, budgetId = null) {
  document.getElementById("budgetCategoryId").value = categoryId === null ? "" : categoryId;
  document.getElementById("budgetRecordId").value = budgetId || "";
  document.getElementById("budgetModalTitle").textContent = `Set Budget – ${name}`;
  document.getElementById("budgetModalDesc").textContent = categoryId === null
    ? "Set the total maximum expenditure allowance for the selected month."
    : `Set the maximum monthly spending cap for ${name}.`;
  document.getElementById("budgetAmount").value = currentLimit > 0 ? currentLimit : "";

  const delBtn = document.getElementById("budgetDeleteBtn");
  if (delBtn) {
    delBtn.style.display = budgetId ? "inline-flex" : "none";
  }

  openModal("budgetModal");
}

async function handleSaveBudget(e) {
  e.preventDefault();
  const btn = document.getElementById("budgetSaveBtn");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "Saving...";

  const rawCatId = document.getElementById("budgetCategoryId").value;
  const categoryId = rawCatId === "" ? null : parseInt(rawCatId, 10);
  const month = parseInt(document.getElementById("budgetMonthSelect").value, 10);
  const year = parseInt(document.getElementById("budgetYearSelect").value, 10);
  const amount = parseFloat(document.getElementById("budgetAmount").value);

  try {
    await API.post("/api/budgets", {
      category_id: categoryId,
      month,
      year,
      amount,
    });
    showToast("Budget limit saved successfully!", "success");
    closeModal("budgetModal");
    loadBudgets();
  } catch (err) {
    showToast(err.message || "Failed to save budget.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Limit";
  }
}

async function handleDeleteBudget() {
  const budgetId = document.getElementById("budgetRecordId").value;
  const delBtn = document.getElementById("budgetDeleteBtn");
  if (!budgetId || delBtn.disabled) return;

  delBtn.disabled = true;
  delBtn.textContent = "Removing...";

  try {
    await API.delete(`/api/budgets/${budgetId}`);
    showToast("Budget limit removed.", "info");
    closeModal("budgetModal");
    loadBudgets();
  } catch (err) {
    showToast(err.message || "Failed to remove budget limit.", "error");
  } finally {
    delBtn.disabled = false;
    delBtn.textContent = "Remove Limit";
  }
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

window.onExpenseCreated = () => loadBudgets();

document.addEventListener("DOMContentLoaded", () => {
  initBudgetControls();
  loadBudgets();
});
