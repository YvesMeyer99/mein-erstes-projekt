import hashlib
import hmac
import time
import urllib.parse


def sign_mexc_params(params: dict, secret: str) -> str:
    """Compute a MEXC Spot API v3 request signature: HMAC-SHA256 of the
    URL-encoded query string, keyed with the API secret, as lowercase
    hex - per MEXC's documented signing scheme."""
    query_string = urllib.parse.urlencode(params)
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def build_signed_params(params: dict, secret: str) -> dict:
    """Return a new params dict with a fresh millisecond timestamp and
    the computed signature attached, ready to send as a signed MEXC
    request's query parameters."""
    signed = dict(params)
    signed["timestamp"] = int(time.time() * 1000)
    signed["signature"] = sign_mexc_params(signed, secret)
    return signed
