"""
ExpenseTrack - Receipt Scanning & OCR Routes
Handles file validation, duplicate prevention via SHA-256 hash, Azure/Local storage,
and Tesseract OCR parsing with review workflows.
"""

import io
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from flask import Blueprint, request, jsonify, render_template, send_from_directory, abort, current_app, session
from werkzeug.utils import secure_filename
from config import Config
from repositories.base import UserAccountNotFoundError
from repositories.receipt_repo import ReceiptRepository
from routes.auth_helper import login_required, get_current_user_id
from services.azure_storage import AzureStorageService
from services.ocr_service import OCRService

receipts_bp = Blueprint("receipts", __name__)

ALLOWED_IMAGE_FORMATS = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}
MAX_IMAGE_PIXELS = 25_000_000


def allowed_file(filename: str) -> bool:
    return bool(filename) and "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


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
    if not file or not file.filename:
        return jsonify({"error": "Validation Error", "message": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({
            "error": "Validation Error",
            "message": f"Invalid file format. Allowed formats: {', '.join(sorted(Config.ALLOWED_EXTENSIONS))}",
        }), 400

    # Read bytes and verify size
    file_bytes = file.read()
    file_size = len(file_bytes)
    if file_size == 0:
        return jsonify({"error": "Validation Error", "message": "Uploaded file is empty."}), 400

    if file_size > Config.MAX_CONTENT_LENGTH:
        return jsonify({"error": "Validation Error", "message": "File size exceeds the 5MB limit."}), 400

    # Strict Image Binary, Format & Resolution Verification
    try:
        with Image.open(io.BytesIO(file_bytes)) as img_probe:
            img_format = (img_probe.format or "").upper()
            width, height = img_probe.size
            img_probe.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, Exception):
        return jsonify({"error": "Validation Error", "message": "Corrupted or invalid image file content."}), 400

    if img_format not in ALLOWED_IMAGE_FORMATS:
        return jsonify({
            "error": "Validation Error",
            "message": f"Unsupported binary image format ({img_format or 'unknown'}). Allowed: PNG, JPEG, WEBP.",
        }), 400

    if width <= 0 or height <= 0 or (width * height) > MAX_IMAGE_PIXELS:
        return jsonify({"error": "Validation Error", "message": "Image resolution is invalid or exceeds safe processing limits."}), 400

    canonical_ext, safe_mime_type = ALLOWED_IMAGE_FORMATS[img_format]
    safe_base = secure_filename(Path(file.filename).stem) or "receipt"
    canonical_name = f"{safe_base}.{canonical_ext}"

    # Calculate SHA-256 for duplicate detection
    file_hash = OCRService.calculate_file_hash(file_bytes)

    # Store file via Azure Blob or Local using verified canonical extension & MIME type
    file.seek(0)
    storage_res = AzureStorageService.upload_receipt(file, canonical_name, safe_mime_type)
    stored_path = storage_res["file_path"]

    # Perform OCR Extraction outside DB lock
    ocr_result = OCRService.process_receipt_image(stored_path, file_bytes)

    # Atomic duplicate check + metadata insert serialized per user
    try:
        save_res = ReceiptRepository().record_receipt_with_dedup_check(
            user_id=user_id,
            file_name=storage_res["file_name"],
            file_path=stored_path,
            file_size=file_size,
            mime_type=safe_mime_type,
            azure_blob_url=storage_res["azure_blob_url"],
            ocr_raw_text=ocr_result.get("raw_text"),
            ocr_status=ocr_result["ocr_status"],
            extracted_amount=ocr_result.get("extracted_amount"),
            extracted_merchant=ocr_result.get("extracted_merchant"),
            extracted_date=ocr_result.get("extracted_date"),
            extracted_payment_method=ocr_result.get("extracted_payment_method"),
            file_hash=file_hash,
        )
        receipt_id = save_res["receipt_id"]
        is_duplicate = save_res["is_duplicate"]
        dup_created_at = save_res["duplicate_created_at"]

        return jsonify({
            "message": "Receipt uploaded and scanned successfully.",
            "receipt_id": receipt_id,
            "file_name": storage_res["file_name"],
            "storage_type": storage_res["storage_type"],
            "azure_blob_url": storage_res["azure_blob_url"],
            "is_duplicate": is_duplicate,
            "duplicate_info": f"Receipt was already uploaded on {dup_created_at.strftime('%Y-%m-%d')}" if is_duplicate and dup_created_at else None,
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

    except UserAccountNotFoundError:
        session.clear()
        if storage_res["storage_type"] == "local":
            Path(stored_path).unlink(missing_ok=True)
        return jsonify({"error": "Unauthorized", "message": "Account session is no longer valid."}), 401
    except Exception as e:
        if storage_res["storage_type"] == "local":
            Path(stored_path).unlink(missing_ok=True)
        current_app.logger.error(f"DB error recording receipt for user {user_id}: {e}")
        return jsonify({"error": "Database Error", "message": "An error occurred while saving receipt metadata."}), 500


@receipts_bp.route("/uploads/receipts/<filename>")
@login_required
def serve_receipt(filename: str):
    """
    Safely serve local receipt files only to authorized users.
    Ensures users cannot access receipts uploaded by other users.
    """
    user_id = get_current_user_id()
    safe_name = secure_filename(filename)
    if not safe_name:
        abort(403)
    rec = ReceiptRepository().get_receipt_by_filename(user_id, safe_name)
    if not rec:
        abort(403)

    upload_dir = Path(Config.UPLOAD_FOLDER).resolve()
    return send_from_directory(upload_dir, safe_name)
