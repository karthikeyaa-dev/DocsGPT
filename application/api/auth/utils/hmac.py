import json
import base64
import hmac, hashlib
from application.api.auth.config import CONFIG

def sign(message: bytes) -> bytes:
    return hmac.new(
        CONFIG.HMAC_SECRET_KEY,
        message,
        CONFIG.HMAC_ALGORITHM
    ).digest()

def verify(message: bytes, mac: bytes) -> bool:
    expected = sign(message)
    return hmac.compare_digest(mac, expected)

def encode_token(payload: dict) -> str:
    """
    Encode a payload dict into a URL-safe HMAC token.
    """
    # 1. Convert payload to JSON bytes
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode()

    # 2. Sign the payload
    mac = sign(payload_bytes)

    # 3. Combine payload + signature
    token_bytes = payload_bytes + b"." + mac

    # 4. Base64 encode for URL safety
    token_str = base64.urlsafe_b64encode(token_bytes).decode()
    return token_str

def decode_token(token: str) -> dict:
    """
    Decode a token string and verify HMAC.
    Returns payload if valid, raises ValueError if invalid.
    """
    try:
        token_bytes = base64.urlsafe_b64decode(token.encode())
        payload_bytes, mac = token_bytes.rsplit(b".", 1)

        # Verify HMAC
        if not verify(payload_bytes, mac):
            raise ValueError("Invalid token signature")

        # Convert bytes back to dict
        payload = json.loads(payload_bytes)
        return payload

    except Exception as e:
        raise ValueError(f"Invalid token: {e}")
