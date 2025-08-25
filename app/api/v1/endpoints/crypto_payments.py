from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any
import httpx
import hmac
import hashlib
import json
from uuid import uuid4
from datetime import datetime

from app.database.session import get_db
from app.core.config import settings
from app.core.security import get_current_user
from app.database.models import User, DemoUser, CryptoPayment
from app.schemas.crypto_payment import PaymentRequest, PaymentResponse, CurrencyListResponse, CallbackData
from app.crud.crypto_payment import create_payment_record, get_payment_by_merchant_order_id, update_payment_status

# Import crypto payment loggers
from app.core.logging_config import (
    crypto_payment_requests_logger,
    crypto_payment_webhooks_logger,
    crypto_payment_errors_logger
)


router = APIRouter()

@router.post("/generate-payment-url", response_model=PaymentResponse)
async def generate_payment_url(
    request: PaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    merchant_order_id = f'livefx_{uuid4().hex}'
    
    # Log the incoming payment request
    crypto_payment_requests_logger.info(
        f"PAYMENT_REQUEST_RECEIVED - User: {current_user.id}, Email: {current_user.email}, "
        f"Amount: {request.baseAmount}, BaseCurrency: {request.baseCurrency}, "
        f"SettledCurrency: {request.settledCurrency}, NetworkSymbol: {request.networkSymbol}, "
        f"MerchantOrderId: {merchant_order_id}"
    )
    
    request_body = {
        'merchantOrderId': merchant_order_id,
        'baseAmount': str(request.baseAmount),
        'baseCurrency': request.baseCurrency,
        'settledCurrency': request.settledCurrency,
        'networkSymbol': request.networkSymbol,
        'callBackUrl': 'https://livefxhubv1.livefxhub.com/api/v1/payments/crypto-callback' # This should be configurable
    }
    
    # Log the request being sent to Tylt
    crypto_payment_requests_logger.info(
        f"TYLT_API_REQUEST - MerchantOrderId: {merchant_order_id}, RequestBody: {json.dumps(request_body)}"
    )

    raw = json.dumps(request_body, separators=(',', ':'), ensure_ascii=False)
    signature = hmac.new(
        bytes(settings.TYLT_API_SECRET, 'utf-8'),
        msg=bytes(raw, 'utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()

    headers = {
        'X-TLP-APIKEY': settings.TYLT_API_KEY,
        'X-TLP-SIGNATURE': signature,
        'Content-Type': 'application/json',
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                'https://api.tylt.money/transactions/merchant/createPayinRequest',
                headers=headers,
                json=request_body
            )
            res.raise_for_status()
            
            # Log successful Tylt API response
            tylt_response = res.json()
            crypto_payment_requests_logger.info(
                f"TYLT_API_SUCCESS - MerchantOrderId: {merchant_order_id}, "
                f"Response: {json.dumps(tylt_response)}"
            )

            # Create payment record before returning response
            await create_payment_record(db, current_user.id, merchant_order_id, request.dict())
            
            crypto_payment_requests_logger.info(
                f"PAYMENT_RECORD_CREATED - MerchantOrderId: {merchant_order_id}, "
                f"User: {current_user.id}, Status: PENDING"
            )

            tylt_data = tylt_response.get("data", tylt_response)
            payment_response_data = {
                "paymentUrl": tylt_data.get("paymentURL"),
                "merchantOrderId": tylt_data.get("merchantOrderId"),
                # Add more fields if your schema expects them
            }

            return {
                "status": True,
                "message": "PaymentUrl Generated Successfully",
                "data": payment_response_data
            }
        except httpx.HTTPStatusError as e:
            crypto_payment_errors_logger.error(
                f"TYLT_API_ERROR - MerchantOrderId: {merchant_order_id}, "
                f"Status: {e.response.status_code}, Error: {e.response.text}"
            )
            return {
                "status": False,
                "message": "Failed to generate PaymentUrl",
                "error": e.response.text
            }
        except Exception as e:
            crypto_payment_errors_logger.error(
                f"PAYMENT_GENERATION_ERROR - MerchantOrderId: {merchant_order_id}, "
                f"Error: {str(e)}", exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/currency-list", response_model=CurrencyListResponse)
async def currency_list(current_user: User = Depends(get_current_user)):
    request_body = {}
    raw = json.dumps(request_body)

    signature = hmac.new(
        bytes(settings.TYLT_API_SECRET, 'utf-8'),
        msg=bytes(raw, 'utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()

    headers = {
        'X-TLP-APIKEY': settings.TYLT_API_KEY,
        'X-TLP-SIGNATURE': signature,
        'Content-Type': 'application/json',
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(
                'https://api.tylt.money/transactions/merchant/getSupportedCryptoCurrenciesList',
                headers=headers
            )
            res.raise_for_status()
            return {
                "status": True,
                "message": "Data Fetched Successfully",
                "data": res.json()
            }
        except httpx.HTTPStatusError as e:
            return {
                "status": False,
                "message": "Failed to fetch data",
                "error": e.response.text
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/crypto-callback")
async def crypto_callback(request: Request, db: AsyncSession = Depends(get_db)):
    # Get request details for logging
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get('user-agent', 'unknown')
    
    try:
        tlp_signature = request.headers.get('x-tlp-signature')
        raw_body = await request.body()
        
        # Log incoming webhook
        crypto_payment_webhooks_logger.info(
            f"WEBHOOK_RECEIVED - IP: {client_ip}, UserAgent: {user_agent}, "
            f"Signature: {tlp_signature}, BodyLength: {len(raw_body)}"
        )

        calculated_hmac = hmac.new(
            bytes(settings.TYLT_API_SECRET, 'utf-8'),
            msg=raw_body,
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hmac, tlp_signature):
            crypto_payment_errors_logger.error(
                f"WEBHOOK_SIGNATURE_INVALID - IP: {client_ip}, "
                f"Expected: {calculated_hmac}, Received: {tlp_signature}"
            )
            raise HTTPException(status_code=400, detail="Invalid HMAC signature")

        data = await request.json()
        
        # Log complete webhook data
        crypto_payment_webhooks_logger.info(
            f"WEBHOOK_DATA_RECEIVED - IP: {client_ip}, "
            f"Data: {json.dumps(data, default=str)}"
        )
        
        merchant_order_id = data.get('merchantOrderId')
        webhook_type = data.get('type')
        webhook_status = data.get('status')
        
        # Process all webhook types, not just completed pay-in
        if merchant_order_id:
            payment = await get_payment_by_merchant_order_id(db, merchant_order_id)
            
            if payment:
                crypto_payment_webhooks_logger.info(
                    f"PAYMENT_FOUND - MerchantOrderId: {merchant_order_id}, "
                    f"CurrentStatus: {payment.status}, WebhookType: {webhook_type}, "
                    f"WebhookStatus: {webhook_status}"
                )
                
                # Update payment with all webhook data
                if webhook_type == 'pay-in' and webhook_status == 'completed':
                    await update_payment_status(db, payment, 'COMPLETED', data)
                    crypto_payment_webhooks_logger.info(
                        f"PAYMENT_COMPLETED - MerchantOrderId: {merchant_order_id}, "
                        f"User: {payment.user_id}, Amount: {payment.base_amount} {payment.base_currency}"
                    )
                    
                    # TODO: Update user's wallet
                    # await add_funds_to_wallet(db, payment.user_id, payment.base_amount)
                    crypto_payment_webhooks_logger.info(
                        f"WALLET_UPDATE_PENDING - User: {payment.user_id}, "
                        f"Amount: {payment.base_amount} {payment.base_currency}"
                    )
                elif webhook_type == 'pay-in' and webhook_status == 'failed':
                    await update_payment_status(db, payment, 'FAILED', data)
                    crypto_payment_webhooks_logger.warning(
                        f"PAYMENT_FAILED - MerchantOrderId: {merchant_order_id}, "
                        f"User: {payment.user_id}"
                    )
                else:
                    # Update with any other status
                    await update_payment_status(db, payment, webhook_status.upper() if webhook_status else 'UNKNOWN', data)
                    crypto_payment_webhooks_logger.info(
                        f"PAYMENT_STATUS_UPDATED - MerchantOrderId: {merchant_order_id}, "
                        f"NewStatus: {webhook_status}, Type: {webhook_type}"
                    )
            else:
                crypto_payment_webhooks_logger.warning(
                    f"PAYMENT_NOT_FOUND - MerchantOrderId: {merchant_order_id}, "
                    f"WebhookType: {webhook_type}, WebhookStatus: {webhook_status}"
                )
        else:
            crypto_payment_webhooks_logger.warning(
                f"WEBHOOK_NO_MERCHANT_ID - IP: {client_ip}, Data: {json.dumps(data, default=str)}"
            )

        return {"status": "ok"}
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        crypto_payment_errors_logger.error(
            f"WEBHOOK_PROCESSING_ERROR - IP: {client_ip}, Error: {str(e)}", 
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")