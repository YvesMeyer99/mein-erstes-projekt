import hashlib
import hmac
import time
import urllib.parse


def sign_binance_params(params: dict, secret: str) -> str:
    """Compute a Binance Spot API v3 request signature: HMAC-SHA256 of the
    URL-encoded query string, keyed with the API secret, as lowercase
    hex - per Binance's documented signing scheme (identical algorithm to
    MEXC's, which mirrors Binance's API design).

    Note: `params` values must be scalar (str/int/etc.), not lists/tuples/
    dicts - `urllib.parse.urlencode` is called without `doseq=True`. This
    codebase's Binance calls only ever pass scalar values (symbol strings,
    timestamps, limits, offsets)."""
    query_string = urllib.parse.urlencode(params)
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def build_signed_params(params: dict, secret: str) -> dict:
    """Return a new params dict with a fresh millisecond timestamp and
    the computed signature attached, ready to send as a signed Binance
    request's query parameters."""
    signed = dict(params)
    signed["timestamp"] = int(time.time() * 1000)
    signed["signature"] = sign_binance_params(signed, secret)
    return signed
