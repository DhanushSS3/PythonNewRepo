# app/services/raw_price_broadcaster.py

import asyncio
import json
import logging
from typing import Set, Dict, Any
from redis.asyncio import Redis
from app.core.cache import REDIS_MARKET_DATA_CHANNEL
from fastapi import WebSocket, WebSocketDisconnect
from app.core.logging_config import websocket_logger

logger = websocket_logger

class RawPriceBroadcaster:
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client
        self.active_connections: Set[WebSocket] = set()
        self.symbols_to_broadcast = {
            'AUDJPY', 'AUDCAD', 'AUDUSD', 'JP225', 'US30',
            'D30', 'CADJPY', 'BTCUSD', 'XAUUSD', 'XAGUSD'
        }
        self._subscriber_task = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        if len(self.active_connections) == 1:
            # Start subscriber when first client connects
            self._subscriber_task = asyncio.create_task(self._subscriber())

    async def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        if not self.active_connections and self._subscriber_task:
            # Stop subscriber when last client disconnects
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
            self._subscriber_task = None

    async def broadcast(self, message: str):
        """Broadcasts message to all connected clients."""
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except WebSocketDisconnect:
                disconnected.add(connection)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.add(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            await self.disconnect(connection)

    async def _subscriber(self):
        """
        Listens to the Redis market data channel and broadcasts filtered data.
        """
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(REDIS_MARKET_DATA_CHANNEL)
        logger.info(f"RawPriceBroadcaster subscribed to '{REDIS_MARKET_DATA_CHANNEL}' for symbols: {self.symbols_to_broadcast}")

        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    try:
                        market_data = json.loads(message['data'])
                        # Filter the data to only include the symbols we want to broadcast
                        filtered_data = {
                            symbol: prices
                            for symbol, prices in market_data.items()
                            if symbol.upper() in self.symbols_to_broadcast
                            and isinstance(prices, dict)  # Ensure we have valid price data
                            and ('b' in prices or 'o' in prices)  # Ensure we have at least one price
                        }

                        if filtered_data:
                            # Format the data for public consumption
                            public_data = {
                                symbol: {
                                    'bid': prices.get('b', prices.get('bid')),
                                    'ask': prices.get('o', prices.get('ask')),
                                    'timestamp': market_data.get('_timestamp', None)
                                }
                                for symbol, prices in filtered_data.items()
                            }
                            await self.broadcast(json.dumps(public_data))

                    except json.JSONDecodeError:
                        logger.warning(f"Could not decode JSON from Redis message: {message['data']}")
                    except Exception as e:
                        logger.error(f"Error processing Redis message in RawPriceBroadcaster: {e}", exc_info=True)

            except asyncio.CancelledError:
                logger.info("RawPriceBroadcaster subscriber task cancelled.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in RawPriceBroadcaster subscriber: {e}", exc_info=True)
                await asyncio.sleep(5)  # Avoid tight loop on persistent errors
