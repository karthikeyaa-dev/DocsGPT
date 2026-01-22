# redis_client.py
import os
import redis
from application.api.auth.config import CONFIG

REDIS_PREFIX = "auth:"

class PrefixedRedis(redis.Redis):
    def __init__(self, *args, prefix="", **kwargs):
        super().__init__(*args, **kwargs)
        self.prefix = prefix

    def prefixed(self, key):
        return f"{self.prefix}{key}"

    def set(self, key, *args, **kwargs):
        return super().set(self.prefixed(key), *args, **kwargs)

    def get(self, key, *args, **kwargs):
        return super().get(self.prefixed(key), *args, **kwargs)

    def delete(self, key, *args, **kwargs):
        return super().delete(self.prefixed(key), *args, **kwargs)

# Initialize Redis with automatic prefix
redis_client = PrefixedRedis(
    host=CONFIG.REDIS_HOST,
    port=CONFIG.REDIS_PORT,
    db=CONFIG.REDIS.DB,
    password=None,
    decode_responses=CONFIG.DECODE_RESPONSE,
    prefix=REDIS_PREFIX,
)

# Test connection immediately
try:
    redis_client.ping()
except redis.ConnectionError:
    raise ConnectionError(
        f"Cannot connect to Redis at {os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}"
    )
