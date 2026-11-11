/**
 * ExpenseTrack - Unified API Client & UI Utilities
 */

const API = {
  async fetch(url, options = {}) {
    const defaultHeaders = {
      "Accept": "application/json",
    };

    if (!(options.body instanceof FormData)) {
      defaultHeaders["Content-Type"] = "application/json";
    }

    const config = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...(options.headers || {}),
      },
    };

    try {
      const response = await fetch(url, config);
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        if (response.status === 401 && !url.includes("/api/auth/login")) {
          window.location.href = "/auth";
          return Promise.reject(new Error("Session expired. Please log in again."));
        }
        const errorMsg = data.message || data.error || `HTTP ${response.status} Error`;
        return Promise.reject(new Error(errorMsg));
      }

      return data;
    } catch (err) {
      console.error(`API Fetch Error [${url}]:`, err);
      throw err;
    }
  },

  get(url) {
    return this.fetch(url, { method: "GET" });
  },

  post(url, data) {
    return this.fetch(url, {
      method: "POST",
      body: data instanceof FormData ? data : JSON.stringify(data),
    });
  },

  put(url, data) {
    return this.fetch(url, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  delete(url) {
    return this.fetch(url, { method: "DELETE" });
  },
};

// UI Toast Notification Dispatcher
function showToast(message, type = "success") {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;

  const iconSvg = {
    success: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>`,
    error: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    warning: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    info: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3B82F6" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
  }[type] || "";

  toast.innerHTML = `
    ${iconSvg}
    <div class="toast-msg" style="flex: 1; font-size: 0.88rem; font-weight: 600; color: var(--text-main, #FFFFFF); line-height: 1.4;"></div>
    <button onclick="this.parentElement.remove()" style="background:none;border:none;color:var(--text-muted, #94A3B8);cursor:pointer;font-size:1.1rem;line-height:1;padding:0 4px;" aria-label="Close notification">&times;</button>
  `;
  toast.querySelector(".toast-msg").textContent = String(message || "");

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Modal Helpers with Accessibility (Escape key & Backdrop dismissal)
function openModal(id) {
  const el = document.getElementById(id);
  if (el) {
    el.classList.add("active");
    const firstInput = el.querySelector("input:not([type='hidden']), select, textarea");
    if (firstInput) {
      setTimeout(() => firstInput.focus(), 50);
    }
  }
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("active");
}

function toggleMobileSidebar() {
  const sb = document.getElementById("appSidebar");
  const ov = document.getElementById("sidebarOverlay");
  if (!sb) return;
  const opening = !sb.classList.contains("open");
  sb.classList.toggle("open", opening);
  if (ov) ov.classList.toggle("active", opening);
}

function closeMobileSidebar() {
  const sb = document.getElementById("appSidebar");
  const ov = document.getElementById("sidebarOverlay");
  if (sb) sb.classList.remove("open");
  if (ov) ov.classList.remove("active");
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal-backdrop.active").forEach(m => m.classList.remove("active"));
    closeMobileSidebar();
  }
});

document.addEventListener("click", (e) => {
  if (e.target.classList && e.target.classList.contains("modal-backdrop")) {
    e.target.classList.remove("active");
  }
});

// Format Currency
function formatCurrency(amount) {
  const val = Number(amount) || 0;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(val);
}

// Global Logout Handler
async function handleLogout() {
  try {
    await API.post("/api/auth/logout");
    showToast("Logged out successfully.", "info");
    setTimeout(() => {
      window.location.href = "/auth";
    }, 400);
  } catch (err) {
    window.location.href = "/auth";
  }
}

