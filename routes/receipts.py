"""
ExpenseTrack - Receipt Scanning & OCR Routes
Handles file validation, duplicate prevention via SHA-256 hash, Azure/Local storage,
and Tesseract OCR parsing with review workflows.
"""

import os
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_from_directory, abort
from werkzeug.utils import secure_filename
from config import Config
from database.db import query_db, execute_db
from routes.auth_helper import login_required, get_current_user_id
from services.azure_storage import AzureStorageService
from services.ocr_service import OCRService

receipts_bp = Blueprint("receipts", __name__)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


@receipts_bp.route("/scan")
@login_required
def scan_page():
    return render_template("scan.html", tesseract_ready=OCRService.is_tesseract_available())


@receipts_bp.route("/api/receipts/scan", methods=["POST"])
@login_required
def scan_receipt():
    user_id = get_current_user_id()

    if "receipt" not in request.files:
        return jsonify({"error": "Validation Error", "message": "No receipt file uploaded."}), 400

    file = request.files["receipt"]
    if file.filename == "":
        return jsonify({"error": "Validation Error", "message": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({
            "error": "Validation Error",
            "message": f"Invalid file format. Allowed formats: {', '.join(Config.ALLOWED_EXTENSIONS)}",
        }), 400

    # Read bytes and check size
    file_bytes = file.read()
    file_size = len(file_bytes)
    if file_size > Config.MAX_CONTENT_LENGTH:
        return jsonify({"error": "Validation Error", "message": "File size exceeds the 5MB limit."}), 400

    # Calculate SHA-256 for duplicate detection
    file_hash = OCRService.calculate_file_hash(file_bytes)

    # Check for duplicate submission by this user
    duplicate_row = query_db(
        """
        SELECT id, file_name, created_at
        FROM uploaded_receipts
        WHERE user_id = %s AND file_hash = %s;
        """,
        (user_id, file_hash),
        one=True,
    )
    is_duplicate = duplicate_row is not None

    # Reset pointer for storage upload
    file.seek(0)
    safe_orig_name = secure_filename(file.filename)
    mime_type = file.content_type or "image/jpeg"

    # Store file via Azure Blob or Local
    storage_res = AzureStorageService.upload_receipt(file, safe_orig_name, mime_type)
    stored_path = storage_res["file_path"]

    # Perform OCR Extraction
    ocr_result = OCRService.process_receipt_image(stored_path, file_bytes)

    # Save to uploaded_receipts table
    try:
        _, receipt_id = execute_db(
            """
            INSERT INTO uploaded_receipts (
                user_id, file_name, file_path, file_size, mime_type,
                azure_blob_url, ocr_raw_text, ocr_status,
                extracted_amount, extracted_merchant, extracted_date,
                extracted_payment_method, file_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                user_id,
                storage_res["file_name"],
                stored_path,
                file_size,
                mime_type,
                storage_res["azure_blob_url"],
                ocr_result.get("raw_text"),
                ocr_result["ocr_status"],
                ocr_result.get("extracted_amount"),
                ocr_result.get("extracted_merchant"),
                ocr_result.get("extracted_date"),
                ocr_result.get("extracted_payment_method"),
                file_hash,
            ),
        )

        return jsonify({
            "message": "Receipt uploaded and scanned successfully.",
            "receipt_id": receipt_id,
            "file_name": storage_res["file_name"],
            "storage_type": storage_res["storage_type"],
            "azure_blob_url": storage_res["azure_blob_url"],
            "is_duplicate": is_duplicate,
            "duplicate_info": f"Receipt was already uploaded on {duplicate_row['created_at'].strftime('%Y-%m-%d')}" if is_duplicate else None,
            "ocr": {
                "status": ocr_result["ocr_status"],
                "message": ocr_result["message"],
                "extracted_amount": ocr_result.get("extracted_amount"),
                "extracted_merchant": ocr_result.get("extracted_merchant"),
                "extracted_date": ocr_result.get("extracted_date"),
                "extracted_payment_method": ocr_result.get("extracted_payment_method"),
                "raw_text_preview": (ocr_result.get("raw_text")[:300] + "...") if ocr_result.get("raw_text") else None,
            }
        }), 201

    except Exception as e:
        return jsonify({"error": "Database Error", "message": f"Failed to record receipt metadata: {str(e)}"}), 500


@receipts_bp.route("/uploads/receipts/<filename>")
@login_required
def serve_receipt(filename: str):
    """
    Safely serve local receipt files only to authorized users.
    Ensures users cannot access receipts uploaded by other users.
    """
    user_id = get_current_user_id()
    # Check if receipt belongs to current user
    rec = query_db(
        "SELECT id FROM uploaded_receipts WHERE user_id = %s AND file_name = %s;",
        (user_id, secure_filename(filename)),
        one=True,
    )
    if not rec:
        abort(403)

    upload_dir = Path(Config.UPLOAD_FOLDER).resolve()
    return send_from_directory(upload_dir, secure_filename(filename))

