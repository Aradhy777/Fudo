# ExpenseTrack – Azure Data Services Architecture (DP-900)

## 1. Executive Overview & DP-900 Alignment

The **Microsoft Certified: Azure Data Fundamentals (DP-900)** curriculum defines the core architectural principles for modern cloud data solutions across structured, semi-structured, and unstructured workloads.

**ExpenseTrack** is designed to map directly onto Azure's core cloud data pillars:

```mermaid
graph TD
    App["Flask Web Application Backend"]

    subgraph "Structured Relational Workload (DP-900)"
        AzureSQL["Azure SQL Database (PaaS) / Local MySQL"]
        Schema["Users, Expenses, Budgets, Categories Tables"]
    end

    subgraph "Unstructured Blob Workload (DP-900)"
        AzureBlob["Azure Blob Storage"]
        Container["Private 'receipts' Container (Hot Tier)"]
    end

    App -->|Tabular Data & Queries (ODBC/PyMySQL)| AzureSQL
    AzureSQL --> Schema
    App -->|Binary Receipts (azure-storage-blob SDK)| AzureBlob
    AzureBlob --> Container
```

---

## 2. Structured Relational Data: Azure SQL vs. Local MySQL

| Dimension | Local MySQL (Current Deployment) | Azure SQL Database (Production Cloud Target) |
|-----------|----------------------------------|----------------------------------------------|
| **Service Model** | IaaS / Local Host Process | PaaS (Fully Managed Platform as a Service) |
| **High Availability** | Single node; requires manual replication | 99.99% SLA with built-in active geo-replication |
| **Backup & Recovery** | Manual `mysqldump` backups | Automated continuous backups with Point-In-Time Restore (PITR) up to 35 days |
| **Scaling** | Vertical host scaling | Dynamic scale up/down with vCore or DTU purchasing models |
| **Security & Threat Detection** | Local file permissions & user table | Microsoft Entra ID (Azure AD), Always Encrypted, Advanced Threat Protection (ATP) |
| **Syntax Dialect** | MySQL 8.0+ Dialect (`AUTO_INCREMENT`) | Transact-SQL (T-SQL) (`IDENTITY(1,1)`) |

### Migration from MySQL to Azure SQL:
To migrate the local database to Azure SQL:
1. Export schema and data via Azure Database Migration Service (DMS) or generate T-SQL script (`IDENTITY(1,1)` replacing `AUTO_INCREMENT`).
2. Switch Python database connector from `pymysql` to `pyodbc` with connection string:
   `Server=tcp:expensetrack-server.database.windows.net,1433;Database=expensetrack;Uid={admin};Pwd={password};Encrypt=yes;TrustServerCertificate=no;`

---

## 3. Unstructured Data: Azure Blob Storage Architecture

Payment screenshots and receipt images represent unstructured binary data. Storing large binary blobs directly in relational database columns (`BLOB`) causes database bloat and degrades query cache efficiency.

### 3.1 Azure Blob Storage Design:
- **Storage Account Type:** General-purpose v2 (standard tier).
- **Container Name:** `receipts`
- **Access Level:** **Private (no anonymous access)**. Public anonymous read access is disabled at both the storage account and container levels.
- **Access Tiers:**
  * **Hot Tier:** For current billing cycle receipts (frequently accessed for verification).
  * **Cool Tier:** Lifecycle management rule transitions receipts older than 60 days to reduce cost.

### 3.2 Python Azure Storage SDK Integration:
In `services/azure_storage.py`, ExpenseTrack uses the official `azure-storage-blob` SDK:
```python
from azure.storage.blob import BlobServiceClient, ContentSettings

blob_service = BlobServiceClient.from_connection_string(Config.AZURE_STORAGE_CONNECTION_STRING)
container_client = blob_service.get_container_client(Config.AZURE_STORAGE_CONTAINER_NAME)
blob_client = container_client.get_blob_client(unique_file_name)
blob_client.upload_blob(file_stream, content_settings=ContentSettings(content_type=mime_type))
```

### 3.3 Transparent Fallback & Production Deployment:
- **When `AZURE_STORAGE_CONNECTION_STRING` is set in `.env`:** The application automatically uploads receipts directly to Azure Blob Storage and stores the secure remote blob URL in the `uploaded_receipts.azure_blob_url` column.
- **When unconfigured (Default Local Mode):** The application safely routes files to `uploads/receipts/` on local disk and serves them through authenticated Flask route `/uploads/receipts/<filename>`.
- **Integrity Guarantee:** In accordance with academic transparency standards, the `/profile` diagnostic view explicitly states whether Azure Blob Storage is active or in local fallback mode.

