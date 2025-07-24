from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.core.security import get_current_admin_user
from app.database.models import User
from app.schemas.wallet import AdminWalletActionRequest, AdminWalletActionResponse
from app.crud.wallet import add_funds_to_wallet, withdraw_funds_from_wallet
from app.core.cache import get_last_known_price, DecimalEncoder, REDIS_MARKET_DATA_CHANNEL
from app.dependencies.redis_client import get_redis_client
from app.core.security import get_current_admin_user
from app.firebase_stream import get_latest_market_data
import json
import asyncio
import logging

logger = logging.getLogger("admin_raw_market_data_ws")

router = APIRouter()

@router.post("/admin/wallet/add-funds", response_model=AdminWalletActionResponse)
async def admin_add_funds(
    req: AdminWalletActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    try:
        balance = await add_funds_to_wallet(db, req.user_id, req.amount, req.currency, req.reason, by_admin=True)
        return AdminWalletActionResponse(status=True, message="Funds added successfully", balance=balance)
    except Exception as e:
        if str(e) == "User not found":
            raise HTTPException(status_code=404, detail="User not found")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/admin/wallet/withdraw-funds", response_model=AdminWalletActionResponse)
async def admin_withdraw_funds(
    req: AdminWalletActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    try:
        wallet_balance = await withdraw_funds_from_wallet(db, req.user_id, req.amount, req.currency, req.reason, by_admin=True)
        return AdminWalletActionResponse(status=True, message="Funds withdrawn successfully", balance=wallet_balance)
    except Exception as e:
        if str(e) == "User not found":
            raise HTTPException(status_code=404, detail="User not found")
        raise HTTPException(status_code=400, detail=str(e))

@router.websocket("/ws/admin/raw-market-data")
async def admin_raw_market_data_websocket(
    websocket: WebSocket,
    redis_client = Depends(get_redis_client),
    db: AsyncSession = Depends(get_db)
):
    # 1. Extract token from query params
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401, reason="Missing token")
        return

    # 2. Clean up token
    token = token.strip('"').strip("'").replace('%22', '').replace('%27', '')

    # 3. Decode and validate token
    from app.core.security import decode_token
    from jose import JWTError, ExpiredSignatureError
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        user_type = payload.get("user_type")
        if user_type != "admin":
            await websocket.close(code=4403, reason="Not authorized (not admin)")
            return
        # Fetch user from DB and check isActive
        from app.database.models import User
        from sqlalchemy.future import select
        result = await db.execute(select(User).filter(User.id == int(user_id), User.user_type == "admin"))
        user = result.scalars().first()
        if not user or not getattr(user, "isActive", 1):
            await websocket.close(code=4403, reason="Admin not found or inactive")
            return
    except ExpiredSignatureError:
        await websocket.close(code=4401, reason="Token expired")
        return
    except JWTError:
        await websocket.close(code=4401, reason="Invalid token")
        return
    except Exception:
        await websocket.close(code=4401, reason="Auth error")
        return

    # IMPORTANT: Accept the WebSocket connection AFTER successful authentication
    await websocket.accept()

    # --- Initial snapshot: last_known_price cache ---
    snapshot = {}
    firebase_snapshot = get_latest_market_data()
    def convert_bo_to_buy_sell(prices):
        if not isinstance(prices, dict):
            return prices
        new_prices = {}
        for k, v in prices.items():
            if k == 'b':
                new_prices['sell'] = v
            elif k == 'o':
                new_prices['buy'] = v
            else:
                new_prices[k] = v
        return new_prices
    if firebase_snapshot:
        for symbol, prices in firebase_snapshot.items():
            last_price = await get_last_known_price(redis_client, symbol)
            if last_price:
                snapshot[symbol] = convert_bo_to_buy_sell(last_price)
            else:
                snapshot[symbol] = convert_bo_to_buy_sell(prices)
    # No 'else: pass' needed here, it's implicitly handled if firebase_snapshot is empty
    # Send initial snapshot
    await websocket.send_text(json.dumps({
        "type": "update",
        "data": snapshot
    }, cls=DecimalEncoder))

    # --- Live updates: subscribe to Redis channel for raw market data ---
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(REDIS_MARKET_DATA_CHANNEL)
    try:
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    try:
                        market_data = json.loads(message['data'])
                        # Convert all price dicts in market_data
                        converted_market_data = {symbol: convert_bo_to_buy_sell(prices) for symbol, prices in market_data.items()}
                        await websocket.send_text(json.dumps({
                            "type": "update",
                            "data": converted_market_data
                        }, cls=DecimalEncoder))
                    except (WebSocketDisconnect, RuntimeError):
                        logger.info("Admin disconnected from raw market data websocket (send).")
                        break  # Exit the loop on disconnect
                    except Exception as e:
                        logger.error(f"Error processing Redis message: {e}", exc_info=True)
                await asyncio.sleep(0.01)
            except (WebSocketDisconnect, RuntimeError):
                logger.info("Admin disconnected from raw market data websocket (outer).")
                break  # Exit the loop on disconnect
            except asyncio.CancelledError:
                logger.info("WebSocket task cancelled.")
                break
    except Exception as e:
        logger.error(f"Error in admin raw market data websocket: {e}", exc_info=True)
    finally:
        await pubsub.unsubscribe(REDIS_MARKET_DATA_CHANNEL)
        await pubsub.close()