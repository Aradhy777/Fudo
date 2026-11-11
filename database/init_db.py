"""
ExpenseTrack - Database Initialization Script
Executes schema.sql and seed.sql to provision the expensetrack database, tables, and demo seed data.
Usage:
    python database/init_db.py
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path so config can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from database.db import get_raw_connection

def split_sql_statements(sql_content: str):
    """
    Split SQL script content into individual executable statements,
    ignoring comments and empty lines.
    """
    statements = []
    current_statement = []
    in_delimiter = False

    for line in sql_content.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("--") or trimmed.startswith("#"):
            continue

        current_statement.append(line)
        if trimmed.endswith(";"):
            statement = "\n".join(current_statement).strip()
            if statement:
                statements.append(statement)
            current_statement = []

    if current_statement:
        statement = "\n".join(current_statement).strip()
        if statement:
            statements.append(statement)

    return statements


def execute_sql_file(connection, file_path: Path):
    """Read and execute all statements in a SQL script file."""
    if not file_path.exists():
        raise FileNotFoundError(f"SQL file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    statements = split_sql_statements(content)
    with connection.cursor() as cursor:
        for stmt in statements:
            try:
                cursor.execute(stmt)
            except Exception as e:
                print(f"[-] Error executing statement: {stmt[:60]}... -> {e}")
                raise
    connection.commit()
    return len(statements)


def initialize_database():
    """Main initialization workflow."""
    print("=" * 60)
    print("ExpenseTrack - Database Initialization")
    print(f"Target Server: {Config.DB_HOST}:{Config.DB_PORT}")
    print(f"Target Database: {Config.DB_NAME}")
    print("=" * 60)

    # 1. Connect without database to ensure database creation
    try:
        conn = get_raw_connection(include_db=False)
        print("[+] Connected to MySQL server successfully.")
    except Exception as e:
        print(f"[!] FAILED to connect to MySQL server: {e}")
        sys.exit(1)

    try:
        # Create database if not exists
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{Config.DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            cursor.execute(f"USE `{Config.DB_NAME}`;")
        conn.commit()
        print(f"[+] Ensured database `{Config.DB_NAME}` exists.")

        # 2. Execute schema.sql
        schema_file = PROJECT_ROOT / "database" / "schema.sql"
        print(f"[*] Applying schema from: {schema_file.name}...")
        n_schema = execute_sql_file(conn, schema_file)
        print(f"[+] Schema created successfully ({n_schema} statements executed).")

        # 3. Execute seed.sql
        seed_file = PROJECT_ROOT / "database" / "seed.sql"
        print(f"[*] Seeding initial data from: {seed_file.name}...")
        n_seed = execute_sql_file(conn, seed_file)
        print(f"[+] Seed data inserted successfully ({n_seed} statements executed).")

        # 4. Verification Check
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total_users FROM users;")
            users_count = cursor.fetchone()["total_users"]
            cursor.execute("SELECT COUNT(*) AS total_categories FROM categories;")
            categories_count = cursor.fetchone()["total_categories"]
            cursor.execute("SELECT COUNT(*) AS total_expenses FROM expenses;")
            expenses_count = cursor.fetchone()["total_expenses"]
            cursor.execute("SELECT COUNT(*) AS total_budgets FROM budgets;")
            budgets_count = cursor.fetchone()["total_budgets"]

        print("-" * 60)
        print("[+] VERIFICATION SUMMARY:")
        print(f"    - Users:        {users_count} (demo user: 'demo_student')")
        print(f"    - Categories:   {categories_count}")
        print(f"    - Expenses:     {expenses_count}")
        print(f"    - Budgets:      {budgets_count}")
        print("=" * 60)
        print("[SUCCESS] Database initialization completed.")

    except Exception as e:
        print(f"[!] Initialization aborted with error: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    initialize_database()

