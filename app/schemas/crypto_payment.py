from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from decimal import Decimal

class PaymentRequest(BaseModel):
    baseCurrency: str
    settledCurrency: str
    networkSymbol: str
    baseAmount: Decimal

class PaymentResponseData(BaseModel):
    paymentUrl: str
    merchantOrderId: str
    # Add other fields from the actual API response as needed

class PaymentResponse(BaseModel):
    status: bool
    message: str
    data: Optional[PaymentResponseData] = None

class Currency(BaseModel):
    id: int
    name: str
    symbol: str
    type: str
    networks: List[Dict[str, Any]]

class CurrencyListResponse(BaseModel):
    status: bool
    message: str
    data: Optional[List[Currency]] = None

class TyltWebhookData(BaseModel):
    """Schema for the data section of Tylt webhook payload"""
    orderId: Optional[str] = None
    merchantOrderId: str
    baseAmount: Optional[Decimal] = None
    baseCurrency: Optional[str] = None
    baseAmountReceived: Optional[Decimal] = None
    settledCurrency: Optional[str] = None
    settledAmountRequested: Optional[Decimal] = None
    settledAmountReceived: Optional[Decimal] = None
    settledAmountCredited: Optional[Decimal] = None
    commission: Optional[Decimal] = None
    network: Optional[str] = None
    depositAddress: Optional[str] = None
    status: str  # Waiting, Confirming, Paid, Completed, Failed, Expired, UnderPayment, OverPayment
    
    class Config:
        extra = "allow"  # Allow additional fields not defined in schema

class CallbackData(BaseModel):
    """Schema for complete Tylt webhook payload"""
    type: str  # pay-in
    data: TyltWebhookData
    
    class Config:
        extra = "allow"  # Allow additional fields not defined in schema