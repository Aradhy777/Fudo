"""
ExpenseTrack - OCR Service & AI-900 Extraction Unit Tests
"""

import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.ocr_service import OCRService


def test_ocr_extraction_heuristics_upi():
    """Test regex heuristic parsing on typical UPI transaction screenshot text."""
    sample_upi_text = """
    Paid to Domino's Pizza
    Transaction ID: UPI/2026/09817263
    Amount: ₹ 450.00
    Date: 26-10-2026
    UPI Ref No: 9817263152
    Google Pay
    """
    res = OCRService.extract_financial_entities(sample_upi_text)
    assert res["extracted_amount"] == 450.00
    assert "Domino" in res["extracted_merchant"]
    assert res["extracted_date"] == "2026-10-26"
    assert res["extracted_payment_method"] == "UPI"


def test_ocr_extraction_heuristics_card():
    """Test regex heuristic parsing on card slip receipt text."""
    sample_card_text = """
    Bookstore Campus Center
    Total: Rs. 1,250.00
    Date: 12/10/2026
    Payment by Credit Card ending in 4112
    Thank you for your visit!
    """
    res = OCRService.extract_financial_entities(sample_card_text)
    assert res["extracted_amount"] == 1250.00
    assert "Bookstore" in res["extracted_merchant"]
    assert res["extracted_date"] == "2026-10-12"
    assert res["extracted_payment_method"] == "Credit Card"


def test_ocr_sha256_hash():
    """Test cryptographic SHA-256 calculation for duplicate receipt detection."""
    content = b"fake-receipt-image-content-for-testing"
    h1 = OCRService.calculate_file_hash(content)
    h2 = OCRService.calculate_file_hash(content)
    assert h1 == h2
    assert len(h1) == 64


def test_ocr_resilient_fallback_on_missing_file():
    """Test that nonexistent file returns failed status cleanly without crashing."""
    res = OCRService.process_receipt_image("nonexistent_path_test.png")
    assert res["ocr_status"] in ("fallback", "failed")
    assert res["extracted_amount"] is None

