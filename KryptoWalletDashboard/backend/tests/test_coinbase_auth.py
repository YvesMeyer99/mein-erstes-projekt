import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.adapters.coinbase_auth import build_coinbase_jwt


def _generate_test_key_pair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return private_pem, private_key.public_key()


def test_jwt_has_correct_header_and_payload_claims():
    private_pem, public_key = _generate_test_key_pair()
    api_key_name = "organizations/org123/apiKeys/key456"

    token = build_coinbase_jwt(
        api_key_name=api_key_name,
        private_key_pem=private_pem,
        method="GET",
        host="api.coinbase.com",
        path="/v2/accounts",
    )

    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["typ"] == "JWT"
    assert header["kid"] == api_key_name
    assert isinstance(header["nonce"], str) and len(header["nonce"]) > 0

    payload = pyjwt.decode(token, public_key, algorithms=["ES256"], options={"verify_exp": False})
    assert payload["iss"] == "cdp"
    assert payload["sub"] == api_key_name
    assert payload["uri"] == "GET api.coinbase.com/v2/accounts"


def test_jwt_is_verifiable_with_the_matching_public_key():
    private_pem, public_key = _generate_test_key_pair()
    token = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")

    # Should not raise.
    pyjwt.decode(token, public_key, algorithms=["ES256"], options={"verify_exp": False})


def test_jwt_rejects_verification_with_a_different_public_key():
    private_pem, _ = _generate_test_key_pair()
    _, other_public_key = _generate_test_key_pair()
    token = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")

    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, other_public_key, algorithms=["ES256"], options={"verify_exp": False})


def test_jwt_expires_120_seconds_after_issuance():
    private_pem, public_key = _generate_test_key_pair()
    before = int(time.time())
    token = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")
    after = int(time.time())

    payload = pyjwt.decode(token, public_key, algorithms=["ES256"], options={"verify_exp": False})
    assert before <= payload["nbf"] <= after
    assert payload["exp"] == payload["nbf"] + 120


def test_two_calls_produce_different_nonces():
    private_pem, _ = _generate_test_key_pair()
    token_a = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")
    token_b = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")

    assert pyjwt.get_unverified_header(token_a)["nonce"] != pyjwt.get_unverified_header(token_b)["nonce"]
