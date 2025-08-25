from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database.models import CryptoPayment
from typing import Optional, Dict, Any

async def create_payment_record(db: AsyncSession, user_id: int, merchant_order_id: str, payment_data: Dict[str, Any]) -> CryptoPayment:
    db_payment = CryptoPayment(
        user_id=user_id,
        merchant_order_id=merchant_order_id,
        base_amount=payment_data['baseAmount'],
        base_currency=payment_data['baseCurrency'],
        settled_currency=payment_data['settledCurrency'],
        network_symbol=payment_data['networkSymbol'],
        status='PENDING'
    )
    db.add(db_payment)
    await db.commit()
    await db.refresh(db_payment)
    return db_payment

async def get_payment_by_merchant_order_id(db: AsyncSession, merchant_order_id: str) -> Optional[CryptoPayment]:
    result = await db.execute(select(CryptoPayment).filter(CryptoPayment.merchant_order_id == merchant_order_id))
    return result.scalars().first()

async def update_payment_status(db: AsyncSession, payment: CryptoPayment, status: str, webhook_data: Optional[Dict[str, Any]] = None) -> CryptoPayment:
    from decimal import Decimal
    import json
    
    payment.status = status
    
    if webhook_data:
        # Store complete webhook data as JSON string
        payment.transaction_details = json.dumps(webhook_data, default=str)
        
        # Extract data from nested structure if present
        data_section = webhook_data.get('data', webhook_data)
        
        # Always update base_amount with baseAmount from webhook
        if 'baseAmount' in data_section:
            try:
                payment.base_amount = Decimal(str(data_section['baseAmount']))
            except (ValueError, TypeError):
                pass  # Keep existing value if conversion fails
        
        # Update new optional fields
        if 'baseAmountReceived' in data_section:
            try:
                payment.base_amount_received = Decimal(str(data_section['baseAmountReceived']))
            except (ValueError, TypeError):
                payment.base_amount_received = None
        
        if 'settledAmountRequested' in data_section:
            try:
                payment.settled_amount_requested = Decimal(str(data_section['settledAmountRequested']))
            except (ValueError, TypeError):
                payment.settled_amount_requested = None
        
        if 'settledAmountReceived' in data_section:
            try:
                payment.settled_amount_received = Decimal(str(data_section['settledAmountReceived']))
            except (ValueError, TypeError):
                payment.settled_amount_received = None
        
        if 'settledAmountCredited' in data_section:
            try:
                payment.settled_amount_credited = Decimal(str(data_section['settledAmountCredited']))
            except (ValueError, TypeError):
                payment.settled_amount_credited = None
        
        if 'commission' in data_section:
            try:
                payment.commission = Decimal(str(data_section['commission']))
            except (ValueError, TypeError):
                payment.commission = None
    
    await db.commit()
    await db.refresh(payment)
    return payment