# app/dependencies/rate_limiter.py

import logging
from fastapi import WebSocket, Request, status, WebSocketException
from redis.asyncio import Redis
import time

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    Manages WebSocket connections with IP-based connection limiting using Redis.
    """
    def __init__(self, redis_client: Redis, max_connections: int = 5, redis_prefix: str = "ws_conn:raw"):
        self.redis_client = redis_client
        self.max_connections = max_connections
        self.prefix = redis_prefix

    def _get_client_ip(self, request: Request) -> str:
        """Extracts the client's IP address from the request."""
        # Standard practice is to check X-Forwarded-For header for reverse proxies
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # The header can contain a comma-separated list of IPs; the first one is the client
            return forwarded_for.split(',')[0].strip()
        # Fallback to the direct client host
        return request.client.host

    async def connect(self, websocket: WebSocket):
        """
        Accepts a new WebSocket connection if the client has not exceeded the connection limit.
        """
        client_ip = self._get_client_ip(websocket)
        if not client_ip:
            logger.warning("Could not determine client IP. Denying connection.")
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Could not determine client IP.")

        redis_key = f"{self.prefix}:{client_ip}"

        try:
            # Increment the connection count for this IP. If the key doesn't exist, it's created with a value of 1.
            # The pipeline ensures atomicity for the INCR and EXPIRE commands.
            pipe = self.redis_client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, 60)  # Set a 60-second TTL to auto-clean stale keys
            current_connections, _ = await pipe.execute()

            if current_connections > self.max_connections:
                logger.warning(f"IP {client_ip} denied connection. Limit of {self.max_connections} reached.")
                # Decrement to counteract the initial increment before raising the exception
                await self.redis_client.decr(redis_key)
                raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=f"Connection limit of {self.max_connections} per IP reached.")

            await websocket.accept()
            logger.info(f"New connection from {client_ip}. Total connections for this IP: {current_connections}")

        except Exception as e:
            logger.error(f"Error during WebSocket connect for IP {client_ip}: {e}", exc_info=True)
            raise WebSocketException(code=status.WS_1011_INTERNAL_ERROR, reason="Server error during connection.")

    async def disconnect(self, websocket: WebSocket):
        """
        Decrements the connection count for the client's IP upon disconnection.
        """
        client_ip = self._get_client_ip(websocket)
        if client_ip:
            redis_key = f"{self.prefix}:{client_ip}"
            try:
                # Use DECR to decrement the connection count.
                await self.redis_client.decr(redis_key)
                logger.info(f"Disconnected: {client_ip}")
            except Exception as e:
                logger.error(f"Error during WebSocket disconnect for IP {client_ip}: {e}", exc_info=True)


class WebSocketRateLimiter:
    def __init__(self, redis_client: Redis, max_connections: int = 5, window_seconds: int = 60):
        self.redis = redis_client
        self.max_connections = max_connections
        self.window_seconds = window_seconds

    async def check_rate_limit(self, websocket: WebSocket) -> bool:
        """
        Check if the IP address has exceeded the rate limit.
        Returns True if allowed, False if rate limit exceeded.
        """
        try:
            client_ip = websocket.client.host
            key = f"ws_rate_limit:{client_ip}"
            
            # Get current connections for this IP
            current_connections = await self.redis.get(key)
            current_count = int(current_connections) if current_connections else 0

            if current_count >= self.max_connections:
                logger.warning(f"Rate limit exceeded for IP {client_ip}: {current_count} connections")
                return False

            # Increment connection count and set expiry
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.window_seconds)
            await pipe.execute()
            
            return True

        except Exception as e:
            logger.error(f"Error in rate limiter: {e}")
            return False

    async def release_connection(self, websocket: WebSocket):
        """
        Release a connection count for an IP address when the WebSocket disconnects.
        """
        try:
            client_ip = websocket.client.host
            key = f"ws_rate_limit:{client_ip}"
            
            # Decrement connection count
            current = await self.redis.get(key)
            if current and int(current) > 0:
                await self.redis.decr(key)
        except Exception as e:
            logger.error(f"Error releasing rate limit: {e}")
