"""
utils/response.py
-----------------
Helpers to build consistent JSON response envelopes.

All API responses follow the shape:
    {
        "success": bool,
        "data":    any | null,
        "error":   str | null
    }
"""

from flask import jsonify
from typing import Any


def success_response(data: Any = None, status: int = 200):
    """
    Build a successful JSON response.

    Args:
        data:   The payload to include under the ``data`` key.
        status: HTTP status code (default 200).

    Returns:
        A Flask ``Response`` object with Content-Type: application/json.
    """
    response = jsonify({"success": True, "data": data, "error": None})
    response.status_code = status
    return response


def error_response(message: str, status: int = 400):
    """
    Build an error JSON response.

    Args:
        message: Human-readable error description.
        status:  HTTP status code (default 400).

    Returns:
        A Flask ``Response`` object with Content-Type: application/json.
    """
    response = jsonify({"success": False, "data": None, "error": message})
    response.status_code = status
    return response


def paginated_response(items: list, page: int, per_page: int, total: int):
    """
    Build a paginated successful JSON response.

    Args:
        items:    List of serialised items for the current page.
        page:     Current page number (1-indexed).
        per_page: Number of items per page.
        total:    Total number of items across all pages.

    Returns:
        A Flask ``Response`` object with pagination metadata.
    """
    response = jsonify(
        {
            "success": True,
            "data": {
                "items": items,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "pages": max(1, -(-total // per_page)),  # ceiling division
                },
            },
            "error": None,
        }
    )
    response.status_code = 200
    return response
