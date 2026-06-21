"""
tests/conftest.py
-----------------
Shared pytest configuration for the Mini Trading CRM test suite.

Sets FERNET_KEY in the environment before any imports happen so that
utils/crypto.py can find a valid key when the test app initialises.
"""

import os

# Set a valid Fernet key for tests before any app code runs.
# This is a deterministic 32-byte base64 key — safe for testing only.
os.environ.setdefault("FERNET_KEY", "q-moE78rUoDTaVc6KJDq8GJ_ZS_OlqyiRHjqV4Wm8Yw=")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("FLASK_ENV", "testing")
