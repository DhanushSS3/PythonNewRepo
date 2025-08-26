#!/usr/bin/env python3
"""
Test script for backend idempotency implementation.
Tests the 5-second TTL duplicate order prevention for place_order and close_order endpoints.
"""

import asyncio
import aiohttp
import json
import time
from decimal import Decimal

# Test configuration
BASE_URL = "http://localhost:8000"  # Adjust as needed
TEST_USER_ID = 1  # Adjust to a valid user ID
TEST_ORDER_ID = "test_order_123"  # For close order tests

# Test data for place_order
PLACE_ORDER_DATA = {
    "symbol": "EURUSD",
    "order_type": "BUY",
    "order_quantity": "1.0",
    "order_price": "1.1000",
    "user_type": "demo",
    "user_id": TEST_USER_ID,
    "order_status": "OPEN",
    "status": "ACTIVE"
}

# Test data for close_order
CLOSE_ORDER_DATA = {
    "order_id": TEST_ORDER_ID,
    "close_price": "1.1050",
    "order_company_name": "EURUSD",
    "order_type": "BUY",
    "order_status": "CLOSED",
    "status": "CLOSED",
    "user_id": TEST_USER_ID
}

async def make_request(session, endpoint, data, headers=None):
    """Make a POST request to the specified endpoint."""
    url = f"{BASE_URL}{endpoint}"
    try:
        async with session.post(url, json=data, headers=headers) as response:
            response_text = await response.text()
            return {
                "status_code": response.status,
                "response": response_text,
                "headers": dict(response.headers)
            }
    except Exception as e:
        return {
            "status_code": 0,
            "response": str(e),
            "headers": {}
        }

async def test_place_order_idempotency():
    """Test idempotency for place_order endpoint."""
    print("🧪 Testing place_order idempotency...")
    
    async with aiohttp.ClientSession() as session:
        # First request - should succeed
        print("📤 Making first place_order request...")
        result1 = await make_request(session, "/orders/", PLACE_ORDER_DATA)
        print(f"✅ First request: Status {result1['status_code']}")
        print(f"   Response: {result1['response'][:200]}...")
        
        # Second request immediately - should be rejected with 429
        print("📤 Making second place_order request immediately...")
        result2 = await make_request(session, "/orders/", PLACE_ORDER_DATA)
        print(f"🚫 Second request: Status {result2['status_code']}")
        print(f"   Response: {result2['response'][:200]}...")
        
        if result2['status_code'] == 429:
            print("✅ Idempotency working correctly - duplicate rejected!")
        else:
            print("❌ Idempotency failed - duplicate was not rejected!")
        
        # Wait 6 seconds and try again - should succeed
        print("⏳ Waiting 6 seconds for TTL to expire...")
        await asyncio.sleep(6)
        
        print("📤 Making third place_order request after TTL...")
        result3 = await make_request(session, "/orders/", PLACE_ORDER_DATA)
        print(f"✅ Third request: Status {result3['status_code']}")
        print(f"   Response: {result3['response'][:200]}...")
        
        if result3['status_code'] in [200, 201]:
            print("✅ TTL expiration working correctly - request allowed after 5 seconds!")
        else:
            print("❌ TTL expiration failed - request still rejected!")

async def test_close_order_idempotency():
    """Test idempotency for close_order endpoint."""
    print("\n🧪 Testing close_order idempotency...")
    
    async with aiohttp.ClientSession() as session:
        # First request - should succeed or fail with business logic error
        print("📤 Making first close_order request...")
        result1 = await make_request(session, "/orders/close", CLOSE_ORDER_DATA)
        print(f"✅ First request: Status {result1['status_code']}")
        print(f"   Response: {result1['response'][:200]}...")
        
        # Second request immediately - should be rejected with 429
        print("📤 Making second close_order request immediately...")
        result2 = await make_request(session, "/orders/close", CLOSE_ORDER_DATA)
        print(f"🚫 Second request: Status {result2['status_code']}")
        print(f"   Response: {result2['response'][:200]}...")
        
        if result2['status_code'] == 429:
            print("✅ Idempotency working correctly - duplicate rejected!")
        else:
            print("❌ Idempotency failed - duplicate was not rejected!")
        
        # Wait 6 seconds and try again - should succeed or fail with business logic
        print("⏳ Waiting 6 seconds for TTL to expire...")
        await asyncio.sleep(6)
        
        print("📤 Making third close_order request after TTL...")
        result3 = await make_request(session, "/orders/close", CLOSE_ORDER_DATA)
        print(f"✅ Third request: Status {result3['status_code']}")
        print(f"   Response: {result3['response'][:200]}...")
        
        if result3['status_code'] != 429:
            print("✅ TTL expiration working correctly - request allowed after 5 seconds!")
        else:
            print("❌ TTL expiration failed - request still rejected!")

async def test_different_requests_allowed():
    """Test that different requests are not blocked by idempotency."""
    print("\n🧪 Testing different requests are allowed...")
    
    # Modify the order data slightly
    different_order_data = PLACE_ORDER_DATA.copy()
    different_order_data["order_quantity"] = "2.0"  # Different quantity
    
    async with aiohttp.ClientSession() as session:
        # First request
        print("📤 Making first request with quantity 1.0...")
        result1 = await make_request(session, "/orders/", PLACE_ORDER_DATA)
        print(f"✅ First request: Status {result1['status_code']}")
        
        # Different request immediately - should succeed
        print("📤 Making second request with quantity 2.0...")
        result2 = await make_request(session, "/orders/", different_order_data)
        print(f"✅ Second request: Status {result2['status_code']}")
        
        if result2['status_code'] != 429:
            print("✅ Different requests correctly allowed!")
        else:
            print("❌ Different requests incorrectly blocked!")

async def main():
    """Run all idempotency tests."""
    print("🚀 Starting Backend Idempotency Tests")
    print("=" * 50)
    
    try:
        await test_place_order_idempotency()
        await test_close_order_idempotency()
        await test_different_requests_allowed()
        
        print("\n" + "=" * 50)
        print("✅ All idempotency tests completed!")
        print("\n📋 Expected Results:")
        print("   - First requests should succeed or fail with business logic errors")
        print("   - Immediate duplicate requests should return 429 (Too Many Requests)")
        print("   - Requests after 6 seconds should be allowed again")
        print("   - Different requests should not be blocked")
        
    except Exception as e:
        print(f"❌ Test execution failed: {e}")

if __name__ == "__main__":
    print("⚠️  Note: Make sure your FastAPI server is running on http://localhost:8000")
    print("⚠️  Note: Adjust TEST_USER_ID and authentication as needed")
    print("⚠️  Note: Some tests may fail with business logic errors - focus on 429 status codes")
    print()
    
    asyncio.run(main())
