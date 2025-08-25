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

class CallbackData(BaseModel):
    type: str
    merchantOrderId: str
    status: str
    # Optional fields that Tylt might send
    transactionId: Optional[str] = None
    amount: Optional[str] = None
    currency: Optional[str] = None
    settledAmount: Optional[str] = None
    settledCurrency: Optional[str] = None
    networkSymbol: Optional[str] = None
    transactionHash: Optional[str] = None
    blockNumber: Optional[str] = None
    confirmations: Optional[int] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    fee: Optional[str] = None
    feeSymbol: Optional[str] = None
    exchangeRate: Optional[str] = None
    
    class Config:
        extra = "allow"  # Allow additional fields not defined in schema