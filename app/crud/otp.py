# app/crud/otp.py
import datetime
import random
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete

from app.database.models import OTP, SignupOTP, User, DemoUser # Import SignupOTP
from app.core.config import get_settings
from app.core.logging_config import otp_generation_logger, otp_verification_logger, otp_failed_attempts_logger

settings = get_settings()

def generate_otp_code(length: int = 6) -> str:
    """
    Generates a random OTP code and logs the generation.
    """
    otp_code = "".join(random.choices("0123456789", k=length))
    
    # Log OTP generation
    otp_generation_logger.info(
        f"OTP_GENERATED - Code: {otp_code} | Length: {length} | "
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    return otp_code

async def create_otp(
    db: AsyncSession,
    user_id: Optional[int] = None,
    demo_user_id: Optional[int] = None,
    force_otp_code: Optional[str] = None
) -> OTP:
    """
    Creates a new OTP record, associating it with either a regular user or a demo user.
    Deletes any existing OTPs for the specified user/demo user.
    """
    if user_id and demo_user_id:
        raise ValueError("OTP record cannot be associated with both a user and a demo user.")
    if not user_id and not demo_user_id:
        raise ValueError("OTP record must be associated with either a user or a demo user.")

    # Delete existing OTPs for the specified user/demo user
    if user_id:
        await db.execute(delete(OTP).where(OTP.user_id == user_id))
    elif demo_user_id:
        await db.execute(delete(OTP).where(OTP.demo_user_id == demo_user_id))

    otp_code_to_use = force_otp_code if force_otp_code else generate_otp_code()
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.OTP_EXPIRATION_MINUTES)

    db_otp = OTP(
        user_id=user_id,
        demo_user_id=demo_user_id, # Assign demo_user_id if present
        otp_code=otp_code_to_use,
        expires_at=expires_at
    )

    db.add(db_otp)
    await db.commit()
    await db.refresh(db_otp)

    # Log OTP creation
    user_type = "demo" if demo_user_id else "live"
    user_identifier = demo_user_id if demo_user_id else user_id
    
    otp_generation_logger.info(
        f"OTP_CREATED - Code: {otp_code_to_use} | User Type: {user_type} | "
        f"User ID: {user_identifier} | Expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    return db_otp

async def create_signup_otp(
    db: AsyncSession,
    email: str,
    user_type: str,
    user_id: Optional[int] = None,
    demo_user_id: Optional[int] = None,
    force_otp_code: Optional[str] = None
) -> SignupOTP:
    """
    Creates a new SignupOTP record for new email signups.
    Replaces Redis-based OTP storage.
    """
    # Delete any existing signup OTPs for this email and user_type
    await db.execute(delete(SignupOTP).where(
        SignupOTP.email == email,
        SignupOTP.user_type == user_type
    ))

    otp_code_to_use = force_otp_code if force_otp_code else generate_otp_code()
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.OTP_EXPIRATION_MINUTES)

    db_signup_otp = SignupOTP(
        email=email,
        user_type=user_type,
        user_id=user_id,
        demo_user_id=demo_user_id,
        otp_code=otp_code_to_use,
        expires_at=expires_at,
        is_verified=False
    )

    db.add(db_signup_otp)
    await db.commit()
    await db.refresh(db_signup_otp)

    # Log SignupOTP creation
    user_identifier = demo_user_id if demo_user_id else user_id
    otp_generation_logger.info(
        f"SIGNUP_OTP_CREATED - Code: {otp_code_to_use} | Email: {email} | User Type: {user_type} | "
        f"User ID: {user_identifier} | Expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    return db_signup_otp

async def get_valid_otp(
    db: AsyncSession,
    otp_code: str,
    user_id: Optional[int] = None,
    demo_user_id: Optional[int] = None
) -> Optional[OTP]:
    """
    Retrieves a valid OTP for a given user_id or demo_user_id and OTP code.
    """
    if user_id and demo_user_id:
        raise ValueError("Cannot validate OTP for both a user and a demo user simultaneously.")
    if not user_id and not demo_user_id:
        raise ValueError("OTP validation requires either a user_id or a demo_user_id.")

    current_time = datetime.datetime.utcnow()
    query = select(OTP).filter(
        OTP.otp_code == otp_code,
        OTP.expires_at > current_time
    )

    if user_id:
        query = query.filter(OTP.user_id == user_id)
    elif demo_user_id:
        query = query.filter(OTP.demo_user_id == demo_user_id)

    result = await db.execute(query)
    otp_record = result.scalars().first()
    
    # Log OTP verification attempt
    user_type = "demo" if demo_user_id else "live"
    user_identifier = demo_user_id if demo_user_id else user_id
    
    if otp_record:
        otp_verification_logger.info(
            f"OTP_VERIFIED - Code: {otp_code} | User Type: {user_type} | "
            f"User ID: {user_identifier} | Valid: True | "
            f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        otp_failed_attempts_logger.warning(
            f"OTP_VERIFICATION_FAILED - Code: {otp_code} | User Type: {user_type} | "
            f"User ID: {user_identifier} | Valid: False | "
            f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    return otp_record

async def get_valid_signup_otp(
    db: AsyncSession,
    email: str,
    user_type: str,
    otp_code: str
) -> Optional[SignupOTP]:
    """
    Retrieves a valid SignupOTP for a given email, user_type, and OTP code.
    """
    current_time = datetime.datetime.utcnow()
    query = select(SignupOTP).filter(
        SignupOTP.email == email,
        SignupOTP.user_type == user_type,
        SignupOTP.otp_code == otp_code,
        SignupOTP.expires_at > current_time,
        SignupOTP.is_verified == False
    )

    result = await db.execute(query)
    signup_otp_record = result.scalars().first()
    
    # Log SignupOTP verification attempt
    if signup_otp_record:
        otp_verification_logger.info(
            f"SIGNUP_OTP_VERIFIED - Code: {otp_code} | Email: {email} | User Type: {user_type} | "
            f"Valid: True | Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        otp_failed_attempts_logger.warning(
            f"SIGNUP_OTP_VERIFICATION_FAILED - Code: {otp_code} | Email: {email} | User Type: {user_type} | "
            f"Valid: False | Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    return signup_otp_record

async def verify_signup_otp(
    db: AsyncSession,
    signup_otp: SignupOTP
) -> None:
    """
    Marks a SignupOTP as verified.
    """
    signup_otp.is_verified = True
    signup_otp.verified_at = datetime.datetime.utcnow()
    await db.commit()
    
    otp_verification_logger.info(
        f"SIGNUP_OTP_MARKED_VERIFIED - Email: {signup_otp.email} | User Type: {signup_otp.user_type} | "
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

async def delete_otp(db: AsyncSession, otp_id: int):
    """
    Deletes an OTP record by its ID.
    """
    await db.execute(delete(OTP).where(OTP.id == otp_id))
    await db.commit()
    
    # Log OTP deletion
    otp_generation_logger.info(
        f"OTP_DELETED - OTP ID: {otp_id} | "
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

async def delete_signup_otp(db: AsyncSession, signup_otp_id: int):
    """
    Deletes a SignupOTP record by its ID.
    """
    await db.execute(delete(SignupOTP).where(SignupOTP.id == signup_otp_id))
    await db.commit()
    
    # Log SignupOTP deletion
    otp_generation_logger.info(
        f"SIGNUP_OTP_DELETED - SignupOTP ID: {signup_otp_id} | "
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

async def delete_all_user_otps(db: AsyncSession, user_id: int):
    """
    Deletes all OTP records for a specific regular user.
    """
    await db.execute(delete(OTP).where(OTP.user_id == user_id))
    await db.commit()
    
    # Log bulk OTP deletion
    otp_generation_logger.info(
        f"ALL_OTPS_DELETED - User ID: {user_id} | User Type: live | "
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

async def delete_all_demo_user_otps(db: AsyncSession, demo_user_id: int):
    """
    Deletes all OTP records for a specific demo user.
    """
    await db.execute(delete(OTP).where(OTP.demo_user_id == demo_user_id))
    await db.commit()
    
    # Log bulk OTP deletion for demo user
    otp_generation_logger.info(
        f"ALL_OTPS_DELETED - Demo User ID: {demo_user_id} | User Type: demo | "
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

async def cleanup_expired_signup_otps(db: AsyncSession):
    """
    Deletes all expired SignupOTP records.
    """
    current_time = datetime.datetime.utcnow()
    await db.execute(delete(SignupOTP).where(SignupOTP.expires_at <= current_time))
    await db.commit()
    
    # Log cleanup
    otp_generation_logger.info(
        f"EXPIRED_SIGNUP_OTPS_CLEANED - Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

# Helper to get user by email and user_type (kept for existing functionality, if any)
async def get_user_by_email_and_type(db: AsyncSession, email: str, user_type: str) -> Optional[User]:
    result = await db.execute(
        select(User).filter(User.email == email, User.user_type == user_type)
    )
    return result.scalars().first()

# Redis OTP flag key format (kept as is for backward compatibility)
def get_otp_flag_key(email: str, user_type: str) -> str:
    return f"otp_verified:{email}:{user_type}"
