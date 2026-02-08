# redis_client.py
import os
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool
from application.api.auth.config import CONFIG


class PrefixedRedis(Redis):
    """
    Redis client that safely prefixes keys.
    """

    # Map Redis commands -> key positions
    # - [0]      → only first argument is a key
    # - "all"    → all arguments are keys
    KEY_POSITIONS = {
        # basic
        "GET": [0],
        "SET": [0],
        "SETEX": [0],
        "EXPIRE": [0],
        "TTL": [0],
        "INCR": [0],
        "DECR": [0],

        # multi-key
        "DEL": "all",
        "MGET": "all",
        "EXISTS": "all",
        "UNLINK": "all",
        "TOUCH": "all",

        # hashes
        "HGET": [0],
        "HSET": [0],
        "HDEL": [0],
        "HEXISTS": [0],

        # lists
        "LPUSH": [0],
        "RPUSH": [0],
        "LPOP": [0],
        "RPOP": [0],

        # sets
        "SADD": [0],
        "SREM": [0],
        "SISMEMBER": [0],
    }

    def __init__(self, *args, prefix: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def execute_command(self, command, *args, **kwargs):
        cmd = command.upper()
        key_positions = self.KEY_POSITIONS.get(cmd)

        if key_positions == "all":
            args = tuple(
                self._key(a) if isinstance(a, str) else a
                for a in args
            )

        elif isinstance(key_positions, list):
            args = tuple(
                self._key(a) if i in key_positions and isinstance(a, str) else a
                for i, a in enumerate(args)
            )

        return await super().execute_command(command, *args, **kwargs)


# -------------------------
# Redis connection pool
# -------------------------
pool = ConnectionPool(
    host=CONFIG.REDIS_HOST,
    port=CONFIG.REDIS_PORT,
    db=CONFIG.REDIS_DB,
    password=None,
    decode_responses=CONFIG.DECODE_RESPONSE,
    max_connections=CONFIG.REDIS_MAX_CONNECTIONS,
    health_check_interval=30,
)

# -------------------------
# Redis client
# -------------------------
redis_client = PrefixedRedis(
    connection_pool=pool,
    prefix=CONFIG.REDIS_PREFIX,
)

# -------------------------
# Async health check
# -------------------------
async def test_redis_connection():
    try:
        await redis_client.ping()
    except Exception as e:
        raise ConnectionError(
            f"Cannot connect to Redis at {CONFIG.REDIS_HOST}:{CONFIG.REDIS_PORT}"
        ) from e
