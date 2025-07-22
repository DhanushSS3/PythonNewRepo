from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from redis.asyncio import Redis
import logging
import json
from app.dependencies.redis_client import get_redis_client
from app.dependencies.rate_limiter import WebSocketRateLimiter
from app.services.raw_price_broadcaster import RawPriceBroadcaster
from app.core.logging_config import websocket_logger
from app.core.cache import get_last_known_price, DecimalEncoder

logger = websocket_logger
router = APIRouter()

# Create a single instance of the broadcaster
_broadcaster = None

def get_broadcaster(redis_client: Redis = Depends(get_redis_client)) -> RawPriceBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = RawPriceBroadcaster(redis_client)
    return _broadcaster

async def get_initial_snapshot(redis_client: Redis, symbols: set) -> dict:
    """
    Get last known prices for all symbols from cache.
    """
    snapshot = {}
    logger.debug(f"Fetching initial snapshot for {len(symbols)} symbols: {sorted(list(symbols))}")
    
    for symbol in symbols:
        try:
            logger.debug(f"Fetching last known price for {symbol}")
            price_data = await get_last_known_price(redis_client, symbol)
            if price_data:
                logger.debug(f"Got price data for {symbol}: {price_data}")
                snapshot[symbol] = {
                    'bid': price_data.get('b'),
                    'ask': price_data.get('o'),
                    'timestamp': None  # Last known price doesn't store timestamp
                }
            else:
                logger.warning(f"No price data found for {symbol}")
        except Exception as e:
            logger.error(f"Error getting last known price for {symbol}: {e}")
    
    logger.debug(f"Snapshot complete. Got prices for {len(snapshot)}/{len(symbols)} symbols. Symbols with data: {sorted(list(snapshot.keys()))}")
    return snapshot

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
        
        # Send initial snapshot of last known prices
        try:
            logger.debug(f"Getting initial snapshot for client {websocket.client.host}")
            snapshot = await get_initial_snapshot(redis_client, broadcaster.symbols_to_broadcast)
            if snapshot:
                snapshot_message = json.dumps({
                    "type": "snapshot",
                    "data": snapshot
                }, cls=DecimalEncoder)  # Use DecimalEncoder for JSON serialization
                logger.debug(f"Sending initial snapshot to client {websocket.client.host} with {len(snapshot)} symbols")
                logger.debug(f"Snapshot message: {snapshot_message}")
                await websocket.send_text(snapshot_message)
            else:
                logger.warning(f"No data in initial snapshot for client {websocket.client.host}")
        except Exception as e:
            logger.error(f"Error sending initial snapshot to client {websocket.client.host}: {e}", exc_info=True)
        
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