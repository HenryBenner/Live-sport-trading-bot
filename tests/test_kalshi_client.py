from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from server.kalshi_client import KalshiClient, KalshiClientError


def inline_private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return pem.strip().replace("\n", "\\n")


def test_private_key_loads_directly_from_environment(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "test-key-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", inline_private_key())

    client = KalshiClient()

    assert client.ready()
    assert client._load_private_key().key_size == 2048


def test_invalid_inline_private_key_has_clear_error(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "test-key-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "not-a-pem")
    client = KalshiClient()

    try:
        client._load_private_key()
    except KalshiClientError as exc:
        assert "not a valid" in str(exc)
    else:
        raise AssertionError("Invalid inline key should be rejected")
