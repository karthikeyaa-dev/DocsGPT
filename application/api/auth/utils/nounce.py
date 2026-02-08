# helpers/nonce.py
from application.api.auth.redis_client import redis_client
import secrets

def store_nonce(payload: dict) -> str:
    """
    Store the nonce from the payload in Redis using payload['exp'] as TTL.

    Args:
        payload: dict containing at least "nonce", "uid", and "exp" keys

    Returns:
        The nonce string
    """
    nonce = payload.get("nonce")
    user_id = payload.get("uid")
    exp = payload.get("exp")

    if not nonce or not user_id or not exp:
        raise ValueError("Payload must contain 'nonce', 'uid', and 'exp'")

    # Calculate TTL in seconds
    ttl = exp - int(time.time())
    if ttl <= 0:
        raise ValueError("Token already expired")

    # Store in Redis with TTL
    await redis_client.set(f"email_verify:{nonce}", user_id, ex=ttl)

    return nonce

def consume_nonce(nonce: str) -> int | None:
    """
    Consume a nonce: read the user_id from Redis and delete the key.
    
    Args:
        nonce: the nonce string from the payload or email link

    Returns:
        user_id if valid, None if nonce does not exist or already used
    """
    key = f"email_verify:{nonce}"
    
    # Get the user_id
    user_id = await redis_client.get(key)
    
    if user_id is None:
        # Token does not exist or already used
        return None

    # Delete the key immediately to prevent reuse
    await redis_client.delete(key)
    
    return int(user_id)
