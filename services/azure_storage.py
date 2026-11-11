"""
ExpenseTrack - Azure Blob Storage Integration Module (DP-900 / Cloud Architecture)
Handles secure receipt uploads to Azure Blob Storage with seamless local fallback
when Azure credentials are not configured.
"""

import logging
import os
import uuid
from pathlib import Path
from config import Config

logger = logging.getLogger(__name__)

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    AZURE_SDK_AVAILABLE = True
except ImportError:
    AZURE_SDK_AVAILABLE = False


class AzureStorageService:
    @staticmethod
    def is_enabled() -> bool:
        """Return True only if Azure SDK is installed and credentials are configured."""
        return AZURE_SDK_AVAILABLE and Config.is_azure_configured()

    @classmethod
    def upload_receipt(cls, file_stream, original_filename: str, mime_type: str) -> dict:
        """
        Upload receipt image to Azure Blob Storage if configured;
        otherwise store locally in Config.UPLOAD_FOLDER.
        
        Returns:
            dict with:
                - storage_type: 'azure' | 'local'
                - file_name: saved unique file name
                - file_path: local or remote access path
                - azure_blob_url: remote url if uploaded to Azure, else None
        """
        extension = Path(original_filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{extension}"

        # 1. Try Azure Blob Storage if configured
        if cls.is_enabled():
            try:
                blob_service = BlobServiceClient.from_connection_string(Config.AZURE_STORAGE_CONNECTION_STRING)
                container_client = blob_service.get_container_client(Config.AZURE_STORAGE_CONTAINER_NAME)

                # Ensure container exists (private access level by default)
                if not container_client.exists():
                    container_client.create_container()

                blob_client = container_client.get_blob_client(unique_name)
                content_settings = ContentSettings(content_type=mime_type)
                
                file_stream.seek(0)
                blob_client.upload_blob(file_stream, overwrite=True, content_settings=content_settings)
                
                return {
                    "storage_type": "azure",
                    "file_name": unique_name,
                    "file_path": blob_client.url,
                    "azure_blob_url": blob_client.url,
                }
            except Exception:
                # Log Azure fallback safely without printing connection details
                logger.warning("Azure Blob upload unavailable; falling back to local receipt storage.")

        # 2. Local File System Storage (Fallback or default development mode)
        upload_dir = Path(Config.UPLOAD_FOLDER)
        upload_dir.mkdir(parents=True, exist_ok=True)
        local_dest = upload_dir / unique_name

        file_stream.seek(0)
        with open(local_dest, "wb") as f:
            f.write(file_stream.read())

        return {
            "storage_type": "local",
            "file_name": unique_name,
            "file_path": str(local_dest).replace("\\", "/"),
            "azure_blob_url": None,
        }

