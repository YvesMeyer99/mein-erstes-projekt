import hashlib
import hmac
import urllib.parse

from app.adapters.mexc_auth import build_signed_params, sign_mexc_params


def test_sign_mexc_params_computes_correct_hmac_sha256_hex():
    params = {"symbol": "BTCUSDT", "timestamp": 1644489390087}
    secret = "45d0b3c26f2644f19bfb98b07741b2f5"

    signature = sign_mexc_params(params, secret)

    expected = hmac.new(
        secret.encode(),
        "symbol=BTCUSDT&timestamp=1644489390087".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert signature == expected


def test_sign_mexc_params_is_lowercase_hex():
    signature = sign_mexc_params({"a": "1"}, "secret")

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
    expected = sign_mexc_params(params_without_signature, "secret")
    assert result["signature"] == expected


def test_different_secrets_produce_different_signatures():
    sig_a = sign_mexc_params({"a": "1"}, "secret-a")
    sig_b = sign_mexc_params({"a": "1"}, "secret-b")

    assert sig_a != sig_b


def test_different_params_produce_different_signatures():
    sig_a = sign_mexc_params({"symbol": "BTCUSDT"}, "secret")
    sig_b = sign_mexc_params({"symbol": "ETHUSDT"}, "secret")

    assert sig_a != sig_b


def test_sign_mexc_params_percent_encodes_special_characters():
    params = {"note": "hello world & more=stuff", "symbol": "BTC/USDT", "unicode": "café"}
    secret = "secret"

    signature = sign_mexc_params(params, secret)

    expected = hmac.new(
        secret.encode(),
        urllib.parse.urlencode(params).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert signature == expected


def test_sign_mexc_params_empty_secret_produces_valid_signature():
    # hmac.new(b"", ...) is mechanically valid even though an empty
    # secret would never be a real credential.
    signature = sign_mexc_params({"a": "1"}, "")

    assert len(signature) == 64
    assert all(c in "0123456789abcdef" for c in signature)


def test_sign_mexc_params_empty_params_does_not_raise():
    signature = sign_mexc_params({}, "secret")

    expected = hmac.new(b"secret", b"", hashlib.sha256).hexdigest()
    assert signature == expected


def test_build_signed_params_empty_params_adds_timestamp_and_signature():
    result = build_signed_params({}, "secret")

    assert set(result.keys()) == {"timestamp", "signature"}
    assert isinstance(result["timestamp"], int)
