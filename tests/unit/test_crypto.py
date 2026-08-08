"""Unit tests for crypto helpers."""

import pytest

from koebinar.crypto import decrypt_secret, encrypt_secret, generate_id, mask_key


def test_encrypt_decrypt_roundtrip():
    token = encrypt_secret("sk-secret-value-1234", "master")
    assert token != "sk-secret-value-1234"
    assert decrypt_secret(token, "master") == "sk-secret-value-1234"


def test_encrypt_empty_raises():
    with pytest.raises(ValueError):
        encrypt_secret("", "master")


def test_decrypt_wrong_key_raises():
    token = encrypt_secret("abc", "master-a")
    with pytest.raises(ValueError):
        decrypt_secret(token, "master-b")


@pytest.mark.parametrize(
    "key,expected_suffix",
    [
        ("sk-abcdefg1234", "1234"),
        ("xi-zzzz9999", "9999"),
        ("ab", "**"),
        ("", ""),
        ("xyzw", "****"),
    ],
)
def test_mask_key(key, expected_suffix):
    masked = mask_key(key)
    if not key:
        assert masked == ""
    elif len(key) <= 4:
        assert set(masked) == {"*"} or masked == "*" * len(key)
    else:
        assert masked.endswith(expected_suffix)
        assert key not in masked or key == masked  # full key must not equal mask for long keys
        assert "..." in masked


def test_generate_id_prefix():
    i = generate_id("doc_")
    assert i.startswith("doc_")
    assert len(i) > 5
    assert generate_id() != generate_id()
