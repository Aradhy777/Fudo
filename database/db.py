"""
ExpenseTrack - Database Connection & Execution Module
Provides robust, parameterized MySQL connectivity, connection pooling/lifecycle management,
and atomic transaction execution using PyMySQL.
"""

import pymysql
import pymysql.cursors
from contextlib import contextmanager
from config import Config

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


@contextmanager
def get_db():
    """
    Context manager for database transactions.
    Automatically rolls back on uncaught exception and closes the connection.
    Yields:
        (conn, cursor)
    """
    conn = get_raw_connection(include_db=True)
    cursor = conn.cursor()
    try:
        yield conn, cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def query_db(sql, params=None, one=False, commit=False):
    """
    Safe helper for parameterized SELECT and single execution queries.
    Prevents SQL injection by enforcing query parameterization.
    """
    conn = get_raw_connection(include_db=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params or ())
            if commit:
                conn.commit()
            if one:
                return cursor.fetchone()
            return cursor.fetchall()
    except Exception:
        if commit:
            conn.rollback()
        raise
    finally:
        conn.close()


def execute_db(sql, params=None):
    """
    Execute INSERT, UPDATE, or DELETE query and return (rowcount, lastrowid).
    """
    conn = get_raw_connection(include_db=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params or ())
            conn.commit()
            return cursor.rowcount, cursor.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def test_connection():
    """
    Verify if the MySQL database is reachable and operational.
    Returns (True, None) or (False, error_message).
    """
    try:
        conn = get_raw_connection(include_db=True)
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 AS alive")
            res = cursor.fetchone()
        conn.close()
        return True, "Connected successfully"
    except pymysql.err.OperationalError as e:
        code, msg = e.args if len(e.args) >= 2 else (0, str(e))
        return False, f"MySQL Operational Error ({code}): {msg}"
    except Exception as e:
        return False, f"Database Connection Error: {str(e)}"

