"""
ExpenseTrack - Database Connection & Execution Module
Provides parameterized MySQL connectivity, safe resource cleanup on exceptions,
and atomic transaction execution using PyMySQL.
"""

import logging
import pymysql
import pymysql.cursors
from contextlib import contextmanager
from config import Config

logger = logging.getLogger(__name__)


def get_raw_connection(include_db=True):
    """
    Establish and return a direct PyMySQL connection.
    If include_db is False, connects to the server without selecting a specific database.
    """
    kwargs = {
        "host": Config.DB_HOST,
        "port": Config.DB_PORT,
        "user": Config.DB_USER,
        "password": Config.DB_PASSWORD,
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
        "connect_timeout": 5,
    }
    if include_db:
        kwargs["database"] = Config.DB_NAME

    return pymysql.connect(**kwargs)


def _safe_close(cursor, conn):
    """Guarantee cursor and socket connection closure without masking prior exceptions."""
    if cursor is not None:
        try:
            cursor.close()
        except Exception:
            pass
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def get_db():
    """
    Context manager for database transactions.
    Automatically rolls back on uncaught exception and safely closes cursor/connection.
    Yields:
        (conn, cursor)
    """
    conn = get_raw_connection(include_db=True)
    cursor = None
    try:
        cursor = conn.cursor()
        yield conn, cursor
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _safe_close(cursor, conn)


def query_db(sql, params=None, one=False, commit=False):
    """
    Safe helper for parameterized SELECT and single execution queries.
    Prevents SQL injection by enforcing query parameterization.
    """
    conn = get_raw_connection(include_db=True)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        if commit:
            conn.commit()
        if one:
            return cursor.fetchone()
        return cursor.fetchall()
    except Exception:
        if commit:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        _safe_close(cursor, conn)


def execute_db(sql, params=None):
    """
    Execute INSERT, UPDATE, or DELETE query and return (rowcount, lastrowid).
    """
    conn = get_raw_connection(include_db=True)
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()
        return cursor.rowcount, cursor.lastrowid
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _safe_close(cursor, conn)


def test_connection():
    """
    Verify if the MySQL database is reachable and operational.
    Returns (True, message) or (False, sanitized_message) while logging full details internally.
    """
    conn = None
    cursor = None
    try:
        conn = get_raw_connection(include_db=True)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 AS alive")
        cursor.fetchone()
        return True, "Connected successfully"
    except Exception as e:
        logger.error("Database connectivity check failed: %s", e)
        return False, "Database connection failed. Check server logs for details."
    finally:
        _safe_close(cursor, conn)
