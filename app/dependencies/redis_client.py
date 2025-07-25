from redis.asyncio import Redis, ConnectionPool
from fastapi import HTTPException, status
from app.core.security import connect_to_redis
import logging
import os

logger = logging.getLogger(__name__)

# ✅ Restore global instance for app-wide singleton
global_redis_client_instance: Redis | None = None

# Create a Redis connection pool for higher concurrency
# Make sure connect_to_redis uses the password and this pool
redis_password = os.getenv('REDIS_PASSWORD')
redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_port = int(os.getenv('REDIS_PORT', 6379))
redis_pool = ConnectionPool(
    host=redis_host,
    port=redis_port,
    password=redis_password,
    max_connections=100  # Increased to 100 to avoid 'Too many connections'. Tune as needed.
    # db left as default (0)
)

async def get_redis_client() -> Redis:
    global global_redis_client_instance
    if global_redis_client_instance is None:
        logger.warning("[Redis] Client not initialized, attempting late connection.")
        # Use the connection pool with password
        global_redis_client_instance = Redis(connection_pool=redis_pool)
        # If connect_to_redis is required for other setup, ensure it uses the same pool and password
        # global_redis_client_instance = await connect_to_redis()
        # If connect_to_redis does not use the pool/password, update it accordingly.
        if global_redis_client_instance is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Redis unavailable"
            )
    return global_redis_client_instance
