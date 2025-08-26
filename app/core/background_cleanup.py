"""
Background cleanup service for expired idempotency keys.
Automatically removes expired keys from the database.
"""

import asyncio
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.core.idempotency import IdempotencyService

logger = logging.getLogger(__name__)

class BackgroundCleanupService:
    """Service to handle background cleanup of expired idempotency keys."""
    
    def __init__(self, cleanup_interval: int = 300):  # 5 minutes default
        self.cleanup_interval = cleanup_interval
        self.is_running = False
        self._task = None
    
    async def start_cleanup_task(self):
        """Start the background cleanup task."""
        if self.is_running:
            logger.warning("Cleanup task is already running")
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"Started idempotency cleanup task with {self.cleanup_interval}s interval")
    
    async def stop_cleanup_task(self):
        """Stop the background cleanup task."""
        if not self.is_running:
            return
        
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped idempotency cleanup task")
    
    async def _cleanup_loop(self):
        """Main cleanup loop that runs periodically."""
        while self.is_running:
            try:
                # Get database session
                async for db in get_db():
                    try:
                        deleted_count = await IdempotencyService.cleanup_expired_keys(db)
                        if deleted_count > 0:
                            logger.info(f"Background cleanup removed {deleted_count} expired idempotency keys")
                        break
                    except Exception as e:
                        logger.error(f"Error during background cleanup: {e}")
                    finally:
                        await db.close()
                
                # Wait for next cleanup cycle
                await asyncio.sleep(self.cleanup_interval)
                
            except asyncio.CancelledError:
                logger.info("Cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in cleanup loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying

# Global cleanup service instance
cleanup_service = BackgroundCleanupService()

async def start_background_cleanup():
    """Start the background cleanup service."""
    await cleanup_service.start_cleanup_task()

async def stop_background_cleanup():
    """Stop the background cleanup service."""
    await cleanup_service.stop_cleanup_task()
