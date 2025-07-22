from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from redis.asyncio import Redis
import logging
from app.dependencies.redis_client import get_redis_client
from app.dependencies.rate_limiter import WebSocketRateLimiter
from app.services.raw_price_broadcaster import RawPriceBroadcaster
from app.core.logging_config import websocket_logger

logger = websocket_logger
router = APIRouter()

# Create a single instance of the broadcaster
_broadcaster = None

def get_broadcaster(redis_client: Redis = Depends(get_redis_client)) -> RawPriceBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = RawPriceBroadcaster(redis_client)
    return _broadcaster

@router.websocket("/ws/public/market-data")
async def public_market_data_websocket(
    websocket: WebSocket,
    broadcaster: RawPriceBroadcaster = Depends(get_broadcaster),
    redis_client: Redis = Depends(get_redis_client)
):
    """
    Public WebSocket endpoint for raw market data.
    Rate limited to 5 connections per IP address.
    Broadcasts raw prices for specific symbols:
    AUDJPY, AUDCAD, AUDUSD, JP225, US30, D30, CADJPY, BTCUSD, XAUUSD, XAGUSD
    """
    # Initialize rate limiter
    rate_limiter = WebSocketRateLimiter(redis_client)
    
    try:
        # Check rate limit before accepting connection
        if not await rate_limiter.check_rate_limit(websocket):
            await websocket.close(code=1008, reason="Rate limit exceeded")
            return

        # Connect to broadcaster
        await broadcaster.connect(websocket)
        
        try:
            # Keep connection alive
            while True:
                data = await websocket.receive_text()
                # Optionally process any incoming messages
                # For now, we just keep the connection alive
        except WebSocketDisconnect:
            logger.info(f"Client disconnected: {websocket.client.host}")
        finally:
            # Clean up
            await broadcaster.disconnect(websocket)
            await rate_limiter.release_connection(websocket)
            
    except Exception as e:
        logger.error(f"Error in public market data websocket: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass 