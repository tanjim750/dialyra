import base64
import hashlib
import hmac
import json
import time

from flask import current_app


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - (len(value) % 4)) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def _sign(payload_b64: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def issue_fastagi_call_token(*, call_session_id: int, business_id: int, ttl_sec: int = 900) -> str:
    secret = str(current_app.config.get("SECRET_KEY") or "")
    if not secret:
        raise RuntimeError("SECRET_KEY is not configured")
    now = int(time.time())
    payload = {
        "call_session_id": int(call_session_id),
        "business_id": int(business_id),
        "iat": now,
        "exp": now + max(30, int(ttl_sec)),
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig_b64 = _sign(payload_b64, secret)
    return f"{payload_b64}.{sig_b64}"


def verify_fastagi_call_token(token: str):
    if not token or "." not in token:
        return None, "Invalid call token"
    secret = str(current_app.config.get("SECRET_KEY") or "")
    if not secret:
        return None, "SECRET_KEY is not configured"
    payload_b64, sig_b64 = token.split(".", 1)
    expected_sig = _sign(payload_b64, secret)
    if not hmac.compare_digest(sig_b64, expected_sig):
        return None, "Invalid call token signature"
    try:
        payload_raw = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_raw)
    except Exception:
        return None, "Invalid call token payload"
    if not isinstance(payload, dict):
        return None, "Invalid call token payload"
    try:
        exp = int(payload.get("exp") or 0)
        call_session_id = int(payload.get("call_session_id") or 0)
        business_id = int(payload.get("business_id") or 0)
    except (TypeError, ValueError):
        return None, "Invalid call token claims"
    if call_session_id <= 0 or business_id <= 0:
        return None, "Invalid call token claims"
    if exp < int(time.time()):
        return None, "Call token expired"
    return payload, None

