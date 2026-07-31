import hashlib
import hmac
import time
import urllib.parse


def sign_mexc_params(params: dict, secret: str) -> str:
    """Compute a MEXC Spot API v3 request signature: HMAC-SHA256 of the
    URL-encoded query string, keyed with the API secret, as lowercase
    hex - per MEXC's documented signing scheme.

    Note: `params` values must be scalar (str/int/etc.), not lists/tuples/
    dicts - `urllib.parse.urlencode` is called without `doseq=True`, so a
    list/tuple value would be mis-encoded as its Python repr instead of
    being expanded into repeated `key=value` pairs. This mirrors an
    existing, accepted limitation in `app/adapters/kraken.py`'s `_sign`;
    MEXC calls in this codebase only ever pass scalar values (symbol
    strings, timestamps, limits)."""
    query_string = urllib.parse.urlencode(params)
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def build_signed_params(params: dict, secret: str) -> dict:
    """Return a new params dict with a fresh millisecond timestamp and
    the computed signature attached, ready to send as a signed MEXC
    request's query parameters.

    Note: as with `sign_mexc_params`, `params` values must be scalar
    (str/int/etc.), not lists/tuples/dicts - see that function's
    docstring for why."""
    signed = dict(params)
    signed["timestamp"] = int(time.time() * 1000)
    signed["signature"] = sign_mexc_params(signed, secret)
    return signed
