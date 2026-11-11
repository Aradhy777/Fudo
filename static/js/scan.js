/**
 * ExpenseTrack - Smart Screenshot Scan & OCR Verification Controller
 */

let categoriesList = [];

async function loadScanCategories() {
  try {
    const res = await API.get("/api/expenses/categories");
    categoriesList = res.categories || [];
    const sel = document.getElementById("verifiedCategory");
    if (sel) {
      sel.innerHTML = '<option value="">Select Category...</option>' + 
        categoriesList.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
    }
  } catch (err) {
    console.error("Failed to load categories:", err);
  }
}

// Drag & Drop Listeners
const dropzone = document.getElementById("receiptDropzone");
if (dropzone) {
  ["dragenter", "dragover"].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach(name => {
    dropzone.addEventListener(name, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });

  dropzone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      processSelectedFile(files[0]);
    }
  });
}

function handleFileSelect(e) {
  if (e.target.files.length > 0) {
    processSelectedFile(e.target.files[0]);
  }
}

function processSelectedFile(file) {
  if (!file.type.match("image.*")) {
    showToast("Please upload a valid image file (PNG, JPG, WEBP).", "error");
    return;
  }

  // Preview Image
  const reader = new FileReader();
  reader.onload = (e) => {
    document.getElementById("receiptImagePreview").src = e.target.result;
    document.getElementById("receiptDropzone").style.display = "none";
    document.getElementById("previewContainer").style.display = "block";
  };
  reader.readAsDataURL(file);

  // Trigger Upload & OCR
  uploadAndScanReceipt(file);
}

async function uploadAndScanReceipt(file) {
  const indicator = document.getElementById("processingIndicator");
  const badge = document.getElementById("extractionStatusBadge");
  const duplicateAlert = document.getElementById("duplicateAlert");
  const confirmBtn = document.getElementById("confirmExpenseBtn");

  indicator.style.display = "block";
  badge.textContent = "Processing OCR...";
  badge.className = "badge warning";
  duplicateAlert.style.display = "none";
  document.getElementById("verifiedReceiptId").value = "";
  confirmBtn.disabled = true;

  const formData = new FormData();
  formData.append("receipt", file);

  try {
    const res = await API.post("/api/receipts/scan", formData);

    document.getElementById("verifiedReceiptId").value = res.receipt_id;

    // Check duplicate
    if (res.is_duplicate) {
      duplicateAlert.style.display = "block";
    }

    // Populate extracted fields
    const ocr = res.ocr || {};
    if (ocr.extracted_amount) {
      document.getElementById("verifiedAmount").value = ocr.extracted_amount;
    }
    if (ocr.extracted_date) {
      document.getElementById("verifiedDate").value = ocr.extracted_date;
    } else {
      document.getElementById("verifiedDate").value = new Date().toISOString().split("T")[0];
    }
    if (ocr.extracted_merchant && ocr.extracted_merchant !== "Unknown Merchant") {
      document.getElementById("verifiedMerchant").value = ocr.extracted_merchant;
      // Auto-suggest category based on merchant
      suggestCategory(ocr.extracted_merchant);
    }
    if (ocr.extracted_payment_method) {
      document.getElementById("verifiedPaymentMethod").value = ocr.extracted_payment_method;
    }

    // Raw text preview if present
    if (ocr.raw_text_preview) {
      document.getElementById("rawTextContainer").style.display = "block";
      document.getElementById("rawTextContent").textContent = ocr.raw_text_preview;
    } else {
      document.getElementById("rawTextContainer").style.display = "none";
    }

    if (ocr.status === "success") {
      badge.textContent = "Fields Extracted";
      badge.className = "badge normal";
      showToast("OCR complete! Please review the extracted fields below.", "success");
    } else if (ocr.status === "fallback") {
      badge.textContent = "Manual Verification";
      badge.className = "badge warning";
      showToast("Tesseract OCR in fallback mode. Please fill in the transaction details.", "info");
    } else {
      badge.textContent = "OCR Text Not Found";
      badge.className = "badge warning";
      showToast("No text detected. Please enter transaction details manually.", "warning");
    }

    confirmBtn.disabled = false;

  } catch (err) {
    showToast(err.message || "Failed to scan receipt.", "error");
    badge.textContent = "Scan Failed";
    badge.className = "badge exceeded";
    confirmBtn.disabled = true;
  } finally {
    indicator.style.display = "none";
  }
}

function suggestCategory(merchantName) {
  const m = merchantName.toLowerCase();
  let matchedCatName = null;

  if (m.includes("swiggy") || m.includes("zomato") || m.includes("canteen") || m.includes("pizza") || m.includes("subway") || m.includes("coffee") || m.includes("cafe")) {
    matchedCatName = "Food";
  } else if (m.includes("uber") || m.includes("ola") || m.includes("metro") || m.includes("bus") || m.includes("rail")) {
    matchedCatName = "Travel";
  } else if (m.includes("amazon") || m.includes("flipkart") || m.includes("decathlon") || m.includes("myntra")) {
    matchedCatName = "Shopping";
  } else if (m.includes("book") || m.includes("coursera") || m.includes("fee") || m.includes("library") || m.includes("udemy")) {
    matchedCatName = "Education";
  } else if (m.includes("cinema") || m.includes("movie") || m.includes("pvr") || m.includes("game")) {
    matchedCatName = "Entertainment";
  } else if (m.includes("jio") || m.includes("airtel") || m.includes("broadband") || m.includes("electricity") || m.includes("bill")) {
    matchedCatName = "Bills";
  } else if (m.includes("pharmacy") || m.includes("apollo") || m.includes("hospital") || m.includes("clinic")) {
    matchedCatName = "Healthcare";
  }

  if (matchedCatName) {
    const found = categoriesList.find(c => c.name.toLowerCase() === matchedCatName.toLowerCase());
    if (found) {
      document.getElementById("verifiedCategory").value = found.id;
    }
  }
}

function resetUpload() {
  document.getElementById("receiptFileInput").value = "";
  document.getElementById("receiptImagePreview").src = "";
  document.getElementById("previewContainer").style.display = "none";
  document.getElementById("receiptDropzone").style.display = "block";
  document.getElementById("verifyExpenseForm").reset();
  document.getElementById("verifiedReceiptId").value = "";
  document.getElementById("duplicateAlert").style.display = "none";
  document.getElementById("rawTextContainer").style.display = "none";
  document.getElementById("extractionStatusBadge").textContent = "Awaiting Upload";
  document.getElementById("extractionStatusBadge").className = "badge neutral";
  document.getElementById("confirmExpenseBtn").disabled = true;
  document.getElementById("verifiedDate").value = new Date().toISOString().split("T")[0];
}

async function handleConfirmExpense(e) {
  e.preventDefault();
  const btn = document.getElementById("confirmExpenseBtn");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "Saving Expense...";

  const receiptIdVal = document.getElementById("verifiedReceiptId").value;
  const payload = {
    amount: parseFloat(document.getElementById("verifiedAmount").value),
    expense_date: document.getElementById("verifiedDate").value,
    merchant: document.getElementById("verifiedMerchant").value.trim(),
    category_id: parseInt(document.getElementById("verifiedCategory").value),
    payment_method: document.getElementById("verifiedPaymentMethod").value,
    notes: document.getElementById("verifiedNotes").value.trim(),
    receipt_id: receiptIdVal ? parseInt(receiptIdVal) : null,
  };

  try {
    await API.post("/api/expenses", payload);
    showToast("Receipt verified and expense saved!", "success");
    setTimeout(() => {
      window.location.href = "/expenses";
    }, 600);
  } catch (err) {
    showToast(err.message || "Failed to confirm expense.", "error");
    btn.disabled = false;
    btn.textContent = "Confirm & Save Expense";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadScanCategories();
  document.getElementById("verifiedDate").value = new Date().toISOString().split("T")[0];
});

