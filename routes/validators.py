"""
ExpenseTrack - Input Validation, Sanitation, Decimal Financial Math & Security Helpers
Centralized validators for financial amounts, dates, string bounds, JSON bodies,
sargable calendar ranges, and sliding-window IP rate limiting.
"""

import time
from calendar import monthrange
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from collections import defaultdict
from flask import request, jsonify, current_app

# Rate Limiter: In-memory sliding window tracker keyed by client remote_addr
_RATE_LIMIT_BUCKETS = defaultdict(list)

ZERO_DEC = Decimal("0.00")
CENT_QUANT = Decimal("0.01")
TENTH_QUANT = Decimal("0.1")
HUNDRED_DEC = Decimal("100")


def rate_limit(max_requests=10, window_seconds=60):
    """
    Decorator for sliding-window rate limiting by client remote address.
    Ignores untrusted X-Forwarded-For spoofing unless TRUST_PROXY_HEADERS is enabled.
    """
    def decorator(f):
        def wrapper(*args, **kwargs):
            if current_app.config.get("TESTING") and not current_app.config.get("ENABLE_RATE_LIMIT_IN_TESTS"):
                return f(*args, **kwargs)

            if current_app.config.get("TRUST_PROXY_HEADERS"):
                ip = (request.headers.get("X-Forwarded-For", request.remote_addr) or "127.0.0.1").split(",")[0].strip()
            else:
                ip = request.remote_addr or "127.0.0.1"

            key = f"{f.__name__}:{ip}"
            now = time.time()
            cutoff = now - window_seconds

            bucket = [t for t in _RATE_LIMIT_BUCKETS.get(key, []) if t > cutoff]
            if len(bucket) >= max_requests:
                _RATE_LIMIT_BUCKETS[key] = bucket
                retry_after = int(window_seconds - (now - bucket[0]))
                return jsonify({
                    "error": "Too Many Requests",
                    "message": f"Rate limit exceeded. Please try again in {max(1, retry_after)} seconds."
                }), 429

            bucket.append(now)
            _RATE_LIMIT_BUCKETS[key] = bucket

            if len(_RATE_LIMIT_BUCKETS) > 1024:
                stale_keys = [k for k, ts in _RATE_LIMIT_BUCKETS.items() if not ts or ts[-1] <= cutoff]
                for sk in stale_keys:
                    _RATE_LIMIT_BUCKETS.pop(sk, None)

            return f(*args, **kwargs)

        wrapper.__name__ = f.__name__
        return wrapper
    return decorator


def get_json_dict(allow_empty=False):
    """
    Safely parse JSON request payload and ensure it is a JSON object (dict).
    Raises ValueError on malformed JSON or non-object types (lists, scalars).
    """
    raw_body = request.get_data(cache=True)
    if not raw_body or not raw_body.strip():
        return {}

    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ValueError("Malformed JSON request body.")

    if not isinstance(data, dict):
        raise ValueError("JSON request body must be a JSON object.")
    return data


def parse_int_param(val, default, min_val=None, max_val=None, required=False, field_name="Parameter"):
    """
    Safely parse an integer query/body parameter with optional bounds and required guard.
    Rejects booleans, floats, and out-of-range integers cleanly.
    """
    if val is None or val == "":
        if required:
            raise ValueError(f"{field_name} is required.")
        return default

    if isinstance(val, bool) or isinstance(val, float):
        raise ValueError(f"{field_name} must be a valid integer.")

    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            if required:
                raise ValueError(f"{field_name} is required.")
            return default
        if "." in cleaned:
            raise ValueError(f"{field_name} must be a whole integer.")
        val = cleaned

    try:
        iv = int(val)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid integer.")

    if min_val is not None and iv < min_val:
        raise ValueError(f"{field_name} must be at least {min_val}.")
    if max_val is not None and iv > max_val:
        raise ValueError(f"{field_name} must not exceed {max_val}.")
    return iv


def validate_amount(val) -> Decimal:
    """
    Validate and return a finite monetary Decimal quantized to 2 decimal places (ROUND_HALF_UP).
    Enforces 0.01 <= amount <= 99999999.99 before and after quantization.
    """
    if val is None or val == "" or isinstance(val, bool):
        raise ValueError("Monetary amount is required.")

    try:
        d = Decimal(str(val).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("A valid positive monetary amount is required.")

    if d.is_nan() or d.is_infinite():
        raise ValueError("Invalid numeric value.")
    if d < Decimal("0.01"):
        raise ValueError("Amount must be at least 0.01.")
    if d > Decimal("99999999.99"):
        raise ValueError("Amount exceeds maximum allowed limit (99,999,999.99).")

    quantized = d.quantize(CENT_QUANT, rounding=ROUND_HALF_UP)
    if quantized < Decimal("0.01") or quantized > Decimal("99999999.99"):
        raise ValueError("Amount must remain within 0.01 and 99,999,999.99.")

    return quantized


def to_decimal(val) -> Decimal:
    """Convert database Decimal/numeric value safely to Decimal quantized to 0.01."""
    if val is None:
        return ZERO_DEC
    if isinstance(val, Decimal):
        return val.quantize(CENT_QUANT, rounding=ROUND_HALF_UP)
    return Decimal(str(val)).quantize(CENT_QUANT, rounding=ROUND_HALF_UP)


def validate_date(val):
    """
    Validate YYYY-MM-DD date string within reasonable range (2020-01-01 to 2050-12-31).
    Returns formatted YYYY-MM-DD string.
    """
    if not val or not isinstance(val, str):
        raise ValueError("Expense date must be a string in YYYY-MM-DD format.")
    try:
        dt = datetime.strptime(val.strip(), "%Y-%m-%d")
        if dt.year < 2020 or dt.year > 2050:
            raise ValueError("Date year must be between 2020 and 2050.")
        return dt.strftime("%Y-%m-%d")
    except ValueError as e:
        if "between 2020 and 2050" in str(e):
            raise
        raise ValueError("Invalid date format. Expected YYYY-MM-DD.")


def validate_string(val, field_name, min_len=1, max_len=100, required=True):
    """
    Validate a string field with min/max length constraints.
    """
    if val is None:
        if required:
            raise ValueError(f"{field_name} is required.")
        return ""
    if not isinstance(val, str):
        raise ValueError(f"{field_name} must be a valid text string.")
    cleaned = val.strip()
    if required and len(cleaned) < min_len:
        raise ValueError(f"{field_name} must be at least {min_len} character(s) long.")
    if len(cleaned) > max_len:
        raise ValueError(f"{field_name} must not exceed {max_len} characters.")
    return cleaned


def date_range_for_month(year: int, month: int) -> tuple[str, str]:
    """
    Return inclusive ISO start and end dates for a given calendar month and year.
    Enables index-friendly sargable SQL range predicates (expense_date >= start AND expense_date <= end).
    """
    _, last_day = monthrange(year, month)
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


def subtract_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """
    Pure standard-library calendar month subtraction (replaces python-dateutil dependency).
    """
    total_months = (year * 12 + (month - 1)) - delta
    return total_months // 12, (total_months % 12) + 1
