#!/usr/bin/env python3
"""
Test script for the specialized logging system for OTPs and emails.
This script tests the logging functionality to ensure it works correctly.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.logging_config import (
    otp_generation_logger, 
    otp_verification_logger, 
    otp_failed_attempts_logger,
    email_sent_logger,
    email_failed_logger,
    email_margin_call_logger
)
from app.crud.otp import generate_otp_code
from app.services.email import send_email, send_margin_call_email

async def test_otp_logging():
    """Test OTP logging functionality."""
    print("Testing OTP logging...")
    
    # Test OTP generation
    otp_code = generate_otp_code()
    print(f"Generated OTP: {otp_code}")
    
    # Test OTP verification logging
    otp_verification_logger.info(
        f"OTP_VERIFIED - Code: {otp_code} - User Type: live - User ID: 123 - Valid: True - "
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    # Test failed OTP attempt
    otp_failed_attempts_logger.warning(
        f"OTP_VERIFICATION_FAILED - Code: 654321 - User Type: live - User ID: 123 - Valid: False - "
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    print("✅ OTP logging tests completed")

async def test_email_logging():
    """Test email logging functionality."""
    print("Testing email logging...")
    
    # Test email sent logging
    email_sent_logger.info(
        f"EMAIL_SENT - Type: test_email - To: test@example.com - Subject: Test Email - "
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    # Test email failed logging
    email_failed_logger.error(
        f"EMAIL_FAILED - Type: test_email - To: test@example.com - Subject: Test Email - "
        f"Error: TestError - Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    # Test margin call email logging
    email_margin_call_logger.info(
        f"MARGIN_CALL_EMAIL_SENT - To: test@example.com - Margin Level: 150% - "
        f"Dashboard URL: https://dashboard.example.com - "
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    print("✅ Email logging tests completed")

def test_log_directories():
    """Test that log directories exist."""
    print("Testing log directories...")
    
    log_dirs = [
        "logs/otps",
        "logs/emails"
    ]
    
    for log_dir in log_dirs:
        if os.path.exists(log_dir):
            print(f"✅ Directory exists: {log_dir}")
        else:
            print(f"❌ Directory missing: {log_dir}")
            os.makedirs(log_dir, exist_ok=True)
            print(f"✅ Created directory: {log_dir}")

def test_log_files():
    """Test that log files are being created."""
    print("Testing log file creation...")
    
    log_files = [
        "logs/otps/otp_generation.log",
        "logs/otps/otp_verification.log", 
        "logs/otps/otp_failed_attempts.log",
        "logs/emails/email_sent.log",
        "logs/emails/email_failed.log",
        "logs/emails/email_margin_call.log"
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            print(f"✅ Log file exists: {log_file}")
        else:
            print(f"❌ Log file missing: {log_file}")

async def main():
    """Run all tests."""
    print("🧪 Testing Specialized Logging System")
    print("=" * 50)
    
    # Test directories
    test_log_directories()
    print()
    
    # Test OTP logging
    await test_otp_logging()
    print()
    
    # Test email logging  
    await test_email_logging()
    print()
    
    # Test log files
    test_log_files()
    print()
    
    print("🎉 All tests completed!")
    print("\nCheck the log files in logs/otps/ and logs/emails/ to verify logging is working correctly.")

if __name__ == "__main__":
    asyncio.run(main()) 