"""
utils/validators.py
-------------------
Input validation helpers used by route handlers.

All validators raise ``ValidationError`` on failure so that the global
error handler automatically returns HTTP 422 with a descriptive message.
"""

import re
from utils.exceptions import ValidationError

# RFC 5322–inspired simple email pattern
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validate_required_fields(data: dict, fields: list[str]) -> None:
    """
    Ensure all listed fields are present and non-empty in ``data``.

    Args:
        data:   Dictionary of request body values.
        fields: List of required field names.

    Raises:
        ValidationError: If any field is missing or blank.
    """
    missing = [f for f in fields if not data.get(f)]
    if missing:
        raise ValidationError(f"Missing required fields: {', '.join(missing)}")


def validate_email(email: str) -> str:
    """
    Validate and normalise an email address.

    Args:
        email: Raw email string from the request.

    Returns:
        Lowercased, stripped email string.

    Raises:
        ValidationError: If the email format is invalid.
    """
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValidationError(f"Invalid email address: {email!r}")
    return email


def validate_positive_int(value: object, field_name: str) -> int:
    """
    Ensure a value can be converted to a positive integer.

    Args:
        value:      The raw value (may be a string from JSON).
        field_name: Name of the field (used in error messages).

    Returns:
        The value as a positive int.

    Raises:
        ValidationError: If conversion fails or the value is ≤ 0.
    """
    try:
        as_int = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"'{field_name}' must be an integer, got {value!r}")
    if as_int <= 0:
        raise ValidationError(f"'{field_name}' must be a positive integer, got {as_int}")
    return as_int


def validate_account_type(value: str) -> str:
    """
    Ensure the account_type is one of the allowed enum values.

    Args:
        value: Raw account_type string from the request.

    Returns:
        Validated account_type string.

    Raises:
        ValidationError: If the value is not a valid account type.
    """
    allowed = {"master", "slave", "standalone"}
    if value not in allowed:
        raise ValidationError(
            f"'account_type' must be one of {sorted(allowed)}, got {value!r}"
        )
    return value
