"""
utils/exceptions.py
-------------------
Custom exception hierarchy for the Mini Trading CRM.

All application exceptions inherit from ``AppError`` so that the global
error handler can catch them uniformly and return a consistent JSON envelope.
"""


class AppError(Exception):
    """
    Base class for all application-level errors.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code to return (default 400).
    """

    status_code: int = 400

    def __init__(self, message: str = "An error occurred") -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ValidationError(AppError):
    """
    Raised when request input fails validation (missing/invalid fields).

    HTTP 422 Unprocessable Entity.
    """

    status_code: int = 422

    def __init__(self, message: str = "Validation failed") -> None:
        super().__init__(message)


class NotFoundError(AppError):
    """
    Raised when a requested resource does not exist in the database.

    HTTP 404 Not Found.
    """

    status_code: int = 404

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message)


class MT5ConnectionError(AppError):
    """
    Raised when a MetaTrader 5 connection or operation fails after retries.

    HTTP 502 Bad Gateway (upstream MT5 server is unresponsive / rejected login).
    """

    status_code: int = 502

    def __init__(self, message: str = "MT5 connection failed") -> None:
        super().__init__(message)


class DuplicateTradeError(AppError):
    """
    Raised when an attempt is made to insert a trade that already exists.

    HTTP 409 Conflict.
    """

    status_code: int = 409

    def __init__(self, message: str = "Trade already exists") -> None:
        super().__init__(message)
