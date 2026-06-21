"""
utils/crypto.py
---------------
Fernet symmetric encryption helpers for storing MT5 passwords.

The Fernet key is read from the FERNET_KEY environment variable (via config).
A new key can be generated with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

IMPORTANT: Losing the Fernet key means existing encrypted passwords can no
           longer be decrypted. Back up the key securely.
"""

import os
from cryptography.fernet import Fernet, InvalidToken
from utils.exceptions import AppError


def _get_fernet() -> Fernet:
    """
    Retrieve a Fernet instance using the key from the environment.

    Raises:
        AppError: If FERNET_KEY is not set or is invalid.
    """
    key = os.environ.get("FERNET_KEY", "")
    if not key:
        raise AppError(
            "FERNET_KEY environment variable is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise AppError(f"Invalid FERNET_KEY: {exc}") from exc


def encrypt_password(plain: str) -> str:
    """
    Encrypt a plain-text MT5 password using Fernet symmetric encryption.

    Args:
        plain: The plain-text password to encrypt.

    Returns:
        A URL-safe base64-encoded ciphertext string.

    Raises:
        AppError: If the Fernet key is missing or invalid.
    """
    fernet = _get_fernet()
    token: bytes = fernet.encrypt(plain.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_password(token: str) -> str:
    """
    Decrypt a Fernet-encrypted password ciphertext.

    Args:
        token: The URL-safe base64-encoded ciphertext string.

    Returns:
        The original plain-text password.

    Raises:
        AppError: If the Fernet key is missing, invalid, or the token is
                  corrupted / was encrypted with a different key.
    """
    fernet = _get_fernet()
    try:
        plain: bytes = fernet.decrypt(token.encode("utf-8"))
        return plain.decode("utf-8")
    except InvalidToken as exc:
        raise AppError(
            "Failed to decrypt password — the token may be corrupted or the "
            "FERNET_KEY may have changed."
        ) from exc
