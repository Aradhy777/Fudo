/**
 * ExpenseTrack - Expenses Management & Data Table Controller
 */

let currentPage = 1;
let totalPages = 1;
let categoriesList = [];

async function loadCategories() {
  try {
    const res = await API.get("/api/expenses/categories");
    categoriesList = res.categories || [];

    const filterSel = document.getElementById("filterCategory");
    const editSel = document.getElementById("editCategory");

    if (filterSel) {
      filterSel.innerHTML = '<option value="">All Categories</option>' + 
        categoriesList.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
    }
    if (editSel) {
      editSel.innerHTML = '<option value="">Select Category...</option>' + 
        categoriesList.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
    }
  } catch (err) {
    console.error("Failed to load categories:", err);
  }
}

async function fetchExpenses(page = 1) {
  currentPage = page;
  const tbody = document.getElementById("expensesTableBody");
  const emptyState = document.getElementById("expensesEmptyState");
  const table = document.getElementById("expensesTable");
  const paginationBar = document.getElementById("paginationBar");

  const search = document.getElementById("filterSearch").value.trim();
  const categoryId = document.getElementById("filterCategory").value;
  const startDate = document.getElementById("filterStartDate").value;
  const endDate = document.getElementById("filterEndDate").value;

  const params = new URLSearchParams({
    page: currentPage,
    limit: 15,
  });
  if (search) params.append("search", search);
  if (categoryId) params.append("category_id", categoryId);
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);

  try {
    const res = await API.get(`/api/expenses?${params.toString()}`);
    const expenses = res.expenses || [];
    const pagination = res.pagination || { total_records: 0, total_pages: 1 };
    totalPages = pagination.total_pages;

    document.getElementById("tableRecordSummary").textContent = 
      `Showing ${expenses.length} of ${pagination.total_records} recorded expenses`;

    if (expenses.length === 0) {
      table.style.display = "none";
      emptyState.style.display = "block";
      paginationBar.style.display = "none";
      return;
    }

    table.style.display = "table";
    emptyState.style.display = "none";
    paginationBar.style.display = "flex";

    tbody.innerHTML = expenses.map(e => `
      <tr>
        <td style="color: #64748B; font-size: 0.84rem; white-space: nowrap;">${e.expense_date}</td>
        <td style="font-weight: 600; color: #1E293B;">${escapeHtml(e.merchant)}</td>
        <td>
          <span class="category-pill" style="background: ${e.category.color}18; color: ${e.category.color};">
            ${escapeHtml(e.category.name)}
          </span>
        </td>
        <td>
          <span class="badge" style="background: #F1F5F9; color: #475569;">${escapeHtml(e.payment_method)}</span>
        </td>
        <td style="color: #64748B; font-size: 0.84rem;">${escapeHtml(e.notes || "-")}</td>
        <td>
          ${e.receipt ? `
            <a href="${e.receipt.azure_blob_url || ('/uploads/receipts/' + e.receipt.file_name)}" target="_blank" 
               class="badge normal" title="View attached receipt image" style="text-decoration:none;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
                <circle cx="12" cy="13" r="3"/>
              </svg>
              Receipt
            </a>
          ` : `<span style="color:#CBD5E1; font-size:0.8rem;">None</span>`}
        </td>
        <td style="text-align: right; font-weight: 700; color: #0F172A; font-variant-numeric: tabular-nums;">
          ${formatCurrency(e.amount)}
        </td>
        <td style="text-align: center;">
          <button class="btn-icon" title="Edit" onclick="openEditModal(${e.id})">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
            </svg>
          </button>
          <button class="btn-icon danger" title="Delete" onclick="deleteExpenseItem(${e.id})">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
            </svg>
          </button>
        </td>
      </tr>
    `).join("");

    // Update Pagination UI
    document.getElementById("paginationInfo").textContent = `Page ${currentPage} of ${totalPages}`;
    document.getElementById("btnPrevPage").disabled = (currentPage <= 1);
    document.getElementById("btnNextPage").disabled = (currentPage >= totalPages);

  } catch (err) {
    showToast(err.message || "Failed to fetch expenses.", "error");
  }
}

function handleFilterSubmit(e) {
  e.preventDefault();
  fetchExpenses(1);
}

function resetFilters() {
  document.getElementById("filterForm").reset();
  fetchExpenses(1);
}

function changePage(delta) {
  const newPage = currentPage + delta;
  if (newPage >= 1 && newPage <= totalPages) {
    fetchExpenses(newPage);
  }
}

async function openEditModal(expenseId) {
  try {
    const res = await API.get(`/api/expenses/${expenseId}`);
    const exp = res.expense;

    document.getElementById("editExpenseId").value = exp.id;
    document.getElementById("editAmount").value = exp.amount;
    document.getElementById("editDate").value = exp.expense_date;
    document.getElementById("editMerchant").value = exp.merchant;
    document.getElementById("editCategory").value = exp.category_id;
    document.getElementById("editPaymentMethod").value = exp.payment_method;
    document.getElementById("editNotes").value = exp.notes || "";

    openModal("editExpenseModal");
  } catch (err) {
    showToast("Failed to load expense details: " + err.message, "error");
  }
}

async function handleUpdateExpense(e) {
  e.preventDefault();
  const id = document.getElementById("editExpenseId").value;
  const btn = document.getElementById("editSaveBtn");
  btn.disabled = true;
  btn.textContent = "Saving...";

  const payload = {
    amount: parseFloat(document.getElementById("editAmount").value),
    expense_date: document.getElementById("editDate").value,
    merchant: document.getElementById("editMerchant").value.trim(),
    category_id: parseInt(document.getElementById("editCategory").value),
    payment_method: document.getElementById("editPaymentMethod").value,
    notes: document.getElementById("editNotes").value.trim(),
  };

  try {
    await API.put(`/api/expenses/${id}`, payload);
    showToast("Expense updated successfully!", "success");
    closeModal("editExpenseModal");
    fetchExpenses(currentPage);
  } catch (err) {
    showToast(err.message || "Update failed.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Changes";
  }
}

async function deleteExpenseItem(id) {
  if (!confirm("Are you sure you want to permanently delete this expense record?")) {
    return;
  }
  try {
    await API.delete(`/api/expenses/${id}`);
    showToast("Expense deleted successfully.", "success");
    fetchExpenses(currentPage);
  } catch (err) {
    showToast(err.message || "Failed to delete expense.", "error");
  }
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Refresh hook for modal additions
window.onExpenseCreated = () => fetchExpenses(1);

document.addEventListener("DOMContentLoaded", async () => {
  await loadCategories();
  fetchExpenses(1);
});

