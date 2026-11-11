"""
ExpenseTrack - Smart Receipt OCR & Information Extraction Service (AI-900 / Computer Vision)
Performs OCR via Tesseract when available, with resilient graceful fallback.
Parses merchant name, transaction amount, date, and payment method via deterministic heuristics.
"""

import re
import os
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from PIL import Image

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

from config import Config


class OCRService:
    @classmethod
    def find_tesseract_binary(cls) -> str | None:
        """Locate Tesseract binary from config, PATH, or standard Windows directories."""
        if Config.TESSERACT_CMD and Path(Config.TESSERACT_CMD).exists():
            return Config.TESSERACT_CMD

        # Check system PATH
        path_binary = shutil.which("tesseract")
        if path_binary:
            return path_binary

        # Common Windows installation directories
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for p in common_paths:
            if os.path.exists(p):
                return p

        return None

    @classmethod
    def is_tesseract_available(cls) -> bool:
        """Check if pytesseract and the underlying binary are both ready."""
        if not PYTESSERACT_AVAILABLE:
            return False
        return cls.find_tesseract_binary() is not None

    @staticmethod
    def calculate_file_hash(file_bytes: bytes) -> str:
        """Compute SHA-256 hash of file content for duplicate receipt detection."""
        return hashlib.sha256(file_bytes).hexdigest()

    @classmethod
    def process_receipt_image(cls, file_path: str, file_bytes: bytes = None) -> dict:
        """
        Process an image file to extract raw text and structured financial entities.
        
        Returns:
            dict containing:
                - ocr_status: 'success' | 'fallback' | 'failed'
                - raw_text: string | None
                - extracted_amount: float | None
                - extracted_merchant: string | None
                - extracted_date: string (YYYY-MM-DD) | None
                - extracted_payment_method: string | None
                - message: human-readable explanation of status
        """
        binary_path = cls.find_tesseract_binary()

        # If Tesseract engine is unavailable on the host machine:
        if not PYTESSERACT_AVAILABLE or not binary_path:
            return {
                "ocr_status": "fallback",
                "raw_text": None,
                "extracted_amount": None,
                "extracted_merchant": None,
                "extracted_date": None,
                "extracted_payment_method": None,
                "message": (
                    "Tesseract OCR engine is not installed on the system PATH. "
                    "The receipt image was saved securely; please verify or enter the details manually below."
                ),
            }

        try:
            pytesseract.pytesseract.tesseract_cmd = binary_path
            image = Image.open(file_path)

            # Convert to grayscale for better contrast / OCR accuracy
            image = image.convert("L")
            raw_text = pytesseract.image_to_string(image)

            if not raw_text or not raw_text.strip():
                return {
                    "ocr_status": "failed",
                    "raw_text": "",
                    "extracted_amount": None,
                    "extracted_merchant": None,
                    "extracted_date": None,
                    "extracted_payment_method": None,
                    "message": "OCR ran successfully, but no readable text was detected on the screenshot.",
                }

            # Parse extracted fields
            extracted = cls.extract_financial_entities(raw_text)
            extracted["ocr_status"] = "success"
            extracted["raw_text"] = raw_text.strip()
            extracted["message"] = "Text and financial fields extracted successfully. Please review and confirm."
            return extracted

        except Exception:
            return {
                "ocr_status": "failed",
                "raw_text": None,
                "extracted_amount": None,
                "extracted_merchant": None,
                "extracted_date": None,
                "extracted_payment_method": None,
                "message": "OCR engine could not read this screenshot; please enter or verify the details manually.",
            }

    @classmethod
    def extract_financial_entities(cls, text: str) -> dict:
        """
        Extract transaction amount, date, merchant, and payment method from OCR text
        using rule-based regex and contextual pattern recognition.
        """
        # 1. Amount Extraction
        amount = None
        # Prioritize explicit total/paid labels over generic line-item currency markers
        amount_patterns = [
            r"(?:grand\s+total|total\s+paid|amount\s+paid|net\s+payable|total|paid|amt|amount)\s*[:\-\s]?\s*(?:₹|rs\.?|inr)?\s*((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?)",
            r"(?:₹|rs\.?|inr)\s*[:\-\s]?\s*((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?)",
            r"(?:credited|debited)\s+(?:by|for)?\s*(?:₹|rs\.?|inr)?\s*((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?)",
            r"\b([0-9]+(?:\.[0-9]{2}))\b",
        ]
        for pattern in amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Clean comma and convert to float
                for m in matches:
                    try:
                        clean_val = float(m.replace(",", ""))
                        if 0 < clean_val < 500000:  # Reasonable transaction range
                            amount = round(clean_val, 2)
                            break
                    except ValueError:
                        continue
                if amount:
                    break

        # 2. Date Extraction
        extracted_date = None
        date_patterns = [
            # DD/MM/YYYY or DD-MM-YYYY
            (r"\b([0-3]?[0-9])[/\-\.]([0-1]?[0-9])[/\-\.](20[2-3][0-9])\b", "%d-%m-%Y"),
            # YYYY-MM-DD
            (r"\b(20[2-3][0-9])[/\-\.]([0-1]?[0-9])[/\-\.]([0-3]?[0-9])\b", "%Y-%m-%d"),
            # DD Mon YYYY (e.g., 24 Oct 2026)
            (r"\b([0-3]?[0-9])\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20[2-3][0-9])\b", "%d %b %Y"),
        ]
        for pattern, date_fmt in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    date_str = match.group(0).replace("/", "-").replace(".", "-")
                    dt = datetime.strptime(date_str, date_fmt)
                    extracted_date = dt.strftime("%Y-%m-%d")
                    break
                except Exception:
                    continue

        # Leave date None when no valid date appears in OCR text (never fabricate today's date)

        # 3. Merchant Extraction
        merchant = None
        # Common payment patterns: "Paid to <Name>", "To: <Name>", "Merchant: <Name>"
        merchant_match = re.search(
            r"\b(?:paid to|sent to|transferred to|to|merchant)\b\s*[:\-\s]?\s*([A-Za-z0-9\s&'\.]{3,40})",
            text,
            re.IGNORECASE
        )
        if merchant_match:
            candidate = merchant_match.group(1).split("\n")[0].strip()
            # Clean unwanted tokens
            candidate = re.sub(r"(?:upi id|vpa|ref no|transaction id|phonepe|google pay).*", "", candidate, flags=re.IGNORECASE).strip()
            if len(candidate) >= 3:
                merchant = candidate[:50]

        # Match recognizable merchant tokens ONLY when actually present in OCR text
        known_merchants = [
            "Swiggy", "Zomato", "Amazon", "Flipkart", "Uber", "Ola",
            "Starbucks", "Cafe Coffee Day", "Subway", "Domino's", "McDonald's",
            "Campus Canteen", "Bookstore", "Decathlon", "Jio", "Airtel", "Apollo Pharmacy"
        ]
        if not merchant:
            for km in known_merchants:
                if re.search(r"\b" + re.escape(km) + r"\b", text, re.IGNORECASE):
                    merchant = km
                    break

        # 4. Payment Method Detection (None unless text indicates a payment mode)
        payment_method = None
        text_lower = text.lower()
        if any(k in text_lower for k in ["upi", "gpay", "google pay", "phonepe", "paytm", "bhim", "vpa"]):
            payment_method = "UPI"
        elif any(k in text_lower for k in ["credit card", "mastercard", "visa card"]):
            payment_method = "Credit Card"
        elif any(k in text_lower for k in ["debit card", "rupay", "atm"]):
            payment_method = "Debit Card"
        elif any(k in text_lower for k in ["net banking", "neft", "rtgs", "imps"]):
            payment_method = "Net Banking"
        elif "cash" in text_lower:
            payment_method = "Cash"

        return {
            "extracted_amount": amount,
            "extracted_merchant": merchant,
            "extracted_date": extracted_date,
            "extracted_payment_method": payment_method,
        }
