import hashlib
import hmac

from app.adapters.binance_auth import build_signed_params, sign_binance_params


def test_sign_binance_params_computes_correct_hmac_sha256_hex():
    params = {"symbol": "BTCUSDT", "timestamp": 1644489390087}
    secret = "45d0b3c26f2644f19bfb98b07741b2f5"

    signature = sign_binance_params(params, secret)

    expected = hmac.new(
        secret.encode(),
        "symbol=BTCUSDT&timestamp=1644489390087".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert signature == expected


def test_sign_binance_params_is_lowercase_hex():
    signature = sign_binance_params({"a": "1"}, "secret")

    assert signature == signature.lower()
    assert all(c in "0123456789abcdef" for c in signature)


def test_build_signed_params_adds_timestamp_and_signature():
    result = build_signed_params({"symbol": "BTCUSDT"}, "secret")

    assert "timestamp" in result and isinstance(result["timestamp"], int)
    assert "signature" in result
    assert result["symbol"] == "BTCUSDT"


def test_build_signed_params_signature_matches_manual_computation():
    result = build_signed_params({"symbol": "BTCUSDT"}, "secret")

    params_without_signature = {k: v for k, v in result.items() if k != "signature"}
    expected = sign_binance_params(params_without_signature, "secret")
    assert result["signature"] == expected


def test_different_secrets_produce_different_signatures():
    sig_a = sign_binance_params({"a": "1"}, "secret-a")
    sig_b = sign_binance_params({"a": "1"}, "secret-b")

    assert sig_a != sig_b


def test_different_params_produce_different_signatures():
    sig_a = sign_binance_params({"symbol": "BTCUSDT"}, "secret")
    sig_b = sign_binance_params({"symbol": "ETHUSDT"}, "secret")

    assert sig_a != sig_b
