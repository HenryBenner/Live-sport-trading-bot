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


def test_no_test_buy_uses_ask_side_and_normalizes_fill_price(monkeypatch):
    client = KalshiClient()
    payloads = []

    def request(method, endpoint, json_body=None):
        payloads.append(json_body)
        return {
            "fill_count": "1.00",
            "average_fill_price": "0.0100",
            "average_fee_paid": "0.0010",
        }

    monkeypatch.setattr(client, "_request", request)
    result = client.place_outcome_buy(
        ticker="TEST-NO",
        outcome_side="no",
        spend_up_to_dollars=1,
        mode="test",
        aggressive_buy_price="0.9900",
    )

    assert payloads[0]["side"] == "ask"
    assert payloads[0]["price"] == "0.0100"
    assert result["average_fill_price"] == "0.9900"
    assert result["outcome_side"] == "no"
