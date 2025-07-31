# OTP System Migration: Redis to Database

## Overview

The OTP system has been migrated from Redis-based storage to database storage to resolve the "invalid OTP" issues and provide better consistency and reliability.

## Changes Made

### 1. **New Database Model: SignupOTP**

Added a new `SignupOTP` model in `app/database/models.py`:

```python
class SignupOTP(Base):
    __tablename__ = "signup_otps"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    user_type = Column(String(20), nullable=False) # 'live' or 'demo'
    otp_code = Column(String(10), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    demo_user_id = Column(Integer, ForeignKey("demo_users.id"), index=True, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="signup_otps")
    demo_user = relationship("DemoUser", back_populates="signup_otps")
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('email', 'user_type', name='_signup_otp_email_user_type_uc'),
    )
```

### 2. **Enhanced CRUD Operations**

Added new functions in `app/crud/otp.py`:

- `create_signup_otp()`: Creates SignupOTP records for new email signups
- `get_valid_signup_otp()`: Retrieves valid SignupOTP records
- `verify_signup_otp()`: Marks SignupOTP as verified
- `delete_signup_otp()`: Deletes SignupOTP records
- `cleanup_expired_signup_otps()`: Cleans up expired records

### 3. **Updated API Endpoints**

Modified both live and demo OTP endpoints in `app/api/v1/endpoints/users.py`:

#### Before (Redis-based):
```python
# Store in Redis
redis_key = f"signup_otp:{email}:{user_type}"
await redis_client.set(redis_key, otp_code, ex=expiry)

# Verify from Redis
stored_otp = await redis_client.get(redis_key)
if stored_otp == otp_code:
    # Verification successful
```

#### After (Database-based):
```python
# Store in Database
await crud_otp.create_signup_otp(db, email=email, user_type=user_type, force_otp_code=otp_code)

# Verify from Database
signup_otp = await crud_otp.get_valid_signup_otp(db, email=email, user_type=user_type, otp_code=otp_code)
if signup_otp:
    await crud_otp.verify_signup_otp(db, signup_otp)
    # Verification successful
```

### 4. **Database Migration**

Created migration script `migrations/create_signup_otp_table.py` to:
- Create the `signup_otps` table
- Add proper indexes and constraints
- Clean up old Redis OTP keys (optional)

## Benefits of Database Migration

### 1. **Consistency**
- All OTP data stored in one place (database)
- No more Redis/Database synchronization issues
- Consistent user type handling

### 2. **Reliability**
- Database transactions ensure data integrity
- No Redis connection failures affecting OTP verification
- Better error handling and logging

### 3. **Debugging**
- Easy to query and inspect OTP records
- Comprehensive logging for all OTP operations
- Better audit trail

### 4. **Scalability**
- Database can handle larger OTP volumes
- Better indexing for performance
- Automatic cleanup of expired OTPs

## How It Works

### 1. **OTP Generation Flow**
```
User requests OTP → Check if user exists → 
If existing inactive user → Create OTP in 'otps' table
If new email → Create SignupOTP in 'signup_otps' table
```

### 2. **OTP Verification Flow**
```
User submits OTP → Check SignupOTP table first → 
If found → Mark as verified and delete
If not found → Check 'otps' table for existing users
If found → Activate user and delete OTP
If not found → Return "Invalid OTP" error
```

### 3. **User Type Handling**
- **Live Users**: Stored in `users` table with `user_type = "live"`
- **Demo Users**: Stored in `demo_users` table (implicitly `user_type = "demo"`)
- **SignupOTP**: Links to both user types via `user_id` or `demo_user_id`

## Migration Steps

### 1. **Run Database Migration**
```bash
python migrations/create_signup_otp_table.py
```

### 2. **Update Application Code**
The code changes have already been made:
- ✅ Updated `models.py` with SignupOTP model
- ✅ Updated `crud/otp.py` with new functions
- ✅ Updated API endpoints in `users.py`

### 3. **Test the New System**
```bash
# Test OTP generation
curl -X POST "http://localhost:8000/api/v1/users/signup/send-otp" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "user_type": "live"}'

# Test OTP verification
curl -X POST "http://localhost:8000/api/v1/users/signup/verify-otp" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "user_type": "live", "otp_code": "123456"}'
```

## Monitoring and Maintenance

### 1. **Database Queries for Monitoring**
```sql
-- Check active SignupOTPs
SELECT email, user_type, created_at, expires_at 
FROM signup_otps 
WHERE expires_at > NOW() AND is_verified = FALSE;

-- Check verified SignupOTPs
SELECT email, user_type, verified_at 
FROM signup_otps 
WHERE is_verified = TRUE 
ORDER BY verified_at DESC;

-- Clean up expired OTPs
DELETE FROM signup_otps WHERE expires_at <= NOW();
```

### 2. **Log Monitoring**
The system now logs all OTP operations:
- OTP generation: `SIGNUP_OTP_CREATED`
- OTP verification: `SIGNUP_OTP_VERIFIED`
- OTP failures: `SIGNUP_OTP_VERIFICATION_FAILED`

### 3. **Automatic Cleanup**
Consider setting up a scheduled task to clean up expired OTPs:
```python
# Run this periodically
await crud_otp.cleanup_expired_signup_otps(db)
```

## Rollback Plan

If needed, the system can be rolled back by:
1. Reverting the code changes
2. Dropping the `signup_otps` table
3. Re-enabling Redis-based OTP storage

## Conclusion

This migration resolves the "invalid OTP" issues by:
1. **Eliminating Redis/Database confusion**: All OTPs now stored in database
2. **Improving user type handling**: Consistent user type logic
3. **Enhancing debugging**: Better logging and database queries
4. **Increasing reliability**: No Redis connection dependencies

The new system is more robust, easier to debug, and provides better consistency for OTP operations. 