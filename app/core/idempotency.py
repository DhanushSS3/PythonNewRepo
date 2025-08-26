"""
Idempotency service for preventing duplicate operations.
Handles backend-generated idempotency keys for order placement and closure operations.
Features 5-second TTL for preventing accidental duplicate orders.
"""

import hashlib
import json
import orjson
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from fastapi import HTTPException

from app.database.models import IdempotencyKeys
from app.core.logging_config import orders_logger


class IdempotencyService:
    """Service for handling backend-generated idempotency keys and deduplication."""
    
    @staticmethod
    def generate_backend_key(request_data: Dict[str, Any], user_id: int, endpoint: str) -> str:
        """
        Generate a backend idempotency key based on request content.
        This creates a unique key for identical requests within the TTL window.
        """
        # Create a normalized version of the request for hashing
        normalized_data = {
            "user_id": user_id,
            "endpoint": endpoint,
            **request_data
        }
        # Sort keys to ensure consistent hashing
        normalized_json = json.dumps(normalized_data, sort_keys=True, default=str)
        hash_value = hashlib.sha256(normalized_json.encode()).hexdigest()
        return f"backend_{endpoint}_{user_id}_{hash_value[:16]}"
    
    @staticmethod
    def generate_request_hash(request_data: Dict[str, Any], user_id: int, user_type: str) -> str:
        """Generate a SHA256 hash of the request payload for deduplication."""
        # Create a normalized version of the request for hashing
        normalized_data = {
            "user_id": user_id,
            "user_type": user_type,
            **request_data
        }
        # Sort keys to ensure consistent hashing
        normalized_json = json.dumps(normalized_data, sort_keys=True, default=str)
        return hashlib.sha256(normalized_json.encode()).hexdigest()
    
    @staticmethod
    async def check_duplicate_request(
        db: AsyncSession,
        idempotency_key: str,
        user_id: int,
        user_type: str,
        endpoint: str
    ) -> Optional["IdempotencyKeys"]:
        """
        Check if a duplicate request exists within the TTL window.
        
        Args:
            db: Database session
            idempotency_key: The backend-generated idempotency key
            user_id: User ID making the request
            user_type: User type ('live' or 'demo')
            endpoint: Endpoint name ('place_order' or 'close_order')
            
        Returns:
            IdempotencyKeys: The created record if duplicate found, None otherwise
        """
        try:
            # First, clean up expired records
            await IdempotencyService.cleanup_expired_keys(db)
            
            result = await db.execute(
                select(IdempotencyKeys).where(
                    and_(
                        IdempotencyKeys.idempotency_key == idempotency_key,
                        IdempotencyKeys.user_id == user_id,
                        IdempotencyKeys.user_type == user_type,
                        IdempotencyKeys.endpoint_name == endpoint,
                        IdempotencyKeys.expires_at > datetime.utcnow()
                    )
                )
            )
            existing_key = result.scalar_one_or_none()
            
            if existing_key:
                orders_logger.info(f"Duplicate request detected: {idempotency_key}, status: {existing_key.status}")
                return existing_key
            
            return None
            
        except Exception as e:
            orders_logger.error(f"Error checking duplicate request: {str(e)}")
            raise
    
    @staticmethod
    async def cleanup_expired_keys(db: AsyncSession) -> int:
        """
        Clean up expired idempotency keys from the database.
        Returns the number of keys cleaned up.
        """
        try:
            from app.database.models import IdempotencyKeys
            current_time = datetime.utcnow()
            
            # Delete expired keys
            delete_stmt = delete(IdempotencyKeys).where(
                IdempotencyKeys.expires_at < current_time
            )
            result = await db.execute(delete_stmt)
            await db.commit()
            
            deleted_count = result.rowcount
            orders_logger.info(f"Cleaned up {deleted_count} expired idempotency keys")
            return deleted_count
            
        except Exception as e:
            orders_logger.error(f"Error cleaning up expired idempotency keys: {e}")
            await db.rollback()
            return 0
    
    @staticmethod
    async def create_idempotency_record(
        db: AsyncSession,
        idempotency_key: str,
        user_id: int,
        user_type: str,
        endpoint: str,
        request_hash: str,
        ttl_seconds: int = 5
    ) -> "IdempotencyKeys":
        """
        Create a new idempotency key record with short TTL for duplicate prevention.
        
        Args:
            db: Database session
            idempotency_key: The backend-generated idempotency key
            user_id: User ID making the request
            user_type: User type ('live' or 'demo')
            endpoint: Endpoint name
            request_hash: Hash of the request payload
            ttl_seconds: Time to live in seconds (default 5)
            
        Returns:
            Created IdempotencyKey record
        """
        try:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        
            new_record = IdempotencyKeys(
                idempotency_key=idempotency_key,
                user_id=user_id,
                user_type=user_type,
                endpoint_name=endpoint,
                status='processing',
                expires_at=expires_at
            )
            
            db.add(new_record)
            await db.commit()
            await db.refresh(new_record)
            
            orders_logger.info(f"Created 5-second TTL idempotency record: {idempotency_key}")
            return new_record
            
        except Exception as e:
            await db.rollback()
            orders_logger.error(f"Error creating idempotency record: {str(e)}")
            raise
    
    @staticmethod
    async def update_idempotency_record(
        db: AsyncSession,
        idempotency_record: "IdempotencyKeys",
        status: str,
        response_data: Optional[Dict[str, Any]] = None,
        order_id: Optional[str] = None
    ) -> None:
        """
        Update an idempotency record with the operation result.
        
        Args:
            db: Database session
            idempotency_record: The idempotency record to update
            status: New status ('completed', 'failed')
            response_data: Response data to store for replay
            order_id: Associated order ID if successful
        """
        try:
            idempotency_record.status = status
            if response_data:
                idempotency_record.response_data = orjson.dumps(response_data).decode()
            if order_id:
                idempotency_record.reference_id = order_id
            
            await db.commit()
            orders_logger.info(f"Updated idempotency record: {idempotency_record.idempotency_key}, status: {status}")
            
        except Exception as e:
            await db.rollback()
            orders_logger.error(f"Error updating idempotency record: {str(e)}")
            raise
    
    @staticmethod
    def handle_duplicate_request(existing_key: IdempotencyKeys) -> None:
        """
        Handle a duplicate request by rejecting it.
        
        Args:
            existing_key: The existing idempotency key record
            
        Raises:
            HTTPException: Always raises 429 Too Many Requests for duplicates
        """
        orders_logger.warning(f"Rejecting duplicate request: {existing_key.idempotency_key}, created at: {existing_key.created_at}")
        raise HTTPException(
            status_code=429,
            detail="Duplicate order request detected. Please wait 5 seconds before placing the same order again."
        )


async def handle_backend_idempotency(
    db: AsyncSession,
    user_id: int,
    user_type: str,
    endpoint: str,
    request_data: Dict[str, Any]
) -> Optional[IdempotencyKeys]:
    """
    Main backend idempotency handler function for preventing duplicate orders.
    
    Args:
        db: Database session
        user_id: User ID making the request
        user_type: User type ('live' or 'demo')
        endpoint: Endpoint name ('place_order' or 'close_order')
        request_data: The request payload data
        
    Returns:
        IdempotencyKey record if created, None if duplicate detected (raises HTTPException)
    """
    # Generate backend idempotency key
    idempotency_key = IdempotencyService.generate_backend_key(
        request_data, user_id, endpoint
    )
    
    # Check for duplicate request
    existing_key = await IdempotencyService.check_duplicate_request(
        db, idempotency_key, user_id, user_type, endpoint
    )
    
    if existing_key:
        # Reject duplicate request
        IdempotencyService.handle_duplicate_request(existing_key)
    
    # Generate request hash for record keeping
    request_hash = IdempotencyService.generate_request_hash(request_data, user_id, user_type)
    
    # Create new idempotency record
    return await IdempotencyService.create_idempotency_record(
        db, idempotency_key, user_id, user_type, endpoint, request_hash, ttl_seconds=5
    )


# Legacy function kept for backward compatibility
async def handle_idempotency(
    db: AsyncSession,
    idempotency_key: Optional[str],
    user_id: int,
    user_type: str,
    endpoint: str,
    request_data: Dict[str, Any]
) -> tuple[Optional[IdempotencyKeys], Optional[Dict[str, Any]]]:
    """
    Legacy idempotency handler function (kept for backward compatibility).
    Use handle_backend_idempotency for new implementations.
    """
    if not idempotency_key:
        return None, None
    
    request_hash = IdempotencyService.generate_request_hash(request_data, user_id, user_type)
    
    # Use the old check method for legacy support
    result = await db.execute(
        select(IdempotencyKeys).where(
            IdempotencyKeys.idempotency_key == idempotency_key
        )
    )
    existing_key = result.scalar_one_or_none()
    
    if existing_key:
        if existing_key.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key already used for a different request"
            )
        
        if existing_key.status == 'completed' and existing_key.response_data:
            try:
                response_data = orjson.loads(existing_key.response_data)
                return existing_key, response_data
            except:
                return existing_key, {"message": "Operation completed successfully"}
    
    idempotency_record = await IdempotencyService.create_idempotency_record(
        db, idempotency_key, user_id, endpoint, request_hash, ttl_seconds=86400  # 24 hours for legacy
    )
    
    return idempotency_record, None
