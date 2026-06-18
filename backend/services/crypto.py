"""
Simple Fernet encryption for credentials at rest.
In production use a proper KMS (AWS KMS, HashiCorp Vault, etc.).
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# In production set ADOPTIMA_SECRET_KEY via environment
SECRET_KEY = os.environ.get("ADOPTIMA_SECRET_KEY", "adoptima-internal-secret-key-for-demo-only")
SALT = os.environ.get("ADOPTIMA_SALT", "adoptima-salt").encode()


def _get_fernet():
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=100_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(SECRET_KEY.encode()))
    return Fernet(key)


def encrypt(text: str) -> str:
    if not text:
        return ""
    return _get_fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    return _get_fernet().decrypt(token.encode()).decode()
