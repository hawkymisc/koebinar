"""Key encryption and masking for BYOK integrations."""

from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken


def _derive_fernet_key(master_key: str) -> bytes:
    digest = hashlib.sha256(master_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str, master_key: str) -> str:
    if not plaintext:
        raise ValueError("plaintext key must not be empty")
    f = Fernet(_derive_fernet_key(master_key))
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str, master_key: str) -> str:
    f = Fernet(_derive_fernet_key(master_key))
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("failed to decrypt secret") from exc


def mask_key(api_key: str, visible_tail: int = 4) -> str:
    """Return a masked representation: prefix hint + last N chars."""
    if not api_key:
        return ""
    if len(api_key) <= visible_tail:
        return "*" * len(api_key)
    prefix = api_key[:3] if api_key.startswith("sk") or api_key.startswith("xi") else api_key[:2]
    return f"{prefix}...{api_key[-visible_tail:]}"


def generate_id(prefix: str = "") -> str:
    body = secrets.token_hex(8)
    return f"{prefix}{body}" if prefix else body
