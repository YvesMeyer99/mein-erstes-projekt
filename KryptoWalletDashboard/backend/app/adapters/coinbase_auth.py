import secrets
import time

import jwt as pyjwt


def build_coinbase_jwt(
    api_key_name: str,
    private_key_pem: str,
    method: str,
    host: str,
    path: str,
) -> str:
    """Build a short-lived ES256 JWT for authenticating one Coinbase App API
    request, per Coinbase's CDP API key authentication scheme. A fresh JWT
    must be built for every request - it expires 120 seconds after issuance
    and is scoped to one specific method+host+path via the `uri` claim."""
    now = int(time.time())
    payload = {
        "iss": "cdp",
        "sub": api_key_name,
        "nbf": now,
        "exp": now + 120,
        "uri": f"{method} {host}{path}",
    }
    headers = {
        "kid": api_key_name,
        "nonce": secrets.token_hex(16),
    }
    return pyjwt.encode(payload, private_key_pem, algorithm="ES256", headers=headers)
