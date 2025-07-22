# app/core/firebase.py

import logging
import json
from typing import Dict, Any, Optional
import decimal
from datetime import datetime

# Ensure firebase_admin is initialized and imported correctly
try:
    import firebase_admin
    from firebase_admin import db, firestore, credentials
except ImportError as e:
    raise ImportError("firebase_admin is not installed or not accessible: " + str(e))

try:
    from app.firebase_stream import firebase_db
except ImportError as e:
    raise ImportError("Could not import firebase_db from app.firebase_stream: " + str(e))

# Initialize firebase_admin lazily
_firebase_initialized = False

def _ensure_firebase_initialized():
    """Ensure Firebase is initialized before use."""
    global _firebase_initialized
    if not _firebase_initialized:
        import os
        service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH")
        database_url = os.getenv("FIREBASE_DATABASE_URL")

        if not service_account_path:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_KEY_PATH is not set in environment or .env file!")
        if not database_url:
            raise RuntimeError("FIREBASE_DATABASE_URL is not set in environment or .env file!")

        if not firebase_admin._apps:
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred, {'databaseURL': database_url})
        
        _firebase_initialized = True

# Import the specialized firebase communication logger
from app.core.logging_config import firebase_comm_logger

def _stringify_value(value: Any) -> str:
    """
    Converts a single value to its string representation.
    Handles None, numbers (including Decimal), dicts/lists (with nested Decimal handling).
    """
    if value is None:
        return ""
    if isinstance(value, (decimal.Decimal, float, int)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)

import asyncio

async def send_order_to_firebase(order_data: Dict[str, Any], account_type: str = "live", delete_after_seconds: int = 1) -> bool:
    try:
        _ensure_firebase_initialized()
        # Log outgoing order data
        firebase_comm_logger.info(f"OUTGOING ORDER DATA: {json.dumps(order_data, default=str)}")
        
        payload = {k: _stringify_value(v) for k, v in order_data.items()}
        payload["account_type"] = account_type
        payload["timestamp"] = _stringify_value(datetime.utcnow().isoformat())
        
        # Log the actual payload being sent
        firebase_comm_logger.info(f"FIREBASE PUSH: trade_data/{account_type} - {json.dumps(payload, default=str)}")
        
        firebase_database_ref = db.reference("trade_data")
        push_result = firebase_database_ref.push(payload)
        
        if push_result and hasattr(push_result, 'key'):
            firebase_comm_logger.info(f"FIREBASE PUSH RESULT: Key={push_result.key}")
        
        log_order_id = order_data.get('order_id') or order_data.get('user_id', 'N/A')

        if delete_after_seconds > 0:
            async def delayed_delete():
                await asyncio.sleep(delete_after_seconds)
                push_result.delete()
                firebase_comm_logger.info(f"FIREBASE DELETE: Deleted order data (ID: {log_order_id}) after {delete_after_seconds} seconds")
            asyncio.create_task(delayed_delete())

        return True
    except Exception as e:
        error_msg = f"Error sending order data to Firebase (ID: {order_data.get('order_id', 'N/A')}): {e}"
        firebase_comm_logger.error(f"FIREBASE ERROR: {error_msg}", exc_info=True)
        return False

async def get_latest_market_data(symbol: str = None) -> Optional[Dict[str, Any]]:
    try:
        _ensure_firebase_initialized()
        ref = db.reference('datafeeds')
        if symbol:
            firebase_comm_logger.debug(f"FIREBASE GET: datafeeds/{symbol.upper()}")
            data = ref.child(symbol.upper()).get()
            firebase_comm_logger.debug(f"FIREBASE RESPONSE: datafeeds/{symbol.upper()} - {json.dumps(data, default=str)}")
            return data
        else:
            firebase_comm_logger.debug(f"FIREBASE GET: datafeeds (all symbols)")
            data = ref.get()
            firebase_comm_logger.debug(f"FIREBASE RESPONSE: datafeeds - received data for {len(data) if data else 0} symbols")
            return data
    except Exception as e:
        error_msg = f"Error getting market data from Firebase: {e}"
        firebase_comm_logger.error(f"FIREBASE ERROR: {error_msg}", exc_info=True)
        return None

def get_latest_market_data_sync(symbol: str = None) -> Optional[Dict[str, Any]]:
    try:
        _ensure_firebase_initialized()
        ref = db.reference('datafeeds')
        if symbol:
            firebase_comm_logger.debug(f"FIREBASE GET (sync): datafeeds/{symbol.upper()}")
            data = ref.child(symbol.upper()).get()
            firebase_comm_logger.debug(f"FIREBASE RESPONSE (sync): datafeeds/{symbol.upper()} - {json.dumps(data, default=str)}")
            return data
        else:
            firebase_comm_logger.debug(f"FIREBASE GET (sync): datafeeds (all symbols)")
            data = ref.get()
            firebase_comm_logger.debug(f"FIREBASE RESPONSE (sync): datafeeds - received data for {len(data) if data else 0} symbols")
            return data
    except Exception as e:
        error_msg = f"Error getting market data from Firebase: {e}"
        firebase_comm_logger.error(f"FIREBASE ERROR (sync): {error_msg}", exc_info=True)
        return None