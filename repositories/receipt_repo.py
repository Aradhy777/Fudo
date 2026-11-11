"""
ExpenseTrack - Receipt Repository

Manages transactional receipt metadata persistence, per-user deduplication
with pessimistic locking, ownership lookup, and cross-dialect transactional
receipt deletion (preserving linked Expense rows).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select

from database.models import UploadedReceipt, delete_receipt_transactional
from database.session import lock_user_row, run_with_deadlock_retry
from repositories.base import BaseRepository, UserAccountNotFoundError


def _parse_optional_date(val: Any) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val))
    except ValueError:
        return None


def _parse_optional_decimal(val: Any) -> Optional[Decimal]:
    if val is None or val == "":
        return None
    return Decimal(str(val))


class ReceiptRepository(BaseRepository):
    """Repository for uploaded receipt persistence and safe deletion."""

    def record_receipt_with_dedup_check(
        self,
        *,
        user_id: int,
        file_name: str,
        file_path: str,
        file_size: int,
        mime_type: str,
        azure_blob_url: Optional[str],
        ocr_raw_text: Optional[str],
        ocr_status: str,
        extracted_amount: Any,
        extracted_merchant: Optional[str],
        extracted_date: Any,
        extracted_payment_method: Optional[str],
        file_hash: Optional[str],
    ) -> dict[str, Any]:
        """
        Acquire a tenant user lock, check for an earlier receipt with the same
        ``file_hash`` for the same user, and record the newly uploaded receipt
        metadata atomically.
        """
        parsed_amount = _parse_optional_decimal(extracted_amount)
        parsed_date = _parse_optional_date(extracted_date)

        def _op() -> dict[str, Any]:
            with self._session() as session:
                if not lock_user_row(session, user_id):
                    raise UserAccountNotFoundError(
                        "Account session is no longer valid."
                    )

                duplicate_row = None
                if file_hash:
                    duplicate_row = session.execute(
                        select(
                            UploadedReceipt.id,
                            UploadedReceipt.file_name,
                            UploadedReceipt.created_at,
                        )
                        .where(
                            UploadedReceipt.user_id == user_id,
                            UploadedReceipt.file_hash == file_hash,
                        )
                        .order_by(UploadedReceipt.id.asc())
                        .limit(1)
                    ).first()

                receipt = UploadedReceipt(
                    user_id=user_id,
                    file_name=file_name,
                    file_path=file_path,
                    file_size=file_size,
                    mime_type=mime_type,
                    azure_blob_url=azure_blob_url,
                    ocr_raw_text=ocr_raw_text,
                    ocr_status=ocr_status,
                    extracted_amount=parsed_amount,
                    extracted_merchant=extracted_merchant,
                    extracted_date=parsed_date,
                    extracted_payment_method=extracted_payment_method,
                    file_hash=file_hash,
                )
                session.add(receipt)
                session.flush()
                return {
                    "receipt_id": int(receipt.id),
                    "is_duplicate": duplicate_row is not None,
                    "duplicate_created_at": (
                        duplicate_row.created_at if duplicate_row else None
                    ),
                }

        return run_with_deadlock_retry(_op, max_attempts=3)

    def get_receipt_by_filename(
        self, user_id: int, file_name: str
    ) -> Optional[dict[str, Any]]:
        """Verify receipt ownership by filename for authenticated file serving."""
        with self._session() as session:
            row = session.execute(
                select(
                    UploadedReceipt.id,
                    UploadedReceipt.file_name,
                    UploadedReceipt.file_path,
                    UploadedReceipt.mime_type,
                ).where(
                    UploadedReceipt.user_id == user_id,
                    UploadedReceipt.file_name == file_name,
                )
            ).first()
            if row is None:
                return None
            return {
                "id": row.id,
                "file_name": row.file_name,
                "file_path": row.file_path,
                "mime_type": row.mime_type,
            }

    def delete_receipt(self, receipt_id: int, user_id: int) -> Optional[str]:
        """
        Transactionally unlink expenses and delete the receipt record across
        MariaDB and SQL Server (using ``delete_receipt_transactional``).
        """
        with self._session() as session:
            return delete_receipt_transactional(session, receipt_id, user_id)
