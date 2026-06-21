"""
utils/error_handlers.py
-----------------------
Flask error handler registration.

Registers:
  - A handler for all AppError subclasses that returns a JSON envelope
    with the correct HTTP status code.
  - A catch-all 500 handler that logs the full traceback and returns
    a generic error message (avoids leaking internals to clients).
"""

import traceback
from flask import Flask, jsonify
from utils.exceptions import AppError
from utils.logger import get_logger

logger = get_logger(__name__)


def register_error_handlers(app: Flask) -> None:
    """
    Attach all custom error handlers to the Flask ``app`` instance.

    Call this from the application factory after blueprints are registered.
    """

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        """
        Handle any AppError subclass.

        Returns a JSON response with:
          - success: false
          - error: the error message string
          - HTTP status from error.status_code
        """
        logger.warning(
            "AppError [%s] %s: %s",
            error.status_code,
            type(error).__name__,
            error.message,
        )
        response = jsonify({"success": False, "data": None, "error": str(error)})
        response.status_code = error.status_code
        return response

    @app.errorhandler(404)
    def handle_not_found(error):
        """Handle Flask's built-in 404 errors."""
        response = jsonify({"success": False, "data": None, "error": "Not found"})
        response.status_code = 404
        return response

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        """Handle Flask's built-in 405 errors."""
        response = jsonify(
            {"success": False, "data": None, "error": "Method not allowed"}
        )
        response.status_code = 405
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        """
        Catch-all handler for any unhandled exception.

        Logs the full traceback server-side and returns a generic 500 message
        to avoid leaking internal implementation details.
        """
        logger.error(
            "Unhandled exception: %s\n%s",
            str(error),
            traceback.format_exc(),
        )
        response = jsonify(
            {
                "success": False,
                "data": None,
                "error": "An internal server error occurred. Please try again later.",
            }
        )
        response.status_code = 500
        return response
