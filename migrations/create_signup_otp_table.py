"""
Migration script to create the signup_otps table.
This replaces Redis-based OTP storage with database storage.
"""

import asyncio
import sys
import os
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Add the app directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.join(current_dir, '..', 'app')
sys.path.insert(0, app_dir)

from core.config import get_settings

settings = get_settings()

async def create_signup_otp_table():
    """
    Creates the signup_otps table in the database.
    """
    # Create async engine using the correct database URL attribute
    engine = create_async_engine(settings.ASYNC_DATABASE_URL)
    
    async with engine.begin() as conn:
        # Create the signup_otps table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS signup_otps (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                user_type VARCHAR(20) NOT NULL,
                otp_code VARCHAR(10) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                is_verified BOOLEAN DEFAULT FALSE,
                verified_at DATETIME NULL,
                user_id INT NULL,
                demo_user_id INT NULL,
                INDEX idx_email_user_type (email, user_type),
                INDEX idx_user_id (user_id),
                INDEX idx_demo_user_id (demo_user_id),
                INDEX idx_expires_at (expires_at),
                UNIQUE KEY unique_email_user_type (email, user_type),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (demo_user_id) REFERENCES demo_users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """))
        
        print("✅ signup_otps table created successfully!")
    
    await engine.dispose()

async def cleanup_old_redis_otp_keys():
    """
    Optional: Clean up old Redis OTP keys if needed.
    This function can be used to clean up any existing Redis OTP keys.
    """
    try:
        from dependencies.redis_client import get_redis_client
        redis_client = await get_redis_client().__anext__()
        
        # Get all signup OTP keys
        keys = await redis_client.keys("signup_otp:*")
        if keys:
            await redis_client.delete(*keys)
            print(f"✅ Cleaned up {len(keys)} old Redis OTP keys")
        else:
            print("ℹ️  No old Redis OTP keys found to clean up")
            
        await redis_client.close()
    except Exception as e:
        print(f"⚠️  Warning: Could not clean up Redis keys: {e}")

async def main():
    """
    Main migration function.
    """
    print("🚀 Starting SignupOTP table migration...")
    
    try:
        # Create the new table
        await create_signup_otp_table()
        
        # Optional: Clean up old Redis keys
        await cleanup_old_redis_otp_keys()
        
        print("✅ Migration completed successfully!")
        print("\n📋 Summary:")
        print("- Created signup_otps table")
        print("- Added proper indexes and constraints")
        print("- Updated OTP endpoints to use database instead of Redis")
        print("- Added comprehensive logging for OTP operations")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 