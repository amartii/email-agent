"""
crypto.py
Encrypts/decrypts sensitive data (Gmail App Password) stored in the DB.
Uses cryptography.Fernet with a key derived from SECRET_KEY.
"""
import base64
import hashlib
from cryptography.fernet import Fernet
from flask import current_app


def _get_fernet() -> Fernet:
    secret = current_app.config["SECRET_KEY"].encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt(plain_text: str) -> str:
    """Encrypt a string and return the ciphertext as a string."""
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    """Decrypt a ciphertext string and return the original plain text."""
    return _get_fernet().decrypt(cipher_text.encode()).decode()
