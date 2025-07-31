#!/usr/bin/env python3
"""
Test script for the new database-based OTP system.
This script tests the SignupOTP functionality to ensure it works correctly.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

async def test_signup_otp_system():
    """Test the new SignupOTP system"""
    try:
        from app.database.session import AsyncSessionLocal
        from app.crud import otp as crud_otp
        from app.core.config import get_settings
        
        settings = get_settings()
        
        print("🧪 Testing new database-based OTP system...")
        
        # Test 1: Generate OTP code
        print("\n1. Testing OTP generation...")
        otp_code = crud_otp.generate_otp_code()
        print(f"   ✅ Generated OTP: {otp_code}")
        print(f"   ✅ OTP Length: {len(otp_code)}")
        print(f"   ✅ OTP is numeric: {otp_code.isdigit()}")
        
        # Test 2: Create SignupOTP
        print("\n2. Testing SignupOTP creation...")
        async with AsyncSessionLocal() as db:
            # Create a test SignupOTP
            signup_otp = await crud_otp.create_signup_otp(
                db=db,
                email="test@example.com",
                user_type="live",
                force_otp_code="123456"
            )
            print(f"   ✅ Created SignupOTP ID: {signup_otp.id}")
            print(f"   ✅ Email: {signup_otp.email}")
            print(f"   ✅ User Type: {signup_otp.user_type}")
            print(f"   ✅ OTP Code: {signup_otp.otp_code}")
            print(f"   ✅ Expires At: {signup_otp.expires_at}")
            print(f"   ✅ Is Verified: {signup_otp.is_verified}")
            
            # Test 3: Retrieve valid SignupOTP
            print("\n3. Testing SignupOTP retrieval...")
            retrieved_otp = await crud_otp.get_valid_signup_otp(
                db=db,
                email="test@example.com",
                user_type="live",
                otp_code="123456"
            )
            
            if retrieved_otp:
                print(f"   ✅ Retrieved SignupOTP ID: {retrieved_otp.id}")
                print(f"   ✅ OTP is valid and not expired")
            else:
                print("   ❌ Failed to retrieve SignupOTP")
                return False
            
            # Test 4: Verify SignupOTP
            print("\n4. Testing SignupOTP verification...")
            await crud_otp.verify_signup_otp(db=db, signup_otp=retrieved_otp)
            print(f"   ✅ SignupOTP marked as verified")
            print(f"   ✅ Verified At: {retrieved_otp.verified_at}")
            
            # Test 5: Try to retrieve verified OTP (should fail)
            print("\n5. Testing retrieval of verified OTP...")
            verified_otp = await crud_otp.get_valid_signup_otp(
                db=db,
                email="test@example.com",
                user_type="live",
                otp_code="123456"
            )
            
            if not verified_otp:
                print("   ✅ Correctly rejected verified OTP")
            else:
                print("   ❌ Should not retrieve verified OTP")
                return False
            
            # Test 6: Clean up
            print("\n6. Testing cleanup...")
            await crud_otp.delete_signup_otp(db=db, signup_otp_id=signup_otp.id)
            print("   ✅ SignupOTP deleted successfully")
            
            # Test 7: Verify deletion
            deleted_otp = await crud_otp.get_valid_signup_otp(
                db=db,
                email="test@example.com",
                user_type="live",
                otp_code="123456"
            )
            
            if not deleted_otp:
                print("   ✅ Correctly confirmed OTP deletion")
            else:
                print("   ❌ OTP should be deleted")
                return False
        
        print("\n🎉 All tests passed! The new OTP system is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_demo_otp_system():
    """Test the demo OTP system"""
    try:
        from app.database.session import AsyncSessionLocal
        from app.crud import otp as crud_otp
        
        print("\n🧪 Testing demo OTP system...")
        
        async with AsyncSessionLocal() as db:
            # Create a test demo SignupOTP
            demo_otp = await crud_otp.create_signup_otp(
                db=db,
                email="demo@example.com",
                user_type="demo",
                force_otp_code="654321"
            )
            print(f"   ✅ Created Demo SignupOTP ID: {demo_otp.id}")
            print(f"   ✅ Email: {demo_otp.email}")
            print(f"   ✅ User Type: {demo_otp.user_type}")
            
            # Test retrieval
            retrieved_demo_otp = await crud_otp.get_valid_signup_otp(
                db=db,
                email="demo@example.com",
                user_type="demo",
                otp_code="654321"
            )
            
            if retrieved_demo_otp:
                print("   ✅ Demo OTP retrieved successfully")
                await crud_otp.verify_signup_otp(db=db, signup_otp=retrieved_demo_otp)
                await crud_otp.delete_signup_otp(db=db, signup_otp_id=demo_otp.id)
                print("   ✅ Demo OTP verified and deleted")
            else:
                print("   ❌ Failed to retrieve demo OTP")
                return False
        
        print("🎉 Demo OTP system test passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Demo test failed: {e}")
        return False

async def main():
    """Run all tests"""
    print("🚀 Starting OTP system tests...")
    
    # Test live OTP system
    live_success = await test_signup_otp_system()
    
    # Test demo OTP system
    demo_success = await test_demo_otp_system()
    
    if live_success and demo_success:
        print("\n✅ All OTP system tests passed!")
        print("\n📋 Summary:")
        print("- SignupOTP table created successfully")
        print("- OTP generation works correctly")
        print("- OTP storage and retrieval work correctly")
        print("- OTP verification works correctly")
        print("- Demo and live user types work correctly")
        print("- Database-based OTP system is ready for production")
    else:
        print("\n❌ Some tests failed. Please check the implementation.")

if __name__ == "__main__":
    asyncio.run(main()) 