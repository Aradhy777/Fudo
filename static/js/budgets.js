/**
 * ExpenseTrack - Budget Planning & Threshold Alert Controller
 */

let currentOverallLimit = 0;

function initBudgetControls() {
  const now = new Date();
  const mSelect = document.getElementById("budgetMonthSelect");
  const ySelect = document.getElementById("budgetYearSelect");
  if (mSelect) mSelect.value = now.getMonth() + 1;
  if (ySelect) ySelect.value = now.getFullYear();
}

async function loadBudgets() {
  const month = document.getElementById("budgetMonthSelect").value;
  const year = document.getElementById("budgetYearSelect").value;
  const mName = document.getElementById("budgetMonthSelect").options[document.getElementById("budgetMonthSelect").selectedIndex].text;

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
  currentOverallLimit = overall.budget_limit;
  document.getElementById("overallLimitVal").textContent = formatCurrency(overall.budget_limit);
  document.getElementById("overallSpentVal").textContent = formatCurrency(overall.total_spent);
  document.getElementById("overallRemainingVal").textContent = formatCurrency(overall.remaining);

  const pct = overall.percentage || 0;
  document.getElementById("overallPercentageLabel").textContent = `${pct}% Used`;

  const bar = document.getElementById("overallProgressBar");
  bar.style.width = `${Math.min(100, pct)}%`;
  bar.className = `progress-bar-fill ${overall.status}`;

  const alertBox = document.getElementById("overallThresholdAlert");
  const badge = document.getElementById("overallStatusBadge");

  if (overall.budget_limit <= 0) {
    badge.innerHTML = `<span class="badge" style="background:#F1F5F9;color:#64748B;">Not Configured</span>`;
    alertBox.style.display = "none";
  } else if (overall.status === "exceeded") {
    badge.innerHTML = `<span class="badge exceeded">Budget Exceeded</span>`;
    alertBox.style.display = "block";
    alertBox.style.background = "#FEF2F2";
    alertBox.style.color = "#991B1B";
    alertBox.style.border = "1px solid #FECACA";
    const overage = overall.total_spent - overall.budget_limit;
    alertBox.innerHTML = `⚠️ <strong>Over Budget:</strong> You have exceeded your monthly limit by <strong>${formatCurrency(overage)}</strong>. Please review discretionary spending immediately.`;
  } else if (overall.status === "warning") {
    badge.innerHTML = `<span class="badge warning">80% Threshold Reached</span>`;
    alertBox.style.display = "block";
    alertBox.style.background = "#FFFBEB";
    alertBox.style.color = "#92400E";
    alertBox.style.border = "1px solid #FDE68A";
    alertBox.innerHTML = `⚠️ <strong>Budget Caution:</strong> You have reached <strong>${pct}%</strong> of your monthly limit. Slow down spending to stay within your monthly budget.`;
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

    let statusPill = `<span class="badge" style="background: #F8FAFC; color: #64748B;">No Limit</span>`;
    if (hasLimit) {
      if (c.status === "exceeded") {
        statusPill = `<span class="badge exceeded">Exceeded (${pct}%)</span>`;
      } else if (c.status === "warning") {
        statusPill = `<span class="badge warning">80% Alert (${pct}%)</span>`;
      } else {
        statusPill = `<span class="badge normal">${pct}% Used</span>`;
      }
    }

    return `
      <div class="stat-card" style="border-top: 3px solid ${c.color};">
        <div class="stat-header">
          <div style="display: flex; align-items: center; gap: 8px;">
            <div style="width: 12px; height: 12px; border-radius: 3px; background: ${c.color};"></div>
            <span style="font-weight: 700; font-size: 0.95rem; color: #0F172A;">${escapeHtml(c.category_name)}</span>
          </div>
          ${statusPill}
        </div>

        <div style="margin: 10px 0;">
          <div style="display: flex; justify-content: space-between; font-size: 0.82rem; color: var(--text-muted); margin-bottom: 4px;">
            <span>Spent: <strong>${formatCurrency(c.total_spent)}</strong></span>
            <span>Limit: <strong>${hasLimit ? formatCurrency(c.budget_limit) : "None"}</strong></span>
          </div>
          <div class="progress-bar-container" style="height: 6px;">
            <div class="progress-bar-fill ${c.status}" style="width: ${hasLimit ? Math.min(100, pct) : 0}%;"></div>
          </div>
        </div>

        <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
          <span style="font-size: 0.78rem; color: var(--text-muted);">
            ${hasLimit ? `Remaining: ${formatCurrency(c.remaining)}` : "No limit set"}
          </span>
          <button class="btn btn-secondary btn-sm" onclick="openBudgetModal(${c.category_id}, '${escapeHtml(c.category_name)}', ${c.budget_limit || 0})">
            ${hasLimit ? "Edit Limit" : "Set Limit"}
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function openOverallBudgetModal() {
  openBudgetModal(null, "Overall Monthly Budget", currentOverallLimit);
}

function openBudgetModal(categoryId, name, currentLimit) {
  document.getElementById("budgetCategoryId").value = categoryId === null ? "" : categoryId;
  document.getElementById("budgetModalTitle").textContent = `Set Budget – ${name}`;
  document.getElementById("budgetModalDesc").textContent = categoryId === null 
    ? "Set the total maximum expenditure allowance for the selected month." 
    : `Set the maximum monthly spending cap for ${name}.`;
  document.getElementById("budgetAmount").value = currentLimit > 0 ? currentLimit : "";

  openModal("budgetModal");
}

async function handleSaveBudget(e) {
  e.preventDefault();
  const btn = document.getElementById("budgetSaveBtn");
  btn.disabled = true;
  btn.textContent = "Saving...";

  const rawCatId = document.getElementById("budgetCategoryId").value;
  const categoryId = rawCatId === "" ? null : parseInt(rawCatId);
  const month = parseInt(document.getElementById("budgetMonthSelect").value);
  const year = parseInt(document.getElementById("budgetYearSelect").value);
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

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

document.addEventListener("DOMContentLoaded", () => {
  initBudgetControls();
  loadBudgets();
});

